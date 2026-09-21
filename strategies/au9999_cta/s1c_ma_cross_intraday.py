"""策略一C：双均线趋势跟踪 + ATR 移动止损 + 盘中提前成交 + T+2 再入场（IntradayMaCrossTrailingStop）。

在策略一A（s1a）基础上只改执行时点，其余规则完全一致：

- 信号：每日 14:45 快照（把 14:45 收盘价当作当日“收盘”，high/low 取 9:30~14:45 区间）
  计算 SMA30 / SMA90 / ATR(14)：趋势向上（SMA30 > SMA90 且收盘价 > SMA90）时空仓即入场；
  移动止损 = max(入场价 − 2.5×ATR(入场日), 14:45 最高收盘 − 2.5×ATR(入场日))，只上移不下移；
  收盘价触及止损或死叉确认即出场；
- 成交：信号成立当日 14:47 分钟收盘价（含单边手续费 0.02% + 滑点 0.02%），
  比 s1a 的“次日开盘”快 17.5 小时，用于规避止损/死叉后的隔夜跳空；
- 再入场：止损或死叉卖出后最早 T+2 日 14:45 重新判断（T+2 日 14:47 成交），
  过滤掉止损后的连环反手（reentry_delay 参数，1 即次日）；
- 仓位：percent_equity 100%（common/constants.py），克数向下取整；不设固定止盈，不加仓。

【与 s1a 的差异对照】

| 模块 | s1a（日线） | s1c（盘中） |
| --- | --- | --- |
| 信号时点 | 15:00 收盘 | 14:45 快照 |
| 成交时点 | 次日 09:30 开盘 | 当日 14:47 |
| 止损后再入场 | 趋势仍向上即次日开盘反手 | 最早 T+2 日 14:45 再判断 |
| 其它 | 相同（趋势过滤 / 移动止损 / 死叉出场 / 仓位） | 相同 |

【数据与实现】

- 数据：data/518880.sh.minutes.csv，由 strategies.common.data_loader.load_minute_snapshots
  聚合为日频快照；SMA/ATR/死叉在装载阶段预计算（backtrader 的 cheat_on_open 模式下
  next_open 中指标尚未更新），公式与 backtrader 同口径。
  指标周期在装载时固定为 SMA 30/90、ATR 14，与 s1a 当前参数一致，改动需同步两处。
- 撮合：引擎启用 cheat_on_open，next_open 中按当日 14:47 的 open 价定量并成交。

【回测（518880.SH，2018-01-02 ~ 2026-09-01，成本单边 0.02% 费 + 0.02% 滑点）】

- s1c        ：总收益 222.5%，最大回撤 18.4%，Sharpe 1.19，53 笔，胜率 52.8%；
- s1a 日线基准：总收益 234.9%，最大回撤 25.1%，Sharpe 1.12，53 笔，胜率 58.5%。
- 差异集中在隔夜跳空（窗口前预热口径）：2026 高位急跌区间 s1c -10.1% / 回撤 13.5%，
  s1a 日线 -12.4% / 回撤 22.1%（同为 2026-01-30 触及止损，日线只能 02-02 开盘成交）；
  代价是常态年份因 T+2 延迟再入场而略跑输。
- 复现：python -m strategies.au9999_cta.run --strategies s1c_ma_cross_intraday --csv data/518880.SH.csv
"""

from __future__ import annotations

import backtrader as bt

from ..common.base import LongOnlyStrategyBase


class IntradayMaCrossTrailingStop(LongOnlyStrategyBase):
    """s1a 的盘中版：14:45 信号 / 14:47 成交 / 卖出后 T+2 再入场。"""

    data_kind = "minute_snapshot"

    params = (
        ("initial_atr_mult", 2.5),   # 初始止损距离
        ("trail_atr_mult", 2.5),     # 移动止损距离
        ("reentry_delay", 2),        # 卖出后最早可在第几个交易日再入场（2 = T+2）
    )

    def __init__(self):
        super().__init__()
        self.entry_atr = None
        self.peak_close = None
        self.exit_bar = None

    # ---------- 信号（读预计算快照线） ----------
    def trend_ok(self) -> bool:
        fast = float(self.data.sma_fast[0])
        slow = float(self.data.sma_slow[0])
        close = float(self.data.signal_close[0])
        if fast != fast or slow != slow or close != close:  # 预热期 NaN
            return False
        return fast > slow and close > slow

    def cross_down(self) -> bool:
        return float(self.data.cross_down[0]) > 0

    # ---------- 决策与成交 ----------
    def next_open(self):
        """cheat_on_open 下本 bar（14:45 信号 + 15:00 估值）完整可见，
        此处下单一律按本 bar 的 open（当日 14:47）撮合。"""
        if self.has_pending_order:
            return

        if not self.position:
            if self.exit_bar is not None and len(self.data) - self.exit_bar < self.p.reentry_delay:
                return
            if self.trend_ok():
                size = self.calc_size(float(self.data.open[0]))
                if size > 0:
                    self.order = self.buy(size=size)
                    reason = "趋势向上 + 再入场" if self.exit_bar is not None else "趋势向上"
                    self.log(f"BUY {size:.0f}g @14:47 ({reason})")
            return

        close = float(self.data.signal_close[0])
        self.peak_close = max(self.peak_close, close)
        self.stop_price = max(
            self.stop_price, self.peak_close - self.p.trail_atr_mult * self.entry_atr
        )
        if close <= self.stop_price:
            self.order = self.close()
            self.log(f"SELL {self.position.size:.0f}g @14:47 (ATR移动止损)")
        elif self.cross_down():
            self.order = self.close()
            self.log(f"SELL {self.position.size:.0f}g @14:47 (死叉)")

    # ---------- 持仓状态 ----------
    def notify_order(self, order):
        completed = order.status == order.Completed
        was_buy = completed and order.isbuy()
        super().notify_order(order)
        if not completed:
            return
        if was_buy:
            self.entry_atr = float(self.data.atr[0])          # 入场日 14:45 快照 ATR
            self.peak_close = float(self.data.signal_close[0])  # 入场日 14:45 快照收盘
            self.stop_price = self.entry_price - self.p.initial_atr_mult * self.entry_atr
        else:
            self.exit_bar = len(self.data)

    def on_position_closed(self):
        self.entry_atr = None
        self.peak_close = None
