from datetime import datetime, timedelta

from AlgorithmImports import *


class MesSimpleBuySellTestStrategy(QCAlgorithm):
    """Single round-trip MES order test for live-paper connectivity checks."""

    def initialize(self):
        if not self.live_mode:
            self.set_start_date(2025, 1, 1)
            self.set_cash(100000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE)

        # Local live mapping is empty in this setup, so add the tradable MES
        # contract directly instead of waiting on the canonical future map file.
        self.contract_expiry = self._get_contract_expiry()
        mes_contract = Symbol.create_future(
            Futures.Indices.MicroSP500EMini,
            Market.CME,
            self.contract_expiry,
        )
        self.mes = self.add_future_contract(
            mes_contract,
            Resolution.MINUTE,
            extended_market_hours=True,
        )

        self.trade_symbol = self.mes.symbol
        self.debug(f"{self.time} configured MES contract {self.trade_symbol.value} expiring {self.contract_expiry:%Y-%m-%d}")

        self.trade_quantity = 1
        self.hold_minutes = 2
        self.max_test_entries = 1

        self.entry_time = None
        self.test_entries = 0

        self.set_warm_up(30, Resolution.MINUTE)

    def on_data(self, data: Slice):
        if self.is_warming_up:
            return

        if not self.mes.exchange.hours.is_open(self.time, True):
            self.debug(f"{self.time} waiting for MES exchange to open before trading {self.trade_symbol.value}")
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

    def _get_contract_expiry(self) -> datetime:
        expiry = self.get_parameter("mes-contract-expiry")
        if expiry:
            return datetime.strptime(expiry, "%Y-%m-%d")

        return datetime(2026, 6, 19)

    def on_order_event(self, order_event: OrderEvent):
        self.log(
            f"{self.time} ORDER {order_event.status} {order_event.direction} "
            f"{order_event.fill_quantity} {order_event.symbol.value} @ {order_event.fill_price:.2f}"
        )
