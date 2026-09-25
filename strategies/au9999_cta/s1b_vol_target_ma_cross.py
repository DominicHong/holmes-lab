"""策略一B：双均线趋势跟踪 + ATR 移动止损 + 波动率目标仓位（VolTargetMaCross）。

择时规则与策略一A（s1a）完全一致：
- 入场：SMA30 > SMA90 且收盘价 > SMA90 的趋势向上期间，空仓即次日开盘买入；
- 移动止损：止损价 = max(入场价 − 2.5×ATR(入场日), 持仓期最高收盘价 − 2.5×ATR(入场日))，
  只上移不下移；收盘价触及即次日开盘平仓，平仓后趋势仍向上则重新入场；
- 趋势出场：死叉确认 → 次日开盘平仓；不设固定止盈。

唯一差异是仓位：目标仓位系数 f = min(1, 目标年化波动 15% / RV60)，再档位化到
{25%, 50%, 75%, 100%}。RV60 = 60 日已实现波动率（样本标准差 × √252，信号日收盘可得）。
- 建仓：次日开盘按 可用现金 × f 折算克数；
- 持仓期**按档位加减仓**：档位变化（上移或下移）时，次日开盘把持仓调整到新档位的
  目标市值（上移加仓、下移部分减仓；加仓受可用现金约束）；
- 档位变化不重置止损状态机（初始止损、移动止损仍按建仓日 ATR 计），
  部分减仓也不计入胜率统计的完整回合；
- RV60 < 15%（或未预热）时 f = 1，策略与 s1a 逐笔一致。

回测（2018-01-01 ~ 2026-09-01，单边手续费 0.02% + 滑点 0.02%；对照 s1a）：
- AU9999    ：总收益 246.5%，最大回撤 17.0%，Sharpe 1.40，34 笔，胜率 58.8%
  （s1a：272.7% / 17.7% / 1.24 / 34 笔 / 61.8%）；
- 518880.SH ：总收益 205.5%，最大回撤 18.5%，Sharpe 1.21，53 笔，胜率 58.5%
  （s1a：234.9% / 25.1% / 1.12 / 53 笔 / 58.5%）。
窗口口径（窗口前预热、窗口起点空仓）下 518880：全区间 227.4%→198.5%（−28.8pp）、
回撤 25.1%→18.5%、Sharpe 1.10→1.18，2026H1 回撤 22.1%→13.2%，三段震荡区间完全一致。
"""

from __future__ import annotations

import math

import backtrader as bt

from ..common.base import LongOnlyStrategyBase
from ..common.constants import MIN_TRADE_GRAMS
from ..common.indicators import RealizedVolatility


class VolTargetMaCross(LongOnlyStrategyBase):
    params = (
        ("fast_period", 30),
        ("slow_period", 90),
        ("atr_period", 14),
        ("initial_atr_mult", 2.5),   # 初始止损距离
        ("trail_atr_mult", 2.5),     # 移动止损距离
        ("target_vol", 0.15),        # 目标年化波动
        ("vol_period", 60),          # 已实现波动率窗口
        ("vol_grid", 0.25),          # 仓位档位网格
        ("min_factor", 0.25),        # 档位下限
    )

    def __init__(self):
        super().__init__()
        self.ma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.ma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.cross_down = bt.indicators.CrossDown(self.ma_fast, self.ma_slow)
        self.rv = RealizedVolatility(self.data.close, period=self.p.vol_period)
        self.entry_atr = None
        self.peak_close = None
        self.signal_factor = 1.0         # 当日收盘确认的目标仓位系数
        self.position_factor = None      # 当前持仓已对齐的档位
        self._entry_factor = 1.0         # 建仓单使用的档位
        self._pending_rebalance_to = None

    # ---------- 仓位系数 ----------
    def factor_for(self, rv: float) -> float:
        """把 RV60 映射为档位化后的目标仓位系数；RV60 无效时按满仓处理。"""
        if rv is None or math.isnan(rv) or rv <= 0:
            return 1.0
        raw = min(1.0, self.p.target_vol / rv)
        steps = math.floor(raw / self.p.vol_grid + 0.5)
        return max(self.p.min_factor, min(1.0, steps * self.p.vol_grid))

    def risk_per_gram(self):
        return self.p.initial_atr_mult * self.atr[0]

    def calc_size(self, price: float) -> float:
        """percent_equity 模式下按建仓时确认的档位系数折算买入克数。"""
        if self.p.position_mode != "percent_equity":
            return super().calc_size(price)
        buy_cash = self.broker.getcash() * self._entry_factor
        return self.size_for_cash(buy_cash, price)

    # ---------- 信号 ----------
    def next(self):
        self.signal_factor = self.factor_for(float(self.rv[0]))
        trend_ok = self.ma_fast[0] > self.ma_slow[0] and self.data.close[0] > self.ma_slow[0]

        if not self.position:
            if self.has_pending_order:
                return
            if trend_ok:
                self._entry_factor = self.signal_factor
                self.buy_next_open(reason=f"趋势向上 + 目标仓位{self.signal_factor:.0%}")
            return

        if self.stop_price is None:
            self.entry_atr = float(self.atr[0])
            self.peak_close = float(self.data.close[0])
            self.stop_price = self.entry_price - self.p.initial_atr_mult * self.entry_atr
            if self.position_factor is None:
                self.position_factor = self._entry_factor

        self.peak_close = max(self.peak_close, float(self.data.close[0]))
        trail = self.peak_close - self.p.trail_atr_mult * self.entry_atr
        self.stop_price = max(self.stop_price, trail)

        if self.has_pending_order:
            return
        if self.data.close[0] <= self.stop_price:
            self._pending_rebalance_to = None
            self.sell_next_open(reason="ATR移动止损")
        elif self.cross_down[0] > 0:
            self._pending_rebalance_to = None
            self.sell_next_open(reason="死叉")
        elif self.signal_factor != self.position_factor:
            self._pending_rebalance_to = self.signal_factor

    def next_open(self):
        """先处理档位调仓，再走基类的建仓流程。"""
        if self._pending_rebalance_to is not None:
            self._rebalance_to(self._pending_rebalance_to)
            return
        super().next_open()

    def _rebalance_to(self, target_factor: float):
        """把持仓调整到「账户权益 × target_factor」对应的克数（上移加仓、下移减仓）。"""
        self._pending_rebalance_to = None
        if not self.position or self.has_pending_order:
            return
        self.position_factor = target_factor
        price = float(self.data.open[0])
        target_size = self.size_for_cash(self.broker.getvalue() * target_factor, price)
        delta = target_size - self.position.size
        delta = float(int(delta / MIN_TRADE_GRAMS) * MIN_TRADE_GRAMS)
        if abs(delta) < MIN_TRADE_GRAMS:
            return
        if delta > 0:
            # 加仓受可用现金约束：按现金可买克数封顶
            max_size = self.size_for_cash(self.broker.getcash(), price)
            delta = min(delta, max_size)
            delta = float(int(delta / MIN_TRADE_GRAMS) * MIN_TRADE_GRAMS)
            if delta < MIN_TRADE_GRAMS:
                return
            self.order = self.buy(size=delta)
            self.log(f"ADD {delta:.0f}g @open（目标仓位{target_factor:.0%}）")
        else:
            self.order = self.sell(size=-delta)
            self.log(f"REDUCE {-delta:.0f}g @open（目标仓位{target_factor:.0%}）")

    # ---------- 回调 ----------
    def notify_order(self, order):
        """仅在首次建仓 / 完全平仓时重置状态；档位调仓不重置止损状态机。"""
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if order.isbuy():
                if self.entry_price is None:  # 建仓单
                    self.entry_price = order.executed.price
                    self.entry_bar = len(self.data)
                    self.entry_commission = order.executed.comm
                    self.stop_price = None
            elif not self.position:  # 完全平仓
                self.entry_price = None
                self.entry_bar = None
                self.stop_price = None
                self.on_position_closed()
        self.order = None

    def on_position_closed(self):
        self.entry_atr = None
        self.peak_close = None
        self.position_factor = None
        self._pending_rebalance_to = None
