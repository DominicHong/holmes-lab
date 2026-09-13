"""绩效统计与结果输出。"""

from __future__ import annotations

from pathlib import Path

import backtrader as bt
import pandas as pd

from .constants import TRADING_DAYS_PER_YEAR


class EquityCurve(bt.Analyzer):
    """逐日记录账户净值；fund mode 下同时记录基金净值（起点为 fundstartval）。"""

    def start(self):
        self.dates = []
        self.values = []
        self.fund_values = []

    def next(self):
        self.dates.append(self.strategy.data.datetime.date(0))
        self.values.append(self.strategy.broker.getvalue())
        self.fund_values.append(self.strategy.broker.fundvalue)

    def get_analysis(self):
        return {
            "dates": self.dates,
            "values": self.values,
            "fund_values": self.fund_values,
        }


class TradeRecorder(bt.Analyzer):
    """逐笔记录已平仓交易。"""

    def start(self):
        self.trades = []
        self._open_size = {}

    def notify_trade(self, trade):
        if trade.justopened:
            self._open_size[trade.ref] = trade.size
        if not trade.isclosed:
            return
        self.trades.append(
            {
                "open_date": bt.num2date(trade.dtopen).date(),
                "close_date": bt.num2date(trade.dtclose).date(),
                "size": self._open_size.pop(trade.ref, trade.size),
                "price_open": trade.price,
                "pnl": trade.pnl,
                "pnl_net": trade.pnlcomm,
                "commission": trade.commission,
                "bars_held": trade.barlen,
            }
        )

    def get_analysis(self):
        return self.trades


_MISSING = object()


def _deep_get(mapping, *keys, default=None):
    current = mapping
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, _MISSING)
        if current is _MISSING:
            return default
    return current


def build_summary(strategy: bt.Strategy, initial_cash: float, strategy_name: str | None = None) -> dict:
    """把各 analyzer 的结果汇总为一行绩效指标。"""
    equity = strategy.analyzers.equity.get_analysis()
    dates, values = equity["dates"], equity["values"]
    final_value = values[-1] if values else initial_cash
    start_date = dates[0] if dates else None
    end_date = dates[-1] if dates else None

    total_return = final_value / initial_cash - 1.0
    years = (end_date - start_date).days / 365.25 if dates else 0.0
    if years > 0 and final_value > 0:
        cagr = (final_value / initial_cash) ** (1.0 / years) - 1.0
    else:
        cagr = 0.0

    drawdown = strategy.analyzers.drawdown.get_analysis()
    max_drawdown = _deep_get(drawdown, "max", "drawdown", default=0.0)

    sharpe_analysis = strategy.analyzers.sharpe.get_analysis()
    sharpe = sharpe_analysis.get("sharperatio")

    sqn = _deep_get(strategy.analyzers.sqn.get_analysis(), "sqn")

    trade_analysis = strategy.analyzers.trade_analysis.get_analysis()
    trades = strategy.analyzers.trades.get_analysis()
    closed = _deep_get(trade_analysis, "total", "closed", default=0)
    won = _deep_get(trade_analysis, "won", "total", default=0)
    lost = _deep_get(trade_analysis, "lost", "total", default=0)
    won_pnl = _deep_get(trade_analysis, "won", "pnl", "total", default=0.0)
    lost_pnl = _deep_get(trade_analysis, "lost", "pnl", "total", default=0.0)

    win_rate = won / closed if closed else 0.0
    if lost_pnl:
        profit_factor = won_pnl / abs(lost_pnl)
    else:
        profit_factor = float("inf") if won_pnl > 0 else 0.0
    net_pnl = _deep_get(trade_analysis, "pnl", "net", "total", default=0.0)

    return {
        "strategy": strategy_name or strategy.__class__.__name__,
        "start": start_date,
        "end": end_date,
        "years": round(years, 2),
        "final_value": round(final_value, 2),
        "total_return": round(total_return, 4),
        "cagr": round(cagr, 4),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "sqn": round(sqn, 3) if sqn is not None else None,
        "trades": closed,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else None,
        "avg_pnl_net": round(net_pnl / closed, 2) if closed else 0.0,
        "commission": round(sum(t["commission"] for t in trades), 2),
    }


def save_results(strategy_name: str, strategy: bt.Strategy, results_dir: str | Path) -> Path:
    """保存单策略净值曲线与逐笔交易到指定策略族的 results 目录。"""
    out_dir = Path(results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    equity = strategy.analyzers.equity.get_analysis()
    pd.DataFrame(
        {
            "date": equity["dates"],
            "equity": equity["values"],
            "fund_value": equity["fund_values"],
        }
    ).to_csv(out_dir / f"{strategy_name}_equity.csv", index=False)
    pd.DataFrame(strategy.analyzers.trades.get_analysis()).to_csv(
        out_dir / f"{strategy_name}_trades.csv", index=False
    )
    return out_dir


def save_summary(summary: pd.DataFrame, results_dir: str | Path) -> Path:
    out_dir = Path(results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out_dir / "summary.csv", index=False)
    return out_dir
