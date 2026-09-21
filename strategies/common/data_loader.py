"""行情数据加载与增量更新。

数据格式约定见 docs/trade_strat/au9999_cta.md：
date, open, high, low, close, volume, amt
AU9999：OHLC 单位元/克，volume 单位千克，amt 单位亿元；
518880.SH：OHLC 单位元/份，volume 单位份，amt 单位亿元。

增量更新用法（在仓库根目录执行）：
    python -m strategies.common.data_loader                    # 更新 AU9999 至最近一个已收盘交易日
    python -m strategies.common.data_loader 518880             # 更新 518880.SH 黄金 ETF 行情
    python -m strategies.common.data_loader 518880 --dry-run   # 只预览增量，不写文件
    python -m strategies.common.data_loader --end 2026-09-01 --source http
数据源优先使用 .env 的 IFIND_USER / IFIND_PASSWORD 登录 iFinD SDK（THS_HD），
失败时自动回退到 IFIND_DATASOURCE_KEY 的 iFinD HTTP 数据接口。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from dataclasses import dataclass
from datetime import time
from pathlib import Path

import pandas as pd
from dotenv import dotenv_values

from .constants import (
    AU9999_DAILY_CSV,
    BACKTEST_END,
    BACKTEST_START,
    GOLD_ETF_DAILY_CSV,
    GOLD_ETF_MINUTES_CSV,
    PROJECT_ROOT,
)
from .indicators import build_ma_cross_signals

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
CSV_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amt"]

IFIND_FIELDS = ["open", "high", "low", "close", "volume", "amt"]
IFIND_HTTP_BASE = "https://quantapi.51ifind.com/api/v1"
ENV = dotenv_values(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Dataset:
    """一个可增量更新的日线数据集。"""

    name: str
    ifind_code: str
    csv_path: Path
    market_close: time


DATASETS: dict[str, Dataset] = {
    "au9999": Dataset("au9999", "AU9999.SHG", AU9999_DAILY_CSV, time(15, 30)),
    "518880": Dataset("518880", "518880.SH", GOLD_ETF_DAILY_CSV, time(15, 0)),
}


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


# ---------- 分钟线快照（s1c 盘中策略） ----------

MINUTE_SNAPSHOT_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "openinterest",
    "signal_close",
    "sig_high",
    "sig_low",
    "sma_fast",
    "sma_slow",
    "atr",
    "cross_down",
]


def read_minute_quotes(csv_path: str | Path = GOLD_ETF_MINUTES_CSV) -> pd.DataFrame:
    """读取分钟线并打上 day（日期）/ hm（时点）标签，供不同信号与成交时点复用。"""
    df = pd.read_csv(
        csv_path,
        usecols=["date", "open", "high", "low", "close", "volume"],
        parse_dates=["date"],
    )
    df = df.sort_values("date").drop_duplicates(subset="date", keep="last")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    df["day"] = df["date"].dt.normalize()
    df["hm"] = df["date"].dt.strftime("%H:%M")
    return df


def _shift_time(hm: str, minutes: int) -> str:
    hour, minute = map(int, hm.split(":"))
    total = (hour * 60 + minute + minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def build_minute_snapshots(
    quotes: pd.DataFrame,
    signal_time: str = "14:45",
    exec_delay_minutes: int = 2,
) -> pd.DataFrame:
    """把分钟线聚合成 s1c 的日频快照（尚未计算指标）：

    - open  = 信号时点后 exec_delay 分钟的收盘价（成交参考价，回测中经滑点成交）；
    - high/low = 9:30 ~ 成交时点的最高/最低（供撮合时的滑点边界使用）；
    - close = 15:00 收盘价（净值估值口径，与日线回测一致）；
    - signal_close / sig_high / sig_low = 信号时点的快照（当作当日“收盘价”算指标）。
    """
    exec_time = _shift_time(signal_time, exec_delay_minutes)
    eod = quotes[quotes["hm"] == "15:00"].set_index("day")
    sig = quotes[quotes["hm"] == signal_time].set_index("day")
    exe = quotes[quotes["hm"] == exec_time].set_index("day")
    up_to_sig = quotes[quotes["hm"] <= signal_time]
    up_to_exec = quotes[quotes["hm"] <= exec_time]

    snap = pd.DataFrame(
        {
            "open": exe["close"],
            "high": up_to_exec.groupby("day")["high"].max(),
            "low": up_to_exec.groupby("day")["low"].min(),
            "close": eod["close"],
            "volume": eod["volume"],
            "signal_close": sig["close"],
            "sig_high": up_to_sig.groupby("day")["high"].max(),
            "sig_low": up_to_sig.groupby("day")["low"].min(),
        }
    )
    snap["openinterest"] = 0.0
    snap = snap.dropna(subset=["open", "high", "low", "close", "signal_close", "sig_high", "sig_low"])
    snap = snap.sort_index()
    snap.index.name = "date"
    return snap


def load_minute_snapshots(
    csv_path: str | Path = GOLD_ETF_MINUTES_CSV,
    start: str | None = None,
    end: str | None = None,
    signal_time: str = "14:45",
    exec_delay_minutes: int = 2,
    fast_period: int = 30,
    slow_period: int = 90,
    atr_period: int = 14,
) -> pd.DataFrame:
    """读取分钟线并生成带预计算指标的 s1c 日频快照。

    backtrader 在 cheat_on_open 的 next_open 中尚未更新指标，因此 SMA/ATR/死叉
    在装载阶段用 strategies.common.indicators 的 pandas 版本算好（与 backtrader 同口径）。
    start/end 缺省时分别取 BACKTEST_START / BACKTEST_END。
    """
    snap = build_minute_snapshots(read_minute_quotes(csv_path), signal_time, exec_delay_minutes)
    _, cross_down, sma_fast, sma_slow, atr = build_ma_cross_signals(
        snap["signal_close"],
        snap["sig_high"],
        snap["sig_low"],
        fast_period=fast_period,
        slow_period=slow_period,
        atr_period=atr_period,
    )
    snap["sma_fast"] = sma_fast
    snap["sma_slow"] = sma_slow
    snap["atr"] = atr
    snap["cross_down"] = cross_down.astype(float)

    start = start or BACKTEST_START
    end = end or BACKTEST_END
    if start is not None:
        snap = snap[snap.index >= pd.Timestamp(start)]
    if end is not None:
        snap = snap[snap.index <= pd.Timestamp(end)]
    return snap[MINUTE_SNAPSHOT_COLUMNS]


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


def _fetch_ifind_sdk(code: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    user, password = ENV.get("IFIND_USER"), ENV.get("IFIND_PASSWORD")
    if not user or not password:
        raise RuntimeError("缺少 IFIND_USER / IFIND_PASSWORD")
    from iFinDPy import THS_HD, THS_iFinDLogin, THS_iFinDLogout  # 延迟导入，无 SDK 环境也能用其他数据源

    login_code = THS_iFinDLogin(user, password)
    if login_code not in (0, -201):  # -201 表示账号已登录，可直接复用
        raise RuntimeError(f"iFinD SDK 登录失败（errorcode={login_code}）")
    try:
        result = THS_HD(
            code,
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


def _fetch_ifind_http(code: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
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
            "codes": code,
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


def fetch_daily(code: str, start, end, source: str = "auto") -> pd.DataFrame:
    """通过 iFinD 获取指定代码的区间日线，返回 index=日期、amt 单位为亿元的行情表。"""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    fetchers = {"sdk": _fetch_ifind_sdk, "http": _fetch_ifind_http}
    if source in fetchers:
        return fetchers[source](code, start, end)
    if source != "auto":
        raise ValueError(f"未知数据源：{source}")
    errors = []
    for name in ("sdk", "http"):
        try:
            return fetchers[name](code, start, end)
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


def _last_closed_day(market_close: time) -> pd.Timestamp:
    now = pd.Timestamp.now()
    if now.time() < market_close:
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


def update_daily(
    dataset: str | Dataset = "au9999",
    csv_path: str | Path | None = None,
    end: str | None = None,
    source: str = "auto",
    dry_run: bool = False,
) -> pd.DataFrame:
    """把 iFinD 上 csv 最后日期之后的增量行情追加到 csv，返回新增行。

    dataset 取 DATASETS 的键名（au9999 / 518880）或 Dataset 对象，csv_path 缺省用数据集自带路径。
    end 缺省为最近一个已收盘交易日（各自收盘前运行不含当天），避免写入盘中未完成 K 线。
    """
    ds = DATASETS[dataset] if isinstance(dataset, str) else dataset
    csv_path = Path(csv_path) if csv_path is not None else ds.csv_path
    last_date = _last_csv_date(csv_path)
    end_ts = pd.Timestamp(end) if end is not None else _last_closed_day(ds.market_close)
    start_ts = end_ts if last_date is None else last_date + pd.Timedelta(days=1)
    if start_ts > end_ts:
        return _empty_frame()
    incremental = fetch_daily(ds.ifind_code, start_ts, end_ts, source=source)
    if last_date is not None:
        incremental = incremental.loc[incremental.index > last_date]
    if not dry_run and not incremental.empty:
        _append_rows(csv_path, incremental)
    return incremental


# ---------- 命令行 ----------

def _cli() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="日线增量更新（数据源：iFinD）")
    parser.add_argument(
        "dataset",
        nargs="?",
        choices=tuple(DATASETS),
        default="au9999",
        help="数据集：au9999=AU9999.SHG 黄金现货，518880=518880.SH 黄金 ETF（默认 au9999）",
    )
    parser.add_argument("--csv", default=None, help="目标 CSV 路径（默认数据集自带路径）")
    parser.add_argument("--end", default=None, help="截止日期 YYYY-MM-DD，默认最近一个已收盘交易日")
    parser.add_argument("--source", choices=("auto", "sdk", "http"), default="auto", help="数据源")
    parser.add_argument("--dry-run", action="store_true", help="只预览增量，不写入 CSV")
    args = parser.parse_args()

    ds = DATASETS[args.dataset]
    csv_path = Path(args.csv) if args.csv is not None else ds.csv_path
    last_date = _last_csv_date(csv_path)
    print(f"数据集：{ds.name}（iFinD：{ds.ifind_code}，收盘：{ds.market_close.strftime('%H:%M')}）")
    print(f"目标文件：{csv_path}（最后日期：{last_date.date() if last_date is not None else '无'}）")
    added = update_daily(ds, csv_path=csv_path, end=args.end, source=args.source, dry_run=args.dry_run)
    if added.empty:
        print("没有需要更新的数据")
        return 0
    print(f"新增 {len(added)} 行（amt 单位亿元）：")
    print(added.to_string())
    print("--dry-run：仅预览，未写入" if args.dry_run else f"已写入 {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
