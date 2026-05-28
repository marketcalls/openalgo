from datetime import timedelta

from AlgorithmImports import *


class FyersBrokerageSmokeTestStrategy(QCAlgorithm):
    """Live FYERS brokerage smoke test for connect, subscribe, and optional order routing."""

    def initialize(self):
        if not self.live_mode:
            self.set_start_date(2025, 1, 1)
            self.set_cash(100000)

        self.symbol_ticker = self.get_parameter("fyers-test-symbol") or "SBIN"
        self.place_test_order = (self.get_parameter("fyers-place-test-order") or "false").lower() == "true"
        self.test_quantity = int(self.get_parameter("fyers-test-quantity") or "1")
        self.hold_minutes = int(self.get_parameter("fyers-test-hold-minutes") or "2")

        equity = self.add_equity(self.symbol_ticker, Resolution.MINUTE, Market.India)
        self.symbol = equity.symbol

        self.entry_time = None
        self.order_submitted = False
        self.last_log_time = None

        self.debug(
            f"FYERS smoke test configured for {self.symbol.value}; "
            f"place_test_order={self.place_test_order}; quantity={self.test_quantity}"
        )

    def on_data(self, data: Slice):
        if self.is_warming_up:
            return

        if self.last_log_time is None or self.time >= self.last_log_time + timedelta(minutes=1):
            has_data = data.contains_key(self.symbol) or data.bars.contains_key(self.symbol) or data.quote_bars.contains_key(self.symbol)
            self.debug(f"{self.time} FYERS heartbeat {self.symbol.value}; has_data={has_data}")
            self.last_log_time = self.time

        holding = self.portfolio[self.symbol]
        if holding.invested:
            if self.entry_time is not None and self.time >= self.entry_time + timedelta(minutes=self.hold_minutes):
                self.liquidate(self.symbol, "FYERS smoke test exit")
                self.entry_time = None
            return

        if not self.place_test_order or self.order_submitted:
            return

        self.market_order(self.symbol, self.test_quantity, tag="FYERS smoke test entry")
        self.entry_time = self.time
        self.order_submitted = True
        self.log(f"{self.time} submitted FYERS smoke test order for {self.test_quantity} {self.symbol.value}")

    def on_order_event(self, order_event: OrderEvent):
        self.log(
            f"{self.time} ORDER {order_event.status} {order_event.direction} "
            f"{order_event.fill_quantity} {order_event.symbol.value} @ {order_event.fill_price:.2f}"
        )
