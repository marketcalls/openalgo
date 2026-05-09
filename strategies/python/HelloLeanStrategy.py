from AlgorithmImports import *


class HelloLeanStrategy(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2024, 1, 1)
        self.set_end_date(2024, 1, 31)
        self.set_cash(100000)

        self.symbol = self.add_equity("SPY", Resolution.DAILY).symbol

    def on_data(self, slice: Slice):
        if self.portfolio.invested:
            return

        self.set_holdings(self.symbol, 1)
        self.debug("Entered SPY")
