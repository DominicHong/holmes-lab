"""backtrader 回测引擎封装。

统一撮合与成本假设：
- 市价单默认在信号次日开盘成交；
- 手续费、滑点取自 common/constants.py；
- 默认启用 fund mode（基金净值口径，净值起点 100）；
- 自动挂载净值、交易记录、回撤、Sharpe、SQN 等 analyzer；
- plot=True 时挂载 backtrader 自带买/卖点 observer，以及自定义持仓 observer。
"""

from __future__ import annotations

import backtrader as bt
import pandas as pd

from .constants import (
    COMMISSION_RATE,
    FUND_MODE,
    FUND_START_VALUE,
    INITIAL_CASH,
    RISK_FREE_RATE,
    SLIPPAGE_RATE,
    TRADING_DAYS_PER_YEAR,
)
from .observers import PositionSize
from .performance import EquityCurve, TradeRecorder, build_summary


def make_cerebro(
    data: pd.DataFrame,
    strategy_cls: type[bt.Strategy],
    strategy_params: dict | None = None,
    initial_cash: float = INITIAL_CASH,
    fund_mode: bool = FUND_MODE,
    fund_start_value: float = FUND_START_VALUE,
    plot: bool = False,
) -> bt.Cerebro:
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(strategy_cls, **(strategy_params or {}))
    cerebro.adddata(bt.feeds.PandasData(dataname=data))
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=COMMISSION_RATE)
    cerebro.broker.set_slippage_perc(SLIPPAGE_RATE, slip_open=True)
    if fund_mode:
        cerebro.broker.set_fundmode(True, fundstartval=fund_start_value)

    cerebro.addanalyzer(EquityCurve, _name="equity")
    cerebro.addanalyzer(TradeRecorder, _name="trades")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(
        bt.analyzers.SharpeRatio,
        _name="sharpe",
        timeframe=bt.TimeFrame.Days,
        compression=1,
        riskfreerate=RISK_FREE_RATE,
        annualize=True,
        factor=TRADING_DAYS_PER_YEAR,
    )
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade_analysis")
    cerebro.addanalyzer(bt.analyzers.SQN, _name="sqn")

    if plot:
        cerebro.addobserver(bt.observers.BuySell, barplot=True)
        cerebro.addobserver(bt.observers.Broker)
        cerebro.addobserver(PositionSize)
    return cerebro


def run_backtest(
    strategy_cls: type[bt.Strategy],
    data: pd.DataFrame,
    strategy_params: dict | None = None,
    initial_cash: float = INITIAL_CASH,
    strategy_name: str | None = None,
    plot: bool = False,
):
    """运行单策略回测，返回 (strategy, summary)。"""
    cerebro = make_cerebro(data, strategy_cls, strategy_params, initial_cash, plot=plot)
    strategy = cerebro.run()[0]
    summary = build_summary(strategy, initial_cash, strategy_name)
    if plot:
        cerebro.plot(style="candlestick", iplot=False)
    return strategy, summary
