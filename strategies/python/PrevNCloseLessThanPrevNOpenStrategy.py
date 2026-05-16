from AlgorithmImports import OrderStatus, QCAlgorithm, Resolution, Slice, TradeBar


class PrevNCloseLessThanPrevNOpenStrategy(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2021, 4, 1)
        self.set_end_date(2021, 12, 31)
        self.set_cash(100000)

        self.spy_symbol = self.add_equity("SPY", Resolution.HOUR).symbol

        # Strategy rules from the provided setup.
        self.stop_loss_points = 10.0
        self.target_profit_points = 20.0

        self.window = []
        self.entry_price = None
        self.pending_entry = False

        self.set_warm_up(3, Resolution.HOUR)

    def on_data(self, data: Slice):
        if self.spy_symbol not in data.bars:
            return

        bar: TradeBar = data.bars[self.spy_symbol]
        self.window.append(bar)
        if len(self.window) > 3:
            self.window.pop(0)

        if self.is_warming_up or len(self.window) < 3:
            return

        holding = self.portfolio[self.spy_symbol]

        if holding.invested and holding.quantity < 0:
            self.manage_short_position(bar)
            return

        if holding.invested:
            return

        if self.pending_entry:
            return

        if self.short_entry_signal():
            quantity = self.calculate_order_quantity(self.spy_symbol, -1.0)
            if quantity != 0:
                self.market_order(
                    self.spy_symbol,
                    quantity,
                    tag="PrevN bearish short entry",
                )
                self.pending_entry = True

    def short_entry_signal(self) -> bool:
        prev_2 = self.window[0]
        prev_1 = self.window[1]
        current = self.window[2]

        return (
            prev_1.close < prev_1.open
            and prev_2.close < prev_2.open
            and current.close < prev_1.close
        )

    def manage_short_position(self, bar: TradeBar):
        if self.entry_price is None:
            return

        stop_price = self.entry_price + self.stop_loss_points
        target_price = self.entry_price - self.target_profit_points

        # If both levels are touched in one bar, choose stop-first (conservative fill assumption).
        if bar.high >= stop_price:
            self.liquidate(self.spy_symbol, "Stop loss hit")
            self.entry_price = None
            return

        if bar.low <= target_price:
            self.liquidate(self.spy_symbol, "Target profit hit")
            self.entry_price = None

    def on_order_event(self, order_event):
        if order_event.symbol != self.spy_symbol:
            return

        if order_event.status in (OrderStatus.CANCELED, OrderStatus.INVALID):
            self.pending_entry = False
            return

        if order_event.status != OrderStatus.FILLED:
            return

        holding = self.portfolio[self.spy_symbol]
        if holding.invested and holding.quantity < 0:
            self.entry_price = float(holding.average_price)
            self.pending_entry = False
            return

        if not holding.invested:
            self.entry_price = None
            self.pending_entry = False