"""IRR / Varied Coupon / Reference 三种税前收益率算法对比。

用法（在仓库根目录执行）：
    python tools/ytm_tax_method_compare.py

样本：交割日 2026-11-12，净 YTM 2.5%；
年付 / 半年付 × 短期 / 中期 / 长期（2 / 5 / 10 年发行）×
低 / 平 / 高票息（1.5% / 2.5% / 3.5%）。
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

SETTLE = Date(12, 11, 2026)
NET_YTM = 0.025
COUPONS = (("低", 0.015), ("平", 0.025), ("高", 0.035))
TENORS = (("短期", 2), ("中期", 5), ("长期", 10))
# (标签, 频率, 到期月份)；到期日 15 日，使交割日大致处于计息期中点
FREQUENCIES = (
    ("年付", FrequencyTypes.ANNUAL, 5),
    ("半年付", FrequencyTypes.SEMI_ANNUAL, 2),
)


def build_rows():
    rows = []
    for freq_label, freq_type, month in FREQUENCIES:
        for tenor_label, tenor in TENORS:
            maturity = Date(15, month, 2026 + tenor)
            issue = maturity.add_tenor(f"-{tenor}Y")
            for coupon_label, coupon in COUPONS:
                bond = Bond(issue, maturity, coupon, freq_type, DayCountTypes.ACT_ACT_ICMA)
                irr = irr_yield(bond, SETTLE, NET_YTM)
                varied = varied_coupon_yield(bond, SETTLE, NET_YTM)
                reference = reference_yield(coupon, NET_YTM)
                num_flows = sum(1 for d in bond.cpn_dts if d > SETTLE)
                reference4 = reference_yield_formula4(
                    coupon, NET_YTM, num_flows, bond.freq
                )
                remaining = DayCount(DayCountTypes.ACT_ACT_ISDA).year_frac(
                    SETTLE, maturity
                )[0]
                rows.append(
                    {
                        "freq": freq_label,
                        "tenor": tenor_label,
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
        f"{'频率':<6}{'期限':<6}{'剩余年':>7}{'t':>7}{'票息':>7}"
        f"{'IRR':>9}{'Varied':>9}{'Ref':>9}{'Ref4':>9}"
        f"{'IRR-Var':>9}{'IRR-Ref':>9}{'IRR-Ref4':>10}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['freq']:<6}{row['tenor']:<6}{row['remaining']:>7.2f}{row['t']:>7.3f}"
            f"{row['coupon'] * 100:>7.2f}"
            f"{row['irr'] * 100:>9.4f}{row['varied'] * 100:>9.4f}"
            f"{row['ref'] * 100:>9.4f}{row['ref4'] * 100:>9.4f}"
            f"{(row['irr'] - row['varied']) * 10000:>9.3f}"
            f"{(row['irr'] - row['ref']) * 10000:>9.3f}"
            f"{(row['irr'] - row['ref4']) * 10000:>10.3f}"
        )


def print_matrix(rows, freq_label, left, right, title):
    print(f"\n{title}（{freq_label}，净 YTM {NET_YTM * 100:.2f}%）")
    print(f"{'期限':<6}" + "".join(f"{label:>12}" for label, _ in COUPONS))
    for tenor_label, _ in TENORS:
        values = []
        for coupon_label, _ in COUPONS:
            row = next(
                r
                for r in rows
                if r["freq"] == freq_label
                and r["tenor"] == tenor_label
                and r["coupon_label"] == coupon_label
            )
            values.append((row[left] - row[right]) * 10000)
        print(f"{tenor_label:<6}" + "".join(f"{value:>12.3f}" for value in values))


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


if __name__ == "__main__":
    sample_rows = build_rows()
    print_detail(sample_rows)
    for freq_label, _, _ in FREQUENCIES:
        print_matrix(sample_rows, freq_label, "irr", "varied", "IRR - Varied (bp)")
        print_matrix(sample_rows, freq_label, "irr", "ref", "IRR - Reference (bp)")
        print_matrix(sample_rows, freq_label, "irr", "ref4", "IRR - Ref-4 (bp)")
    print_summary(sample_rows)
