"""RMS engine — singleton tick-driven dispatcher for per-leg risk rules.

Phase 3 scope:
  - In-memory active_runs registry + symbol -> runs reverse index.
  - Tick callback registered with market_data_service.subscribe_critical.
  - Per-tick pipeline (per affected run):
      1. is_trade_management_safe gate
      2. compute leg LTP (from market_data_service cache)
      3. evaluate per-leg trail X/Y → persist new SL + anchor
      4. evaluate per-leg target → exit on hit
      5. evaluate per-leg SL → exit on hit
      6. write strategy_pnl_snapshot row (debounced ~1Hz; minimal here)
  - Lifecycle: register_run on StrategyLegFilledEvent (last leg fills)
    and on StrategyStateChangedEvent → IN_TRADE; unregister on terminal
    states.

Phase 4 will extend this with strategy-level rules (overall SL / target /
profit lock / trail-to-entry). Phase 5 adds the realtime broadcaster +
debounced live UI updates.

Concurrency model: single dispatcher (no thread pool). Eventlet single-
worker production model means serial evaluation is the right shape — see
plan §3.2 + §14.3 #7. Each leg evaluation is microseconds; even 50 active
runs × 1000 ticks/sec is comfortable.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from database.strategy_v2_db import (
    StrategyLeg,
    StrategyPosition,
    StrategyRiskConfig,
    StrategyRun,
    StrategyV2,
    db_session,
)
from events.strategy_events import (
    StrategyRmsTriggeredEvent,
    StrategyTrailAdvancedEvent,
)
from services.strategy.rms_evaluators import (
    direction_of,
    evaluate_overall_sl,
    evaluate_overall_target,
    evaluate_profit_lock_arm,
    evaluate_profit_lock_floor,
    evaluate_sl,
    evaluate_target,
    evaluate_trail,
    evaluate_trail_to_entry,
)
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)


# Module-level lazy imports — these touch market_data_service at first-tick
# time only, avoiding eager-load cycles.


# ---------------------------------------------------------------------------
# In-memory run state
# ---------------------------------------------------------------------------


@dataclass
class _LegRuntime:
    """Hot-path leg state — read on every tick.

    Mirrors the strategy_legs + strategy_positions row but kept in memory so
    the tick callback never hits the DB. Persistence happens after rule
    evaluation, only when state actually changes.
    """
    leg_id: int
    position_id: int                  # FK into strategy_positions for persists
    symbol: str
    exchange: str
    tick_size: float
    direction: str                    # "long" | "short"
    avg_entry: float
    net_qty: int                      # signed (positive=long, negative=short)

    # Per-leg risk config
    target_enabled: bool = False
    target_value: Optional[float] = None
    target_unit: Optional[str] = None

    sl_enabled: bool = False
    sl_value: Optional[float] = None
    sl_unit: Optional[str] = None

    trail_enabled: bool = False
    trail_x: Optional[float] = None
    trail_y: Optional[float] = None
    trail_unit: Optional[str] = None

    # Live RMS state
    current_sl_price: Optional[float] = None
    last_trail_anchor: Optional[float] = None
    trail_advances_count: int = 0
    trail_to_entry_armed: bool = False
    last_ltp: Optional[float] = None  # cached for aggregate MTM across legs


@dataclass
class _RunRuntime:
    run_id: int
    strategy_id: int
    legs: dict[int, _LegRuntime] = field(default_factory=dict)

    # Strategy-level RMS config (cached at register-time)
    overall_sl_enabled: bool = False
    overall_sl_abs: Optional[float] = None
    overall_target_enabled: bool = False
    overall_target_abs: Optional[float] = None
    lock_profit_enabled: bool = False
    lock_at_abs: Optional[float] = None
    lock_min_abs: Optional[float] = None
    trail_to_entry_enabled: bool = False
    trail_to_entry_threshold: float = 0.0
    trail_to_entry_unit: str = "pct"

    # Live strategy-level state
    peak_mtm: float = 0.0
    profit_locked: bool = False


def _symbol_key(exchange: str, symbol: str) -> str:
    return f"{exchange}:{symbol}"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class RmsEngine:
    """Singleton dispatcher. Thread-safe registry + serial tick callback."""

    def __init__(self):
        self._lock = threading.RLock()
        self._runs: dict[int, _RunRuntime] = {}
        self._symbol_to_runs: dict[str, set[int]] = defaultdict(set)
        # Subscriber id from market_data_service.subscribe_critical, if any.
        # We use a single engine-wide subscription with a filter that grows
        # as runs are registered — simpler than re-subscribing per run.
        self._subscriber_id: Optional[int] = None

    # ----------------- Lifecycle -----------------

    def register_run(self, run_id: int) -> bool:
        """Hydrate a run from the DB and start monitoring its legs.

        Idempotent: if already registered, a no-op return True. Returns
        False if the run can't be hydrated (no legs / no positions / not
        IN_TRADE).
        """
        with self._lock:
            if run_id in self._runs:
                return True

            run = db_session.query(StrategyRun).filter(StrategyRun.id == run_id).first()
            if run is None:
                logger.warning("rms_engine.register_run: run_id=%s not found", run_id)
                return False
            if run.state != "IN_TRADE":
                # Engine only monitors IN_TRADE runs. ENTERING runs have no
                # positions yet; EXITING/CLOSED runs are flat.
                return False

            positions = (
                db_session.query(StrategyPosition)
                .filter(
                    StrategyPosition.run_id == run_id,
                    StrategyPosition.leg_state.in_(("OPEN", "EXITING_LEG")),
                )
                .all()
            )
            if not positions:
                logger.warning("rms_engine.register_run: run_id=%s has no open legs", run_id)
                return False

            # StrategyRun has no `strategy` relationship — fetch legs by FK.
            strategy_legs = (
                db_session.query(StrategyLeg)
                .filter(StrategyLeg.strategy_id == run.strategy_id)
                .all()
            )
            legs_by_id = {l.id: l for l in strategy_legs}

            # Load strategy_risk_config (Phase 4) — cache at register-time so
            # the tick loop never hits the DB for config.
            cfg = (
                db_session.query(StrategyRiskConfig)
                .filter(StrategyRiskConfig.strategy_id == run.strategy_id)
                .first()
            )

            runtime = _RunRuntime(
                run_id=run_id,
                strategy_id=run.strategy_id,
                peak_mtm=float(run.peak_mtm or 0),
                profit_locked=bool(run.profit_locked),
            )
            if cfg is not None:
                runtime.overall_sl_enabled = bool(cfg.overall_sl_enabled)
                runtime.overall_sl_abs = (
                    float(cfg.overall_sl_abs) if cfg.overall_sl_abs is not None else None
                )
                runtime.overall_target_enabled = bool(cfg.overall_target_enabled)
                runtime.overall_target_abs = (
                    float(cfg.overall_target_abs) if cfg.overall_target_abs is not None else None
                )
                runtime.lock_profit_enabled = bool(cfg.lock_profit_enabled)
                runtime.lock_at_abs = (
                    float(cfg.lock_at_abs) if cfg.lock_at_abs is not None else None
                )
                runtime.lock_min_abs = (
                    float(cfg.lock_min_abs) if cfg.lock_min_abs is not None else None
                )
                runtime.trail_to_entry_enabled = bool(cfg.trail_to_entry_enabled)
                runtime.trail_to_entry_threshold = float(cfg.trail_to_entry_threshold or 0)
                runtime.trail_to_entry_unit = cfg.trail_to_entry_unit or "pct"

            for pos in positions:
                leg_def = legs_by_id.get(pos.leg_id)
                if leg_def is None:
                    logger.warning(
                        "rms_engine.register_run: position run=%s leg=%s missing leg row",
                        run_id, pos.leg_id,
                    )
                    continue

                avg_entry = float(pos.avg_entry) if pos.avg_entry is not None else 0.0
                net_qty = pos.net_qty or 0
                if net_qty == 0 or avg_entry == 0:
                    # Defensive — flat or no entry price means we can't compute
                    # SL/target. Skip this leg.
                    continue

                leg = _LegRuntime(
                    leg_id=pos.leg_id,
                    position_id=pos.id,
                    symbol=pos.symbol,
                    exchange=pos.exchange,
                    tick_size=float(leg_def.tick_size_cache or 0.05),
                    direction=direction_of(net_qty),
                    avg_entry=avg_entry,
                    net_qty=net_qty,
                    target_enabled=bool(leg_def.target_enabled),
                    target_value=(
                        float(leg_def.target_value) if leg_def.target_value is not None else None
                    ),
                    target_unit=leg_def.target_unit,
                    sl_enabled=bool(leg_def.sl_enabled),
                    sl_value=(
                        float(leg_def.sl_value) if leg_def.sl_value is not None else None
                    ),
                    sl_unit=leg_def.sl_unit,
                    trail_enabled=bool(leg_def.trail_enabled),
                    trail_x=(
                        float(leg_def.trail_x) if leg_def.trail_x is not None else None
                    ),
                    trail_y=(
                        float(leg_def.trail_y) if leg_def.trail_y is not None else None
                    ),
                    trail_unit=leg_def.trail_unit,
                    current_sl_price=(
                        float(pos.current_sl_price)
                        if pos.current_sl_price is not None
                        else None
                    ),
                    last_trail_anchor=(
                        float(pos.last_trail_anchor)
                        if pos.last_trail_anchor is not None
                        else avg_entry
                    ),
                    trail_advances_count=int(pos.trail_advances_count or 0),
                    trail_to_entry_armed=bool(pos.trail_to_entry_armed),
                    last_ltp=(
                        float(pos.ltp_decimal) if pos.ltp_decimal is not None else None
                    ),
                )
                runtime.legs[pos.leg_id] = leg
                self._symbol_to_runs[_symbol_key(pos.exchange, pos.symbol)].add(run_id)

            if not runtime.legs:
                return False

            self._runs[run_id] = runtime
            self._refresh_subscription()
            logger.info(
                "rms_engine: registered run_id=%s strategy_id=%s legs=%s",
                run_id, run.strategy_id, len(runtime.legs),
            )
            return True

    def unregister_run(self, run_id: int) -> None:
        """Stop monitoring a run. Called when state transitions to a terminal
        state (CLOSED, EXIT_FAILED, ERRORED, STOPPED, ENTRY_FAILED) or
        EXITING (engine stops monitoring new triggers but the fill watcher
        keeps reconciling)."""
        with self._lock:
            runtime = self._runs.pop(run_id, None)
            if runtime is None:
                return
            for leg in runtime.legs.values():
                key = _symbol_key(leg.exchange, leg.symbol)
                refs = self._symbol_to_runs.get(key, set())
                refs.discard(run_id)
                if not refs:
                    self._symbol_to_runs.pop(key, None)
            self._refresh_subscription()
            logger.info("rms_engine: unregistered run_id=%s", run_id)

    def active_run_ids(self) -> list[int]:
        with self._lock:
            return list(self._runs.keys())

    # ----------------- Subscription management -----------------

    def _refresh_subscription(self) -> None:
        """Re-subscribe to market_data_service with the current symbol set.

        Held inside _lock by the caller. Unsubscribes the old subscription
        first so the filter set is replaced atomically.
        """
        # Lazy import — avoids forcing market_data_service to load before app
        # startup is complete.
        from services.market_data_service import get_market_data_service

        mds = get_market_data_service()

        if self._subscriber_id is not None:
            mds.unsubscribe_priority(self._subscriber_id)
            self._subscriber_id = None

        if not self._symbol_to_runs:
            return

        filter_symbols = set(self._symbol_to_runs.keys())
        self._subscriber_id = mds.subscribe_critical(
            callback=self._on_tick,
            filter_symbols=filter_symbols,
            name="rms_engine",
        )

    # ----------------- Tick callback (HOT PATH) -----------------

    def _on_tick(self, data: dict) -> None:
        """Single tick from market_data_service. Dispatches to every active
        run that holds the symbol."""
        try:
            from services.market_data_service import get_market_data_service

            symbol = data.get("symbol")
            exchange = data.get("exchange")
            if not symbol or not exchange:
                return
            key = _symbol_key(exchange, symbol)

            ltp_field = (data.get("data") or {}).get("ltp")
            if ltp_field is None:
                return
            try:
                ltp = float(ltp_field)
            except (TypeError, ValueError):
                return
            if ltp <= 0:
                return

            mds = get_market_data_service()
            safe, reason = mds.is_trade_management_safe()
            if not safe:
                # Stale feed / disconnected — skip RMS evaluation for safety.
                # Plan §6.2: never trigger SL on stale data.
                logger.debug("rms_engine: tick gated — feed not safe (%s)", reason)
                return

            with self._lock:
                affected = list(self._symbol_to_runs.get(key, ()))

            for run_id in affected:
                self._evaluate_run(run_id, key, ltp)

        except Exception:
            # Don't let exceptions propagate into market_data_service —
            # it would unsubscribe us. Log + carry on.
            logger.exception("rms_engine: tick callback failed")

    def _evaluate_run(self, run_id: int, symbol_key: str, ltp: float) -> None:
        """Per-run, per-tick evaluation. Held briefly under the run lock so
        config edits / unregister don't race."""
        with self._lock:
            runtime = self._runs.get(run_id)
            if runtime is None:
                return

        # Stamp the new ltp on the matching leg(s) before per-leg eval so
        # aggregate MTM later sees the latest tick.
        ticked_legs: list[_LegRuntime] = []
        for leg in list(runtime.legs.values()):
            if _symbol_key(leg.exchange, leg.symbol) == symbol_key:
                leg.last_ltp = ltp
                ticked_legs.append(leg)

        # Per-leg rule evaluation for the legs whose symbol just ticked.
        # If a leg fires an exit, _fire_exit drops it from runtime.legs;
        # subsequent strategy-level evaluation will sum what's left.
        for leg in ticked_legs:
            try:
                self._evaluate_leg(runtime, leg, ltp)
            except Exception:
                logger.exception(
                    "rms_engine: leg evaluation failed run=%s leg=%s",
                    run_id, leg.leg_id,
                )

        # Strategy-level rules — only meaningful if the run has multiple legs
        # active OR a single leg with overall caps. The aggregate uses
        # last_ltp from each leg (NOT the just-ticked LTP for un-ticked legs;
        # they keep their last seen value).
        try:
            self._evaluate_strategy_level(runtime)
        except Exception:
            logger.exception(
                "rms_engine: strategy-level evaluation failed run=%s", run_id,
            )

    def _evaluate_leg(self, run: _RunRuntime, leg: _LegRuntime, ltp: float) -> None:
        """The four rules in priority order.

        Order matters: trail update first so the new SL is used when checking
        whether SL is hit on the SAME tick. Otherwise a sharp move could
        bypass a trail advance and trigger the original SL. Plan §6.1
        ordering.
        """
        anchor = leg.last_trail_anchor or leg.avg_entry
        current_sl = leg.current_sl_price

        # ----- Trail X/Y -----
        if leg.trail_enabled and current_sl is not None:
            td = evaluate_trail(
                enabled=leg.trail_enabled,
                trail_x=leg.trail_x, trail_y=leg.trail_y, trail_unit=leg.trail_unit,
                avg_entry=leg.avg_entry, ltp=ltp, direction=leg.direction,
                tick_size=leg.tick_size,
                last_anchor=anchor,
                current_sl_price=current_sl,
            )
            if td.advanced and td.new_sl_price is not None and td.new_anchor is not None:
                leg.current_sl_price = td.new_sl_price
                leg.last_trail_anchor = td.new_anchor
                leg.trail_advances_count += td.advances
                self._persist_trail(leg)
                bus.publish(
                    StrategyTrailAdvancedEvent(
                        strategy_id=run.strategy_id,
                        run_id=run.run_id,
                        leg_id=leg.leg_id,
                        advances=td.advances,
                        new_sl=td.new_sl_price,
                        ltp=ltp,
                    )
                )
                current_sl = td.new_sl_price

        # ----- Initialise SL on first tick if not yet set -----
        if leg.sl_enabled and current_sl is None and leg.sl_value is not None:
            sd = evaluate_sl(
                enabled=True, sl_value=leg.sl_value, sl_unit=leg.sl_unit,
                avg_entry=leg.avg_entry, ltp=ltp, direction=leg.direction,
                tick_size=leg.tick_size,
                current_sl_price=None,
            )
            if sd.sl_price is not None:
                leg.current_sl_price = sd.sl_price
                # Persist initial SL — first tick only.
                self._persist_trail(leg)
                current_sl = sd.sl_price

        # ----- Target -----
        if leg.target_enabled:
            target_decision = evaluate_target(
                enabled=True,
                target_value=leg.target_value, target_unit=leg.target_unit,
                avg_entry=leg.avg_entry, ltp=ltp, direction=leg.direction,
                tick_size=leg.tick_size,
            )
            if target_decision.triggered:
                self._fire_exit(
                    run, leg,
                    rule="LEG_TARGET",
                    threshold=target_decision.target_price or 0.0,
                    ltp=ltp,
                    reason="exit_leg_target",
                )
                return  # one rule per tick

        # ----- SL -----
        if leg.sl_enabled and current_sl is not None:
            sl_decision = evaluate_sl(
                enabled=True, sl_value=leg.sl_value, sl_unit=leg.sl_unit,
                avg_entry=leg.avg_entry, ltp=ltp, direction=leg.direction,
                tick_size=leg.tick_size,
                current_sl_price=current_sl,
            )
            if sl_decision.triggered:
                self._fire_exit(
                    run, leg,
                    rule="LEG_SL",
                    threshold=sl_decision.sl_price or 0.0,
                    ltp=ltp,
                    reason="exit_leg_sl",
                )
                return

    # ----------------- Strategy-level evaluation (Phase 4) -----------------

    def _evaluate_strategy_level(self, run: _RunRuntime) -> None:
        """After per-leg rules, evaluate run-wide rules.

        Order matches plan §6.1:
          4. Overall SL / Overall Target — short-circuit; full strategy exit
          5. Profit lock arm + floor
          6. Trail-to-entry per leg

        We compute aggregate MTM from in-memory leg.last_ltp values. Legs
        without a tick yet (leg.last_ltp is None) contribute 0 to mtm —
        this is conservative (treats as flat) and self-correcting once
        every leg has been touched.
        """
        if not run.legs:
            return

        # ---- Aggregate MTM ----
        agg_mtm = 0.0
        for leg in run.legs.values():
            if leg.last_ltp is None:
                continue
            sign = 1 if leg.direction == "long" else -1
            mtm = (leg.last_ltp - leg.avg_entry) * abs(leg.net_qty) * sign
            agg_mtm += mtm

        prev_peak = run.peak_mtm
        if agg_mtm > run.peak_mtm:
            run.peak_mtm = agg_mtm

        peak_changed = run.peak_mtm != prev_peak

        # ---- 4a. Overall SL ----
        sl_decision = evaluate_overall_sl(
            enabled=run.overall_sl_enabled,
            overall_sl_abs=run.overall_sl_abs,
            aggregate_mtm=agg_mtm,
        )
        if sl_decision.triggered:
            self._persist_run_state(run, agg_mtm)
            self._fire_strategy_exit(run, "OVERALL_SL", sl_decision.threshold, agg_mtm)
            return

        # ---- 4b. Overall Target ----
        tgt_decision = evaluate_overall_target(
            enabled=run.overall_target_enabled,
            overall_target_abs=run.overall_target_abs,
            aggregate_mtm=agg_mtm,
        )
        if tgt_decision.triggered:
            self._persist_run_state(run, agg_mtm)
            self._fire_strategy_exit(run, "OVERALL_TARGET", tgt_decision.threshold, agg_mtm)
            return

        # ---- 5a. Profit lock arm (latch) ----
        arm_now = evaluate_profit_lock_arm(
            enabled=run.lock_profit_enabled,
            lock_at_abs=run.lock_at_abs,
            peak_mtm=run.peak_mtm,
            already_armed=run.profit_locked,
        )
        if arm_now:
            run.profit_locked = True
            bus.publish(
                StrategyRmsTriggeredEvent(
                    strategy_id=run.strategy_id, run_id=run.run_id, leg_id=0,
                    rule="PROFIT_LOCK_ARMED",
                    ltp=agg_mtm, threshold=run.lock_at_abs or 0.0,
                )
            )

        # ---- 5b. Profit lock floor exit ----
        if run.profit_locked:
            floor_decision = evaluate_profit_lock_floor(
                armed=True,
                lock_min_abs=run.lock_min_abs,
                aggregate_mtm=agg_mtm,
            )
            if floor_decision.triggered:
                self._persist_run_state(run, agg_mtm)
                self._fire_strategy_exit(
                    run, "PROFIT_LOCK", floor_decision.threshold, agg_mtm,
                )
                return

        # ---- 6. Trail-to-entry per leg ----
        if run.trail_to_entry_enabled:
            for leg in list(run.legs.values()):
                if leg.trail_to_entry_armed or leg.last_ltp is None:
                    continue
                d = evaluate_trail_to_entry(
                    enabled=True,
                    threshold=run.trail_to_entry_threshold,
                    threshold_unit=run.trail_to_entry_unit,  # type: ignore[arg-type]
                    avg_entry=leg.avg_entry,
                    ltp=leg.last_ltp,
                    direction=leg.direction,  # type: ignore[arg-type]
                    tick_size=leg.tick_size,
                    current_sl_price=leg.current_sl_price,
                    already_armed=False,
                )
                if d.arm_now:
                    leg.trail_to_entry_armed = True
                    if d.new_sl_price is not None:
                        leg.current_sl_price = d.new_sl_price
                    self._persist_trail(leg)
                    bus.publish(
                        StrategyRmsTriggeredEvent(
                            strategy_id=run.strategy_id, run_id=run.run_id,
                            leg_id=leg.leg_id, rule="TRAIL_TO_ENTRY",
                            ltp=leg.last_ltp,
                            threshold=run.trail_to_entry_threshold,
                            new_sl=d.new_sl_price or 0.0,
                        )
                    )

        # Persist run-level state on peak change (debounced — we only write
        # when the peak actually moved, not on every tick).
        if peak_changed:
            self._persist_run_state(run, agg_mtm)

    def _persist_run_state(self, run: _RunRuntime, agg_mtm: float) -> None:
        """Write peak_mtm + profit_locked back to strategy_runs."""
        try:
            db_session.execute(
                StrategyRun.__table__.update()
                .where(StrategyRun.id == run.run_id)
                .values(
                    peak_mtm=Decimal(str(run.peak_mtm)),
                    profit_locked=run.profit_locked,
                    max_unrealized_pnl=Decimal(str(max(run.peak_mtm, agg_mtm))),
                )
            )
            db_session.commit()
        except Exception:
            db_session.rollback()
            logger.exception("rms_engine._persist_run_state failed run=%s", run.run_id)
        finally:
            db_session.remove()

    def _fire_strategy_exit(
        self,
        run: _RunRuntime,
        rule: str,
        threshold: float,
        agg_mtm: float,
    ) -> None:
        """Drop the entire run from the registry, publish the trigger event,
        call exit_service.exit_strategy. Engine sees the EXITING transition
        downstream via on_state_changed and unregisters cleanly."""
        run_id = run.run_id
        strategy_id = run.strategy_id

        # Remove ALL legs of this run from monitoring before placing exits.
        with self._lock:
            r = self._runs.pop(run_id, None)
            if r is not None:
                for leg in r.legs.values():
                    key = _symbol_key(leg.exchange, leg.symbol)
                    refs = self._symbol_to_runs.get(key, set())
                    refs.discard(run_id)
                    if not refs:
                        self._symbol_to_runs.pop(key, None)
            self._refresh_subscription()

        bus.publish(
            StrategyRmsTriggeredEvent(
                strategy_id=strategy_id, run_id=run_id, leg_id=0,
                rule=rule, ltp=agg_mtm, threshold=threshold,
            )
        )

        # Lazy import — exit_service has the same restx_api circular dance.
        from services.strategy.exit_service import exit_strategy

        try:
            exit_strategy(run_id=run_id, reason=f"exit_{rule.lower()}")
        except Exception:
            logger.exception(
                "rms_engine._fire_strategy_exit: exit_strategy failed run=%s", run_id,
            )

    # ----------------- Side-effect helpers -----------------

    def _persist_trail(self, leg: _LegRuntime) -> None:
        """Write current_sl_price + last_trail_anchor + advances back to
        strategy_positions. Engine pre-checks that the row exists; this is
        a UPDATE-WHERE, no INSERT."""
        try:
            db_session.execute(
                StrategyPosition.__table__.update()
                .where(StrategyPosition.id == leg.position_id)
                .values(
                    current_sl_price=Decimal(str(leg.current_sl_price))
                    if leg.current_sl_price is not None
                    else None,
                    last_trail_anchor=Decimal(str(leg.last_trail_anchor))
                    if leg.last_trail_anchor is not None
                    else None,
                    trail_advances_count=leg.trail_advances_count,
                    trail_to_entry_armed=leg.trail_to_entry_armed,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            db_session.commit()
        except Exception:
            db_session.rollback()
            logger.exception("rms_engine._persist_trail failed leg=%s", leg.leg_id)
        finally:
            db_session.remove()

    def _fire_exit(
        self,
        run: _RunRuntime,
        leg: _LegRuntime,
        *,
        rule: str,
        threshold: float,
        ltp: float,
        reason: str,
    ) -> None:
        """Publish StrategyRmsTriggeredEvent and call exit_service.close_leg.

        Drops the leg from the runtime registry immediately — even if the
        broker call takes a few hundred ms, we don't want subsequent ticks
        re-firing the same rule on the same leg. The fill watcher
        (position_tracker) handles the leg state transition CLOSED.
        """
        # Remove from active monitoring before placing the exit (idempotency).
        with self._lock:
            r = self._runs.get(run.run_id)
            if r is not None:
                r.legs.pop(leg.leg_id, None)
                if not r.legs:
                    self._runs.pop(run.run_id, None)
                key = _symbol_key(leg.exchange, leg.symbol)
                refs = self._symbol_to_runs.get(key, set())
                refs.discard(run.run_id)
                if not refs:
                    self._symbol_to_runs.pop(key, None)
            self._refresh_subscription()

        bus.publish(
            StrategyRmsTriggeredEvent(
                strategy_id=run.strategy_id,
                run_id=run.run_id,
                leg_id=leg.leg_id,
                rule=rule,
                ltp=ltp,
                threshold=threshold,
                new_sl=leg.current_sl_price or 0.0,
            )
        )

        # Lazy import — exit_service brings in broker_adapter_impls which
        # has the existing restx_api circular-import dance.
        from services.strategy.exit_service import close_leg

        try:
            close_leg(
                run_id=run.run_id,
                leg_id=leg.leg_id,
                reason=reason,
            )
        except Exception:
            logger.exception(
                "rms_engine._fire_exit: close_leg failed run=%s leg=%s",
                run.run_id, leg.leg_id,
            )

    # ----------------- Bus event subscribers -----------------

    def on_state_changed(self, event) -> None:
        """Subscribed to strategy.state_changed.

        Transitions ENTERING→IN_TRADE: register the run.
        Transitions to terminal states: unregister.
        """
        new_state = getattr(event, "new_state", "")
        run_id = getattr(event, "run_id", 0)
        if not run_id:
            return
        if new_state == "IN_TRADE":
            self.register_run(run_id)
        elif new_state in (
            "EXITING", "CLOSED",
            "EXIT_FAILED", "ERRORED", "STOPPED", "ENTRY_FAILED",
        ):
            self.unregister_run(run_id)


# Module-level singleton — wired in subscribers/__init__.py.
engine: RmsEngine = RmsEngine()


def get_engine() -> RmsEngine:
    """Public accessor — useful for tests."""
    return engine


def on_strategy_state_changed(event) -> None:
    """Bus subscriber — wired in subscribers/__init__.py:register_all."""
    engine.on_state_changed(event)
