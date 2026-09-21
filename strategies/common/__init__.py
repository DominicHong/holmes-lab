"""全策略公用的常量、数据、指标、基类与回测工具。"""

from .base import LongOnlyStrategyBase
from .constants import (
    AU9999_DAILY_CSV,
    BACKTEST_END,
    BACKTEST_START,
    COMMISSION_RATE,
    DATA_DIR,
    FIXED_GRAMS,
    FUND_MODE,
    FUND_START_VALUE,
    GOLD_ETF_DAILY_CSV,
    GOLD_ETF_MINUTES_CSV,
    INITIAL_CASH,
    MIN_TRADE_GRAMS,
    POSITION_MODE,
    POSITION_PERCENT,
    PROJECT_ROOT,
    RISK_FREE_RATE,
    RISK_PER_TRADE,
    SLIPPAGE_RATE,
    TRADING_DAYS_PER_YEAR,
)
from .engine import run_backtest
from .feeds import IntradaySnapshotData
from .indicators import BollingerBandwidth, OnBalanceVolume, RollingPercentile
from .observers import PositionSize
from .performance import EquityCurve, TradeRecorder, build_summary, save_results, save_summary

__all__ = [
    "AU9999_DAILY_CSV",
    "BACKTEST_END",
    "BACKTEST_START",
    "BollingerBandwidth",
    "COMMISSION_RATE",
    "DATA_DIR",
    "EquityCurve",
    "FIXED_GRAMS",
    "FUND_MODE",
    "FUND_START_VALUE",
    "GOLD_ETF_DAILY_CSV",
    "GOLD_ETF_MINUTES_CSV",
    "INITIAL_CASH",
    "IntradaySnapshotData",
    "LongOnlyStrategyBase",
    "MIN_TRADE_GRAMS",
    "OnBalanceVolume",
    "POSITION_MODE",
    "POSITION_PERCENT",
    "PROJECT_ROOT",
    "PositionSize",
    "RISK_FREE_RATE",
    "RISK_PER_TRADE",
    "RollingPercentile",
    "SLIPPAGE_RATE",
    "TRADING_DAYS_PER_YEAR",
    "TradeRecorder",
    "build_summary",
    "load_daily_csv",
    "load_minute_snapshots",
    "read_minute_quotes",
    "run_backtest",
    "save_results",
    "save_summary",
    "update_daily",
]

_LAZY_NAMES = {"load_daily_csv", "load_minute_snapshots", "read_minute_quotes", "update_daily"}


def __getattr__(name: str):
    """延迟导入 data_loader，避免 python -m 执行该模块时被包 __init__ 提前加载（runpy 告警）。"""
    if name in _LAZY_NAMES:
        from . import data_loader

        return getattr(data_loader, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
