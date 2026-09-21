"""CTA 策略族批量回测入口（默认 AU9999，可切换任意日线 CSV；s1c 用分钟线聚合快照）。

用法（在仓库根目录执行）：
    python -m strategies.au9999_cta.run
    python -m strategies.au9999_cta.run --strategies s1a_ma_cross_trailing s5_rsi_mean_reversion
    python -m strategies.au9999_cta.run --strategies s1c_ma_cross_intraday
    python -m strategies.au9999_cta.run --start 2020-01-01 --end 2022-12-31
    python -m strategies.au9999_cta.run --csv data/518880.SH.csv
    python -m strategies.au9999_cta.run --plot --verbose

默认回测 AU9999（区间 2018-01-01 ~ 2026-09-01，结果存 results/）；
指定 --csv 时默认回测该 CSV 的全部区间，结果存 results/<csv 文件名>/，避免覆盖 AU9999 结果。
s1c_ma_cross_intraday 的数据来自分钟线（--minute-csv，默认 data/518880.sh.minutes.csv），
由 data_loader 聚合为 14:45 信号 / 14:47 成交的日频快照。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import backtrader as bt
import pandas as pd

from ..common.constants import AU9999_DAILY_CSV, GOLD_ETF_MINUTES_CSV
from ..common.data_loader import load_daily_csv, load_minute_snapshots
from ..common.engine import run_backtest
from ..common.feeds import IntradaySnapshotData
from ..common.performance import save_results, save_summary
from . import BACKTEST_END, BACKTEST_START, RESULTS_DIR, STRATEGIES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="日频纯多头 CTA 策略回测（默认 AU9999）")
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=sorted(STRATEGIES),
        default=sorted(STRATEGIES),
        help="要回测的策略（默认全部）",
    )
    parser.add_argument("--csv", default=None, help="行情 CSV 路径（默认 AU9999 日线）")
    parser.add_argument(
        "--minute-csv",
        default=None,
        help="分钟线 CSV 路径（仅供 s1c 盘中策略，默认 data/518880.sh.minutes.csv）",
    )
    parser.add_argument("--start", default=None, help="回测起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="回测结束日期 YYYY-MM-DD")
    parser.add_argument("--results-dir", default=None, help="结果输出目录（默认按标的自适应）")
    parser.add_argument("--plot", action="store_true", help="回测结束后绘图")
    parser.add_argument("--verbose", action="store_true", help="打印每笔买卖信号")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()

    csv_path = AU9999_DAILY_CSV if args.csv is None else Path(args.csv)
    minute_csv = GOLD_ETF_MINUTES_CSV if args.minute_csv is None else Path(args.minute_csv)
    start = args.start or BACKTEST_START
    end = args.end or BACKTEST_END
    if args.results_dir is not None:
        results_dir = Path(args.results_dir)
    elif args.csv is None:
        results_dir = RESULTS_DIR
    else:
        results_dir = RESULTS_DIR / csv_path.stem

    daily_data: pd.DataFrame | None = None
    intraday_data: pd.DataFrame | None = None

    summaries = []
    for name in args.strategies:
        strategy_cls = STRATEGIES[name]
        if getattr(strategy_cls, "data_kind", "daily") == "minute_snapshot":
            if intraday_data is None:
                intraday_data = load_minute_snapshots(minute_csv, start=start, end=end)
                print(f"分钟快照文件: {minute_csv}")
                print(
                    f"数据区间: {intraday_data.index[0].date()} ~ {intraday_data.index[-1].date()}，"
                    f"共 {len(intraday_data)} 个交易日\n"
                )
            data, data_feed = intraday_data, IntradaySnapshotData
        else:
            if daily_data is None:
                daily_data = load_daily_csv(csv_path, start=start, end=end)
                print(f"数据文件: {csv_path}")
                print(
                    f"数据区间: {daily_data.index[0].date()} ~ {daily_data.index[-1].date()}，"
                    f"共 {len(daily_data)} 根日 K 线\n"
                )
            data, data_feed = daily_data, bt.feeds.PandasData

        strategy, summary = run_backtest(
            strategy_cls,
            data,
            strategy_params={"verbose": args.verbose},
            strategy_name=name,
            data_feed=data_feed,
            plot=args.plot,
        )
        save_results(name, strategy, results_dir=results_dir)
        summaries.append(summary)
        print(
            f"[{name}] 完成：交易 {summary['trades']} 笔，"
            f"总收益 {summary['total_return']:.2%}，最大回撤 {summary['max_drawdown']:.2f}%"
        )

    summary_df = pd.DataFrame(summaries)
    out_dir = save_summary(summary_df, results_dir=results_dir)
    print("\n================ 回测汇总 ================")
    print(summary_df.to_string(index=False))
    print(f"\n净值/交易/汇总结果已保存至: {out_dir}")


if __name__ == "__main__":
    main()
