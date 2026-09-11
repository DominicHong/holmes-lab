"""策略四：ATR 通道突破（Keltner 风格）。

入场：EMA20 > EMA60，且收盘价 > 昨日计算的上通道（EMA20 + 2×ATR(14)）。
出场：收盘价 < 当日下通道（EMA20 - 2×ATR(14)），
      或收盘价触及移动止损（持仓期最高收盘价 - 2×ATR(14)，只上移不下移）。
信号收盘确认，次日开盘成交；只做多。
"""

from __future__ import annotations

import backtrader as bt

from ..common.base import LongOnlyStrategyBase


class KeltnerBreakout(LongOnlyStrategyBase):
    params = (
        ("ema_fast_period", 20),
        ("ema_slow_period", 60),
        ("atr_period", 14),
        ("channel_mult", 2.0),
        ("trail_mult", 2.0),
    )

    def __init__(self):
        super().__init__()
        self.ema_fast = bt.indicators.EMA(self.data.close, period=self.p.ema_fast_period)
        self.ema_slow = bt.indicators.EMA(self.data.close, period=self.p.ema_slow_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.upper = self.ema_fast + self.p.channel_mult * self.atr
        self.lower = self.ema_fast - self.p.channel_mult * self.atr
        self.upper_prev = self.upper(-1)
        self.max_close = None

    def on_position_closed(self):
        self.max_close = None

    def risk_per_gram(self):
        return self.p.trail_mult * self.atr[0]

    def next(self):
        if not self.position:
            if self.has_pending_order:
                return
            trend_ok = self.ema_fast[0] > self.ema_slow[0]
            if trend_ok and self.data.close[0] > self.upper_prev[0]:
                self.buy_next_open(reason="EMA多头 + 突破上通道")
            return

        close = float(self.data.close[0])
        self.max_close = close if self.max_close is None else max(self.max_close, close)
        candidate = self.max_close - self.p.trail_mult * self.atr[0]
        self.stop_price = candidate if self.stop_price is None else max(self.stop_price, candidate)

        if self.has_pending_order:
            return
        if close < self.lower[0]:
            self.sell_next_open(reason="跌破下通道")
        elif close <= self.stop_price:
            self.sell_next_open(reason="ATR移动止损")
