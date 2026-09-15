"""策略一C：双均线趋势跟踪 + 量能过滤 + ATR 量能自适应止损（VolFilteredMaCross）。

策略逻辑见 docs/trade_strat/gold_vol_ma_cross.md，在 s1b 基础上增加三个量能模块：
- 入场降档：量能健康（VOL_MA5 > VOL_MA20 或 OBV > OBV_SMA20）95% 仓位，否则 70%；
- 再入场节流：止损平仓后进入 5 个交易日冷却期，须放量反攻 / 缩量回踩企稳 / 第 5 日兜底才再入场；
- 出场自适应：移动止损状态机 NORMAL 2.5×ATR、量价背离 1.8×ATR、天量 1.5×ATR
  （天量基准锁定天量日收盘价），出现"放量创新高"恢复 NORMAL。

另提供三个消融开关（默认全开，即文档全量版）：
- use_volume_stop=False        → 仅保留 NORMAL 2.5×ATR 移动止损；
- use_reentry_gate=False       → 止损后不冷却，趋势向上即再入场；
- use_position_downgrade=False → 入场恒用 healthy_percent 仓位。

信号收盘确认，次日开盘成交；只做多，死叉出场不进入冷却期。
"""

from __future__ import annotations

import backtrader as bt

from ..common.base import LongOnlyStrategyBase
from ..common.constants import MIN_TRADE_GRAMS, SIZE_CASH_BUFFER
from ..common.indicators import OnBalanceVolume


class VolFilteredMaCross(LongOnlyStrategyBase):
    params = (
        ("fast_period", 20),
        ("slow_period", 60),
        ("atr_period", 14),
        ("initial_atr_mult", 2.0),            # 初始止损距离
        ("trail_atr_mult", 2.5),              # NORMAL 移动止损距离
        ("diverge_atr_mult", 1.8),            # 量价背离收紧距离
        ("climax_atr_mult", 1.5),             # 天量收紧距离
        ("climax_profit_threshold", 0.05),    # 天量触发所需持仓浮盈
        ("vol_fast", 5),
        ("vol_slow", 20),
        ("obv_period", 20),
        ("surge_mult", 1.5),                  # 放量阈值（兼"放量创新高"恢复条件）
        ("climax_mult", 2.5),                 # 天量阈值
        ("climax_lookback", 60),              # 天量需为近 N 日（含当日）最大成交量
        ("dead_volume_mult", 0.2),            # 地量阈值，地量日量能信号按中性处理
        ("reentry_surge_ratio", 1.2),         # 再入场：放量反攻量比
        ("reentry_pullback_atr", 1.0),        # 再入场：收盘价距 SMA20 上限（ATR 倍数）
        ("reentry_shrink_ratio", 0.8),        # 再入场：缩量回踩量比上限
        ("cooldown_days", 5),                 # 止损冷却期（交易日）
        ("healthy_percent", 0.95),            # 量能健康基准仓位
        ("unhealthy_percent", 0.70),          # 量能不佳降档仓位
        ("use_volume_stop", True),            # 消融开关：出场自适应
        ("use_reentry_gate", True),           # 消融开关：再入场节流
        ("use_position_downgrade", True),     # 消融开关：入场降档
    )

    def __init__(self):
        super().__init__()
        self.ma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.ma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.cross_down = bt.indicators.CrossDown(self.ma_fast, self.ma_slow)
        self.vol_ma_fast = bt.indicators.SMA(self.data.volume, period=self.p.vol_fast)
        self.vol_ma_slow = bt.indicators.SMA(self.data.volume, period=self.p.vol_slow)
        self.obv = OnBalanceVolume(self.data)
        self.obv_sma = bt.indicators.SMA(self.obv, period=self.p.obv_period)
        self.vol_max = bt.indicators.Highest(self.data.volume, period=self.p.climax_lookback)
        self.entry_atr = None
        self.entry_percent = None
        self.peak_close = None
        self.peak_obv = None
        self.diverge_active = False
        self.climax_basis = None
        self.cooldown_days_left = 0
        self.exit_kind = ""

    # ---------- 仓位：量能健康 95% / 不健康 70% ----------
    def calc_size(self, price: float) -> float:
        if self.p.position_mode != "percent_equity":
            return super().calc_size(price)
        percent = self.p.position_percent if self.entry_percent is None else self.entry_percent
        budget = self.broker.getvalue() * percent
        grams = budget / (price * (1.0 + SIZE_CASH_BUFFER))
        return float(int(grams / MIN_TRADE_GRAMS) * MIN_TRADE_GRAMS)

    # ---------- 量能信号 ----------
    def vol_ratio(self) -> float:
        vol_ma = float(self.vol_ma_slow[0])
        return float(self.data.volume[0]) / vol_ma if vol_ma > 0 else 0.0

    def vol_healthy(self) -> bool:
        return bool(self.vol_ma_fast[0] > self.vol_ma_slow[0] or self.obv[0] > self.obv_sma[0])

    def enter(self, reason: str):
        healthy = self.vol_healthy()
        if self.p.use_position_downgrade and not healthy:
            self.entry_percent = self.p.unhealthy_percent
        else:
            self.entry_percent = self.p.healthy_percent
        self.buy_next_open(reason=f"{reason}（仓位 {self.entry_percent:.0%}）")

    def reentry_triggered(self, cooldown_day: int) -> bool:
        ratio = self.vol_ratio()
        # a. 放量反攻：收阳且量比 ≥ 1.2
        if self.data.close[0] > self.data.open[0] and ratio >= self.p.reentry_surge_ratio:
            return True
        # b. 缩量回踩企稳：距 SMA20 ≤ 1×ATR、未跌破 SMA60、量比 ≤ 0.8
        near_ma20 = (
            abs(self.data.close[0] - self.ma_fast[0]) <= self.p.reentry_pullback_atr * self.atr[0]
        )
        if near_ma20 and self.vol_ratio() <= self.p.reentry_shrink_ratio:
            return True
        # c. 冷却兜底：第 5 个交易日收盘（趋势向上由调用方保证）
        return cooldown_day >= self.p.cooldown_days

    # ---------- 主循环 ----------
    def next(self):
        if self.position:
            self.next_in_position()
        else:
            self.next_flat()

    def next_flat(self):
        if self.has_pending_order:
            return
        trend_ok = self.ma_fast[0] > self.ma_slow[0] and self.data.close[0] > self.ma_slow[0]
        if self.cooldown_days_left > 0:
            cooldown_day = self.p.cooldown_days - self.cooldown_days_left + 1
            reentry = trend_ok and self.reentry_triggered(cooldown_day)
            self.cooldown_days_left -= 1
            if not reentry:
                return
            self.cooldown_days_left = 0
            self.enter("止损冷却后再入场")
            return
        if trend_ok:
            self.enter("趋势向上首次入场")

    def next_in_position(self):
        if self.stop_price is None:
            self.entry_atr = float(self.atr[0])
            self.peak_close = float(self.data.close[0])
            self.peak_obv = float(self.obv[0])
            self.stop_price = self.entry_price - self.p.initial_atr_mult * self.entry_atr

        close = float(self.data.close[0])
        self.update_stop(close)

        if self.has_pending_order:
            return
        if close <= self.stop_price:
            self.exit_kind = "stop"
            self.sell_next_open(reason=f"量能自适应移动止损（{self.stop_state_name()}）")
        elif self.cross_down[0] > 0:
            self.exit_kind = "cross"
            self.sell_next_open(reason="死叉")

    def stop_state_name(self) -> str:
        if self.climax_basis is not None:
            return "CLIMAX"
        return "DIVERGE" if self.diverge_active else "NORMAL"

    def update_stop(self, close: float):
        vol_ma = float(self.vol_ma_slow[0])
        volume = float(self.data.volume[0])
        ratio = volume / vol_ma if vol_ma > 0 else 0.0
        dead_volume = vol_ma > 0 and volume < self.p.dead_volume_mult * vol_ma
        new_high = close > self.peak_close
        profitable = close / self.entry_price - 1.0 > self.p.climax_profit_threshold

        climax = profitable and ratio >= self.p.climax_mult and volume >= float(self.vol_max[0])
        diverge = (
            new_high
            and self.vol_ma_fast[0] < self.vol_ma_slow[0]
            and float(self.obv[0]) < self.peak_obv
        )
        recover = new_high and ratio >= self.p.surge_mult

        # 状态触发优先级 CLIMAX > DIVERGE > NORMAL 恢复；地量日信号按中性处理
        if self.p.use_volume_stop and not dead_volume:
            if climax:
                self.climax_basis = close
            elif diverge:
                self.diverge_active = True
            elif recover:
                self.climax_basis = None
                self.diverge_active = False

        self.peak_close = max(self.peak_close, close)
        self.peak_obv = max(self.peak_obv, float(self.obv[0]))

        if self.climax_basis is not None:
            candidate = self.climax_basis - self.p.climax_atr_mult * self.entry_atr
        elif self.diverge_active:
            candidate = self.peak_close - self.p.diverge_atr_mult * self.entry_atr
        else:
            candidate = self.peak_close - self.p.trail_atr_mult * self.entry_atr
        self.stop_price = max(self.stop_price, candidate)

    def on_position_closed(self):
        if self.exit_kind == "stop" and self.p.use_reentry_gate:
            self.cooldown_days_left = self.p.cooldown_days
        self.exit_kind = ""
        self.entry_atr = None
        self.entry_percent = None
        self.peak_close = None
        self.peak_obv = None
        self.diverge_active = False
        self.climax_basis = None
