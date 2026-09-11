"""策略五：RSI 均值回归（震荡市专用）。

入场：ADX(14) < 25（震荡市）且 RSI(14) < 30（超卖）。
出场：RSI(14) > 50 回归，或收盘价触及 入场前 3 日最低价 - 1×ATR(14)，
      或持仓满 10 个交易日的时间止损。
信号收盘确认，次日开盘成交；只做多。
"""

from __future__ import annotations

import backtrader as bt

from ..common.base import LongOnlyStrategyBase


class RsiMeanReversion(LongOnlyStrategyBase):
    params = (
        ("rsi_period", 14),
        ("rsi_entry", 30.0),
        ("rsi_exit", 50.0),
        ("adx_period", 14),
        ("adx_max", 25.0),
        ("atr_period", 14),
        ("stop_lookback", 3),
        ("atr_stop_mult", 1.0),
        ("max_hold_bars", 10),
    )

    def __init__(self):
        super().__init__()
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.adx = bt.indicators.ADX(self.data, period=self.p.adx_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        # 入场前 N 日最低价：用 low(-1) 取「入场日之前」的窗口
        self.prior_low = bt.indicators.Lowest(self.data.low(-1), period=self.p.stop_lookback)

    def risk_per_gram(self):
        stop = self.prior_low[0] - self.p.atr_stop_mult * self.atr[0]
        return float(self.data.close[0]) - stop

    def next(self):
        if not self.position:
            if self.has_pending_order:
                return
            ranging = self.adx[0] < self.p.adx_max
            oversold = self.rsi[0] < self.p.rsi_entry
            if ranging and oversold:
                self.buy_next_open(reason="震荡市 + RSI超卖")
            return

        if self.stop_price is None:
            self.stop_price = self.prior_low[0] - self.p.atr_stop_mult * self.atr[0]

        if self.has_pending_order:
            return
        bars_held = len(self.data) - self.entry_bar
        if self.data.close[0] <= self.stop_price:
            self.sell_next_open(reason="ATR硬止损")
        elif self.rsi[0] > self.p.rsi_exit:
            self.sell_next_open(reason="RSI回归")
        elif bars_held >= self.p.max_hold_bars:
            self.sell_next_open(reason="时间止损")
