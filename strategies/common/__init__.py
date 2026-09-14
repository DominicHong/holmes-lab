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
    INITIAL_CASH,
    MIN_TRADE_GRAMS,
    POSITION_MODE,
    POSITION_PERCENT,
    PROJECT_ROOT,
    RISK_FREE_RATE,
    RISK_PER_TRADE,
    SIZE_CASH_BUFFER,
    SLIPPAGE_RATE,
    TRADING_DAYS_PER_YEAR,
)
from .data_loader import load_daily_csv
from .engine import run_backtest
from .indicators import BollingerBandwidth, RollingPercentile
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
    "INITIAL_CASH",
    "LongOnlyStrategyBase",
    "MIN_TRADE_GRAMS",
    "POSITION_MODE",
    "POSITION_PERCENT",
    "PROJECT_ROOT",
    "PositionSize",
    "RISK_FREE_RATE",
    "RISK_PER_TRADE",
    "RollingPercentile",
    "SIZE_CASH_BUFFER",
    "SLIPPAGE_RATE",
    "TRADING_DAYS_PER_YEAR",
    "TradeRecorder",
    "build_summary",
    "load_daily_csv",
    "run_backtest",
    "save_results",
    "save_summary",
]
