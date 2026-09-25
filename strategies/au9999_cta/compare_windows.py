"""按文档《回测验证》口径，比较任意日线/盘中策略在各区间中的表现。

用法（在仓库根目录执行）：
    python -m strategies.au9999_cta.compare_windows
    python -m strategies.au9999_cta.compare_windows --strategies s1a_ma_cross_trailing s1b_vol_target_ma_cross
    python -m strategies.au9999_cta.compare_windows --strategies s2_donchian_breakout s7_macd_turtle \\
        --results-dir strategies/au9999_cta/results/window_comparison_s2_s7

默认对比 Buy-and-Hold / s1a / s1c；--strategies 可指定 STRATEGIES 中的任意组合，
因此也用于 s1a vs s1b、s2 vs s7 等成对对比。

口径（docs/trade_strat/au9999_cta.md 回测验证）：
- 标的 518880.SH：日线 data/518880.SH.csv（B&H / s1a 等日线策略），
  分钟线 data/518880.sh.minutes.csv（s1c，14:45 信号 / 14:47 成交）；
- 窗口前预热、窗口起点空仓：
  · 日线策略一次性加载全历史，指标自然预热；动态子类加 trade_start 参数，
    窗口起点前不登记入场，因此窗口开始时指标已预热且账户空仓；
  · s1c 由 load_minute_snapshots 在装载阶段对全历史预计算 SMA30/90、ATR14 后再按窗口切片；
- 成本单边手续费 0.02% + 滑点 0.02%，percent_equity 100%，取自 common/constants.py；
- 指标：收益率、年化、最大回撤、Sharpe（窗口内日收益，252 日年化，
  无风险利率取 common/constants.py 的 RISK_FREE_RATE，默认 0 即不减）、胜率、交易次数；
  除交易统计天然只含窗口内已平仓交易外，净值类指标也只在窗口切片上复算，
  避免预热空仓段稀释 Sharpe。
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import backtrader as bt
import pandas as pd

from ..common.constants import (
    GOLD_ETF_DAILY_CSV,
    GOLD_ETF_MINUTES_CSV,
    INITIAL_CASH,
    RISK_FREE_RATE,
    TRADING_DAYS_PER_YEAR,
)
from ..common.data_loader import load_daily_csv, load_minute_snapshots
from ..common.engine import run_backtest
from ..common.feeds import IntradaySnapshotData
from . import RESULTS_DIR, STRATEGIES

DEFAULT_STRATEGIES = [
    "buy_and_hold",
    "s1a_ma_cross_trailing",
    "s1c_ma_cross_intraday",
]

SHORT_NAMES = {
    "buy_and_hold": "BuyAndHold",
    "s1a_ma_cross_trailing": "s1a",
    "s1b_vol_target_ma_cross": "s1b",
    "s1c_ma_cross_intraday": "s1c",
    "s2_donchian_breakout": "s2",
    "s3_bollinger_squeeze": "s3",
    "s4_keltner_breakout": "s4",
    "s5_rsi_mean_reversion": "s5",
    "s7_macd_turtle": "s7",
}

# (区间名, 起始, 结束)，取自文档《回测验证》与附录：默认全区间 + 3 个熊市 + 3 个震荡区间。
WINDOWS: list[tuple[str, str, str]] = [
    ("全区间 2018-2026", "2018-01-01", "2026-09-01"),
    ("熊市 2014-2015", "2014-03-17", "2015-08-10"),
    ("熊市 2020-2021", "2020-08-07", "2021-03-05"),
    ("熊市 2026H1", "2026-01-29", "2026-07-01"),
    ("震荡 2017H2", "2017-07-21", "2018-01-17"),
    ("震荡 2018H2", "2018-05-25", "2018-10-24"),
    ("震荡 2021-2022", "2021-07-08", "2022-03-04"),
]

GATE_PARAM = "trade_start"


def window_gated(cls: type[bt.Strategy]) -> type[bt.Strategy]:
    """给日线策略加 trade_start：窗口起点前不登记入场（指标仍随全历史预热）。"""

    class WindowGated(cls):
        params = ((GATE_PARAM, None),)

        def buy_next_open(self, reason: str = ""):
            start = self.p.trade_start
            if start is not None and self.data.datetime.date(0) < start:
                return
            super().buy_next_open(reason)

    WindowGated.__name__ = f"WindowGated{cls.__name__}"
    WindowGated.__qualname__ = WindowGated.__name__
    return WindowGated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="多策略分区间回测对比（518880.SH）")
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=sorted(STRATEGIES),
        default=DEFAULT_STRATEGIES,
        help="要对比的策略（默认三个：buy_and_hold / s1a / s1c）",
    )
    parser.add_argument("--daily-csv", default=None, help="日线 CSV（默认 data/518880.SH.csv）")
    parser.add_argument("--minute-csv", default=None, help="分钟线 CSV（默认 data/518880.sh.minutes.csv）")
    parser.add_argument("--results-dir", default=None, help="结果目录（默认 results/window_comparison）")
    return parser.parse_args()


def window_summary(
    strategy: bt.Strategy,
    strategy_name: str,
    window_name: str,
    start: str,
    end: str,
    initial_cash: float = INITIAL_CASH,
) -> dict | None:
    """在窗口切片上复算净值类指标，并统计窗口内已平仓交易。"""
    equity = strategy.analyzers.equity.get_analysis()
    frame = pd.DataFrame(
        {"date": pd.to_datetime(list(equity["dates"])), "value": equity["values"]}
    )
    frame = frame[(frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end))]
    frame = frame.reset_index(drop=True)
    if frame.empty:
        return None

    # 起点空仓：窗口起点前净值恒为 initial_cash，序列前补初始资金使首个窗口日收益定义完整
    values = pd.Series([initial_cash, *frame["value"].tolist()], dtype="float64")
    final_value = float(frame["value"].iloc[-1])
    total_return = final_value / initial_cash - 1.0
    span_days = (frame["date"].iloc[-1] - frame["date"].iloc[0]).days
    years = span_days / 365.25
    cagr = (final_value / initial_cash) ** (1.0 / years) - 1.0 if years > 0 and final_value > 0 else 0.0

    returns = values.pct_change().dropna()
    std = float(returns.std(ddof=1))
    # 无风险利率与 common/constants.py 一致（默认 0，即不减无风险利率）；
    # 年化利率按 (1+rf)^(1/252)-1 折算为日频，与 backtrader SharpeRatio 口径一致
    daily_rf = (1.0 + RISK_FREE_RATE) ** (1.0 / TRADING_DAYS_PER_YEAR) - 1.0
    sharpe = (
        float((returns.mean() - daily_rf) / std * math.sqrt(TRADING_DAYS_PER_YEAR))
        if len(returns) > 1 and std > 0
        else None
    )
    max_drawdown = float((values / values.cummax() - 1.0).min() * 100.0)

    start_date, end_date = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    trades = [
        trade
        for trade in strategy.analyzers.trades.get_analysis()
        if start_date <= trade["close_date"] <= end_date
    ]
    closed = len(trades)
    won = sum(1 for trade in trades if float(trade["pnl_net"]) > 0)

    return {
        "window": window_name,
        "strategy": strategy_name,
        "start": frame["date"].iloc[0].date(),
        "end": frame["date"].iloc[-1].date(),
        "years": round(years, 2),
        "total_return": round(total_return, 4),
        "cagr": round(cagr, 4),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "trades": closed,
        "win_rate": round(won / closed, 4) if closed else None,
    }


def run_window(
    name: str,
    window: tuple[str, str, str],
    daily_data: pd.DataFrame | None,
    snapshots: pd.DataFrame | None,
    gated_classes: dict[str, type[bt.Strategy]],
) -> dict | None:
    _, start, end = window
    cls = STRATEGIES[name]
    if getattr(cls, "data_kind", "daily") == "minute_snapshot":
        assert snapshots is not None
        data = snapshots[(snapshots.index >= pd.Timestamp(start)) & (snapshots.index <= pd.Timestamp(end))]
        strategy, _ = run_backtest(cls, data, strategy_name=name, data_feed=IntradaySnapshotData)
    else:
        assert daily_data is not None
        strategy, _ = run_backtest(
            gated_classes[name],
            daily_data,
            strategy_params={GATE_PARAM: pd.Timestamp(start).date()},
            strategy_name=name,
        )
    return window_summary(strategy, name, window[0], start, end)


def format_table(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.copy()
    display["total_return"] = display["total_return"].map(lambda v: f"{v:+.2%}")
    display["cagr"] = display["cagr"].map(lambda v: f"{v:+.2%}")
    display["max_drawdown"] = display["max_drawdown"].map(lambda v: f"{v:.2f}%")
    display["sharpe"] = display["sharpe"].map(lambda v: "-" if pd.isna(v) else f"{v:.2f}")
    display["win_rate"] = display["win_rate"].map(lambda v: "-" if pd.isna(v) else f"{v:.2%}")
    return display


def pivot_markdown(df: pd.DataFrame, value_col: str, formatter) -> list[str]:
    order = list(dict.fromkeys(df["label"]))
    pivot = df.pivot(index="window", columns="label", values=value_col)
    columns = [label for label in order if label in pivot.columns]
    pivot = pivot[columns]
    lines = [
        "| 区间 | " + " | ".join(columns) + " |",
        "| --- | " + " | ".join(["---:"] * len(columns)) + " |",
    ]
    for window, row in pivot.iterrows():
        lines.append(f"| {window} | " + " | ".join(formatter(v) for v in row) + " |")
    return lines


def write_markdown(
    rows: list[dict],
    out_path: Path,
    daily_data: pd.DataFrame,
    snapshots: pd.DataFrame | None,
) -> None:
    df = pd.DataFrame(rows)
    df["label"] = df["strategy"].map(SHORT_NAMES)
    has_intraday = snapshots is not None and (df["strategy"] == "s1c_ma_cross_intraday").any()
    data_note = f"日线 {daily_data.index[0].date()} ~ {daily_data.index[-1].date()}"
    if snapshots is not None:
        data_note += f"，分钟快照 {snapshots.index[0].date()} ~ {snapshots.index[-1].date()}"
    lines = [
        "# 518880.SH 多策略分区间回测对比",
        "",
        f"> 生成时间：{pd.Timestamp.now():%Y-%m-%d %H:%M}；数据：{data_note}。",
        "> 复现：`python -m strategies.au9999_cta.compare_windows`",
        "",
        "## 口径",
        "",
        "- 标的 518880.SH；s1c 使用分钟线 14:45 信号 / 14:47 成交，其余策略日线收盘确认、次日开盘成交。",
        "- 窗口前预热、窗口起点空仓：日线策略全历史喂指标 + `trade_start` 屏蔽窗口前入场；",
        "  s1c 预计算指标后按窗口切片。",
        "- 成本：单边手续费 0.02% + 滑点 0.02%；仓位 `percent_equity` 100%（s1b 为波动率目标档位），1 克取整。",
        "- 指标在窗口切片上复算：收益 = 窗口末/初始资金−1；Sharpe = (窗口日收益均值 − 日频无风险利率)/",
        "  std(ddof=1)×√252（无风险利率取 RISK_FREE_RATE，默认 0）；",
        "  最大回撤 = 窗口净值（含起点）峰谷回撤；胜率/次数 = 窗口内已平仓交易。B&H 无平仓交易，胜率记 `-`。",
        "- 熊市/震荡区间取自文档《回测验证》：熊市 2014-03-17~2015-08-10、2020-08-07~2021-03-05、",
        "  2026-01-29~2026-07-01；震荡 2017-07-21~2018-01-17、2018-05-25~2018-10-24、2021-07-08~2022-03-04。",
        "",
    ]
    if has_intraday:
        lines.extend(
            [
                "> **与文档 s1c 分段数字的差异说明**：文档策略一C 章节引用的分段数字（如 2026H1 s1c -10.1% /",
                "> 回撤 13.5%）来自未纳入版本库的旧实验（仅残留 `results/intraday_timing/summary.csv`），",
                "> 该实验未强制“窗口起点空仓”：其 2026H1 数字可由 s1c 全历史连续运行、持仓跨越窗口起点复现",
                "> （本仓库连续运行复算 -9.85% / 回撤 13.53%，与“2026-01-30 当日 14:47 离场”的叙述一致）。",
                "> 本表按文档统一约定统一为窗口前预热、窗口起点空仓，故 s1c 在上述窗口的数值与文档旧数字不同；",
                "> 全区间口径两者一致，本表 s1a/s1c/B&H 全区间结果与文档表格一致。",
                "",
            ]
        )

    for _, group in df.groupby("window", sort=False):
        head = group.iloc[0]
        lines.append(f"## {head['window']}（{head['start']} ~ {head['end']}）")
        lines.append("")
        lines.append("| 策略 | 收益率 | 年化 | 最大回撤 | Sharpe | 交易次数 | 胜率 |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        display = format_table(group[["strategy", "total_return", "cagr", "max_drawdown", "sharpe", "trades", "win_rate"]])
        for _, row in display.iterrows():
            lines.append(
                f"| {SHORT_NAMES[row['strategy']]} | {row['total_return']} | {row['cagr']} | "
                f"{row['max_drawdown']} | {row['sharpe']} | {row['trades']} | {row['win_rate']} |"
            )
        lines.append("")

    lines.append("## 总收益对照")
    lines.append("")
    lines.extend(pivot_markdown(df, "total_return", lambda v: f"{v:+.2%}"))
    lines.append("")
    lines.append("## 最大回撤对照")
    lines.append("")
    lines.extend(pivot_markdown(df, "max_drawdown", lambda v: f"{v:.2f}%"))
    lines.append("")
    lines.append("## Sharpe 对照")
    lines.append("")
    lines.extend(pivot_markdown(df, "sharpe", lambda v: "-" if pd.isna(v) else f"{v:.2f}"))
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()

    daily_csv = Path(args.daily_csv) if args.daily_csv else GOLD_ETF_DAILY_CSV
    minute_csv = Path(args.minute_csv) if args.minute_csv else GOLD_ETF_MINUTES_CSV
    results_dir = Path(args.results_dir) if args.results_dir else RESULTS_DIR / "window_comparison"
    results_dir.mkdir(parents=True, exist_ok=True)

    needs_minute = any(getattr(STRATEGIES[name], "data_kind", "daily") == "minute_snapshot" for name in args.strategies)
    daily_data = load_daily_csv(daily_csv)  # 全历史，指标预热用
    snapshots = load_minute_snapshots(minute_csv) if needs_minute else None
    gated_classes = {
        name: window_gated(STRATEGIES[name])
        for name in args.strategies
        if getattr(STRATEGIES[name], "data_kind", "daily") != "minute_snapshot"
    }
    print(f"日线：{daily_csv}（{daily_data.index[0].date()} ~ {daily_data.index[-1].date()}）")
    if snapshots is not None:
        print(f"分钟快照：{minute_csv}（{snapshots.index[0].date()} ~ {snapshots.index[-1].date()}）")
    print()

    rows: list[dict] = []
    for window in WINDOWS:
        print(f"================ {window[0]}（{window[1]} ~ {window[2]}）================")
        window_rows = []
        for name in args.strategies:
            summary = run_window(name, window, daily_data, snapshots, gated_classes)
            if summary is not None:
                summary["label"] = SHORT_NAMES.get(name, name)
                rows.append(summary)
                window_rows.append(summary)
        table = pd.DataFrame(window_rows)
        print(
            format_table(
                table[["label", "total_return", "cagr", "max_drawdown", "sharpe", "trades", "win_rate"]]
            ).to_string(index=False)
        )
        print()

    result = pd.DataFrame(rows)
    csv_path = results_dir / "summary.csv"
    result.to_csv(csv_path, index=False, encoding="utf-8-sig")

    pivot = result.pivot(index="window", columns="label", values="total_return")
    pivot = pivot[[SHORT_NAMES[name] for name in args.strategies if SHORT_NAMES[name] in pivot.columns]]
    print("================ 总收益对照（行=区间，列=策略）================")
    print(pivot.map(lambda v: f"{v:+.2%}").to_string())
    print()

    md_path = results_dir / "report.md"
    write_markdown(rows, md_path, daily_data, snapshots)
    print(f"对比 CSV：{csv_path}")
    print(f"Markdown 报告：{md_path}")


if __name__ == "__main__":
    main()
