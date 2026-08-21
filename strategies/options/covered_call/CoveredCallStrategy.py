from datetime import datetime

from AlgorithmImports import Market, OptionRight, OptionStyle, QCAlgorithm, Resolution, Slice, Symbol


class CoveredCallStrategy(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2023, 8, 3)
        self.set_end_date(2023, 8, 3)
        self.set_cash(100000)

        self.underlying = self.add_equity("SPY", Resolution.MINUTE).symbol
        self.contract_size = 100

        # Match a contract that exists in local data:
        # 20230803_spy_minute_*_american_call_4700000_20230901.csv
        self.short_call_symbol = Symbol.create_option(
            self.underlying,
            Market.USA,
            OptionStyle.AMERICAN,
            OptionRight.CALL,
            470.0,
            datetime(2023, 9, 1),
        )
        self.add_option_contract(self.short_call_symbol, Resolution.MINUTE)

        self.stock_entry_submitted = False
        self.call_entry_submitted = False
        self.call_sold = False

    def on_data(self, data: Slice):
        if self.is_warming_up:
            return

        underlying_price = self.securities[self.underlying].price
        if underlying_price <= 0:
            return

        if self.portfolio[self.underlying].quantity < self.contract_size:
            if not self.stock_entry_submitted:
                self.market_order(self.underlying, self.contract_size)
                self.stock_entry_submitted = True
                self.debug(f"{self.time} bought {self.contract_size} shares of SPY")
            return

        if self.stock_entry_submitted and self.portfolio[self.underlying].quantity >= self.contract_size:
            self.stock_entry_submitted = False

        if self.call_sold:
            return

        if self.call_entry_submitted:
            return

        if not data.contains_key(self.short_call_symbol):
            return

        option_price = self.securities[self.short_call_symbol].price
        if option_price <= 0:
            return

        self.market_order(self.short_call_symbol, -1)
        self.call_entry_submitted = True
        self.call_sold = True

        self.debug(
            f"{self.time} sold call {self.short_call_symbol.value} at approx {option_price:.2f}"
        )