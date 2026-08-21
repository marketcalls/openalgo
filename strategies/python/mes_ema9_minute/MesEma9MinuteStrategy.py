from datetime import datetime, timedelta

from AlgorithmImports import *


class MesEma9MinuteStrategy(QCAlgorithm):
    """Small, observable MES intraday experiment using a 1-minute EMA9 cross."""

    def initialize(self):
        if not self.live_mode:
            self.set_start_date(2025, 1, 1)
            self.set_end_date(2025, 3, 31)
            self.set_cash(100000)

        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE)
        self.set_time_zone(TimeZones.CHICAGO)

        self.ema_period = int(self.get_parameter("ema-period") or 9)
        self.trade_quantity = int(self.get_parameter("quantity") or 1)

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

        self.ema = ExponentialMovingAverage(self.ema_period)
        self.previous_close = None
        self.previous_ema = None
        self.entry_time = None
        self.entry_price = None
        self.initial_entry_done = False
        self.last_wait_log = None
        self.set_warm_up(self.ema_period + 2, Resolution.MINUTE)

        self.log(
            f"MES EMA9 initialized: qty={self.trade_quantity}; "
            "immediate initial entry, EMA9 signal exits/reversals"
        )

    def on_data(self, data: Slice):
        self._select_trade_symbol(data)
        if self.trade_symbol is None:
            self._log_wait("waiting for MES mapped/front-month contract")
            return

        bar = data.bars.get(self.trade_symbol)
        if bar is None:
            return

        close = float(bar.close)
        self.ema.update(IndicatorDataPoint(self.time, close))
        if not self.ema.is_ready:
            self.previous_close = close
            self.previous_ema = float(self.ema.current.value)
            return

        ema_value = float(self.ema.current.value)
        if self.is_warming_up:
            self.previous_close = close
            self.previous_ema = ema_value
            return

        holding = self.portfolio[self.trade_symbol]
        if not self.initial_entry_done:
            self.initial_entry_done = True
            direction = self.trade_quantity if close >= ema_value else -self.trade_quantity
            self._set_position(direction, "immediate EMA9-direction entry")
        elif holding.invested:
            if self._is_bearish_cross(close, ema_value):
                self._set_position(-self.trade_quantity, "EMA9 bearish reversal")
            elif self._is_bullish_cross(close, ema_value):
                self._set_position(self.trade_quantity, "EMA9 bullish reversal")

        # MES is traded as a day-trading experiment: flatten before the 16:00 CT break.
        if self.time.hour == 15 and self.time.minute >= 55 and holding.invested:
            self._exit("end-of-day flatten")

        self.previous_close = close
        self.previous_ema = ema_value

    def _set_position(self, target_quantity, reason):
        current = int(self.portfolio[self.trade_symbol].quantity)
        delta = target_quantity - current
        if delta == 0:
            return
        self.market_order(self.trade_symbol, delta, tag=reason)
        self.entry_time = self.time if target_quantity else None
        self.entry_price = float(self.securities[self.trade_symbol].price) if target_quantity else None
        self.log(f"{self.time} {reason}: target={target_quantity}, delta={delta}")

    def _exit(self, reason):
        if self.portfolio[self.trade_symbol].invested:
            self.liquidate(self.trade_symbol, reason)
        self.entry_time = None
        self.entry_price = None

    def _is_bullish_cross(self, close, ema_value):
        return self.previous_close is not None and self.previous_ema is not None and self.previous_close <= self.previous_ema and close > ema_value

    def _is_bearish_cross(self, close, ema_value):
        return self.previous_close is not None and self.previous_ema is not None and self.previous_close >= self.previous_ema and close < ema_value

    def _get_manual_contract(self):
        expiry = self.get_parameter("mes-contract-expiry")
        if not expiry:
            return None
        return Symbol.create_future(
            Futures.Indices.MicroSP500EMini,
            Market.CME,
            datetime.strptime(expiry, "%Y-%m-%d"),
        )

    def _select_trade_symbol(self, data):
        if self.manual_contract is not None:
            return
        mapped = self.mes_root.mapped
        if mapped is not None and mapped != self.mes_root.symbol:
            self.trade_symbol = mapped
            return
        chain = data.future_chains.get(self.mes_root.symbol)
        if chain:
            contracts = sorted(
                [contract for contract in chain if contract.expiry.date() >= self.time.date()],
                key=lambda contract: contract.expiry,
            )
            if contracts:
                self.trade_symbol = contracts[0].symbol

    def _log_wait(self, message):
        if self.last_wait_log is None or self.time - self.last_wait_log >= timedelta(minutes=5):
            self.debug(f"{self.time} {message}")
            self.last_wait_log = self.time

    def on_order_event(self, order_event: OrderEvent):
        self.log(
            f"{self.time} ORDER {order_event.status} {order_event.direction} "
            f"{order_event.fill_quantity} {order_event.symbol.value} @ {order_event.fill_price:.2f}"
        )
