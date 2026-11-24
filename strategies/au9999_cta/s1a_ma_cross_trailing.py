"""策略一A：双均线趋势跟踪 + SMA10 贴线参考带 + ATR 移动止损 + 趋势再入场。

- 入场：SMA30 > SMA90 且收盘价 > SMA90 的趋势向上期间，空仓即次日开盘买入，不等新金叉；
  新增 SMA10 参考带：收盘价仅高于 SMA10 但距离不足 1.5×ATR 时（贴线区）不入场，
  等价格回踩到 SMA10 下方（回踩买点）或拉开到 1.5×ATR 以上（趋势确立）再入场。
- 移动止损：止损价 = max(入场价 − 2.5×ATR(入场日), 持仓期最高收盘价 − 2.5×ATR(入场日))，
  只上移不下移；收盘价触及即次日开盘平仓，平仓后趋势仍向上则重新入场。
- 趋势出场：死叉确认 → 次日开盘平仓。不设固定止盈，不加仓。

参数于 2026-09 由 SMA 20/60 + 2.0/2.5 调整为 SMA 30/90 + 2.5/2.5：
双标的 2018-2026 全区间收益与 Sharpe 改善（20/60 在 2023 年后趋势变长时偏快），
但 2026 年高位急跌窗口最大回撤更深（518880 约 25%），熊市防御不优于原参数。

2026-11 引入 SMA10 贴线参考带（ref_band_atr=1.5）：趋势过滤本身不动，只跳过
「刚站上 SMA10、趋势方向未明」的入场，减少震荡期的反复摩擦。双标的、长短两个
区间均改善（518880 2018-2026 窗口口径 227.4%→241.3%，Sharpe 1.10→1.15，
交易 56→52，胜率 55.4%→61.5%；AU9999 265.9%→272.6%，回撤 17.7%→15.6%）。

回测（2018-01-01 ~ 2026-09-01，单边手续费 0.02% + 滑点 0.02%）：
- AU9999    ：总收益 279.5%，最大回撤 15.6%，Sharpe 1.26，33 笔，胜率 66.7%；
- 518880.SH ：总收益 244.6%，最大回撤 25.1%，Sharpe 1.16，50 笔，胜率 62.0%。
"""

from __future__ import annotations

import math

import backtrader as bt

from ..common.base import LongOnlyStrategyBase


class MaCrossTrailingStop(LongOnlyStrategyBase):
    params = (
        ("fast_period", 30),
        ("slow_period", 90),
        ("atr_period", 14),
        ("initial_atr_mult", 2.5),   # 初始止损距离
        ("trail_atr_mult", 2.5),     # 移动止损距离
        ("ref_period", 10),          # SMA 参考线周期
        ("ref_band_atr", 1.5),       # 贴线区宽度：0 ~ ref_band_atr×ATR 不入场
    )

    def __init__(self):
        super().__init__()
        self.ma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.ma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.ma_ref = bt.indicators.SMA(self.data.close, period=self.p.ref_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.cross_down = bt.indicators.CrossDown(self.ma_fast, self.ma_slow)
        self.entry_atr = None
        self.peak_close = None

    def risk_per_gram(self):
        return self.p.initial_atr_mult * self.atr[0]

    def entry_zone_ok(self) -> bool:
        """SMA 参考带：刚站上参考线但尚未拉开距离（贴线区）时方向不明，不入场。

        收盘价低于参考线（回踩）或高于参考线 ref_band_atr×ATR 以上（趋势确立）才允许入场。
        """
        atr = float(self.atr[0])
        if not math.isfinite(atr) or atr <= 0:
            return True
        dist = (float(self.data.close[0]) - float(self.ma_ref[0])) / atr
        return not (0.0 < dist <= self.p.ref_band_atr)

    def next(self):
        trend_ok = self.ma_fast[0] > self.ma_slow[0] and self.data.close[0] > self.ma_slow[0]

        if not self.position:
            if self.has_pending_order:
                return
            if trend_ok and self.entry_zone_ok():
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
