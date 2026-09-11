"""行情数据加载。

数据格式约定见 docs/trade_strat/au9999_cta.md：
date, open, high, low, close, volume, amt
OHLC 单位元/克，volume 单位千克，amt 单位亿元。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .constants import AU9999_DAILY_CSV, BACKTEST_END, BACKTEST_START

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


def load_au9999_daily(
    csv_path: str | Path = AU9999_DAILY_CSV,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """读取 AU9999 日 K 线，返回以日期为索引、含 openinterest 列的 OHLCV 表。"""
    df = pd.read_csv(csv_path)
    df.columns = [str(col).strip().lower() for col in df.columns]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    df = df.sort_values("date").drop_duplicates(subset="date", keep="last")
    df = df.set_index("date")
    for col in OHLCV_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=OHLCV_COLUMNS)
    df["openinterest"] = 0.0

    start = start or BACKTEST_START
    end = end or BACKTEST_END
    if start is not None:
        df = df[df.index >= pd.Timestamp(start)]
    if end is not None:
        df = df[df.index <= pd.Timestamp(end)]

    return df[OHLCV_COLUMNS + ["openinterest"]]
