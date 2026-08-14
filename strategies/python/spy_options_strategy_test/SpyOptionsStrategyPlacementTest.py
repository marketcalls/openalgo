from datetime import timedelta

from AlgorithmImports import *


class ManualOptionContract:
    def __init__(self, symbol: Symbol, last_price: float, bid_price: float, ask_price: float):
        self.symbol = symbol
        self.right = symbol.id.option_right
        self.strike = symbol.id.strike_price
        self.expiry = symbol.id.date
        self.last_price = last_price
        self.bid_price = bid_price if bid_price > 0 else last_price
        self.ask_price = ask_price if ask_price > 0 else last_price


class SpyOptionsStrategyPlacementTest(QCAlgorithm):
    """Live-paper placement test for SPY covered call and iron butterfly orders."""

    def initialize(self):
        if not self.live_mode:
            self.set_start_date(2025, 1, 2)
            self.set_cash(100000)

        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE)

        self.test_strategy = self.get_parameter("spy-options-test-strategy") or "iron_butterfly_0dte"
        self.place_test_order = self._get_bool_parameter("spy-options-place-test-order", False)
        self.quantity = int(self.get_parameter("spy-options-quantity") or "1")
        self.wing_width = float(self.get_parameter("spy-options-wing-width") or "5")
        self.hold_minutes = int(self.get_parameter("spy-options-hold-minutes") or "2")

        self.spy = self.add_equity("SPY", Resolution.MINUTE).symbol
        option = self.add_option("SPY", Resolution.MINUTE)
        option.set_filter(self._option_filter)
        self.option_symbol = option.symbol

        self.opened_tickets = []
        self.opened_symbols = set()
        self.opened_strategy = None
        self.entry_time = None
        self.test_submitted = False
        self.last_wait_log = None
        self.manual_contract_symbols = set()
        self.manual_contracts_added = False

        self.set_warm_up(10, Resolution.MINUTE)

        self.debug(
            f"{self.time} configured SPY option placement test; "
            f"strategy={self.test_strategy}; place_order={self.place_test_order}; "
            f"quantity={self.quantity}; wing_width={self.wing_width}"
        )

    def _option_filter(self, universe):
        if self.test_strategy == "iron_butterfly_0dte":
            return universe.include_weeklys().strikes(-30, 30).expiration(0, 0)

        if self.test_strategy == "covered_call":
            return universe.include_weeklys().strikes(-20, 30).expiration(0, 14)

        return universe.include_weeklys().strikes(-30, 30).expiration(1, 14)

    def on_data(self, data: Slice):
        if self.is_warming_up:
            return

        self._manage_open_position()

        if self.test_submitted:
            return

        if not self.place_test_order:
            self._log_wait("order placement disabled; set SPY_OPTIONS_PLACE_TEST_ORDER=true to submit the test order")
            return

        chain = self._get_option_chain(data)
        if chain is None:
            spy_price = float(self.securities[self.spy].price)
            if spy_price <= 0:
                self._log_wait("waiting for SPY price")
                return

            if not self.manual_contracts_added:
                self._add_manual_contracts(spy_price)
                return

            chain_contracts = self._manual_contracts_from_securities()
            if not chain_contracts:
                self._log_wait("waiting for manually subscribed SPY option contracts")
                return
        else:
            chain_contracts = list(chain)

        spy_price = float(self.securities[self.spy].price)
        if spy_price <= 0:
            self._log_wait("waiting for SPY price")
            return

        strategy = self._build_strategy(chain_contracts, spy_price)
        if strategy is None:
            return

        tickets = self.buy(strategy, self.quantity)
        self.opened_tickets = list(tickets)
        self.opened_symbols = {ticket.symbol for ticket in self.opened_tickets}
        self.opened_strategy = strategy
        self.entry_time = self.time
        self.test_submitted = True

        self.log(
            f"{self.time} submitted {self.test_strategy} placement test "
            f"qty={self.quantity}; legs={self._describe_strategy(strategy)}"
        )

    def _get_option_chain(self, data: Slice):
        chain = data.option_chains.get(self.option_symbol)
        if chain is not None:
            return chain

        for chain in data.option_chains.values():
            if chain.underlying is not None and chain.underlying.symbol == self.spy:
                return chain

        return None

    def _build_strategy(self, contracts, spy_price: float):
        if self.test_strategy == "covered_call":
            return self._build_covered_call(contracts, spy_price)

        if self.test_strategy in {"iron_butterfly", "iron_butterfly_0dte"}:
            return self._build_iron_butterfly(contracts, spy_price)

        self.error(f"Unsupported spy-options-test-strategy: {self.test_strategy}")
        self.test_submitted = True
        return None

    def _build_covered_call(self, contracts, spy_price: float):
        calls = self._tradable_contracts(contracts, OptionRight.CALL)
        calls = [contract for contract in calls if float(contract.strike) >= spy_price]
        if not calls:
            self._log_wait("waiting for covered-call OTM calls")
            return None

        contract = min(calls, key=lambda contract: (contract.expiry, abs(float(contract.strike) - spy_price)))
        self.debug(f"{self.time} selected covered call strike={contract.strike} expiry={contract.expiry:%Y-%m-%d}")
        return OptionStrategies.covered_call(self.option_symbol, contract.strike, contract.expiry)

    def _build_iron_butterfly(self, contracts, spy_price: float):
        contracts = self._tradable_contracts(contracts)
        if self.test_strategy == "iron_butterfly_0dte":
            contracts = [contract for contract in contracts if contract.expiry.date() == self.time.date()]

        by_expiry = {}
        for contract in contracts:
            by_expiry.setdefault(contract.expiry, []).append(contract)

        for expiry in sorted(by_expiry):
            expiry_contracts = by_expiry[expiry]
            call_strikes = {float(contract.strike) for contract in expiry_contracts if contract.right == OptionRight.CALL}
            put_strikes = {float(contract.strike) for contract in expiry_contracts if contract.right == OptionRight.PUT}
            common_strikes = sorted(call_strikes.intersection(put_strikes))
            if not common_strikes:
                continue

            atm = self._nearest_strike(common_strikes, spy_price)
            lower = self._nearest_strike([strike for strike in common_strikes if strike < atm], atm - self.wing_width)
            upper = self._nearest_strike([strike for strike in common_strikes if strike > atm], atm + self.wing_width)
            if lower is None or upper is None:
                continue

            width = min(atm - lower, upper - atm)
            lower = atm - width
            upper = atm + width
            if lower not in common_strikes or upper not in common_strikes:
                continue

            self.debug(f"{self.time} selected iron butterfly strikes={lower}/{atm}/{upper} expiry={expiry:%Y-%m-%d}")
            return OptionStrategies.iron_butterfly(self.option_symbol, lower, atm, upper, expiry)

        self._log_wait(f"waiting for {self.test_strategy} contracts around SPY={spy_price:.2f}")
        return None

    def _tradable_contracts(self, source_contracts, right=None):
        contracts = []
        for contract in source_contracts:
            if right is not None and contract.right != right:
                continue
            if contract.bid_price <= 0 or contract.ask_price <= 0:
                continue
            contracts.append(contract)
        return contracts

    def _add_manual_contracts(self, spy_price: float):
        symbols = list(self.option_chain_provider.get_option_contract_list(self.spy, self.time))
        if not symbols:
            self._log_wait("OptionChainProvider returned no SPY contracts")
            return

        if self.test_strategy == "covered_call":
            selected = self._select_manual_covered_call_symbols(symbols, spy_price)
        else:
            selected = self._select_manual_iron_butterfly_symbols(symbols, spy_price)

        if not selected:
            self._log_wait(f"no SPY option symbols matched {self.test_strategy} around SPY={spy_price:.2f}")
            return

        for symbol in selected:
            self.add_option_contract(symbol, Resolution.MINUTE)
            self.manual_contract_symbols.add(symbol)

        self.manual_contracts_added = True
        self.debug(f"{self.time} manually subscribed SPY option contracts: {', '.join(symbol.value for symbol in selected)}")

    def _select_manual_covered_call_symbols(self, symbols, spy_price: float):
        calls = [
            symbol
            for symbol in symbols
            if symbol.id.option_right == OptionRight.CALL
            and float(symbol.id.strike_price) >= spy_price
            and 0 <= (symbol.id.date.date() - self.time.date()).days <= 14
        ]
        if not calls:
            return []

        return [min(calls, key=lambda symbol: (symbol.id.date, abs(float(symbol.id.strike_price) - spy_price)))]

    def _select_manual_iron_butterfly_symbols(self, symbols, spy_price: float):
        max_days = 0 if self.test_strategy == "iron_butterfly_0dte" else 14
        min_days = 0 if self.test_strategy == "iron_butterfly_0dte" else 1

        by_expiry = {}
        for symbol in symbols:
            days = (symbol.id.date.date() - self.time.date()).days
            if days < min_days or days > max_days:
                continue
            by_expiry.setdefault(symbol.id.date, []).append(symbol)

        for expiry in sorted(by_expiry):
            expiry_symbols = by_expiry[expiry]
            call_strikes = {
                float(symbol.id.strike_price)
                for symbol in expiry_symbols
                if symbol.id.option_right == OptionRight.CALL
            }
            put_strikes = {
                float(symbol.id.strike_price)
                for symbol in expiry_symbols
                if symbol.id.option_right == OptionRight.PUT
            }
            common_strikes = sorted(call_strikes.intersection(put_strikes))
            if not common_strikes:
                continue

            atm = self._nearest_strike(common_strikes, spy_price)
            lower = self._nearest_strike([strike for strike in common_strikes if strike < atm], atm - self.wing_width)
            upper = self._nearest_strike([strike for strike in common_strikes if strike > atm], atm + self.wing_width)
            if lower is None or upper is None:
                continue

            width = min(atm - lower, upper - atm)
            lower = atm - width
            upper = atm + width
            wanted = {
                (OptionRight.PUT, lower),
                (OptionRight.PUT, atm),
                (OptionRight.CALL, atm),
                (OptionRight.CALL, upper),
            }
            selected = []
            for right, strike in wanted:
                match = next(
                    (
                        symbol
                        for symbol in expiry_symbols
                        if symbol.id.option_right == right and float(symbol.id.strike_price) == float(strike)
                    ),
                    None,
                )
                if match is None:
                    selected = []
                    break
                selected.append(match)
            if selected:
                return selected

        return []

    def _manual_contracts_from_securities(self):
        contracts = []
        for symbol in self.manual_contract_symbols:
            if not self.securities.contains_key(symbol):
                continue
            security = self.securities[symbol]
            if not security.has_data or security.price <= 0:
                continue
            bid = getattr(security, "bid_price", 0)
            ask = getattr(security, "ask_price", 0)
            contracts.append(ManualOptionContract(symbol, security.price, bid, ask))
        return contracts

    def _nearest_strike(self, strikes, target):
        if not strikes:
            return None
        return min(strikes, key=lambda strike: abs(float(strike) - float(target)))

    def _manage_open_position(self):
        if not self.opened_symbols or self.entry_time is None:
            return

        if self.time < self.entry_time + timedelta(minutes=self.hold_minutes):
            return

        invested_symbols = [
            symbol
            for symbol in self.opened_symbols
            if self.portfolio.contains_key(symbol) and self.portfolio[symbol].invested
        ]
        if not invested_symbols:
            self.opened_symbols = set()
            return

        for symbol in invested_symbols:
            self.liquidate(symbol, f"{self.test_strategy} placement test exit")

        if self.portfolio[self.spy].invested and self.test_strategy == "covered_call":
            self.liquidate(self.spy, "covered call placement test exit")

    def _describe_strategy(self, strategy):
        parts = []
        for leg in strategy.option_legs:
            right = "C" if leg.right == OptionRight.CALL else "P"
            parts.append(f"{leg.quantity:+d} {right}{float(leg.strike):g} {leg.expiration:%Y-%m-%d}")
        for leg in strategy.underlying_legs:
            parts.append(f"{leg.quantity:+d} underlying")
        return ", ".join(parts)

    def _log_wait(self, message: str):
        if self.last_wait_log is None or self.time - self.last_wait_log >= timedelta(minutes=2):
            self.debug(f"{self.time} {message}")
            self.last_wait_log = self.time

    def _get_bool_parameter(self, name: str, default: bool) -> bool:
        value = self.get_parameter(name)
        if value is None or value == "":
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def on_order_event(self, order_event: OrderEvent):
        self.log(
            f"{self.time} ORDER {order_event.status} {order_event.direction} "
            f"{order_event.fill_quantity} {order_event.symbol.value} @ {order_event.fill_price:.2f}"
        )
