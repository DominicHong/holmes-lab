"""行情数据加载与增量更新。

数据格式约定见 docs/trade_strat/au9999_cta.md：
date, open, high, low, close, volume, amt
OHLC 单位元/克，volume 单位千克，amt 单位亿元。

增量更新用法（在仓库根目录执行）：
    python -m strategies.common.data_loader               # 更新至最近一个已收盘交易日
    python -m strategies.common.data_loader --dry-run     # 只预览增量，不写文件
    python -m strategies.common.data_loader --end 2026-09-01 --source http
数据源优先使用 .env 的 IFIND_USER / IFIND_PASSWORD 登录 iFinD SDK（THS_HD），
失败时自动回退到 IFIND_DATASOURCE_KEY 的 iFinD HTTP 数据接口。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import time
from pathlib import Path

import pandas as pd
from dotenv import dotenv_values

from .constants import AU9999_DAILY_CSV, BACKTEST_END, BACKTEST_START, PROJECT_ROOT

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
CSV_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amt"]

IFIND_CODE = "AU9999.SHG"
IFIND_FIELDS = ["open", "high", "low", "close", "volume", "amt"]
IFIND_HTTP_BASE = "https://quantapi.51ifind.com/api/v1"
MARKET_CLOSE = time(15, 30)
ENV = dotenv_values(PROJECT_ROOT / ".env")


def load_daily_csv(
    csv_path: str | Path,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """读取任意标的的日 K 线 CSV（date/open/high/low/close/volume[,...]）。

    返回以日期为索引、含 openinterest 列的 OHLCV 表。
    start/end 缺省时分别取 BACKTEST_START / BACKTEST_END（默认全区间）。
    """
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


# ---------- iFinD 数据抓取 ----------

def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame({col: pd.Series(dtype=float) for col in IFIND_FIELDS}, index=pd.DatetimeIndex([]))


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """统一为 index=日期、列为 IFIND_FIELDS 的表；成交额由元换算为亿元。"""
    df = df.rename(columns={"time": "date", "amount": "amt"}).copy()
    df["date"] = pd.to_datetime(df["date"])
    for col in IFIND_FIELDS:
        if col not in df.columns:
            raise RuntimeError(f"iFinD 返回数据缺少字段：{col}")
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["amt"] = df["amt"] / 1e8
    df = df.dropna(subset=IFIND_FIELDS)
    return df.sort_values("date").drop_duplicates("date", keep="last").set_index("date")[IFIND_FIELDS]


def _fetch_ifind_sdk(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    user, password = ENV.get("IFIND_USER"), ENV.get("IFIND_PASSWORD")
    if not user or not password:
        raise RuntimeError("缺少 IFIND_USER / IFIND_PASSWORD")
    from iFinDPy import THS_HD, THS_iFinDLogin, THS_iFinDLogout  # 延迟导入，无 SDK 环境也能用其他数据源

    login_code = THS_iFinDLogin(user, password)
    if login_code not in (0, -201):  # -201 表示账号已登录，可直接复用
        raise RuntimeError(f"iFinD SDK 登录失败（errorcode={login_code}）")
    try:
        result = THS_HD(
            IFIND_CODE,
            ";".join(IFIND_FIELDS),
            "",
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
    finally:
        if login_code == 0:
            THS_iFinDLogout()
    if result.errorcode != 0:
        raise RuntimeError(f"THS_HD 查询失败（errorcode={result.errorcode}）：{result.errmsg}")
    if result.data is None or result.data.empty:
        return _empty_frame()
    return _normalize(result.data)


def _post_json(url: str, headers: dict, payload: dict) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_ifind_http(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    key = ENV.get("IFIND_DATASOURCE_KEY")
    if not key:
        raise RuntimeError("缺少 IFIND_DATASOURCE_KEY")
    token = _post_json(
        f"{IFIND_HTTP_BASE}/get_access_token",
        {"Content-Type": "application/json", "refresh_token": key},
        {},
    )
    if token.get("errorcode") != 0:
        raise RuntimeError(
            f"iFinD 获取 access_token 失败（errorcode={token.get('errorcode')}）：{token.get('errmsg')}"
        )
    result = _post_json(
        f"{IFIND_HTTP_BASE}/cmd_history_quotation",
        {
            "Content-Type": "application/json",
            "access_token": token["data"]["access_token"],
            "ifindlang": "cn",
        },
        {
            "codes": IFIND_CODE,
            "indicators": "open,high,low,close,volume,amount",
            "startdate": start.strftime("%Y-%m-%d"),
            "enddate": end.strftime("%Y-%m-%d"),
        },
    )
    if result.get("errorcode") != 0:
        raise RuntimeError(
            f"iFinD 历史行情查询失败（errorcode={result.get('errorcode')}）：{result.get('errmsg')}"
        )
    tables = result.get("tables") or []
    if not tables or not tables[0].get("table"):
        return _empty_frame()
    table = tables[0]
    df = pd.DataFrame(table["table"])
    df["date"] = table["time"]
    return _normalize(df)


def fetch_au9999_daily(start, end, source: str = "auto") -> pd.DataFrame:
    """通过 iFinD 获取 AU9999 区间日线，返回 index=日期、amt 单位为亿元的行情表。"""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    fetchers = {"sdk": _fetch_ifind_sdk, "http": _fetch_ifind_http}
    if source in fetchers:
        return fetchers[source](start, end)
    if source != "auto":
        raise ValueError(f"未知数据源：{source}")
    errors = []
    for name in ("sdk", "http"):
        try:
            return fetchers[name](start, end)
        except Exception as exc:  # 登录/权限/网络失败时回退到下一个数据源
            errors.append(f"{name}: {exc}")
    raise RuntimeError("iFinD 数据获取失败 -> " + "；".join(errors))


# ---------- 增量更新 ----------

def _last_csv_date(csv_path: Path) -> pd.Timestamp | None:
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    dates = pd.to_datetime(df[CSV_COLUMNS[0]], errors="coerce").dropna()
    return dates.max() if len(dates) else None


def _last_closed_day() -> pd.Timestamp:
    now = pd.Timestamp.now()
    if now.time() < MARKET_CLOSE:
        return now.normalize() - pd.Timedelta(days=1)
    return now.normalize()


def _format_number(value) -> str:
    return f"{float(value):.10g}"


def _append_rows(csv_path: Path, rows: pd.DataFrame) -> None:
    if csv_path.exists():
        lines = csv_path.read_text(encoding="utf-8").splitlines()
        while lines and not lines[-1].strip(",\t "):  # 清掉文件末尾的空行
            lines.pop()
    else:
        lines = []
    if not lines:
        lines = [",".join(CSV_COLUMNS)]
    for date, row in rows.iterrows():
        cells = [f"{date.year}/{date.month}/{date.day}"] + [
            _format_number(row[col]) for col in IFIND_FIELDS
        ]
        lines.append(",".join(cells))
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_au9999_daily(
    csv_path: str | Path = AU9999_DAILY_CSV,
    end: str | None = None,
    source: str = "auto",
    dry_run: bool = False,
) -> pd.DataFrame:
    """把 iFinD 上 csv 最后日期之后的增量行情追加到 csv，返回新增行。

    end 缺省为最近一个已收盘交易日（15:30 前运行不含当天），避免写入盘中未完成 K 线。
    """
    csv_path = Path(csv_path)
    last_date = _last_csv_date(csv_path)
    end_ts = pd.Timestamp(end) if end is not None else _last_closed_day()
    start_ts = end_ts if last_date is None else last_date + pd.Timedelta(days=1)
    if start_ts > end_ts:
        return _empty_frame()
    incremental = fetch_au9999_daily(start_ts, end_ts, source=source)
    if last_date is not None:
        incremental = incremental.loc[incremental.index > last_date]
    if not dry_run and not incremental.empty:
        _append_rows(csv_path, incremental)
    return incremental


# ---------- 命令行 ----------

def _cli() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="AU9999 日线增量更新（数据源：iFinD）")
    parser.add_argument("--csv", default=str(AU9999_DAILY_CSV), help="目标 CSV 路径")
    parser.add_argument("--end", default=None, help="截止日期 YYYY-MM-DD，默认最近一个已收盘交易日")
    parser.add_argument("--source", choices=("auto", "sdk", "http"), default="auto", help="数据源")
    parser.add_argument("--dry-run", action="store_true", help="只预览增量，不写入 CSV")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    last_date = _last_csv_date(csv_path)
    print(f"目标文件：{csv_path}（最后日期：{last_date.date() if last_date is not None else '无'}）")
    added = update_au9999_daily(csv_path, end=args.end, source=args.source, dry_run=args.dry_run)
    if added.empty:
        print("没有需要更新的数据")
        return 0
    print(f"新增 {len(added)} 行（amt 单位亿元）：")
    print(added.to_string())
    print("--dry-run：仅预览，未写入" if args.dry_run else f"已写入 {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
