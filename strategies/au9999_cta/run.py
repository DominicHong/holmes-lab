"""AU9999 五个 CTA 策略的批量回测入口。

用法（在仓库根目录执行）：
    python -m strategies.au9999_cta.run
    python -m strategies.au9999_cta.run --strategies s1_ma_cross_atr s5_rsi_mean_reversion
    python -m strategies.au9999_cta.run --start 2020-01-01 --end 2022-12-31
    python -m strategies.au9999_cta.run --plot --verbose
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from ..common.data_loader import load_au9999_daily
from ..common.engine import run_backtest
from ..common.performance import save_results, save_summary
from . import BACKTEST_END, BACKTEST_START, RESULTS_DIR, STRATEGIES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AU9999 日频纯多头 CTA 策略回测")
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=sorted(STRATEGIES),
        default=sorted(STRATEGIES),
        help="要回测的策略（默认全部）",
    )
    parser.add_argument("--start", default=BACKTEST_START, help="回测起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=BACKTEST_END, help="回测结束日期 YYYY-MM-DD")
    parser.add_argument("--plot", action="store_true", help="回测结束后绘图")
    parser.add_argument("--verbose", action="store_true", help="打印每笔买卖信号")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    data = load_au9999_daily(start=args.start, end=args.end)
    print(f"数据区间: {data.index[0].date()} ~ {data.index[-1].date()}，共 {len(data)} 根日 K 线\n")

    summaries = []
    for name in args.strategies:
        strategy_cls = STRATEGIES[name]
        strategy, summary = run_backtest(
            strategy_cls,
            data,
            strategy_params={"verbose": args.verbose},
            strategy_name=name,
            plot=args.plot,
        )
        save_results(name, strategy, results_dir=RESULTS_DIR)
        summaries.append(summary)
        print(
            f"[{name}] 完成：交易 {summary['trades']} 笔，"
            f"总收益 {summary['total_return']:.2%}，最大回撤 {summary['max_drawdown']:.2f}%"
        )

    summary_df = pd.DataFrame(summaries)
    out_dir = save_summary(summary_df, results_dir=RESULTS_DIR)
    print("\n================ 回测汇总 ================")
    print(summary_df.to_string(index=False))
    print(f"\n净值/交易/汇总结果已保存至: {out_dir}")


if __name__ == "__main__":
    main()
