"""纯多头策略基类。

统一实现：
- 只做多：出场一律 close()，绝不反手做空；
- 信号收盘确认、次日开盘成交（backtrader 市价单默认撮合行为）；
- 仓位计算（固定克数 / 可用现金比例 / 风险预算）；
- 订单状态管理与持仓期成交记录。
"""

from __future__ import annotations

import backtrader as bt

from .constants import (
    COMMISSION_RATE,
    FIXED_GRAMS,
    MIN_TRADE_GRAMS,
    POSITION_MODE,
    POSITION_PERCENT,
    RISK_PER_TRADE,
    SLIPPAGE_RATE,
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
        self._pending_entry = False
        self._entry_reason = ""

    # ---------- 日志 ----------
    def log(self, message: str):
        if self.p.verbose:
            print(f"{self.data.datetime.date(0)} {self.__class__.__name__}: {message}")

    # ---------- 仓位 ----------
    def risk_per_gram(self) -> float | None:
        """子类可覆盖：返回每克对应的止损风险（元/克），供风险预算模式使用。"""
        return None

    def size_for_cash(self, buy_cash: float, price: float) -> float:
        """按含滑点与手续费的实际成交成本，把买入金额折算成克数。"""
        cost_per_gram = price * (1.0 + SLIPPAGE_RATE) * (1.0 + COMMISSION_RATE)
        grams = buy_cash / cost_per_gram
        return float(int(grams / MIN_TRADE_GRAMS) * MIN_TRADE_GRAMS)

    def calc_size(self, price: float) -> float:
        mode = self.p.position_mode
        if mode == "fixed_grams":
            return float(int(self.p.fixed_grams / MIN_TRADE_GRAMS) * MIN_TRADE_GRAMS)
        if mode == "risk_budget":
            risk_per_gram = self.risk_per_gram()
            if not risk_per_gram or risk_per_gram <= 0:
                return 0.0
            grams = self.broker.getvalue() * self.p.risk_per_trade / risk_per_gram
            return float(int(grams / MIN_TRADE_GRAMS) * MIN_TRADE_GRAMS)
        # percent_equity：只控制买入金额占可用现金的比例，克数由金额反推
        buy_cash = self.broker.getcash() * self.p.position_percent
        return self.size_for_cash(buy_cash, price)

    @property
    def has_pending_order(self) -> bool:
        return self.order is not None

    # ---------- 下单 ----------
    def buy_next_open(self, reason: str = ""):
        """仅登记入场意图；实际定量与下单在次日 next_open（cheat_on_open）完成。"""
        if self.position or self.has_pending_order or self._pending_entry:
            return
        self._pending_entry = True
        self._entry_reason = reason

    def next_open(self):
        """cheat_on_open：开盘前按实际开盘价定量并提交买入。"""
        if not self._pending_entry:
            return
        self._pending_entry = False
        if self.position or self.has_pending_order:
            return
        size = self.calc_size(float(self.data.open[0]))
        if size <= 0:
            return
        self.order = self.buy(size=size)
        self.log(f"BUY {size:.0f}g @open ({self._entry_reason})")

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
