"""IRR / Varied Coupon / Reference 三种税前收益率算法对比。

用法（在仓库根目录执行）：
    python tools/ytm_tax_method_compare.py

样本：以 2026-11-12 所在计息期为基准，取 t≈0.1 / 0.5 / 0.9 三个交割日；
统一净 YTM 3.0%；年付 / 半年付 × 短期 / 中期 / 长期（2 / 5 / 10 年发行）×
低 / 平 / 高票息（1% / 3% / 5%），共 2×3×3×3 = 54 个样本。
"""

from __future__ import annotations

import statistics

from financepy.products.bonds import Bond
from financepy.utils import Date, DayCount, DayCountTypes, FrequencyTypes

from ytm_before_tax_ifind import (
    irr_yield,
    reference_yield,
    reference_yield_formula4,
    varied_coupon_yield,
)

BASE_SETTLE = Date(12, 11, 2026)
NET_YTM = 0.03
COUPONS = (("低", 0.01), ("平", 0.03), ("高", 0.05))
TENORS = (("短期", 2), ("中期", 5), ("长期", 10))
# (标签, 频率, 到期月份)；到期日 15 日，使基准交割日大致处于计息期中点
FREQUENCIES = (
    ("年付", FrequencyTypes.ANNUAL, 5),
    ("半年付", FrequencyTypes.SEMI_ANNUAL, 2),
)
# t = (下一付息日 - 交割日) / (下一付息日 - 上一付息日)
TARGET_TS = (("0.1", 0.1), ("0.5", 0.5), ("0.9", 0.9))


def settle_for_t(bond, base_settle, target_t):
    """在基准交割日所在计息期内，取剩余比例为 target_t 的交割日。"""
    prev_dt = max(dt for dt in bond.cpn_dts if dt <= base_settle)
    next_dt = min(dt for dt in bond.cpn_dts if dt > base_settle)
    offset = int(round(target_t * (next_dt - prev_dt)))
    return next_dt.add_days(-offset)


def build_rows():
    rows = []
    for freq_label, freq_type, month in FREQUENCIES:
        for tenor_label, tenor in TENORS:
            maturity = Date(15, month, 2026 + tenor)
            issue = maturity.add_tenor(f"-{tenor}Y")
            schedule_bond = Bond(
                issue, maturity, COUPONS[0][1], freq_type, DayCountTypes.ACT_ACT_ICMA
            )
            for t_label, t_target in TARGET_TS:
                settle = settle_for_t(schedule_bond, BASE_SETTLE, t_target)
                for coupon_label, coupon in COUPONS:
                    bond = Bond(
                        issue, maturity, coupon, freq_type, DayCountTypes.ACT_ACT_ICMA
                    )
                    irr = irr_yield(bond, settle, NET_YTM)
                    varied = varied_coupon_yield(bond, settle, NET_YTM)
                    reference = reference_yield(coupon, NET_YTM)
                    num_flows = sum(1 for d in bond.cpn_dts if d > settle)
                    reference4 = reference_yield_formula4(
                        coupon, NET_YTM, num_flows, bond.freq
                    )
                    remaining = DayCount(DayCountTypes.ACT_ACT_ISDA).year_frac(
                        settle, maturity
                    )[0]
                    rows.append(
                        {
                            "freq": freq_label,
                            "tenor": tenor_label,
                            "t_label": t_label,
                            "remaining": remaining,
                            "t": bond.alpha,
                            "coupon_label": coupon_label,
                            "coupon": coupon,
                            "irr": irr,
                            "varied": varied,
                            "ref": reference,
                            "ref4": reference4,
                        }
                    )
    return rows


def print_detail(rows):
    print("=== 明细（%，差异为 bp）===")
    header = (
        f"{'频率':<6}{'期限':<6}{'t档':<6}{'剩余年':>7}{'t':>7}{'票息':>7}"
        f"{'IRR':>9}{'Varied':>9}{'Ref':>9}{'Ref4':>9}"
        f"{'IRR-Var':>9}{'IRR-Ref':>9}{'IRR-Ref4':>10}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['freq']:<6}{row['tenor']:<6}{row['t_label']:<6}"
            f"{row['remaining']:>7.2f}{row['t']:>7.3f}"
            f"{row['coupon'] * 100:>7.2f}"
            f"{row['irr'] * 100:>9.4f}{row['varied'] * 100:>9.4f}"
            f"{row['ref'] * 100:>9.4f}{row['ref4'] * 100:>9.4f}"
            f"{(row['irr'] - row['varied']) * 10000:>9.3f}"
            f"{(row['irr'] - row['ref']) * 10000:>9.3f}"
            f"{(row['irr'] - row['ref4']) * 10000:>10.3f}"
        )


def print_matrix(rows, freq_label, left, right, title):
    print(f"\n{title}（{freq_label}，净 YTM {NET_YTM * 100:.2f}%）")
    print(f"{'期限':<6}{'t档':<6}" + "".join(f"{label:>12}" for label, _ in COUPONS))
    for tenor_label, _ in TENORS:
        for t_label, _ in TARGET_TS:
            values = []
            for coupon_label, _ in COUPONS:
                row = next(
                    r
                    for r in rows
                    if r["freq"] == freq_label
                    and r["tenor"] == tenor_label
                    and r["t_label"] == t_label
                    and r["coupon_label"] == coupon_label
                )
                values.append((row[left] - row[right]) * 10000)
            print(
                f"{tenor_label:<6}{t_label:<6}"
                + "".join(f"{value:>12.3f}" for value in values)
            )


def print_summary(rows):
    print("\n=== 汇总 ===")
    for left, right, label in (
        ("irr", "varied", "IRR - Varied Coupon"),
        ("irr", "ref", "IRR - Reference"),
        ("irr", "ref4", "IRR - Ref-4"),
    ):
        diffs = [abs((row[left] - row[right]) * 10000) for row in rows]
        print(
            f"{label:<20} 平均绝对差 {statistics.mean(diffs):>7.3f} bp，"
            f"最大绝对差 {max(diffs):>7.3f} bp"
        )

    print("\n=== 按 t 分档 ===")
    for t_label, _ in TARGET_TS:
        subset = [row for row in rows if row["t_label"] == t_label]
        print(f"t≈{t_label}")
        for left, right, label in (
            ("irr", "varied", "IRR - Varied"),
            ("irr", "ref", "IRR - Ref"),
            ("irr", "ref4", "IRR - Ref4"),
        ):
            diffs = [abs((row[left] - row[right]) * 10000) for row in subset]
            print(
                f"  {label:<15} 平均绝对差 {statistics.mean(diffs):>7.3f} bp，"
                f"最大绝对差 {max(diffs):>7.3f} bp"
            )


if __name__ == "__main__":
    sample_rows = build_rows()
    print_detail(sample_rows)
    for freq_label, _, _ in FREQUENCIES:
        print_matrix(sample_rows, freq_label, "irr", "varied", "IRR - Varied (bp)")
        print_matrix(sample_rows, freq_label, "irr", "ref", "IRR - Reference (bp)")
        print_matrix(sample_rows, freq_label, "irr", "ref4", "IRR - Ref-4 (bp)")
    print_summary(sample_rows)
