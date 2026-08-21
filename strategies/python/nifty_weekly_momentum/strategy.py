"""NIFTY Weekly Momentum Strategy — Lean QCAlgorithm.

Signal: Weighted z-score from OpenAlgo depth data on NIFTY 50 constituent
single-stock futures (data-only, never ordered).
Trade: Exact ATM W+1 NIFTY CE/PE via OpenAlgo.

This is a thin shell over the pure-Python signal_engine and risk_ledger
modules. The signal engine is fully testable without Lean.
"""
from __future__ import annotations

from collections import deque
from datetime import timedelta, datetime, time
import math
from pathlib import Path

from AlgorithmImports import (
    DataNormalizationMode,
    Market,
    NullBuyingPowerModel,
    OptionRight,
    OrderStatus,
    QCAlgorithm,
    Resolution,
    Slice,
    Symbol,
    TickType,
    TimeZones,
)

from strategies.python.nifty_weekly_momentum.contract_map import (
    ContractMapError,
    FuturesContractMap,
    load_contract_map,
)
from strategies.python.nifty_weekly_momentum.frame_sampler import FuturesFrameSampler
from strategies.python.nifty_weekly_momentum.option_model import (
    OptionQuote,
    ValuationPolicy,
    build_entry_plan,
    evaluate_long_option,
    realized_volatility,
)
from strategies.python.nifty_weekly_momentum.signal_engine import (
    SignalEngine,
    ConstituentConfig,
)
from strategies.python.nifty_weekly_momentum.risk_ledger import RiskLedger


class NiftyWeeklyMomentumStrategy(QCAlgorithm):
    """Intraday NIFTY weekly options momentum strategy.

    Entry window: 09:20 - 14:00 IST (13:00 on W0 expiry day).
    Exit: signal invalidation, premium stop, target, 30-min max hold, or 15:00.
    Risk: ₹2,000 daily ceiling on ₹100,000; 3 trades × ₹500.
    """

    SIGNAL_CHART = "NWM Signal"
    VALUATION_CHART = "NWM Valuation"
    DEPTH_TICK_SOURCE = "OPENALGO_DEPTH"

    def initialize(self):
        self.set_account_currency("INR")
        self.set_start_date(2026, 8, 17)
        self.set_end_date(2030, 12, 31)
        self.set_cash(100_000)
        self.set_time_zone(TimeZones.Kolkata)

        # ── Parameters ──────────────────────────────────────────────────
        self.mode = self._cfg_str("mode", "data-only").strip().lower()
        if self.mode not in {"data-only", "signal-only", "paper", "live"}:
            raise ValueError(f"Unsupported mode: {self.mode}")
        self.futures_map_path = self._cfg_str("futures-map-path", "").strip()
        self.entry_time = self._cfg_time("entry-time", "09:20")
        self.last_entry_time = self._cfg_time("last-entry-time", "14:00")
        self.expiry_last_entry_time = self._cfg_time("expiry-last-entry-time", "13:00")
        self.exit_time = self._cfg_time("exit-time", "15:00")
        self.max_hold_minutes = self._cfg_int("max-hold-minutes", 30)
        self.cooldown_minutes = self._cfg_int("cooldown-minutes", 10)
        self.max_trades = self._cfg_int("max-trades", 3)
        self.per_trade_risk = self._cfg_float("per-trade-risk", 500.0)
        self.daily_loss_budget = self._cfg_float("daily-loss-budget", 2000.0)
        self.chase_cap_pct = self._cfg_float("chase-cap-pct", 0.5)
        self.spread_threshold_pct = self._cfg_float("spread-threshold-pct", 1.5)
        self.iv_rv_threshold = self._cfg_float("iv-rv-threshold", 1.25)
        self.iv_rv_max = self._cfg_float("iv-rv-max", 1.60)
        self.max_ask_iv_premium = self._cfg_float("max-ask-iv-premium", 0.02)
        self.risk_free_rate = self._cfg_float("risk-free-rate", 0.06)
        self.estimated_fees_per_lot = self._cfg_float("estimated-fees-per-lot", 100.0)
        self.stop_loss_fraction = self._cfg_float("premium-stop-fraction", 0.25)
        self.target_fraction = self._cfg_float("premium-target-fraction", 0.40)
        self.no_progress_minutes = self._cfg_int("no-progress-minutes", 10)
        self.entry_timeout_seconds = self._cfg_int("entry-timeout-seconds", 6)
        self.entry_reprice_seconds = self._cfg_int("entry-reprice-seconds", 2)
        self.entry_z_min = self._cfg_float("entry-z-min", 2.0)
        self.entry_z_max = self._cfg_float("entry-z-max", 3.5)
        self.bullish_breadth = self._cfg_float("bullish-breadth", 0.65)
        self.bearish_breadth = self._cfg_float("bearish-breadth", 0.35)

        # ── State ────────────────────────────────────────────────────────
        self._signal_engine: SignalEngine | None = None
        self._frame_sampler: FuturesFrameSampler | None = None
        self._contract_map: FuturesContractMap | None = None
        self._risk = RiskLedger(
            capital=100_000,
            daily_loss_budget=self.daily_loss_budget,
            per_trade_risk=self.per_trade_risk,
            max_trades=self.max_trades,
        )
        self._trade_id = 0
        self._active_option_symbol: Symbol | None = None
        self._active_direction: str = ""
        self._active_entry_price: float = 0.0
        self._active_entry_time: datetime | None = None
        self._active_lots: int = 0
        self._active_lot_size: int = 0
        self._entry_ticket = None
        self._entry_order_id: int | None = None
        self._entry_submitted_time: datetime | None = None
        self._entry_original_ask = 0.0
        self._entry_maximum_limit = 0.0
        self._entry_reference_mid = 0.0
        self._entry_reprices = 0
        self._entry_fill_quantity = 0
        self._entry_fill_notional = 0.0
        self._exit_ticket = None
        self._exit_order_id: int | None = None
        self._exit_reason = ""
        self._exit_fill_quantity = 0
        self._exit_fill_notional = 0.0
        self._trade_fees = 0.0
        self._cooldown_until: datetime | None = None
        self._w0_expiry: datetime | None = None
        self._w1_expiry: datetime | None = None
        self._w1_contracts: list[Symbol] = []
        self._w1_atm_strike: float = 0.0
        self._nifty_index: Symbol | None = None
        self._constituents: list[ConstituentConfig] = []
        self._future_symbols: dict[Symbol, str] = {}
        self._index_history: deque[tuple[float, float]] = deque(maxlen=600)
        self._latest_index_price: tuple[float, float] | None = None
        self._option_symbols: set[Symbol] = set()
        self._option_quotes: dict[Symbol, tuple[float, OptionQuote]] = {}
        self._bullish_streak = 0
        self._bearish_streak = 0
        self._last_entry_evaluation: float | None = None
        self._session_date = None
        self._next_setup_retry: datetime | None = None
        self._last_entry_rejection: tuple[str, datetime] | None = None
        self._last_second: int = -1
        self._state_key = "nifty-weekly-momentum-state-v1"

        # ── NIFTY index (mandatory market confirmation) ──────────────────
        self._nifty_index = self.add_index("NIFTY", Resolution.TICK, Market.INDIA).symbol
        self._nifty_index_security = self.securities[self._nifty_index]
        self._nifty_index_security.set_data_normalization_mode(DataNormalizationMode.RAW)

        # ── Scheduling ───────────────────────────────────────────────────
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(9, 14, 0),
            self._prepare_session,
        )
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(self.entry_time.hour, self.entry_time.minute, 0),
            self._on_entry_window_open,
        )
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(self.exit_time.hour, self.exit_time.minute, 0),
            self._force_flat,
        )
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.every(timedelta(minutes=1)),
            self._on_minute_tick,
        )

        self.debug(f"NiftyWeeklyMomentumStrategy initialized mode={self.mode}")

    # ── Session lifecycle ─────────────────────────────────────────────

    def _on_entry_window_open(self):
        """Ensure the session is ready when the entry window opens."""
        self._prepare_session()

    def _prepare_session(self):
        session_date = self.time.date()
        if self._session_date != session_date:
            self._session_date = session_date
            self._reset_daily_state()
            self._signal_engine = None
            self._frame_sampler = None
            self._contract_map = None
            self._future_symbols.clear()
            self._next_setup_retry = None

        if self._signal_engine is not None and self._w1_expiry is not None:
            return
        if self._next_setup_retry is not None and self.time < self._next_setup_retry:
            return

        self._next_setup_retry = self.time + timedelta(minutes=1)
        if self._signal_engine is None:
            self._load_constituents()
        if self._w1_expiry is None:
            self._resolve_expiries()

    def _on_minute_tick(self):
        """Cooldown management and stale-data checks."""
        self._prepare_session()
        if self._cooldown_until is not None and self.time >= self._cooldown_until:
            self._cooldown_until = None
            self._risk.end_cooldown()

    def _reset_daily_state(self):
        self._trade_id = 0
        self._active_option_symbol = None
        self._active_direction = ""
        self._active_entry_price = 0.0
        self._active_entry_time = None
        self._active_lots = 0
        self._active_lot_size = 0
        self._entry_ticket = None
        self._entry_order_id = None
        self._entry_submitted_time = None
        self._entry_original_ask = 0.0
        self._entry_maximum_limit = 0.0
        self._entry_reference_mid = 0.0
        self._entry_reprices = 0
        self._entry_fill_quantity = 0
        self._entry_fill_notional = 0.0
        self._exit_ticket = None
        self._exit_order_id = None
        self._exit_reason = ""
        self._exit_fill_quantity = 0
        self._exit_fill_notional = 0.0
        self._trade_fees = 0.0
        self._cooldown_until = None
        self._w0_expiry = None
        self._w1_expiry = None
        self._w1_contracts = []
        self._bullish_streak = 0
        self._bearish_streak = 0
        self._last_entry_evaluation = None
        self._index_history.clear()
        self._latest_index_price = None
        self._option_symbols.clear()
        self._option_quotes.clear()
        self._last_second = -1
        if self._signal_engine is not None:
            self._signal_engine.reset()
        if self._frame_sampler is not None:
            self._frame_sampler.reset()
        self._risk = RiskLedger(
            capital=self._risk.capital,
            daily_loss_budget=self.daily_loss_budget,
            per_trade_risk=self.per_trade_risk,
            max_trades=self.max_trades,
        )

    # ── Expiry resolution ─────────────────────────────────────────────

    def _resolve_expiries(self):
        """Resolve W0 then request the next distinct broker-listed expiry."""
        try:
            first_chain = list(self.option_chain_provider.get_option_contract_list(
                self._nifty_index, self.time))
            if not first_chain:
                self.debug("_resolve_expiries: no W0 contracts; will retry")
                return

            self._w0_expiry = min(contract.id.date for contract in first_chain)
            second_chain = list(self.option_chain_provider.get_option_contract_list(
                self._nifty_index, self._w0_expiry + timedelta(days=1)))
            later_expiries = sorted({
                contract.id.date for contract in second_chain
                if contract.id.date > self._w0_expiry
            })
            if not later_expiries:
                self.debug("_resolve_expiries: no distinct W+1 contracts; will retry")
                return

            candidate = later_expiries[0]
            if (candidate.date() - self.time.date()).days > 16:
                self.debug(f"_resolve_expiries: W+1 {candidate.date()} is more than 16 days away")
                return

            self._w1_expiry = candidate
            self._w1_contracts = [
                contract for contract in second_chain if contract.id.date == candidate
            ]
            self.debug(
                f"_resolve_expiries: W0={self._w0_expiry.date()} "
                f"W1={self._w1_expiry.date()} contracts={len(self._w1_contracts)}"
            )
        except Exception as exc:
            self.debug(f"_resolve_expiries: {exc}")

    # ── Constituents ───────────────────────────────────────────────────

    def _load_constituents(self):
        """Load the daily map and subscribe each exact OpenAlgo future."""
        map_path = self._contract_map_file()
        try:
            contract_map = load_contract_map(map_path, self.time.date())
        except ContractMapError as exc:
            self.debug(f"_load_constituents: {exc}")
            return

        constituents: list[ConstituentConfig] = []
        future_symbols: dict[Symbol, str] = {}
        for contract in contract_map.contracts:
            lean_symbol = Symbol.create_future(
                contract.openalgo_symbol,
                Market.INDIA,
                datetime.combine(contract.expiry, time()),
            )
            security = self.add_future_contract(lean_symbol, Resolution.TICK)
            security.set_data_normalization_mode(DataNormalizationMode.RAW)
            future_symbols[security.symbol] = contract.openalgo_symbol
            constituents.append(ConstituentConfig(
                symbol=contract.openalgo_symbol,
                nse_symbol=contract.nse_symbol,
                weight=contract.normalized_weight,
                is_top10=contract.is_top10,
            ))

        self._contract_map = contract_map
        self._future_symbols = future_symbols
        self._constituents = constituents
        self._frame_sampler = FuturesFrameSampler(
            (constituent.symbol for constituent in constituents),
            max_quote_age_seconds=2.0,
        )
        self._signal_engine = SignalEngine(constituents)
        self._last_second = -1
        self.debug(
            f"_load_constituents: subscribed {len(constituents)} futures "
            f"expiry={contract_map.common_expiry} raw_weight={contract_map.raw_weight_covered:.2f}%"
        )

    # ── Main data handler ─────────────────────────────────────────────

    def on_data(self, data: Slice):
        self._prepare_session()
        self._advance_signal_clock()
        self._ingest_ticks(data)

        # Manage open option position
        if self._active_option_symbol is not None:
            self._manage_position()
            return

        # Check entry conditions
        if not self._can_enter():
            return

        signal = self._signal_engine.result() if self._signal_engine else None
        if signal is None or not signal.valid:
            return

        if self._last_entry_evaluation == signal.timestamp:
            return
        self._last_entry_evaluation = signal.timestamp

        # Entry logic
        direction = self._qualified_direction()
        if direction is None:
            return
        if self.mode == "live":
            self._attempt_entry(direction, signal)
        elif self.mode in {"signal-only", "paper"}:
            self.debug(
                f"SIGNAL {direction} z={signal.z_score:.2f} breadth={signal.breadth:.2f} "
                f"fresh={signal.fresh_weight_pct:.1f}%"
            )

    def _advance_signal_clock(self):
        if self._frame_sampler is None or self._signal_engine is None:
            return

        current_second = int(self._timestamp(self.time))
        if self._last_second < 0:
            self._last_second = current_second
            return
        if current_second <= self._last_second:
            return
        if current_second - self._last_second > 10:
            self._frame_sampler.reset()
            self._signal_engine.reset()
            self._bullish_streak = 0
            self._bearish_streak = 0
            self._last_second = current_second
            return

        while self._last_second < current_second:
            frames = self._frame_sampler.build_frame(self._last_second)
            frame_timestamp = float(self._last_second + 1)
            self._record_index_frame(frame_timestamp)
            self._signal_engine.update(frame_timestamp, frames)
            self._update_signal_streaks()
            self._plot_signal()
            self._last_second += 1

    def _ingest_ticks(self, data: Slice):
        if self._frame_sampler is None:
            return

        for lean_symbol, openalgo_symbol in self._future_symbols.items():
            if not data.ticks.contains_key(lean_symbol):
                continue
            for tick in data.ticks[lean_symbol]:
                self._ingest_future_tick(openalgo_symbol, tick)

        self._ingest_index_ticks(data)
        self._ingest_option_ticks(data)

    def _ingest_future_tick(self, openalgo_symbol: str, tick):
        if not self._is_depth_tick(tick):
            return
        timestamp = self._timestamp(tick.end_time)
        if tick.tick_type == TickType.QUOTE:
            self._frame_sampler.ingest_quote(
                openalgo_symbol,
                timestamp,
                float(tick.bid_price),
                float(tick.ask_price),
                float(tick.bid_size),
                float(tick.ask_size),
            )
        elif tick.tick_type == TickType.TRADE:
            self._frame_sampler.ingest_trade(
                openalgo_symbol,
                timestamp,
                float(tick.value),
                float(tick.quantity),
            )

    def _ingest_index_ticks(self, data: Slice):
        if self._nifty_index is not None and data.ticks.contains_key(self._nifty_index):
            for tick in data.ticks[self._nifty_index]:
                if not self._is_depth_tick(tick):
                    continue
                timestamp = self._timestamp(tick.end_time)
                if tick.tick_type == TickType.QUOTE and tick.bid_price > 0 and tick.ask_price > 0:
                    self._latest_index_price = (
                        timestamp,
                        (float(tick.bid_price) + float(tick.ask_price)) / 2.0,
                    )
                elif tick.tick_type == TickType.TRADE and tick.value > 0:
                    self._latest_index_price = (timestamp, float(tick.value))

    def _ingest_option_ticks(self, data: Slice):
        for symbol in self._option_symbols:
            if not data.ticks.contains_key(symbol):
                continue
            for tick in data.ticks[symbol]:
                if tick.tick_type != TickType.QUOTE or not self._is_depth_tick(tick):
                    continue
                self._option_quotes[symbol] = (
                    self._timestamp(tick.end_time),
                    OptionQuote(
                        bid=float(tick.bid_price),
                        ask=float(tick.ask_price),
                        bid_size=float(tick.bid_size),
                        ask_size=float(tick.ask_size),
                    ),
                )

    def _record_index_frame(self, frame_timestamp: float):
        if self._latest_index_price is None:
            return
        timestamp, price = self._latest_index_price
        age = frame_timestamp - timestamp
        if 0 <= age <= 2.0:
            self._index_history.append((frame_timestamp, price))

    def _update_signal_streaks(self):
        signal = self._signal_engine.result() if self._signal_engine else None
        if signal is None or not signal.valid:
            self._bullish_streak = 0
            self._bearish_streak = 0
            return

        bullish = (
            self.entry_z_min <= signal.z_score <= self.entry_z_max
            and signal.breadth >= self.bullish_breadth
            and self._index_confirms("long", signal.timestamp)
        )
        bearish = (
            -self.entry_z_max <= signal.z_score <= -self.entry_z_min
            and signal.breadth <= self.bearish_breadth
            and self._index_confirms("short", signal.timestamp)
        )
        self._bullish_streak = self._bullish_streak + 1 if bullish else 0
        self._bearish_streak = self._bearish_streak + 1 if bearish else 0

    def _qualified_direction(self) -> str | None:
        if self._bullish_streak >= 3:
            return "long"
        if self._bearish_streak >= 3:
            return "short"
        return None

    def _index_confirms(self, direction: str, timestamp: float) -> bool:
        if not self._index_history:
            return False
        current_timestamp, current_price = self._index_history[-1]
        if timestamp - current_timestamp > 2.0:
            return False

        target = timestamp - 30.0
        candidates = [point for point in self._index_history if point[0] <= target]
        if not candidates:
            return False
        prior_timestamp, prior_price = candidates[-1]
        if target - prior_timestamp > 5.0 or prior_price <= 0:
            return False
        if direction == "long":
            return current_price > prior_price
        return current_price < prior_price

    def _plot_signal(self):
        signal = self._signal_engine.result() if self._signal_engine else None
        if signal is None:
            return
        self.plot(self.SIGNAL_CHART, "Z-Score", signal.z_score)
        self.plot(self.SIGNAL_CHART, "Breadth %", signal.breadth * 100.0)
        self.plot(self.SIGNAL_CHART, "Fresh Weight %", signal.fresh_weight_pct)
        self.plot("NWM Risk", "Remaining Risk", self._risk.remaining_risk)

    def _can_enter(self) -> bool:
        if self._w1_expiry is None:
            return False
        if not self._risk.can_enter():
            return False
        now = self.time
        if now.time() < self.entry_time:
            return False
        # Expiry-day cutoff
        cutoff = self.expiry_last_entry_time
        if self._w0_expiry and now.date() == self._w0_expiry.date():
            if now.time() >= cutoff:
                return False
        elif now.time() >= self.last_entry_time:
            return False
        if self._cooldown_until is not None and now < self._cooldown_until:
            return False
        return True

    def _attempt_entry(self, direction: str, signal):
        """Select W+1 ATM option and submit bounded limit order."""
        if self._entry_submission_blocked():
            return

        pair = self._subscribe_current_atm_pair()
        if pair is None:
            return
        call_symbol, put_symbol = pair
        call_quote = self._fresh_option_quote(call_symbol)
        put_quote = self._fresh_option_quote(put_symbol)
        if call_quote is None or put_quote is None:
            self._reject_entry("waiting for fresh W+1 ATM call and put depth")
            return

        current_realized_vol = realized_volatility(list(self._index_history))
        if current_realized_vol is None or current_realized_vol <= 0:
            self._reject_entry("insufficient NIFTY observations for realized volatility")
            return

        right = OptionRight.CALL if direction == "long" else OptionRight.PUT
        option_symbol = call_symbol if right == OptionRight.CALL else put_symbol
        candidate_quote = call_quote if right == OptionRight.CALL else put_quote
        security = self.securities[option_symbol]
        lot_size = int(security.symbol_properties.lot_size)
        tick_size = float(security.symbol_properties.minimum_price_variation)
        if lot_size <= 0 or tick_size <= 0:
            self._reject_entry("invalid broker lot size or tick size")
            return

        expiry_close = datetime.combine(self._w1_expiry.date(), time(15, 30))
        seconds_to_expiry = (expiry_close - self.time).total_seconds()
        valuation = evaluate_long_option(
            call_quote=call_quote,
            put_quote=put_quote,
            candidate_right="call" if right == OptionRight.CALL else "put",
            strike=self._w1_atm_strike,
            seconds_to_expiry=seconds_to_expiry,
            realized_vol=current_realized_vol,
            lot_size=lot_size,
            planned_risk=self.per_trade_risk,
            estimated_fees=self.estimated_fees_per_lot,
            policy=ValuationPolicy(
                rate=self.risk_free_rate,
                max_iv_rv_ratio=self.iv_rv_threshold,
                max_ask_iv_premium=self.max_ask_iv_premium,
            ),
        )
        self._plot_valuation(valuation)
        if not valuation.allowed:
            self._reject_entry(valuation.reason)
            return

        plan = build_entry_plan(
            quote=candidate_quote,
            lot_size=lot_size,
            tick_size=tick_size,
            per_trade_risk=self.per_trade_risk,
            remaining_risk=self._risk.remaining_risk,
            capital=self._risk.capital,
            estimated_fees_per_lot=self.estimated_fees_per_lot,
            stop_loss_fraction=self.stop_loss_fraction,
            spread_threshold_pct=self.spread_threshold_pct,
            chase_cap_pct=self.chase_cap_pct,
        )
        if not plan.allowed:
            self._reject_entry(plan.reason)
            return

        self._trade_id += 1
        self._active_option_symbol = option_symbol
        self._active_direction = direction
        self._active_entry_price = 0.0
        self._active_entry_time = None
        self._active_lots = plan.quantity
        self._active_lot_size = lot_size
        self._entry_submitted_time = self.time
        self._entry_original_ask = candidate_quote.ask
        self._entry_maximum_limit = plan.maximum_limit_price
        self._entry_reference_mid = candidate_quote.midpoint
        self._entry_reprices = 0
        self._entry_fill_quantity = 0
        self._entry_fill_notional = 0.0
        self._trade_fees = 0.0

        self._risk.open_trade(
            trade_id=self._trade_id,
            timestamp=self._timestamp(self.time),
            direction=direction,
            symbol=option_symbol.value,
            lots=plan.quantity,
            entry_price=plan.limit_price,
            reserved_risk=plan.reserved_risk,
            position_side="long",
        )

        try:
            self._entry_ticket = self.limit_order(
                option_symbol,
                plan.quantity,
                plan.limit_price,
                tag=f"NWM|{self._trade_id}|entry|{direction}",
            )
            self._entry_order_id = int(self._entry_ticket.order_id)
        except Exception as exc:
            self._risk.cancel_trade(self._trade_id)
            self._reset_active()
            self.error(f"entry submission failed: {exc}")
            return

        self.debug(
            f"ENTRY_SUBMITTED {direction} {option_symbol.value} qty={plan.quantity} "
            f"lots={plan.lots} limit={plan.limit_price:.2f} z={signal.z_score:.2f} "
            f"breadth={signal.breadth:.2f} iv_rv={valuation.iv_rv_ratio:.2f}"
        )

    def _manage_position(self):
        """Monitor open option position for exit conditions."""
        if self._entry_ticket is not None:
            self._manage_pending_entry()
            return
        if self._exit_ticket is not None or self._active_entry_price <= 0:
            return

        quote = self._fresh_option_quote(self._active_option_symbol)
        if quote is None:
            return
        bid = quote.bid

        self._risk.update_unrealized(bid, self._active_lots, "long", self._active_entry_price)
        self.plot("NWM Option", "Bid", bid)
        self.plot("NWM Option", "Entry", self._active_entry_price)
        self.plot("NWM Risk", "Net P&L", self._risk.net_pnl)

        reason = self._position_exit_reason(bid)
        if reason is not None:
            self._close_position(reason, emergency=reason in {"RISK_HALT", "DATA_INVALID"})

    def _manage_pending_entry(self):
        if self._entry_ticket is None or self._entry_submitted_time is None:
            return
        if self._qualified_direction() != self._active_direction:
            self._cancel_pending_entry("signal invalidated")
            return

        elapsed = (self.time - self._entry_submitted_time).total_seconds()
        if elapsed >= self.entry_timeout_seconds:
            self._cancel_pending_entry("entry timeout")
            return

        quote = self._fresh_option_quote(self._active_option_symbol)
        if quote is None:
            self._cancel_pending_entry("option depth became stale")
            return

        next_reprice_at = self.entry_reprice_seconds * (self._entry_reprices + 1)
        if self._entry_reprices >= 2 or elapsed < next_reprice_at:
            return
        tick_size = float(
            self.securities[self._active_option_symbol].symbol_properties.minimum_price_variation
        )
        next_limit = min(
            self._entry_maximum_limit,
            self._round_up_tick(quote.ask, tick_size),
        )
        response = self._entry_ticket.update_limit_price(
            next_limit,
            f"NWM|{self._trade_id}|reprice={self._entry_reprices + 1}",
        )
        if response.is_success:
            self._entry_reprices += 1
            self.debug(f"ENTRY_REPRICE id={self._entry_order_id} limit={next_limit:.2f}")

    def _cancel_pending_entry(self, reason: str):
        if self._entry_ticket is None or self._entry_ticket.status == OrderStatus.CANCEL_PENDING:
            return
        response = self._entry_ticket.cancel(f"NWM entry cancel: {reason}")
        if response.is_success:
            self.debug(f"ENTRY_CANCEL_REQUEST id={self._entry_order_id} reason={reason}")

    def _position_exit_reason(self, bid: float) -> str | None:
        if self.time.time() >= self.exit_time:
            return "EOD"
        if self._risk.is_halted():
            return "RISK_HALT"

        signal = self._signal_engine.result() if self._signal_engine else None
        if signal is None or not signal.valid:
            return "DATA_INVALID"
        if self._active_direction == "long" and signal.z_score < 0.5:
            return "SIGNAL_INVALID"
        if self._active_direction == "short" and signal.z_score > -0.5:
            return "SIGNAL_INVALID"

        pnl_ratio = (bid - self._active_entry_price) / self._active_entry_price
        if pnl_ratio <= -self.stop_loss_fraction:
            return "PREMIUM_STOP"
        if pnl_ratio >= self.target_fraction:
            return "TARGET"
        if self._active_entry_time is None:
            return None

        hold_minutes = (self.time - self._active_entry_time).total_seconds() / 60.0
        if hold_minutes >= self.no_progress_minutes and bid <= self._active_entry_price:
            return "NO_PROGRESS"
        if hold_minutes >= self.max_hold_minutes:
            return "MAX_HOLD"
        return None

    def _close_position(self, reason: str, emergency: bool = False):
        """Close the active option position at marketable limit."""
        if self._active_option_symbol is None or self._exit_ticket is not None:
            return
        if self._entry_ticket is not None:
            self._cancel_pending_entry(reason)
            return

        quantity = abs(int(self.portfolio[self._active_option_symbol].quantity))
        if quantity <= 0:
            return

        quote = self._fresh_option_quote(self._active_option_symbol)
        if quote is None and not emergency:
            return

        tag = f"NWM|{self._trade_id}|exit|{reason}"
        if quote is None:
            self._exit_ticket = self.market_order(
                self._active_option_symbol, -quantity, asynchronous=True, tag=tag
            )
            submitted_price = 0.0
        else:
            submitted_price = quote.bid
            self._exit_ticket = self.limit_order(
                self._active_option_symbol, -quantity, submitted_price, tag=tag
            )
        self._exit_order_id = int(self._exit_ticket.order_id)
        self._exit_reason = reason
        self.debug(
            f"EXIT_SUBMITTED {reason} {self._active_option_symbol.value} "
            f"qty={quantity} limit={submitted_price:.2f}"
        )

    def _reset_active(self):
        self._active_option_symbol = None
        self._active_direction = ""
        self._active_entry_price = 0.0
        self._active_entry_time = None
        self._active_lots = 0
        self._active_lot_size = 0
        self._entry_ticket = None
        self._entry_order_id = None
        self._entry_submitted_time = None
        self._entry_original_ask = 0.0
        self._entry_maximum_limit = 0.0
        self._entry_reference_mid = 0.0
        self._entry_reprices = 0
        self._entry_fill_quantity = 0
        self._entry_fill_notional = 0.0
        self._exit_ticket = None
        self._exit_order_id = None
        self._exit_reason = ""
        self._exit_fill_quantity = 0
        self._exit_fill_notional = 0.0
        self._trade_fees = 0.0

    def _force_flat(self):
        """EOD force flatten."""
        self._risk.force_flat()
        if self._entry_ticket is not None:
            self._cancel_pending_entry("EOD")
        if self._active_option_symbol is not None:
            self._close_position("EOD", emergency=True)

    # ── Order events ──────────────────────────────────────────────────

    def on_order_event(self, order_event):
        self.debug(
            f"OrderEvent id={order_event.order_id} symbol={order_event.symbol.value} "
            f"status={order_event.status} qty={order_event.quantity} "
            f"fill_qty={order_event.fill_quantity} fill_px={order_event.fill_price}"
        )

        if self._active_option_symbol != order_event.symbol:
            return

        self._trade_fees += abs(float(order_event.order_fee.value.amount))
        if self._entry_order_id == order_event.order_id:
            self._handle_entry_order_event(order_event)
        elif self._exit_order_id == order_event.order_id:
            self._handle_exit_order_event(order_event)

    def _handle_entry_order_event(self, order_event):
        fill_quantity = int(order_event.fill_quantity)
        if fill_quantity > 0:
            self._entry_fill_quantity += fill_quantity
            self._entry_fill_notional += fill_quantity * float(order_event.fill_price)
            self._active_lots = self._entry_fill_quantity
            self._active_entry_price = self._entry_fill_notional / self._entry_fill_quantity
            if self._active_entry_time is None:
                self._active_entry_time = self.time
            self._risk.update_open_trade(
                self._trade_id,
                self._active_entry_price,
                self._entry_fill_quantity,
            )

        if order_event.status == OrderStatus.FILLED:
            self._entry_ticket = None
            self.debug(
                f"ENTRY_FILLED qty={self._entry_fill_quantity} avg={self._active_entry_price:.2f}"
            )
        elif order_event.status in {OrderStatus.CANCELED, OrderStatus.INVALID}:
            self._entry_ticket = None
            if self._entry_fill_quantity == 0:
                self._risk.cancel_trade(self._trade_id)
                self._cooldown_until = self.time + timedelta(minutes=self.cooldown_minutes)
                self._bullish_streak = 0
                self._bearish_streak = 0
                self._reset_active()
            else:
                self.debug(
                    f"ENTRY_PARTIAL_FINAL qty={self._entry_fill_quantity} "
                    f"avg={self._active_entry_price:.2f}"
                )

    def _handle_exit_order_event(self, order_event):
        fill_quantity = abs(int(order_event.fill_quantity))
        if fill_quantity > 0:
            self._exit_fill_quantity += fill_quantity
            self._exit_fill_notional += fill_quantity * float(order_event.fill_price)

        if order_event.status == OrderStatus.FILLED:
            exit_price = self._exit_fill_notional / max(1, self._exit_fill_quantity)
            lots = max(1, self._active_lots // max(1, self._active_lot_size))
            fees = max(self._trade_fees, self.estimated_fees_per_lot * lots)
            self._risk.close_trade(
                trade_id=self._trade_id,
                exit_time=self._timestamp(self.time),
                exit_price=exit_price,
                fees=fees,
                slippage=0.0,
            )
            self._cooldown_until = self.time + timedelta(minutes=self.cooldown_minutes)
            self.debug(
                f"EXIT_FILLED reason={self._exit_reason} qty={self._exit_fill_quantity} "
                f"avg={exit_price:.2f} net={self._risk.net_pnl:.2f}"
            )
            self._reset_active()
        elif order_event.status in {OrderStatus.CANCELED, OrderStatus.INVALID}:
            self._exit_ticket = None
            self._exit_order_id = None
            self.debug(f"EXIT_RETRY_REQUIRED reason={self._exit_reason}")

    # ── Helpers ───────────────────────────────────────────────────────

    def _entry_submission_blocked(self) -> bool:
        return (
            self.mode != "live"
            or self._w1_expiry is None
            or not self._w1_contracts
            or self._entry_ticket is not None
            or self._exit_ticket is not None
        )

    def _subscribe_current_atm_pair(self) -> tuple[Symbol, Symbol] | None:
        spot = float(self._nifty_index_security.price)
        if spot <= 0:
            return None
        return self._subscribe_atm_pair(spot)

    def _cfg_time(self, key: str, default: str) -> time:
        val = self.get_parameter(key)
        s = val if val is not None else default
        try:
            return datetime.strptime(s, "%H:%M").time()
        except Exception:
            return time(9, 20)

    def _cfg_float(self, key: str, default: float) -> float:
        val = self.get_parameter(key)
        return float(val) if val is not None else default

    def _cfg_int(self, key: str, default: int) -> int:
        val = self.get_parameter(key)
        return int(val) if val is not None else default

    def _cfg_str(self, key: str, default: str) -> str:
        val = self.get_parameter(key)
        return str(val) if val is not None else default

    def _subscribe_atm_pair(self, spot: float) -> tuple[Symbol, Symbol] | None:
        contracts_by_strike: dict[float, dict[OptionRight, Symbol]] = {}
        for contract in self._w1_contracts:
            strike = float(contract.id.strike_price)
            contracts_by_strike.setdefault(strike, {})[contract.id.option_right] = contract

        complete_strikes = [
            strike for strike, contracts in contracts_by_strike.items()
            if OptionRight.CALL in contracts and OptionRight.PUT in contracts
        ]
        if not complete_strikes:
            self._reject_entry("W+1 chain has no complete call/put strike")
            return None

        strike = min(complete_strikes, key=lambda value: abs(value - spot))
        self._w1_atm_strike = strike
        call_symbol = contracts_by_strike[strike][OptionRight.CALL]
        put_symbol = contracts_by_strike[strike][OptionRight.PUT]
        for symbol in (call_symbol, put_symbol):
            if not self.securities.contains_key(symbol):
                security = self.add_index_option_contract(symbol, Resolution.TICK)
                security.set_data_normalization_mode(DataNormalizationMode.RAW)
                security.set_buying_power_model(NullBuyingPowerModel())
            self._option_symbols.add(symbol)
        return call_symbol, put_symbol

    def _fresh_option_quote(self, symbol: Symbol | None) -> OptionQuote | None:
        if symbol is None or symbol not in self._option_quotes:
            return None
        timestamp, quote = self._option_quotes[symbol]
        age = self._timestamp(self.time) - timestamp
        if age < 0 or age > 1.0 or quote.bid <= 0 or quote.ask <= quote.bid:
            return None
        return quote

    def _plot_valuation(self, valuation):
        self.plot(self.VALUATION_CHART, "IV/RV", valuation.iv_rv_ratio)
        self.plot(self.VALUATION_CHART, "Projected Carry", valuation.projected_decay)
        self.plot(self.VALUATION_CHART, "All-In Friction", valuation.all_in_friction)

    def _reject_entry(self, reason: str):
        if (
            self._last_entry_rejection is None
            or self._last_entry_rejection[0] != reason
            or self.time - self._last_entry_rejection[1] >= timedelta(minutes=1)
        ):
            self.debug(f"ENTRY_REJECTED {reason}")
            self._last_entry_rejection = (reason, self.time)

    @classmethod
    def _is_depth_tick(cls, tick) -> bool:
        return str(getattr(tick, "sale_condition", "")).upper() == cls.DEPTH_TICK_SOURCE

    @staticmethod
    def _round_up_tick(value: float, tick_size: float) -> float:
        return round(math.ceil(value / tick_size - 1e-12) * tick_size, 10)

    def _contract_map_file(self) -> Path:
        if self.futures_map_path:
            return Path(self.futures_map_path).expanduser()
        repo_root = Path(__file__).resolve().parents[3]
        return repo_root / ".tmp" / f"nifty-futures-map-{self.time.date().isoformat()}.json"

    @staticmethod
    def _timestamp(value: datetime) -> float:
        if value.tzinfo is not None:
            return value.timestamp()
        return (value - datetime(1970, 1, 1)).total_seconds()

    def on_end_of_algorithm(self):
        self.debug(f"Final state: {self._risk.summary()}")
