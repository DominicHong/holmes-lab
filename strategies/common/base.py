"""纯多头策略基类。

统一实现：
- 只做多：出场一律 close()，绝不反手做空；
- 信号收盘确认、次日开盘成交（backtrader 市价单默认撮合行为）；
- 仓位计算（固定克数 / 总资金比例 / 风险预算）；
- 订单状态管理与持仓期成交记录。
"""

from __future__ import annotations

import backtrader as bt

from .constants import (
    FIXED_GRAMS,
    MIN_TRADE_GRAMS,
    POSITION_MODE,
    POSITION_PERCENT,
    RISK_PER_TRADE,
    SIZE_CASH_BUFFER,
)


class LongOnlyStrategyBase(bt.Strategy):
    params = (
        ("position_mode", POSITION_MODE),
        ("fixed_grams", FIXED_GRAMS),
        ("position_percent", POSITION_PERCENT),
        ("risk_per_trade", RISK_PER_TRADE),
        ("verbose", False),
    )

    def __init__(self):
        self.order = None
        self.entry_price = None
        self.entry_bar = None
        self.entry_commission = 0.0
        self.stop_price = None

    # ---------- 日志 ----------
    def log(self, message: str):
        if self.p.verbose:
            print(f"{self.data.datetime.date(0)} {self.__class__.__name__}: {message}")

    # ---------- 仓位 ----------
    def risk_per_gram(self) -> float | None:
        """子类可覆盖：返回每克对应的止损风险（元/克），供风险预算模式使用。"""
        return None

    def calc_size(self, price: float) -> float:
        mode = self.p.position_mode
        if mode == "fixed_grams":
            grams = self.p.fixed_grams
        elif mode == "risk_budget":
            risk_per_gram = self.risk_per_gram()
            if not risk_per_gram or risk_per_gram <= 0:
                return 0.0
            grams = self.broker.getvalue() * self.p.risk_per_trade / risk_per_gram
        else:  # percent_equity
            budget = self.broker.getvalue() * self.p.position_percent
            grams = budget / (price * (1.0 + SIZE_CASH_BUFFER))
        return float(int(grams / MIN_TRADE_GRAMS) * MIN_TRADE_GRAMS)

    @property
    def has_pending_order(self) -> bool:
        return self.order is not None

    # ---------- 下单 ----------
    def buy_next_open(self, reason: str = ""):
        if self.position or self.has_pending_order:
            return
        size = self.calc_size(float(self.data.close[0]))
        if size <= 0:
            return
        self.order = self.buy(size=size)
        self.log(f"BUY {size:.0f}g @next open ({reason})")

    def sell_next_open(self, reason: str = ""):
        if not self.position or self.has_pending_order:
            return
        self.order = self.close()
        self.log(f"SELL {self.position.size:.0f}g @next open ({reason})")

    # ---------- 回调 ----------
    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.entry_price = order.executed.price
                self.entry_bar = len(self.data)
                self.entry_commission = order.executed.comm
                self.stop_price = None
            else:
                self.entry_price = None
                self.entry_bar = None
                self.stop_price = None
                self.on_position_closed()
        self.order = None

    def on_position_closed(self):
        """子类可覆盖：清理持仓期间维护的状态。"""
