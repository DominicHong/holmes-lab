"""策略一：双均线趋势跟踪 + ATR 硬止损。

入场：MA20 > MA60 且收盘价 > MA60，且当日出现金叉（昨 MA20 ≤ 昨 MA60，今 MA20 > MA60）。
出场：收盘价触及 入场价 - 2×ATR(14)（入场日 ATR，持仓期固定）或 MA20 下穿 MA60。
信号收盘确认，次日开盘成交；只做多。
"""

from __future__ import annotations

import backtrader as bt

from ..common.base import LongOnlyStrategyBase


class MaCrossAtrStop(LongOnlyStrategyBase):
    params = (
        ("fast_period", 20),
        ("slow_period", 60),
        ("atr_period", 14),
        ("atr_stop_mult", 2.0),
    )

    def __init__(self):
        super().__init__()
        self.ma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.ma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.cross_up = bt.indicators.CrossUp(self.ma_fast, self.ma_slow)
        self.cross_down = bt.indicators.CrossDown(self.ma_fast, self.ma_slow)

    def risk_per_gram(self):
        return self.p.atr_stop_mult * self.atr[0]

    def next(self):
        if not self.position:
            if self.has_pending_order:
                return
            if self.cross_up[0] > 0 and self.data.close[0] > self.ma_slow[0]:
                self.buy_next_open(reason="金叉 + 收盘价 > MA60")
            return

        if self.stop_price is None:
            self.stop_price = self.entry_price - self.p.atr_stop_mult * self.atr[0]

        if self.has_pending_order:
            return
        if self.data.close[0] <= self.stop_price:
            self.sell_next_open(reason="ATR硬止损")
        elif self.cross_down[0] > 0:
            self.sell_next_open(reason="死叉")
