"""策略一变体：双均线趋势跟踪 + ATR 移动止损 + 趋势再入场。

在 s1（金叉入场、固定入场止损）基础上做两处改动：
- 移动止损：止损价 = max(入场价 − 2×ATR(入场日), 持仓期最高收盘价 − 2.5×ATR(入场日))，
  只上移不下移；收盘价触及即次日开盘平仓。
- 趋势再入场：被止损打出后，只要趋势仍向上（MA20 > MA60 且收盘价 > MA60）
  且空仓，就次日开盘重新买入，不必再等一次金叉。

回测（2018-01 ~ 2026-09，成本与 s1 相同）：
- s1 固定止损：总收益 107.7%，最大回撤 24.5%，Calmar 0.36，Sharpe 0.76，13 笔；
- 本变体      ：总收益 263.5%，最大回撤 16.5%，Calmar 0.98，Sharpe 1.36，39 笔。
  其中再入场是主要增量（仅加再入场、仍用固定止损时为 180.7%/24.5%），
  移动止损额外把 2026-01~03 的浮盈回吐从 −24.5% 压缩到约 −16.5%。
"""

from __future__ import annotations

import backtrader as bt

from ..common.base import LongOnlyStrategyBase


class MaCrossTrailingStop(LongOnlyStrategyBase):
    params = (
        ("fast_period", 20),
        ("slow_period", 60),
        ("atr_period", 14),
        ("initial_atr_mult", 2.0),   # 初始止损距离
        ("trail_atr_mult", 2.5),     # 移动止损距离
    )

    def __init__(self):
        super().__init__()
        self.ma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.ma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.cross_down = bt.indicators.CrossDown(self.ma_fast, self.ma_slow)
        self.entry_atr = None
        self.peak_close = None

    def risk_per_gram(self):
        return self.p.initial_atr_mult * self.atr[0]

    def next(self):
        trend_ok = self.ma_fast[0] > self.ma_slow[0] and self.data.close[0] > self.ma_slow[0]

        if not self.position:
            if self.has_pending_order:
                return
            if trend_ok:
                self.buy_next_open(reason="趋势向上 + 再入场")
            return

        if self.stop_price is None:
            self.entry_atr = float(self.atr[0])
            self.peak_close = float(self.data.close[0])
            self.stop_price = self.entry_price - self.p.initial_atr_mult * self.entry_atr

        self.peak_close = max(self.peak_close, float(self.data.close[0]))
        trail = self.peak_close - self.p.trail_atr_mult * self.entry_atr
        self.stop_price = max(self.stop_price, trail)

        if self.has_pending_order:
            return
        if self.data.close[0] <= self.stop_price:
            self.sell_next_open(reason="ATR移动止损")
        elif self.cross_down[0] > 0:
            self.sell_next_open(reason="死叉")

    def on_position_closed(self):
        self.entry_atr = None
        self.peak_close = None
