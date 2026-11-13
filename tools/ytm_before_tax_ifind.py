"""国债税前收益率计算（iFinD 数据源，支持 SDK / HTTP）。

用法（在仓库根目录执行）：
    python tools/ytm_before_tax_ifind.py
    python tools/ytm_before_tax_ifind.py --source sdk
    python tools/ytm_before_tax_ifind.py --source http

数据源：
- sdk：iFinD Python SDK，读取 .env 的 IFIND_USER / IFIND_PASSWORD；
- http：iFinD HTTP API，读取 .env 的 IFIND_DATASOURCE_KEY；
- auto：先 SDK，失败后自动回退 HTTP。

税前收益率算法见 docs/treasury_tax/国债税后收益率公式 - IRR版.md：
先由国债自身定价方程得到全价 P0，再按“同价位、税后 IRR 打平”的恒定票息
虚拟债解出 K，最后用 K 的税前现金流贴现解 y。逐期复利口径与 FinancePy
的 CFETS 分支一致；最后一个付息周期按 ACT_365L 年化、单利贴现。
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import tkinter as tk
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tkinter import END, Button, Entry, Frame, Label, messagebox

from dotenv import dotenv_values
from financepy.products.bonds import Bond, YTMCalcType
from financepy.utils import Date, DayCount, DayCountTypes, FrequencyTypes
from scipy import optimize

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV = dotenv_values(PROJECT_ROOT / ".env")

IFIND_API_BASE = "https://quantapi.51ifind.com/api/v1"
TAX_RATE = 0.25  # 企业所得税税率，税前还原用 1/(1-T)=4/3

# iFinD 债券基础数据指标（均已在 SuperCommand 中确认）。
BOND_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "sec_name": ("ths_bond_short_name_bond", "ths_bond_name_bond"),
    "maturity_date": ("ths_maturity_date_bond",),
    "coupon_type": ("ths_interest_type_bond",),
    "issue_date": ("ths_interest_begin_date_bond",),
    "coupon": ("ths_nominal_interest_current_bond",),
    "coupon_freq": ("ths_interest_paid_times_y_bond",),
}

_IFIND_ACCESS_TOKEN: str | None = None


@dataclass(frozen=True)
class BondTerms:
    """债券静态要素。贴现债不需要起息日/票面利率/付息频率。"""

    issue_date: Date | None
    maturity_date: Date
    sec_name: str
    coupon_type: str
    coupon: float
    coupon_freq: int


# ---------- iFinD 数据层 ----------

def _post_json(url: str, headers: dict, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _ifind_access_token() -> str:
    """用 refresh token 换取 access token（进程内缓存）。"""
    global _IFIND_ACCESS_TOKEN
    if _IFIND_ACCESS_TOKEN:
        return _IFIND_ACCESS_TOKEN
    key = ENV.get("IFIND_DATASOURCE_KEY")
    if not key:
        raise RuntimeError("缺少 IFIND_DATASOURCE_KEY，无法使用 iFinD HTTP 模式")
    result = _post_json(
        f"{IFIND_API_BASE}/get_access_token",
        {"Content-Type": "application/json", "refresh_token": key},
        {},
    )
    if result.get("errorcode") != 0:
        raise RuntimeError(
            f"iFinD 获取 access_token 失败（errorcode={result.get('errorcode')}）：{result.get('errmsg')}"
        )
    _IFIND_ACCESS_TOKEN = result["data"]["access_token"]
    return _IFIND_ACCESS_TOKEN


def _login_ifind_sdk() -> int:
    from iFinDPy import THS_iFinDLogin  # 延迟导入，HTTP 模式无需 SDK

    user, password = ENV.get("IFIND_USER"), ENV.get("IFIND_PASSWORD")
    if not user or not password:
        raise RuntimeError("缺少 IFIND_USER / IFIND_PASSWORD，无法使用 iFinD SDK 模式")
    login_code = THS_iFinDLogin(user, password)
    if login_code not in (0, -201):  # -201 表示账号已登录，可直接复用
        raise RuntimeError(f"iFinD SDK 登录失败（errorcode={login_code}）")
    return login_code


def _logout_ifind_sdk() -> None:
    from iFinDPy import THS_iFinDLogout

    THS_iFinDLogout()


def _ifind_bd_sdk(bond_code: str, indicator: str):
    from iFinDPy import THS_BD

    result = THS_BD(bond_code, indicator, "")
    if result.errorcode != 0:
        raise RuntimeError(f"{indicator}: {result.errmsg}")
    if result.data is None or result.data.empty:
        raise RuntimeError(f"{indicator}: 无数据")
    return result.data.iloc[0][indicator]


def _ifind_bd_http(token: str, bond_code: str, indicator: str):
    payload = {
        "codes": bond_code,
        "indipara": [{"indicator": indicator, "indiparams": []}],
    }
    result = _post_json(
        f"{IFIND_API_BASE}/basic_data_service",
        {"Content-Type": "application/json", "access_token": token, "ifindlang": "cn"},
        payload,
    )
    if result.get("errorcode") != 0:
        raise RuntimeError(f"{indicator}: {result.get('errmsg')}")
    tables = result.get("tables") or []
    if not tables:
        raise RuntimeError(f"{indicator}: 无数据")
    values = (tables[0].get("table") or {}).get(indicator)
    if not values:
        raise RuntimeError(f"{indicator}: 无数据")
    return values[0]


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _probe_field(probe, field: str):
    last_error = None
    for indicator in BOND_FIELD_CANDIDATES[field]:
        try:
            value = probe(indicator)
        except Exception as exc:
            last_error = exc
            continue
        if not _is_blank(value):
            return value
        last_error = RuntimeError(f"{indicator}: 返回空值")
    candidates = "、".join(BOND_FIELD_CANDIDATES[field])
    raise RuntimeError(
        f"字段 {field} 没有可用的 iFinD 指标（候选：{candidates}）。"
        f"请在 SuperCommand 中确认指标代码后更新 BOND_FIELD_CANDIDATES；最后错误：{last_error}"
    )


def _collect_bond_fields(probe) -> dict:
    values = {field: _probe_field(probe, field) for field in ("sec_name", "maturity_date", "coupon_type")}
    coupon_type = str(values["coupon_type"])
    is_discount = any(key in coupon_type for key in ("贴现", "零息"))
    if not is_discount:
        for field in ("issue_date", "coupon", "coupon_freq"):
            values[field] = _probe_field(probe, field)
    return values


def _to_float(value) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return float(str(value).replace("%", "").strip())


def _to_date(value) -> Date:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = str(int(value))
    else:
        text = str(value).strip()
    if len(text) >= 8 and text[:8].isdigit():
        return Date(int(text[6:8]), int(text[4:6]), int(text[0:4]))
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.datetime.strptime(text, fmt).date()
            return Date(parsed.day, parsed.month, parsed.year)
        except ValueError:
            continue
    raise ValueError(f"无法解析日期：{value!r}")


def _parse_frequency(value) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    text = str(value).strip()
    for key, freq in (("半年", 2), ("季", 4), ("月", 12)):
        if key in text:
            return freq
    match = re.search(r"(\d+)\s*次", text)  # "2次/年"、"每年2次"
    if match:
        return int(match.group(1))
    if "年" in text:
        return 1
    return int(float(text))


def _build_bond_terms(values: dict) -> BondTerms:
    coupon_type = str(values["coupon_type"]).strip()
    is_discount = any(key in coupon_type for key in ("贴现", "零息"))
    if is_discount:
        coupon = 0.0
        coupon_freq = 1
        issue_date = None
    else:
        issue_date = _to_date(values["issue_date"])
        coupon = _to_float(values["coupon"]) / 100.0
        coupon_freq = _parse_frequency(values["coupon_freq"])
    return BondTerms(
        issue_date=issue_date,
        maturity_date=_to_date(values["maturity_date"]),
        sec_name=str(values["sec_name"]).strip(),
        coupon_type=coupon_type,
        coupon=coupon,
        coupon_freq=coupon_freq,
    )


def _fetch_bond_terms(bond_code: str, mode: str) -> BondTerms:
    if mode == "sdk":
        login_code = _login_ifind_sdk()
        try:
            values = _collect_bond_fields(lambda indicator: _ifind_bd_sdk(bond_code, indicator))
        finally:
            if login_code == 0:
                _logout_ifind_sdk()
    elif mode == "http":
        token = _ifind_access_token()
        values = _collect_bond_fields(lambda indicator: _ifind_bd_http(token, bond_code, indicator))
    else:
        raise ValueError(f"未知数据源：{mode}")
    return _build_bond_terms(values)


def fetch_bond_terms(bond_code: str, source: str = "auto") -> BondTerms:
    """获取债券静态要素：sdk / http / auto（先 SDK 后 HTTP）。"""
    modes = (source,) if source != "auto" else ("sdk", "http")
    errors = []
    for mode in modes:
        try:
            return _fetch_bond_terms(bond_code, mode)
        except Exception as exc:
            errors.append(f"{mode}: {exc}")
    raise RuntimeError("iFinD 债券数据获取失败 -> " + "；".join(errors))


# ---------- 税前收益率计算 ----------

def _parse_input_date(text: str) -> Date:
    text = text.replace(" ", "")
    for fmt in ("%y-%m-%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            parsed = datetime.datetime.strptime(text, fmt).date()
            return Date(parsed.day, parsed.month, parsed.year)
        except ValueError:
            continue
    raise ValueError(f"无法解析日期：{text!r}，请使用 年-月-日 或 两位年份-月-日")


def _last_period_alpha(maturity_date, settlement_date):
    """最后一个付息周期的 ACT_365L 年化比例。"""
    return 1 - DayCount(DayCountTypes.ACT_365L).year_frac(
        maturity_date.add_tenor("-12M"),
        settlement_date,
        maturity_date,
        freq_type=FrequencyTypes.ANNUAL,
    )[0]


def _num_flows(bond, settlement_date):
    return sum(1 for dt in bond.cpn_dts if dt > settlement_date)


def _solve_yield(price_gap, ytm):
    try:
        return optimize.newton(price_gap, x0=ytm, tol=1e-12, maxiter=100)
    except (RuntimeError, ValueError):
        return optimize.brentq(price_gap, 1e-8, 1.0)


def irr_yield(bond, settlement_date, ytm):
    """IRR 版（恒定票息两步法），返回税前到期收益率（小数）。"""
    full_price = bond.dirty_price_from_ytm(settlement_date, ytm, YTMCalcType.CFETS)
    alpha = bond.alpha
    freq = bond.freq
    coupon_per_period = bond.cpn / freq
    num_flows = _num_flows(bond, settlement_date)
    if num_flows <= 0:
        raise RuntimeError("债券已到期，无法计算")

    if num_flows == 1:
        alpha_last = _last_period_alpha(bond.maturity_dt, settlement_date)
        k = coupon_per_period / (1.0 - alpha * TAX_RATE)
        return ((k + 1.0) * 100.0 / full_price - 1.0) / alpha_last

    v = 1.0 / (1.0 + ytm / freq)
    a = sum(v ** (alpha + k) for k in range(num_flows))
    k = coupon_per_period * a / (
        (1.0 - TAX_RATE) * a + TAX_RATE * (1.0 - alpha) * v ** alpha
    )
    tax_bond = Bond(
        bond.issue_dt,
        bond.maturity_dt,
        k * freq,
        bond.freq_type,
        DayCountTypes.ACT_ACT_ICMA,
    )
    price_gap = lambda y: tax_bond.dirty_price_from_ytm(
        settlement_date, y, YTMCalcType.CFETS
    ) - full_price
    return _solve_yield(price_gap, ytm)


def varied_coupon_yield(bond, settlement_date, ytm):
    """Varied Coupon 版（时变票息一步法），返回税前到期收益率（小数）。"""
    full_price = bond.dirty_price_from_ytm(settlement_date, ytm, YTMCalcType.CFETS)
    alpha = bond.alpha
    freq = bond.freq
    coupon_per_period = bond.cpn / freq
    num_flows = _num_flows(bond, settlement_date)
    if num_flows <= 0:
        raise RuntimeError("债券已到期，无法计算")

    first_coupon = coupon_per_period / (1.0 - alpha * TAX_RATE)
    if num_flows == 1:
        alpha_last = _last_period_alpha(bond.maturity_dt, settlement_date)
        return ((first_coupon + 1.0) * 100.0 / full_price - 1.0) / alpha_last

    def price(y):
        v = 1.0 / (1.0 + y / freq)
        pv = first_coupon * v ** alpha
        for k in range(1, num_flows):
            pv += (coupon_per_period / (1.0 - TAX_RATE)) * v ** (alpha + k)
        pv += v ** (alpha + num_flows - 1)
        return pv * 100.0

    return _solve_yield(lambda y: price(y) - full_price, ytm)


def reference_yield(coupon, ytm):
    """超简便公式 y = r + cT/(1-T)，返回小数。"""
    return ytm + coupon * TAX_RATE / (1.0 - TAX_RATE)


def reference_yield_formula4(coupon, ytm, num_flows, freq):
    """文档一次简式(4)：y = r + (1/n+r)/(1/n+c) * cT/(1-T)，按期计算后年化。"""
    if num_flows <= 0:
        raise RuntimeError("债券已到期，无法计算")
    coupon_p = coupon / freq
    ytm_p = ytm / freq
    y_p = ytm_p + (1.0 / num_flows + ytm_p) / (1.0 / num_flows + coupon_p) * (
        coupon_p * TAX_RATE / (1.0 - TAX_RATE)
    )
    return y_p * freq


class YieldTaxIFind(tk.Frame):
    def __init__(self, root, source: str = "auto"):
        super().__init__(root)
        self.pack()
        self.source = source
        self.ma = tk.StringVar()  # 债券代码1
        self.ytm = tk.DoubleVar()  # 债券到期收益率1
        self.settle = tk.StringVar(value=str(datetime.date.today() + datetime.timedelta(days=1)))  # 交割日期1
        self.ma2 = tk.StringVar()  # 债券代码2
        self.ytm2 = tk.DoubleVar()  # 债券到期收益率2
        self.settle2 = tk.StringVar(value=str(datetime.date.today() + datetime.timedelta(days=1)))  # 交割日期2

        frame2 = Frame(self)
        Label(frame2, text='税前收益率(%) ').grid(row=0, column=0)
        self.disp_tf = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf.grid(row=0, column=1)
        self.disp_tf3 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf3.grid(row=0, column=2, padx=5)
        Label(frame2, text='参考值(%)').grid(row=1, column=0)
        self.disp_tf2 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf2.grid(row=1, column=1)
        self.disp_tf4 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf4.grid(row=1, column=2, padx=5)
        Label(frame2, text='债券简称').grid(row=2, column=0)
        self.disp_tf5 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf5.grid(row=2, column=1)
        self.disp_tf6 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf6.grid(row=2, column=2, padx=5)
        Label(frame2, text='剩余期限(年)').grid(row=3, column=0)
        self.disp_tf7 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf7.grid(row=3, column=1)
        self.disp_tf8 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf8.grid(row=3, column=2, padx=5)
        Label(frame2, text='票面利率(%)').grid(row=4, column=0)
        self.disp_tf9 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf9.grid(row=4, column=1)
        self.disp_tf10 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf10.grid(row=4, column=2, padx=5)
        frame2.grid(pady=5)

        root.geometry('500x300')
        root.title('税前收益率计算（iFinD）')

        self.init_inputs()

    def init_inputs(self):
        frame1 = Frame(self)
        Label(frame1, text='  债券代码* ').grid(row=0, column=0)
        Entry(frame1, textvariable=self.ma).grid(row=0, column=1)
        Entry(frame1, textvariable=self.ma2).grid(row=0, column=2, padx=5)
        Label(frame1, text='ytm*(%)').grid(row=1, column=0)
        Entry(frame1, textvariable=self.ytm).grid(row=1, column=1)
        Entry(frame1, textvariable=self.ytm2).grid(row=1, column=2, padx=5)
        Label(frame1, text='交割日期*').grid(row=2, column=0)
        Entry(frame1, textvariable=self.settle).grid(row=2, column=1)
        Entry(frame1, textvariable=self.settle2).grid(row=2, column=2, padx=5)
        Label(frame1, text='日期格式：年-月-日  例：23-01-03\n 带星号为要输入内容，其余为输出结果').grid(row=3,
                                                                                                      columnspan=2)

        frame3 = Frame(self)
        Button(frame3, text='计算', width=10, command=self.button_active).grid(row=0, column=0, pady=5)

        frame1.grid(pady=5)
        frame3.grid(pady=5)

    def button_active(self):
        output_entries = (
            self.disp_tf, self.disp_tf2, self.disp_tf3, self.disp_tf4, self.disp_tf5,
            self.disp_tf6, self.disp_tf7, self.disp_tf8, self.disp_tf9, self.disp_tf10,
        )
        for entry in output_entries:
            entry.delete(0, END)

        sides = (
            ("左侧", self.ma, self.ytm, self.settle,
             (self.disp_tf, self.disp_tf2, self.disp_tf5, self.disp_tf7, self.disp_tf9)),
            ("右侧", self.ma2, self.ytm2, self.settle2,
             (self.disp_tf3, self.disp_tf4, self.disp_tf6, self.disp_tf8, self.disp_tf10)),
        )
        errors = []
        for label, code_var, ytm_var, settle_var, entries in sides:
            bond_code = code_var.get().replace(" ", "")
            if not bond_code:
                continue
            if "." not in bond_code:
                bond_code += ".IB"
            try:
                ytm_value = float(ytm_var.get()) / 100
                settlement_date = _parse_input_date(settle_var.get())
                ytm_tax, reference, sec_name, remaining_years, coupon_rate = self.read_and_calculate(
                    bond_code, ytm_value, settlement_date, source=self.source
                )
                values = (
                    f"{ytm_tax:.4f}",
                    f"{reference:.4f}",
                    sec_name,
                    f"{remaining_years:.2f}",
                    f"{coupon_rate:.2f}",
                )
                for entry, value in zip(entries, values):
                    entry.insert(0, value)
            except Exception as exc:
                errors.append(f"{label}：{exc}")

        if errors:
            messagebox.showerror("计算失败", "\n".join(errors))

    @staticmethod
    def read_and_calculate(bond_code, ytm, t, source="auto"):
        terms = fetch_bond_terms(bond_code, source=source)
        settlement_date = t  # financepy Date
        if settlement_date >= terms.maturity_date:
            raise RuntimeError("交割日期必须早于到期日")

        remaining_years = DayCount(DayCountTypes.ACT_ACT_ISDA).year_frac(
            settlement_date, terms.maturity_date
        )[0]

        coupon_type = terms.coupon_type
        is_discount = any(key in coupon_type for key in ("贴现", "零息"))
        if is_discount:
            alpha = 1 - DayCount(DayCountTypes.ACT_365L).year_frac(
                terms.maturity_date.add_tenor("-12M"),
                settlement_date,
                terms.maturity_date,
                freq_type=FrequencyTypes.ANNUAL,
            )[0]
            if alpha <= 0:
                raise RuntimeError("贴现债券已到期")
            full_price = 100.0 / (1.0 + alpha * ytm)
            ytm_tax = (
                (100.0 + (100.0 - full_price) * TAX_RATE / (1.0 - TAX_RATE)) / full_price - 1.0
            ) / alpha
            reference = ytm / (1.0 - TAX_RATE) * 100.0
            display_coupon = 0.0
        else:
            if terms.issue_date is None:
                raise RuntimeError("附息债券缺少起息日")
            if terms.coupon_freq == 2:
                freq_type = FrequencyTypes.SEMI_ANNUAL
            elif terms.coupon_freq == 4:
                freq_type = FrequencyTypes.QUARTERLY
            elif terms.coupon_freq == 12:
                freq_type = FrequencyTypes.MONTHLY
            else:
                freq_type = FrequencyTypes.ANNUAL

            bond = Bond(terms.issue_date, terms.maturity_date, terms.coupon,
                        freq_type, DayCountTypes.ACT_ACT_ICMA)
            ytm_tax = irr_yield(bond, settlement_date, ytm)
            reference = reference_yield(terms.coupon, ytm) * 100.0
            display_coupon = terms.coupon * 100.0

        return ytm_tax * 100.0, reference, terms.sec_name, remaining_years, display_coupon


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='国债税前收益率计算（iFinD 数据源）')
    parser.add_argument('--source', choices=('auto', 'sdk', 'http'), default='auto',
                        help='iFinD 数据源：auto=先 SDK 后 HTTP（默认）')
    args = parser.parse_args()

    root = tk.Tk()
    application = YieldTaxIFind(root=root, source=args.source)
    application.mainloop()
