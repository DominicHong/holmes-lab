"""自定义 observer。

backtrader 只自带净值/买卖点等 observer，没有持仓数量 observer，
因此这里补一个 PositionSize，把每根 K 线的持仓克数画成独立子图。
"""

from __future__ import annotations

import backtrader as bt


class PositionSize(bt.Observer):
    """逐根 K 线记录当前持仓数量（au9999 单位为克）。"""

    _stclock = True

    lines = ("position",)

    plotinfo = dict(plot=True, subplot=True, plotname="Position", plotymargin=0.05)
    plotlines = dict(position=dict(_name="position(g)"))

    def next(self):
        self.lines.position[0] = float(self._owner.position.size)
