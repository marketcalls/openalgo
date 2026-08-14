from datetime import datetime, timedelta

from AlgorithmImports import *


class MesSimpleBuySellTestStrategy(QCAlgorithm):
    """Single round-trip MES order test for live-paper connectivity checks."""

    def initialize(self):
        if not self.live_mode:
            self.set_start_date(2025, 1, 1)
            self.set_cash(100000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE)

        self.mes_root = self.add_future(
            Futures.Indices.MicroSP500EMini,
            Resolution.MINUTE,
            extended_market_hours=True,
            fill_forward=True,
        )
        self.mes_root.set_filter(timedelta(0), timedelta(days=120))

        self.trade_symbol = None
        self.manual_contract = self._get_manual_contract()
        if self.manual_contract is not None:
            self.add_future_contract(
                self.manual_contract,
                Resolution.MINUTE,
                extended_market_hours=True,
                fill_forward=True,
            )
            self.trade_symbol = self.manual_contract
            self.debug(f"{self.time} configured explicit MES contract {self.trade_symbol.value}")
        else:
            self.debug(f"{self.time} configured canonical MES future; waiting for IB/Lean mapped contract")

        self.trade_quantity = 1
        self.hold_minutes = 2
        self.max_test_entries = 1

        self.entry_time = None
        self.test_entries = 0
        self.last_wait_log = None

        self.set_warm_up(30, Resolution.MINUTE)

    def on_data(self, data: Slice):
        if self.is_warming_up:
            return

        self._select_trade_symbol(data)
        if self.trade_symbol is None:
            self._log_wait("waiting for MES mapped/front-month contract")
            return

        security = self.securities[self.trade_symbol] if self.securities.contains_key(self.trade_symbol) else None
        if security is None:
            self._log_wait(f"waiting for MES security subscription {self.trade_symbol.value}")
            return

        if not security.exchange.hours.is_open(self.time, True):
            self._log_wait(f"waiting for MES exchange to open before trading {self.trade_symbol.value}")
            return

        if not self._has_tradeable_price(data, security):
            self._log_wait(f"waiting for live MES price data for {self.trade_symbol.value}")
            return

        holding = self.portfolio[self.trade_symbol]

        if holding.invested:
            if self.entry_time is not None and self.time >= self.entry_time + timedelta(minutes=self.hold_minutes):
                self.liquidate(self.trade_symbol, "MES connectivity test exit")
                self.entry_time = None
            return

        if self.test_entries >= self.max_test_entries:
            return

        self.market_order(self.trade_symbol, self.trade_quantity, tag="MES connectivity test entry")
        self.entry_time = self.time
        self.test_entries += 1
        self.log(f"{self.time} submitted MES connectivity test entry for {self.trade_symbol.value}")

    def _get_manual_contract(self):
        expiry = self.get_parameter("mes-contract-expiry")
        if not expiry:
            return None

        contract_expiry = datetime.strptime(expiry, "%Y-%m-%d")
        return Symbol.create_future(
            Futures.Indices.MicroSP500EMini,
            Market.CME,
            contract_expiry,
        )

    def _select_trade_symbol(self, data: Slice):
        if self.manual_contract is not None:
            return

        mapped = self.mes_root.mapped
        if mapped is not None and mapped != self.mes_root.symbol:
            if self.trade_symbol != mapped:
                self.trade_symbol = mapped
                self.log(f"{self.time} active MES mapped contract -> {self.trade_symbol.value}")
            return

        chain = data.future_chains.get(self.mes_root.symbol)
        if chain is None:
            return

        contracts = sorted(
            [contract for contract in chain if contract.expiry.date() >= self.time.date()],
            key=lambda contract: contract.expiry,
        )
        if contracts:
            symbol = contracts[0].symbol
            if self.trade_symbol != symbol:
                self.trade_symbol = symbol
                self.log(f"{self.time} active MES front contract from chain -> {self.trade_symbol.value}")

    def _has_tradeable_price(self, data: Slice, security) -> bool:
        if data.bars.contains_key(self.trade_symbol) or data.quote_bars.contains_key(self.trade_symbol):
            return True

        return security.has_data and security.price is not None and security.price > 0

    def _log_wait(self, message: str):
        if self.last_wait_log is None or self.time - self.last_wait_log >= timedelta(minutes=5):
            symbol = self.trade_symbol.value if self.trade_symbol is not None else "MES"
            self.debug(f"{self.time} {message}; symbol={symbol}")
            self.last_wait_log = self.time

    def on_order_event(self, order_event: OrderEvent):
        self.log(
            f"{self.time} ORDER {order_event.status} {order_event.direction} "
            f"{order_event.fill_quantity} {order_event.symbol.value} @ {order_event.fill_price:.2f}"
        )
