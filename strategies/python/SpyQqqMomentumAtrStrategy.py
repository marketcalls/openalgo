from AlgorithmImports import MovingAverageType, QCAlgorithm, Resolution, Slice, Symbol


class SpyQqqMomentumAtrStrategy(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2018, 1, 1)
        self.set_end_date(2024, 12, 31)
        self.set_cash(100000)

        self.lookback = 90
        self.atr_period = 20
        self.atr_multiple = 2.5
        self.risk_fraction = 0.01
        self.max_allocation = 1.0

        self.symbols = []
        self.symbol_data = {}
        for ticker in ["SPY", "QQQ"]:
            symbol = self.add_equity(ticker, Resolution.DAILY).symbol
            self.symbols.append(symbol)
            self.symbol_data[symbol] = SymbolState(
                symbol,
                self.atr(symbol, self.atr_period, MovingAverageType.SIMPLE, Resolution.DAILY),
            )

        self.selected_symbol = None
        self.stop_price = None

        self.set_warm_up(max(self.lookback + 1, self.atr_period + 1), Resolution.DAILY)

        self.schedule.on(
            self.date_rules.month_start(self.symbols[0]),
            self.time_rules.after_market_open(self.symbols[0], 30),
            self.rebalance,
        )

    def on_data(self, data: Slice):
        if self.is_warming_up or self.selected_symbol is None:
            return

        if not self.portfolio[self.selected_symbol].invested:
            return

        atr = self.symbol_data[self.selected_symbol].atr.current.value
        if atr <= 0:
            return

        current_price = self.securities[self.selected_symbol].price
        if current_price <= 0:
            return

        desired_stop = round(current_price - self.atr_multiple * atr, 2)
        if desired_stop <= 0:
            return

        if self.stop_price is None:
            self.stop_price = desired_stop
            return

        if current_price <= self.stop_price:
            self.debug(
                f"{self.time.date()} ATR stop triggered for {self.selected_symbol.Value} price={current_price:.2f} stop={self.stop_price:.2f}"
            )
            self.exit_positions("ATR stop triggered")
            return

        if desired_stop > self.stop_price:
            self.stop_price = desired_stop

    def rebalance(self):
        if self.is_warming_up:
            return

        best_symbol = None
        best_momentum = float("-inf")

        for symbol in self.symbols:
            momentum = self.calculate_momentum(symbol)
            if momentum is None:
                continue

            if momentum > best_momentum:
                best_momentum = momentum
                best_symbol = symbol

        if best_symbol is None:
            return

        if best_momentum <= 0:
            self.exit_positions("Momentum below zero")
            return

        if self.selected_symbol != best_symbol:
            self.exit_positions(f"Rotate into {best_symbol.Value}")

        target_weight = self.calculate_target_weight(best_symbol)
        if target_weight <= 0:
            self.exit_positions("ATR sizing returned zero")
            return

        self.selected_symbol = best_symbol
        self.set_holdings(best_symbol, target_weight)
        self.refresh_stop_level(best_symbol)

        self.debug(
            f"{self.time.date()} holding {best_symbol.Value} momentum={best_momentum:.2%} weight={target_weight:.2%}"
        )

    def calculate_momentum(self, symbol: Symbol):
        history = self.history(symbol, self.lookback + 1, Resolution.DAILY)
        if history.empty:
            return None

        closes = history["close"]
        if len(closes) < self.lookback + 1:
            return None

        start_price = float(closes.iloc[0])
        end_price = float(closes.iloc[-1])
        if start_price <= 0:
            return None

        return end_price / start_price - 1.0

    def calculate_target_weight(self, symbol: Symbol):
        atr = self.symbol_data[symbol].atr.current.value
        price = self.securities[symbol].price
        if atr <= 0 or price <= 0:
            return 0

        stop_distance = self.atr_multiple * atr
        if stop_distance <= 0:
            return 0

        portfolio_value = self.portfolio.total_portfolio_value
        risk_budget = portfolio_value * self.risk_fraction
        target_value = risk_budget * price / stop_distance
        return min(self.max_allocation, target_value / portfolio_value)

    def refresh_stop_level(self, symbol: Symbol):
        atr = self.symbol_data[symbol].atr.current.value
        price = self.securities[symbol].price
        if atr <= 0 or price <= 0:
            return

        stop_price = round(price - self.atr_multiple * atr, 2)
        if stop_price <= 0:
            return

        self.stop_price = stop_price

    def exit_positions(self, reason: str):
        for symbol in self.symbols:
            if self.portfolio[symbol].invested:
                self.liquidate(symbol, reason)

        self.selected_symbol = None
        self.stop_price = None


class SymbolState:
    def __init__(self, symbol: Symbol, atr):
        self.symbol = symbol
        self.atr = atr