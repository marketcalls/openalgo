from datetime import date, datetime, timedelta

from AlgorithmImports import *


class OpenAlgoOrderPlacementTest(QCAlgorithm):
    """Throwaway live order-placement test for the OpenAlgo Lean brokerage."""

    def initialize(self):
        if not self.live_mode:
            self.set_start_date(2026, 5, 29)
            self.set_cash(1000000)

        self.place_test_orders = self._get_bool_parameter("openalgo-place-test-orders", False)
        self.quantity = int(self.get_parameter("openalgo-test-quantity") or "1")
        self.hold_minutes = int(self.get_parameter("openalgo-hold-minutes") or "5")
        self.submit_without_price = self._get_bool_parameter("openalgo-submit-without-price", True)

        self.sbin_ticker = self.get_parameter("openalgo-sbin-symbol") or "SBIN"
        self.nifty_future_ticker = self.get_parameter("openalgo-nifty-future-symbol") or "NIFTY"
        self.expiry = self._parse_expiry(self.get_parameter("openalgo-fo-expiry"))

        self.sbin = self.add_equity(self.sbin_ticker, Resolution.MINUTE, Market.India).symbol
        self.nifty_future = self._add_future_contract(self.nifty_future_ticker, self.expiry)

        self.entry_legs = []
        self.exit_legs = []
        self._register_bull_call_spread("nifty", "NIFTY", Market.India)
        self._register_bull_call_spread("banknifty", "BANKNIFTY", Market.India)
        self._register_bull_call_spread("sensex", "SENSEX", Market.India)

        self.entry_submitted = False
        self.exit_submitted = False
        self.entry_time = None
        self.last_wait_log = None

        self.debug(
            f"{self.time} configured OpenAlgo order placement test; "
            f"place_orders={self.place_test_orders}; quantity={self.quantity}; "
            f"expiry={self.expiry:%Y-%m-%d}; hold_minutes={self.hold_minutes}"
        )

    def on_data(self, data: Slice):
        if self.exit_submitted:
            return

        if self.entry_submitted:
            if self.time >= self.entry_time + timedelta(minutes=self.hold_minutes):
                self._submit_exit_orders()
            return

        if not self.place_test_orders:
            self._log_wait("order placement disabled; set OPENALGO_PLACE_TEST_ORDERS=true")
            return

        if not self._ready_for_entry(data):
            return

        self._submit_entry_orders()

    def _submit_entry_orders(self):
        self.entry_legs = [
            (self.sbin, self.quantity, "buy SBIN"),
            (self.nifty_future, self.quantity, "buy current-month NIFTY future"),
        ] + self.entry_legs

        for symbol, quantity, tag in self.entry_legs:
            self.market_order(symbol, quantity, asynchronous=True, tag=f"OpenAlgo test entry: {tag}")
            self.log(f"{self.time} submitted entry {quantity:+d} {symbol.value}; {tag}")

        self.entry_time = self.time
        self.entry_submitted = True
        self.log(f"{self.time} entry batch submitted; exit scheduled after {self.hold_minutes} minutes")

    def _submit_exit_orders(self):
        self.exit_legs = [
            (self.sbin, -self.quantity, "sell SBIN"),
            (self.nifty_future, -self.quantity, "sell NIFTY future"),
        ] + self.exit_legs

        for symbol, quantity, tag in self.exit_legs:
            self.market_order(symbol, quantity, asynchronous=True, tag=f"OpenAlgo test exit: {tag}")
            self.log(f"{self.time} submitted exit {quantity:+d} {symbol.value}; {tag}")

        self.exit_submitted = True
        self.log(f"{self.time} exit batch submitted")

    def _register_bull_call_spread(self, key: str, ticker: str, market: str):
        if not self._get_bool_parameter(f"openalgo-{key}-spread-enabled", True):
            self.debug(f"{ticker} bull call spread disabled by configuration")
            return

        long_strike = self._get_float_parameter(f"openalgo-{key}-long-call-strike")
        short_strike = self._get_float_parameter(f"openalgo-{key}-short-call-strike")
        if long_strike <= 0 or short_strike <= 0:
            self.debug(f"{ticker} bull call spread skipped; configure long/short call strikes")
            return

        if short_strike <= long_strike:
            self.error(f"{ticker} bull call spread skipped; short strike must be above long strike")
            return

        underlying = Symbol.create(ticker, SecurityType.EQUITY, market)
        long_call = Symbol.create_option(
            underlying,
            market,
            OptionStyle.EUROPEAN,
            OptionRight.CALL,
            long_strike,
            self.expiry,
        )
        short_call = Symbol.create_option(
            underlying,
            market,
            OptionStyle.EUROPEAN,
            OptionRight.CALL,
            short_strike,
            self.expiry,
        )

        self.add_option_contract(long_call, Resolution.MINUTE)
        self.add_option_contract(short_call, Resolution.MINUTE)

        self.entry_legs.extend(
            [
                (long_call, self.quantity, f"buy {ticker} {long_strike:g} call"),
                (short_call, -self.quantity, f"sell {ticker} {short_strike:g} call"),
            ]
        )
        self.exit_legs.extend(
            [
                (long_call, -self.quantity, f"sell {ticker} {long_strike:g} call"),
                (short_call, self.quantity, f"buy {ticker} {short_strike:g} call"),
            ]
        )

        self.debug(
            f"{self.time} registered {ticker} bull call spread "
            f"{long_strike:g}/{short_strike:g} expiring {self.expiry:%Y-%m-%d}"
        )

    def _add_future_contract(self, ticker: str, expiry: datetime) -> Symbol:
        symbol = Symbol.create_future(ticker, Market.India, expiry)
        self.add_future_contract(symbol, Resolution.MINUTE)
        return symbol

    def _ready_for_entry(self, data: Slice) -> bool:
        if self.submit_without_price:
            return True

        symbols = [self.sbin, self.nifty_future] + [symbol for symbol, _, _ in self.entry_legs]
        missing = [
            symbol.value
            for symbol in symbols
            if not self.securities.contains_key(symbol) or float(self.securities[symbol].price) <= 0
        ]
        if missing:
            self._log_wait(f"waiting for tradable price on {', '.join(missing[:4])}")
            return False
        return True

    def _parse_expiry(self, value: str) -> datetime:
        if value:
            return datetime.strptime(value.strip(), "%Y-%m-%d")

        today = datetime.utcnow().date()
        expiry = self._last_weekday(today.year, today.month, 3)
        if today > expiry:
            next_month = today.replace(day=28) + timedelta(days=4)
            expiry = self._last_weekday(next_month.year, next_month.month, 3)
        return datetime(expiry.year, expiry.month, expiry.day)

    def _last_weekday(self, year: int, month: int, weekday: int) -> date:
        if month == 12:
            cursor = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            cursor = date(year, month + 1, 1) - timedelta(days=1)

        while cursor.weekday() != weekday:
            cursor -= timedelta(days=1)
        return cursor

    def _get_bool_parameter(self, name: str, default: bool) -> bool:
        value = self.get_parameter(name)
        if value is None or str(value).strip() == "":
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def _get_float_parameter(self, name: str) -> float:
        value = self.get_parameter(name)
        if value is None or str(value).strip() == "":
            return 0.0
        return float(value)

    def _log_wait(self, message: str):
        if self.last_wait_log == message:
            return
        self.last_wait_log = message
        self.debug(f"{self.time} {message}")
