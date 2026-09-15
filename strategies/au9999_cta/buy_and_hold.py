"""买入并持有基准：首个交易日收盘确认，次日开盘买入，持有至回测结束。

用于与主动策略对比，展示标的本身的收益/回撤特征；不设止损与出场。
"""

from __future__ import annotations

from ..common.base import LongOnlyStrategyBase


class BuyAndHold(LongOnlyStrategyBase):
    def next(self):
        if not self.position and not self.has_pending_order:
            self.buy_next_open(reason="买入并持有")
