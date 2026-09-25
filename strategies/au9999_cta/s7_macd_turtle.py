"""策略七：唐奇安通道突破 + MACD 动量过滤 + ATR 自适应止损（MacdTurtle，30/15 版）。

入场：空仓且 收盘价 > Up30（前 30 日最高价，不含当日）且 MACD 柱 HIST > 0 →
      次日开盘买入，仓位 100%。
出场：
- 初始止损 = 入场价 − 2.5×ATR(入场日)，持仓期间固定，作为止损绝对下限；
- 动态止损每日重算：止损价 = max(初始止损, 持仓期最高收盘价 − 系数×ATR(入场日))，
  系数在 MACD 正常（DIF ≥ DEA）时取 2.5、转弱（DIF < DEA）时收紧到 1.5，
  系数放宽时止损价允许下移（非严格棘轮，为动量恢复留空间）；
- 通道出场：收盘价 < Dn15（前 15 日最低价，不含当日）→ 次日开盘平仓；
- 执行优先级：止损优先于通道出场；不设固定止盈，不加仓。

对比策略二：入场周期 20→30、出场周期 10→15（放大以过滤震荡假突破），
新增 MACD 柱动量过滤与动态收紧止损，硬止损由 2×ATR 放宽到 2.5×ATR。

回测（2018-01-01 ~ 2026-09-01，单边手续费 0.02% + 滑点 0.02%；对照 s2）：
- AU9999    ：总收益 154.9%，最大回撤 12.4%，Sharpe 1.25，26 笔，胜率 80.8%
  （s2：33.6% / 17.1% / 0.41 / 9 笔 / 55.6%）；
- 518880.SH ：总收益 100.1%，最大回撤 16.8%，Sharpe 0.89，37 笔，胜率 64.9%
  （s2：39.5% / 16.8% / 0.43 / 20 笔 / 60.0%）。
窗口口径（窗口前预热、窗口起点空仓）下 518880：全区间 39.5%→97.1%、回撤 16.8%→16.8%；
熊市/震荡分段表现互有胜负（2020-2021、2021-2022 s7 更差）。
"""

from __future__ import annotations

import backtrader as bt

from ..common.base import LongOnlyStrategyBase


class MacdTurtle(LongOnlyStrategyBase):
    params = (
        ("entry_period", 30),        # 唐奇安入场周期（前 N 日最高价）
        ("exit_period", 15),         # 唐奇安出场周期（前 N 日最低价）
        ("macd_fast", 12),
        ("macd_slow", 26),
        ("macd_signal", 9),
        ("atr_period", 14),
        ("initial_atr_mult", 2.5),   # 初始止损 / MACD 正常时的动态止损系数
        ("tight_atr_mult", 1.5),     # MACD 转弱时的收紧系数
    )

    def __init__(self):
        super().__init__()
        # high(-1) / low(-1) 取「昨日及之前」的窗口，避免把当日算入
        self.upper_prev = bt.indicators.Highest(self.data.high(-1), period=self.p.entry_period)
        self.lower_prev = bt.indicators.Lowest(self.data.low(-1), period=self.p.exit_period)
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.macd_fast,
            period_me2=self.p.macd_slow,
            period_signal=self.p.macd_signal,
        )
        self.hist = (self.macd.macd - self.macd.signal) * 2.0
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.entry_atr = None
        self.peak_close = None
        self.initial_stop = None

    def risk_per_gram(self):
        return self.p.initial_atr_mult * self.atr[0]

    def next(self):
        if not self.position:
            if self.has_pending_order:
                return
            breakout = self.data.close[0] > self.upper_prev[0]
            momentum_ok = self.hist[0] > 0
            if breakout and momentum_ok:
                self.buy_next_open(reason="突破30日高点 + MACD柱为正")
            return

        close = float(self.data.close[0])
        if self.stop_price is None:
            self.entry_atr = float(self.atr[0])
            self.peak_close = close
            self.initial_stop = self.entry_price - self.p.initial_atr_mult * self.entry_atr
            self.stop_price = self.initial_stop
        self.peak_close = max(self.peak_close, close)

        # MACD 转弱（HIST < 0 等价于 DIF < DEA）→ 止损系数收紧到 1.5
        weak = self.macd.macd[0] < self.macd.signal[0]
        mult = self.p.tight_atr_mult if weak else self.p.initial_atr_mult
        self.stop_price = max(self.initial_stop, self.peak_close - mult * self.entry_atr)

        if self.has_pending_order:
            return
        if close <= self.stop_price:
            self.sell_next_open(reason="ATR自适应止损")
        elif close < self.lower_prev[0]:
            self.sell_next_open(reason="跌破15日低点")

    def on_position_closed(self):
        self.entry_atr = None
        self.peak_close = None
        self.initial_stop = None
