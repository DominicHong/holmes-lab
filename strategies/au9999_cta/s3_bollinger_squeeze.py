"""策略三：布林带挤压突破。

入场：昨日带宽 < 近 200 日带宽的 10% 分位（波动率挤压），
      且收盘价 > 当日布林上轨，且当日带宽较昨日扩张 ≥ 30%。
出场：收盘价 < 当日布林中轨（SMA20），或收盘价触及 入场日布林中轨 - 1×ATR(14)。
信号收盘确认，次日开盘成交；只做多。
"""

from __future__ import annotations

import backtrader as bt

from ..common.base import LongOnlyStrategyBase
from ..common.indicators import BollingerBandwidth, RollingPercentile


class BollingerSqueeze(LongOnlyStrategyBase):
    params = (
        ("bb_period", 20),
        ("bb_dev", 2.0),
        ("squeeze_lookback", 200),
        ("squeeze_percentile", 10.0),
        ("expansion_mult", 1.3),
        ("atr_period", 14),
        ("atr_stop_mult", 1.0),
    )

    def __init__(self):
        super().__init__()
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev
        )
        self.bandwidth = BollingerBandwidth(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev
        )
        self.bw_percentile = RollingPercentile(
            self.bandwidth,
            period=self.p.squeeze_lookback,
            percentile=self.p.squeeze_percentile,
        )
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.bw_prev = self.bandwidth(-1)
        self.bw_percentile_prev = self.bw_percentile(-1)

    def risk_per_gram(self):
        return float(self.data.close[0]) - (self.bb.mid[0] - self.p.atr_stop_mult * self.atr[0])

    def next(self):
        if not self.position:
            if self.has_pending_order:
                return
            squeezed = self.bw_prev[0] < self.bw_percentile_prev[0]
            breakout = self.data.close[0] > self.bb.top[0]
            expanding = self.bandwidth[0] >= self.bw_prev[0] * self.p.expansion_mult
            if squeezed and breakout and expanding:
                self.buy_next_open(reason="挤压后放量突破上轨")
            return

        if self.stop_price is None:
            self.stop_price = self.bb.mid[0] - self.p.atr_stop_mult * self.atr[0]

        if self.has_pending_order:
            return
        if self.data.close[0] <= self.stop_price:
            self.sell_next_open(reason="ATR硬止损")
        elif self.data.close[0] < self.bb.mid[0]:
            self.sell_next_open(reason="跌破中轨")
