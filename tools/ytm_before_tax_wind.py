import tkinter as tk
from tkinter import *
from WindPy import w
import pandas as pd
from financepy.utils import *
from financepy.products.bonds import *
from scipy import optimize
import datetime

w.start()


class YieldTaxWind(tk.Frame):
    def __init__(self, root):
        super().__init__(root)
        self.master = root
        self.pack()
        self.ma = tk.StringVar()  # 债券代码1
        self.ytm = tk.DoubleVar()  # 债券到期收益率1
        self.settle = tk.StringVar(value=str(datetime.date.today() + datetime.timedelta(days=1)))  # 交割日期1
        self.ma2 = tk.StringVar()  # 债券代码2
        self.ytm2 = tk.DoubleVar()  # 债券到期收益率2
        self.settle2 = tk.StringVar(value=str(datetime.date.today() + datetime.timedelta(days=1)))  # 交割日期2
        frame2 = Frame(self)
        Label(frame2, text='税前收益率 ').grid(row=0, column=0)
        self.disp_tf = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf.grid(row=0, column=1)
        self.disp_tf3 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf3.grid(row=0, column=2, padx=5)
        Label(frame2, text='参考值').grid(row=1, column=0)
        self.disp_tf2 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf2.grid(row=1, column=1)
        self.disp_tf4 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf4.grid(row=1, column=2, padx=5)
        Label(frame2, text='债券简称').grid(row=2, column=0)
        self.disp_tf5 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf5.grid(row=2, column=1)
        self.disp_tf6 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf6.grid(row=2, column=2, padx=5)
        Label(frame2, text='剩余期限').grid(row=3, column=0)
        self.disp_tf7 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf7.grid(row=3, column=1)
        self.disp_tf8 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf8.grid(row=3, column=2, padx=5)
        Label(frame2, text='票面利率').grid(row=4, column=0)
        self.disp_tf9 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf9.grid(row=4, column=1)
        self.disp_tf10 = Entry(frame2, width=20, font=('Arial', 10))
        self.disp_tf10.grid(row=4, column=2, padx=5)
        frame2.grid(pady=5)

        root.geometry('500x300')
        root.title('税前收益率计算')

        self.int_wind()

    def int_wind(self):
        frame1 = Frame(self)
        Label(frame1, text='  债券代码* ').grid(row=0, column=0)
        Entry(frame1, textvariable=self.ma).grid(row=0, column=1)
        Entry(frame1, textvariable=self.ma2).grid(row=0, column=2, padx=5)
        Label(frame1, text='ytm*').grid(row=1, column=0)
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
        self.disp_tf.delete(0, END)
        self.disp_tf2.delete(0, END)
        self.disp_tf3.delete(0, END)
        self.disp_tf4.delete(0, END)
        self.disp_tf5.delete(0, END)
        self.disp_tf6.delete(0, END)
        self.disp_tf7.delete(0, END)
        self.disp_tf8.delete(0, END)
        self.disp_tf9.delete(0, END)
        self.disp_tf10.delete(0, END)
        u = self.ma.get()
        p = self.ytm.get()
        t1 = self.settle.get()
        u2 = self.ma2.get()
        p2 = self.ytm2.get()
        t2 = self.settle2.get()
        u = u.replace(" ", "")
        t1 = t1.replace(" ", "")
        u2 = u2.replace(" ", "")
        t2 = t2.replace(" ", "")
        if u.find('.') == -1:
            u += ".IB"
        if u2.find('.') == -1:
            u2 += ".IB"
        t = t1[2:]
        t = datetime.datetime.strptime(t, '%y-%m-%d').date()
        ytm = float(p) / 100
        bond_code = u
        if bond_code != ".IB":
            ytm_tax, reference, sec_name, remaining_years, coupon_rate = YieldTaxWind.read_and_calculate(bond_code,
                                                                                                         ytm, t)
            self.disp_tf.insert(0, f'{ytm_tax}')
            self.disp_tf2.insert(0, f'{reference}')
            self.disp_tf5.insert(0, f'{sec_name}')
            self.disp_tf7.insert(0, f'{remaining_years:.2f}years')
            self.disp_tf9.insert(0, f'{coupon_rate:.2f}')

        # Right side
        t = t2[2:]
        t = datetime.datetime.strptime(t, '%y-%m-%d').date()
        ytm = float(p2) / 100
        bond_code = u2
        if bond_code != ".IB":
            ytm_tax, reference, sec_name, remaining_years, coupon_rate = YieldTaxWind.read_and_calculate(bond_code,
                                                                                                         ytm, t)
            self.disp_tf3.insert(0, f'{ytm_tax}')
            self.disp_tf4.insert(0, f'{reference}')
            self.disp_tf6.insert(0, f'{sec_name}')
            self.disp_tf8.insert(0, f'{remaining_years:.2f}years')
            self.disp_tf10.insert(0, f'{coupon_rate:.2f}')

    @staticmethod
    def ytm_to_price_equation(ytm_t, c, f, n, alpha, full_price):
        return ((((1.0 / (1.0 + ytm_t / f)) ** alpha) * (c / f * (1.0 - alpha) + c / f / 0.75 * alpha) + (
                (1.0 / (1.0 + ytm_t / f)) ** (alpha + 1)) * c / f / 0.75 * (
                         1.0 - (1.0 / (1.0 + ytm_t / f)) ** n) / (1.0 - (1.0 / (1.0 + ytm_t / f))) + (
                         1.0 / (1.0 + ytm_t / f)) ** (alpha + n)) * 100.0 - full_price)

    @staticmethod
    def get_bond_data_by_wind(bond_code):
        today = datetime.date.today()
        w_data = w.wsd(bond_code,
                       "trade_code,fullname,sec_name,carrydate,maturitydate,couponrate,interestfrequency,coupon",
                       str(today), str(today), "credibility=1")
        while w_data.Data == [['CWSDService: No data.']]:
            today = today + datetime.timedelta(days=2)
            w_data = w.wsd(bond_code,
                           "trade_code,fullname,sec_name,carrydate,maturitydate,couponrate,interestfrequency,coupon",
                           str(today), str(today), "credibility=1")
        df = pd.DataFrame(w_data.Data, index=w_data.Fields, columns=w_data.Times)
        df = df.T
        issue_date = Date(df['CARRYDATE'][0].day, df['CARRYDATE'][0].month, df['CARRYDATE'][0].year)
        maturity_date = Date(df['MATURITYDATE'][0].day, df['MATURITYDATE'][0].month, df['MATURITYDATE'][0].year)
        sec_name = df['SEC_NAME'][0]
        coupon_type = df['COUPON'][0]
        coupon = df['COUPONRATE'][0] / 100
        coupon_freq = df['INTERESTFREQUENCY'][0]
        return issue_date, maturity_date, sec_name, coupon_type, coupon, coupon_freq

    @staticmethod
    def read_and_calculate(bond_code, ytm, t):
        issue_date, maturity_date, sec_name, coupon_type, coupon, coupon_freq = YieldTaxWind.get_bond_data_by_wind(
            bond_code)
        settlement_date = Date(t.day, t.month, t.year)
        print(settlement_date)
        remaining_years = (DayCount(DayCountTypes.ACT_ACT_ISDA).year_frac(settlement_date, maturity_date)[0])
        if coupon_type == '贴现':
            alpha = (1 - (DayCount(DayCountTypes.ACT_365L).year_frac(maturity_date.add_tenor("-12M"), settlement_date,
                                                                     maturity_date, freq_type=FrequencyTypes.ANNUAL)[
                0]))
            full_price = 100 / (1 + alpha * ytm)
            ytm_tax = ((100 + (100 - full_price) / 3) / full_price - 1) / alpha
            reference = ytm * 4 / 3 * 100
            coupon = 0.0
        else:
            accrual_type = DayCountTypes.ACT_ACT_ICMA
            face = ONE_MILLION
            if coupon_freq == 2:
                freq_type = FrequencyTypes.SEMI_ANNUAL
            elif coupon_freq == 4:
                freq_type = FrequencyTypes.QUARTERLY
            else:
                freq_type = FrequencyTypes.ANNUAL
            bond = Bond(issue_date, maturity_date, coupon, freq_type, accrual_type)
            full_price = bond.dirty_price_from_ytm(settlement_date, ytm, YTMCalcType.CFETS)
            f = annual_frequency(bond._freq_type)
            c = bond._coupon
            n = 0
            for dt in bond._coupon_dates:
                if dt > settlement_date:
                    n += 1
            n = n - 1
            alpha = bond._alpha
            if n == 0:
                full_price = (c / f + 1) / (1 + (1 - (
                    DayCount(DayCountTypes.ACT_365L).year_frac(maturity_date.add_tenor("-12M"), settlement_date,
                                                               maturity_date, freq_type=FrequencyTypes.ANNUAL)[
                        0])) * ytm) * 100
                ytm_tax = ((c / f * (1 - alpha) + c / f / 0.75 * alpha + 1) / (full_price / 100) - 1) / (1 - (
                    DayCount(DayCountTypes.ACT_365L).year_frac(maturity_date.add_tenor("-12M"), settlement_date,
                                                               maturity_date, freq_type=FrequencyTypes.ANNUAL)[0]))
            else:
                ytm_tax = optimize.newton(YieldTaxWind.ytm_to_price_equation,
                                          x0=0.05,
                                          fprime=None,
                                          tol=1e-8,
                                          args=(c, f, n, alpha, full_price),
                                          maxiter=50,
                                          fprime2=None)
            reference = (c / 3 + ytm) * 100
        return ytm_tax * 100, reference, sec_name, remaining_years, coupon * 100


if __name__ == '__main__':
    root = tk.Tk()
    application = YieldTaxWind(root=root)
    application.mainloop()
