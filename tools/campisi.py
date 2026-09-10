import pandas as pd
from tqdm import tqdm
from financepy.utils import Date, DayCountTypes, FrequencyTypes
from financepy.products.bonds import Bond, YTMCalcType
from dataclasses import dataclass
from math import log

pd.set_option("display.max_columns", None)
pd.set_option("display.width", None)
pd.set_option("display.max_rows", None)


@dataclass
class Position:
    bond_id: str
    bond: Bond
    last_trade_date: Date
    size: float = 0  # >= 0
    clean_price: float = 0  # >= 0
    dirty_price: float = 0  # dirty price from clean_price
    ytm: float = 0  # ytm from clean_price
    income_return: float = (
        0  # >= 0, income accumulated since the creation of the position
    )
    capital_return: float = (
        0  # capital return accumulated since the creation of the position
    )
    cash_flow = (
        []
    )  # cash flow from the bond, content like :[date,action,bond_id,size,amount]

    def buy(self, size: float, clean_price: float, trade_date: Date) -> tuple:
        if size <= 0 or clean_price <= 0:
            raise ValueError("Size or clean_price must be positive")
        old_size = self.size
        # Calculate income_return
        income_return = (
            self.size
            * self.dirty_price
            * log(self.ytm + 1)
            * (trade_date - self.last_trade_date)
            / 365
        )
        self.income_return = self.income_return + income_return
        # Calculate capital_return
        capital_return = 0

        # Update cashflow
        # coupon during holding period
        for i, j in zip(self.bond.cpn_dts, self.bond.flow_amounts):
            if (i > self.last_trade_date) & (i <= trade_date):
                self.cash_flow.append(
                    [i, "coupon", self.bond_id, self.size, j * self.size * 100]
                )
        # buy bond and cash out
        self.cash_flow.append(
            [
                trade_date,
                "buy",
                self.bond_id,
                size,
                -size * (clean_price + self.bond.accrued_interest(trade_date)),
            ]
        )

        # Update Position
        self.size = self.size + size
        self.clean_price = (
            old_size * self.clean_price + size * clean_price
        ) / self.size
        self.dirty_price = self.clean_price + self.bond.accrued_interest(trade_date)
        self.ytm = self.bond.yield_to_maturity(
            trade_date, self.clean_price, YTMCalcType.CFETS
        )
        self.last_trade_date = trade_date

        return income_return, capital_return

    def sell(self, size: float, clean_price: float, trade_date: Date) -> tuple:
        if size <= 0 or clean_price <= 0:
            raise ValueError("Size or clean_price must be positive")
        # Calculate income_return
        income_return = (
            self.size
            * self.dirty_price
            * log(self.ytm + 1)
            * (trade_date - self.last_trade_date)
            / 365
        )

        self.income_return = self.income_return + income_return
        # Calculate capital_return
        md = self.bond.modified_duration(
            self.last_trade_date, self.ytm, YTMCalcType.CFETS
        )

        ytm_sold = self.bond.yield_to_maturity(
            trade_date, clean_price, YTMCalcType.CFETS
        )
        capital_return = size * self.dirty_price * (-md) * (ytm_sold - self.ytm)

        # 凸性的影响
        convexity = (
            self.bond.convexity_from_ytm(
                self.last_trade_date, self.ytm, YTMCalcType.CFETS
            )
            / 2
        )
        capital_return_convexity = (
            self.size
            * self.dirty_price
            * convexity
            * (ytm_sold - self.ytm)
            * (ytm_sold - self.ytm)
            * 100
        )
        capital_return = capital_return + capital_return_convexity
        self.capital_return = self.capital_return + capital_return

        # Update cashflow
        # coupon during holding period
        for i, j in zip(self.bond.cpn_dts, self.bond.flow_amounts):
            if (i > self.last_trade_date) & (i <= trade_date):
                self.cash_flow.append(
                    [i, "coupon", self.bond_id, self.size, j * self.size * 100]
                )
        # sell bond and cash in
        self.cash_flow.append(
            [
                trade_date,
                "sell",
                self.bond_id,
                size,
                size * (clean_price + self.bond.accrued_interest(trade_date)),
            ]
        )

        # Update Position
        self.size = self.size - size
        self.last_trade_date = trade_date

        return income_return, capital_return

    def sell_buy(self, clean_price: float, trade_date: Date):
        size = self.size
        if size > 0:
            self.sell(self.size, clean_price, trade_date)
            self.buy(size, clean_price, trade_date)


class Campisi:
    def __init__(self):
        self.positions = []
        self.income_return: float = 0.0
        self.capital_return: float = 0.0

    def load_trades(self):
        trade_file = "./campisi.xlsx"
        trades = pd.read_excel(trade_file, sheet_name="trades")
        fair_values = pd.read_excel(
            trade_file, sheet_name="fair_clean_price (fluctuations)", index_col=0
        )
        # fairs = pd.read_excel(trade_file, sheet_name="fair_clean_price (to10)", index_col=0)
        # fairs = pd.read_excel(trade_file, sheet_name="fair_clean_price (to05) ", index_col=0)
        # fairs = pd.read_excel(trade_file,sheet_name="fair_clean_price (to10to05)",index_col=0)
        # fairs = pd.read_excel(trade_file, sheet_name="fair_clean_price (to10) (2)", index_col=0)
        for index, row in trades.iterrows():
            # before new trade day, sell all the bonds and then buy back at fair price
            if index != 0:
                if row["date"] > trades.at[index - 1, "date"]:
                    fairs_i = fair_values[
                        (fair_values.index < row["date"])
                        & (fair_values.index >= trades.at[index - 1, "date"])
                    ]
                    for fairs_i_date, fairs_i_price in fairs_i.iterrows():
                        fairs_i_date_format = Date(
                            fairs_i_date.day, fairs_i_date.month, fairs_i_date.year
                        )
                        for position in self.positions:
                            position.sell_buy(
                                float(fairs_i_price[position.bond_id]),
                                fairs_i_date_format,
                            )

            bond_code = row["code"]
            trade_date = Date(row["date"].day, row["date"].month, row["date"].year)
            size = row["size"]
            clean_price = row["clean_price"]
            # Assuming 'action' column specifies 'buy' or 'sell'
            action = row["action"]

            position = next((p for p in self.positions if p.bond_id == bond_code), None)

            if position:  # If bond already exists in the positions
                if action == "buy":
                    position.buy(size, clean_price, trade_date)
                elif action == "sell":
                    position.sell(size, clean_price, trade_date)

            else:  # Add a new bond to the positions
                issue_date = Date(
                    row["issue_date"].day,
                    row["issue_date"].month,
                    row["issue_date"].year,
                )
                maturity_date = Date(
                    row["maturity_date"].day,
                    row["maturity_date"].month,
                    row["maturity_date"].year,
                )
                coupon = row["coupon_rate"]
                dc_type = DayCountTypes.ACT_ACT_ICMA
                coupon_freq = row["coupon_frequency"]
                if coupon_freq == 2:
                    freq_type = FrequencyTypes.SEMI_ANNUAL
                elif coupon_freq == 4:
                    freq_type = FrequencyTypes.QUARTERLY
                else:
                    freq_type = FrequencyTypes.ANNUAL
                bond = Bond(issue_date, maturity_date, coupon, freq_type, dc_type)
                new_position = Position(
                    bond_id=bond_code, bond=bond, last_trade_date=trade_date
                )
                self.positions.append(new_position)
                if action == "buy":
                    new_position.buy(size, clean_price, trade_date)
                elif action == "sell":
                    new_position.sell(size, clean_price, trade_date)
            # after loading the last trade, sell all the bonds
            if index == trades.index[-1]:
                for position in self.positions:
                    if position.size != 0:
                        fair_clean_price = float(
                            fair_values.at[row["date"], position.bond_id]
                        )
                        position.sell(position.size, fair_clean_price, trade_date)

    def get_income_return(self):
        income = 0
        for position in self.positions:
            income = income + position.income_return
        return income

    def get_capital_return(self):
        capital_return = 0
        for position in self.positions:
            capital_return = capital_return + position.capital_return
        return capital_return

    def total_return(self):
        return self.get_income_return() + self.get_capital_return()

    def get_cash_flow(self):
        cash_flow = []
        for position in self.positions:
            cash_flow = cash_flow + position.cash_flow
        return cash_flow

    def actual_return(self):
        cash_flow = [i[-1] for i in self.get_cash_flow()]
        return sum(cash_flow)


def main():
    campisi = Campisi()
    campisi.load_trades()
    for i in campisi.positions[0].cash_flow:
        print(i)
    print(f"income_return:{campisi.get_income_return()/10000:.2f}")
    print(f"capital_return:{campisi.get_capital_return()/10000:.2f}")
    print(f"total_return:{campisi.total_return()/10000:.2f}")
    print(f"actual_return:{campisi.actual_return()/10000:.2f}")
    print(
        f"return_error:{campisi.total_return()/10000-campisi.actual_return()/10000:.2f}"
    )
    print(
        f"return_erro_ratio:{abs(campisi.total_return()/campisi.actual_return()-1):.2%}"
    )


if __name__ == "__main__":
    main()
