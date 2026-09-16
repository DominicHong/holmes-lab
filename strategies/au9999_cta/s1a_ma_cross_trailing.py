"""策略一A：双均线趋势跟踪 + ATR 移动止损 + 趋势再入场。

- 入场：SMA30 > SMA90 且收盘价 > SMA90 的趋势向上期间，空仓即次日开盘买入，不等新金叉。
- 移动止损：止损价 = max(入场价 − 2.5×ATR(入场日), 持仓期最高收盘价 − 2.5×ATR(入场日))，
  只上移不下移；收盘价触及即次日开盘平仓，平仓后趋势仍向上则重新入场。
- 趋势出场：死叉确认 → 次日开盘平仓。不设固定止盈，不加仓。

参数于 2026-09 由 SMA 20/60 + 2.0/2.5 调整为 SMA 30/90 + 2.5/2.5：
双标的 2018-2026 全区间收益与 Sharpe 改善（20/60 在 2023 年后趋势变长时偏快），
但 2026 年高位急跌窗口最大回撤更深（518880 约 25%），熊市防御不优于原参数。

回测（2018-01-01 ~ 2026-09-01，单边手续费 0.02% + 滑点 0.02%）：
- AU9999    ：总收益 272.7%，最大回撤 17.7%，Sharpe 1.24，34 笔，胜率 61.8%；
- 518880.SH ：总收益 234.9%，最大回撤 25.1%，Sharpe 1.12，53 笔，胜率 58.5%。
"""

from __future__ import annotations

import backtrader as bt

from ..common.base import LongOnlyStrategyBase


class MaCrossTrailingStop(LongOnlyStrategyBase):
    params = (
        ("fast_period", 30),
        ("slow_period", 90),
        ("atr_period", 14),
        ("initial_atr_mult", 2.5),   # 初始止损距离
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
