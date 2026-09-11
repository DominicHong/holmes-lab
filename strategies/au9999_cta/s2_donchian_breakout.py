"""策略二：唐奇安通道突破（20 日入场 / 10 日出场）。

入场：成交量 > 前 20 日均量 × 1.5，且收盘价 > 昨日计算的 20 日最高价。
出场：收盘价 < 昨日计算的 10 日最低价，或收盘价触及 入场价 - 2×ATR(14)。
信号收盘确认，次日开盘成交；只做多。
"""

from __future__ import annotations

import backtrader as bt

from ..common.base import LongOnlyStrategyBase


class DonchianBreakout(LongOnlyStrategyBase):
    params = (
        ("entry_period", 20),
        ("exit_period", 10),
        ("volume_period", 20),
        ("volume_mult", 1.5),
        ("atr_period", 14),
        ("atr_stop_mult", 2.0),
    )

    def __init__(self):
        super().__init__()
        # 用 high(-1) / low(-1) / volume(-1) 取「昨日及之前」的窗口，避免把当日算入
        self.upper_prev = bt.indicators.Highest(self.data.high(-1), period=self.p.entry_period)
        self.lower_prev = bt.indicators.Lowest(self.data.low(-1), period=self.p.exit_period)
        self.volume_sma_prev = bt.indicators.SMA(self.data.volume(-1), period=self.p.volume_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)

    def risk_per_gram(self):
        return self.p.atr_stop_mult * self.atr[0]

    def next(self):
        if not self.position:
            if self.has_pending_order:
                return
            breakout = self.data.close[0] > self.upper_prev[0]
            volume_ok = self.data.volume[0] > self.volume_sma_prev[0] * self.p.volume_mult
            if breakout and volume_ok:
                self.buy_next_open(reason="突破20日高点 + 放量")
            return

        if self.stop_price is None:
            self.stop_price = self.entry_price - self.p.atr_stop_mult * self.atr[0]

        if self.has_pending_order:
            return
        if self.data.close[0] <= self.stop_price:
            self.sell_next_open(reason="ATR硬止损")
        elif self.data.close[0] < self.lower_prev[0]:
            self.sell_next_open(reason="跌破10日低点")
