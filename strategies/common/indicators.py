"""全策略公用的自定义指标。"""

from __future__ import annotations

import math
from typing import Sequence

import backtrader as bt
import numpy as np
import pandas as pd


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


# ---------- pandas 向量化版本（供分钟快照等预处理数据使用） ----------

def sma(values: Sequence[float], period: int) -> np.ndarray:
    """简单移动平均，与 backtrader SMA 同口径：前 period-1 个值为 NaN。"""
    return pd.Series(values, dtype=float).rolling(period).mean().to_numpy()


def wilder_atr(high, low, close, period: int = 14) -> np.ndarray:
    """Wilder ATR，与 backtrader ATR 同口径：

    TR = max(high, prev_close) - min(low, prev_close)；
    首个有效值在 index=period（种子 = mean(TR[1:period+1])），之后按 1/period 递推。
    """
    h, l, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    n = len(c)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    prev_close = c[:-1]
    tr[1:] = np.maximum.reduce(
        [h[1:] - l[1:], np.abs(h[1:] - prev_close), np.abs(l[1:] - prev_close)]
    )
    atr = np.full(n, np.nan)
    if n > period:
        atr[period] = tr[1 : period + 1].mean()
        alpha = 1.0 / period
        for i in range(period + 1, n):
            atr[i] = atr[i - 1] + alpha * (tr[i] - atr[i - 1])
    return atr


def build_ma_cross_signals(
    close: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    fast_period: int = 30,
    slow_period: int = 90,
    atr_period: int = 14,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """双均线信号：返回 (trend_ok, cross_down, sma_fast, sma_slow, atr)。

    trend_ok = SMA(fast) > SMA(slow) 且 close > SMA(slow)，指标未预热时为 False；
    cross_down = 前一日 SMA(fast) > SMA(slow) 且当日 SMA(fast) <= SMA(slow)。
    """
    fast_ma = sma(close, fast_period)
    slow_ma = sma(close, slow_period)
    atr = wilder_atr(high, low, close, atr_period)
    close_arr = np.asarray(close, dtype=float)
    valid = ~(np.isnan(fast_ma) | np.isnan(slow_ma) | np.isnan(atr))
    with np.errstate(invalid="ignore"):
        trend_ok = valid & (fast_ma > slow_ma) & (close_arr > slow_ma)
        cross_down = np.zeros(len(close_arr), dtype=bool)
        cross_down[1:] = (
            valid[1:] & (fast_ma[:-1] > slow_ma[:-1]) & (fast_ma[1:] <= slow_ma[1:])
        )
    return trend_ok, cross_down, fast_ma, slow_ma, atr
