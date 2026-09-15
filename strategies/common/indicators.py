"""全策略公用的自定义指标。"""

from __future__ import annotations

import math

import backtrader as bt
import numpy as np


class OnBalanceVolume(bt.Indicator):
    """能量潮 OBV：收涨累加当日成交量，收跌累减，平盘不变。"""

    lines = ("obv",)

    def __init__(self):
        self.addminperiod(2)

    def next(self):
        base = self.lines.obv[-1]
        if math.isnan(base):
            base = 0.0
        if self.data.close[0] > self.data.close[-1]:
            self.lines.obv[0] = base + self.data.volume[0]
        elif self.data.close[0] < self.data.close[-1]:
            self.lines.obv[0] = base - self.data.volume[0]
        else:
            self.lines.obv[0] = base


class BollingerBandwidth(bt.Indicator):
    """布林带宽 = (上轨 - 下轨) / 中轨。"""

    lines = ("bw",)
    params = (
        ("period", 20),
        ("devfactor", 2.0),
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(
            self.data, period=self.p.period, devfactor=self.p.devfactor
        )
        self.addminperiod(self.p.period)

    def next(self):
        mid = self.bb.mid[0]
        self.lines.bw[0] = (self.bb.top[0] - self.bb.bot[0]) / mid if mid else 0.0


class RollingPercentile(bt.Indicator):
    """滚动分位数值（默认近 200 日的 10% 分位）。"""

    lines = ("pct",)
    params = (
        ("period", 200),
        ("percentile", 10.0),
    )

    def __init__(self):
        self.addminperiod(self.p.period)

    def next(self):
        window = self.data.get(size=self.p.period)
        self.lines.pct[0] = float(np.percentile(window, self.p.percentile))
