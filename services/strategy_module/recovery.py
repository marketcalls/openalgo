"""Boot recovery: rebuild every run that was still open when the process died.

``state`` is in-process, so a crash, a deploy or a restart takes every live run
with it while the positions those runs were managing are still at the broker.
:func:`recover_all` runs once at startup, before the tick feed begins, and puts
the state back from what was persisted:

* ``sm_strategy_order`` says what is actually held. Every order the engine
  places is written before the broker answers, so the rows are the record of
  the book: which legs entered, which were refused, which have already exited.
* ``sm_strategy_checkpoint`` says where the risk had got to. The newest row
  carries the ratchets, which cannot be derived from an order: the trailed
  stop, the favourable extreme, the peak and trough, the lock-profit floor.

Precedence between the two, applied field by field
--------------------------------------------------

**Orders win on identity and on negative facts.** Symbol, exchange, quantity,
side, and the order ids come from the order rows whenever a leg has any. So
does "this did not happen": an entry the broker rejected is a leg that holds
nothing, and no checkpoint may say otherwise.

**A fill recorded anywhere counts as a fill.** The checkpoint may upgrade a
*working* order to filled, and only in that direction. It is written from the
same fill that ``engine.apply_fill`` applies to the live state, and it can
therefore witness a fill that reached the run before the row was updated. It
can never downgrade: a dead order stays dead.

**Everything volatile comes from the checkpoint.** Last price, effective stop,
effective target, trail flags, the favourable extremes, realized P&L, and the
run aggregates (P&L, peak, trough, lock floor, trail-to-entry). None of it is
derivable from an order, and all of it re-derives from the next tick if it is
missing, which is exactly what a run that crashed before its first checkpoint
gets.

Two invariants
--------------

**Every leg carries a position.** A leg without one is evaluated as a short by
the risk core, which silently inverts its P&L, its stop and its target. A leg
whose side cannot be established from either source fails the run rather than
being guessed at.

**One bad run cannot wedge the boot.** A run whose rows are malformed beyond
reconstruction is closed with ``stop_reason="recovery_failed"`` and a critical
event, so the operator is told and the next start is not blocked. A run whose
rows prove exposure but cannot fit the live-plus-superseded state is different:
it stays open and reserved, emits a critical reconciliation event, and is not
installed in memory. Closing that run would falsely assert that the broker is
flat and make the strategy reusable over unmanaged exposure.

Nothing here imports the tick feed. :func:`recover_all` returns the
``(symbol, exchange)`` pairs each recovered run still needs prices for, and the
caller subscribes them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from database import strategy_module_db as store
from services.strategy_module import state
from utils.db_sessions import remove_all_scoped_sessions
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "RecoveredRun",
    "normalise_order_status",
    "order_is_dead",
    "order_is_filled",
    "order_is_working",
    "recover_all",
    "recover_run",
]


# ---------------------------------------------------------------------------
# Order status, normalised in one place
#
# Broker status strings are not standardised, and the module this is ported
# from normalises them in two separate functions that disagree with each other:
# one counts "submitted", "trigger_pending" and "modified" as live orders, the
# other treats them as unknown and therefore dead. A leg could be read as
# holding nothing by one and as holding a position by the other, on the same
# row. There is one table here, and every predicate below is derived from it.
#
# The classification that matters is three-way: filled, still working, or dead.
# An unrecognised string is treated as WORKING, which is the conservative
# reading. Treating an unknown exit as dead would let a second exit be placed
# against a position that is already on its way out, and a second exit does not
# close a position twice - it opens the opposite one.
# ---------------------------------------------------------------------------

_FILLED_STATUSES = frozenset(
    {
        "complete",
        "completed",
        "filled",
        "fill",
        "executed",
        "traded",
        "trade",
        "success",
        "successful",
    }
)

_CANCELLED_STATUSES = frozenset({"cancelled", "canceled", "cancel", "expired", "lapsed"})

_REJECTED_STATUSES = frozenset({"rejected", "reject", "failed", "failure", "error", "invalid"})

_WORKING_STATUSES = frozenset(
    {
        "pending",
        "open",
        "submitted",
        "trigger_pending",
        "trigger_pending_amo",
        "modified",
        "modify",
        "modify_pending",
        "queued",
        "placed",
        "received",
        "transit",
        "validation_pending",
        "open_pending",
        "put_order_req_received",
        "after_market_order_req_received",
        "amo_req_received",
    }
)

#: Statuses that still count as pending rather than as a live order at the
#: exchange. Cosmetic only: both are "working".
_PENDING_STATUSES = frozenset({"pending", "queued", "validation_pending", "transit"})


def normalise_order_status(raw: Any) -> str:
    """One broker or store status string as one of ``store.ORDER_STATUSES``.

    The single place any status string is interpreted. Everything else in this
    module goes through :func:`order_is_filled`, :func:`order_is_working` or
    :func:`order_is_dead`, which are all derived from this.

    Args:
        raw: Whatever the row or the broker called it.

    Returns:
        One of ``pending``, ``open``, ``complete``, ``cancelled``, ``rejected``.
    """
    text = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in _FILLED_STATUSES:
        return "complete"
    if text in _CANCELLED_STATUSES:
        return "cancelled"
    if text in _REJECTED_STATUSES:
        return "rejected"
    if text in _PENDING_STATUSES:
        return "pending"
    if text in _WORKING_STATUSES:
        return "open"
    # Conservative: an unrecognised status is an order that may yet fill, not
    # one that can be written off. See the note above the table.
    logger.warning("Unrecognised order status %r during recovery; treating it as working", raw)
    return "open"


def order_is_filled(raw: Any) -> bool:
    """Whether this status means the order filled."""
    return normalise_order_status(raw) == "complete"


def order_is_dead(raw: Any) -> bool:
    """Whether this status means the order will never fill."""
    return normalise_order_status(raw) in ("cancelled", "rejected")


def order_is_working(raw: Any) -> bool:
    """Whether this status means the order is still live and may yet fill."""
    return normalise_order_status(raw) in ("pending", "open")


def _position_from_action(action: Any) -> str:
    """The side a leg holds, from the action that opened it.

    Strict on purpose. A leg with no side is evaluated as a short by the risk
    core, so guessing here inverts a real position's P&L, stop and target
    without anything in the logs to say so.
    """
    normalised = str(action or "").strip().upper()
    if normalised == "BUY":
        return "B"
    if normalised == "SELL":
        return "S"
    raise ValueError(f"Cannot derive a position from order action {action!r}")


def _normalise_position(value: Any) -> str:
    """A stored B/S, refusing anything else."""
    normalised = str(value or "").strip().upper()
    if normalised in ("B", "S"):
        return normalised
    raise ValueError(f"Unusable leg position: {value!r}")


def _float(value: Any, default: float | None = None) -> float | None:
    """A number, or the default when it is missing or unusable."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecoveredRun:
    """What one run's recovery produced."""

    run_id: int
    strategy_id: int | None = None
    #: Whether the run was rebuilt. False means it was finalised or skipped.
    ok: bool = False
    #: Whether this call closed the run rather than resuming it: either it
    #: could not be rebuilt, or it came back holding nothing.
    finalised: bool = False
    #: Every ``(symbol, exchange)`` the run still needs ticks for.
    symbols: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    legs: int = 0
    open_legs: int = 0
    error: str | None = None


class _ManagedRecoveryError(RuntimeError):
    """Persisted exposure exists but cannot be represented safely in memory."""


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def recover_all() -> dict[int, set[tuple[str, str]]]:
    """Rebuild every run that was still open, once, at startup.

    Call before the tick feed starts: a run must be back in ``state`` before a
    price for one of its legs can arrive, or the tick is evaluated against a
    run that does not exist yet and is simply lost.

    Returns:
        ``{run_id: {(symbol, exchange), ...}}`` for every run that came back
        live, so the caller can subscribe exactly what still carries risk. Runs
        that were finalised (unrecoverable, or already flat) are absent.
    """
    resumed: dict[int, set[tuple[str, str]]] = {}
    try:
        # Ids first: the rows are ORM objects, and the session cleanup below
        # detaches them.
        run_ids = [run.id for run in store.list_open_runs()]
    except Exception:
        logger.exception("Could not list open runs; no run was recovered")
        return resumed

    if not run_ids:
        logger.info("Strategy recovery: no open run to recover")
        return resumed

    failed = 0
    try:
        for run_id in run_ids:
            result = recover_run(run_id)
            if result.ok:
                resumed[run_id] = set(result.symbols)
            elif result.finalised:
                failed += 1
    finally:
        # Startup runs outside any Flask app context, so teardown_appcontext
        # never fires for the sessions this bound.
        remove_all_scoped_sessions()

    logger.info(
        "Strategy recovery: %s of %s open runs resumed, %s finalised, watching %s instruments",
        len(resumed),
        len(run_ids),
        failed,
        len({pair for pairs in resumed.values() for pair in pairs}),
    )
    return resumed


def recover_run(run_id: int) -> RecoveredRun:
    """Rebuild one run, or finalise it if it cannot be rebuilt.

    Never raises. A run that cannot be reconstructed is closed with
    ``stop_reason="recovery_failed"`` and a critical event, because the
    alternative is a boot that fails the same way every time.
    """
    try:
        return _recover_run(run_id)
    except _ManagedRecoveryError as exc:
        logger.exception("Run %s needs manual recovery reconciliation", run_id)
        strategy_id = _strategy_id_for(run_id)
        _record_event(
            strategy_id,
            "recovery_failed",
            f"Run {run_id} remains open for manual reconciliation: {exc}",
            run_id=run_id,
            severity="critical",
        )
        return RecoveredRun(
            run_id=run_id,
            strategy_id=strategy_id,
            ok=False,
            finalised=False,
            error=str(exc),
        )
    except Exception as exc:
        logger.exception("Could not recover run %s", run_id)
        strategy_id = _strategy_id_for(run_id)
        finalised = _finalise(
            run_id,
            strategy_id,
            reason="recovery_failed",
            kind="recovery_failed",
            severity="critical",
            message=f"Run {run_id} could not be recovered and was closed: {exc}",
        )
        return RecoveredRun(
            run_id=run_id,
            strategy_id=strategy_id,
            ok=False,
            finalised=finalised,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------


def _recover_run(run_id: int) -> RecoveredRun:
    """Rebuild one run. Raises when the run cannot be reconstructed."""
    existing = state.get_run_state(run_id)
    if existing is not None:
        # Already live in this process. Recovery is idempotent so that a second
        # call, or a recovery racing a run that started normally, cannot
        # overwrite live state with a snapshot of it.
        logger.debug("Run %s already has live state; leaving it alone", run_id)
        return RecoveredRun(
            run_id=run_id,
            strategy_id=existing.get("strategy_id"),
            ok=True,
            symbols=frozenset(state.subscribed_symbols(existing)),
            legs=len(existing.get("legs", {})),
            open_legs=len(state.open_legs(existing)),
        )

    run_row = store.get_run(run_id)
    if run_row is None:
        logger.warning("Run %s does not exist; nothing to recover", run_id)
        return RecoveredRun(run_id=run_id, ok=False, error="Run not found")
    # Keep no ORM row alive across the store calls below. Any commit expires
    # it, and worker/session cleanup can then detach it before recovery reaches
    # the stop facts again.
    strategy_id = int(run_row.strategy_id)
    stopped_at = run_row.stopped_at
    stop_requested_reason = run_row.stop_requested_reason
    if stopped_at is not None:
        logger.debug("Run %s is already stopped; nothing to recover", run_id)
        return RecoveredRun(
            run_id=run_id, strategy_id=strategy_id, ok=False, error="Run is already stopped"
        )

    from services.strategy_module import ack_reconciliation

    ack_repairs = ack_reconciliation.reconcile(run_id)
    if ack_repairs.unresolved_exposure:
        raise _ManagedRecoveryError(
            f"{ack_repairs.unresolved_exposure} broker acknowledgement event(s) could not "
            "be linked to exact order rows; possible exposure remains reserved"
        )

    orders = store.list_orders(run_id)
    checkpoint = store.latest_checkpoint(run_id) or {}
    config_legs = _config_legs(strategy_id)

    rebuilt = _rebuild_state(
        run_id,
        strategy_id,
        orders,
        checkpoint,
        config_legs,
        stopping=stop_requested_reason is not None,
    )
    if not rebuilt.get("pnl_realized_authoritative", True):
        _record_event(
            strategy_id,
            "recovery_succeeded",
            (
                f"Run {run_id} recovered with only partially valued realized P&L; "
                "one or more durable fills have no usable price and no matching checkpoint "
                "total. The known portion is retained, but manual P&L reconciliation is required."
            ),
            run_id=run_id,
            severity="critical",
        )
    symbols = state.subscribed_symbols(rebuilt)
    open_count = len(state.open_legs(rebuilt))

    if not symbols:
        # Every leg is closed or was refused, so the run holds nothing. It was
        # never finalised because the process died between the last exit fill
        # and the finalise that fill would have triggered. Resuming it would
        # leave a strategy reading as running while holding nothing, which is
        # exactly the state engine._finalise exists to prevent, and no tick
        # would ever arrive to close it.
        stop_reason = stop_requested_reason or "manual"
        pending_stop = stop_requested_reason is not None
        finalised = _finalise(
            run_id,
            strategy_id,
            reason=stop_reason,
            kind="run_stopped" if pending_stop else "recovery_succeeded",
            severity="info",
            message=(
                f"Run stopped ({stop_reason}); recovery confirmed it was flat"
                if pending_stop
                else "Recovered flat: every leg had already closed, so the run was finished"
            ),
            pnl=_final_pnl(checkpoint, rebuilt),
        )
        if finalised:
            logger.info("Run %s recovered flat and was finished", run_id)
        else:
            logger.warning("Run %s recovered flat but terminal ownership was not won", run_id)
        return RecoveredRun(
            run_id=run_id,
            strategy_id=strategy_id,
            ok=False,
            finalised=finalised,
            legs=len(rebuilt["legs"]),
            error=None if finalised else "Could not atomically finish the recovered flat run",
        )

    state.hydrate_run_state(run_id, rebuilt)
    _record_event(
        strategy_id,
        "recovery_succeeded",
        f"Run {run_id} recovered: {open_count} open of {len(rebuilt['legs'])} legs, "
        f"{len(symbols)} instruments resubscribed"
        + ("" if checkpoint else " (no checkpoint; risk levels re-derive on the next tick)"),
        run_id=run_id,
    )
    logger.info(
        "Recovered run %s: %s legs, %s open, %s instruments%s",
        run_id,
        len(rebuilt["legs"]),
        open_count,
        len(symbols),
        "" if checkpoint else ", no checkpoint",
    )
    return RecoveredRun(
        run_id=run_id,
        strategy_id=strategy_id,
        ok=True,
        symbols=frozenset(symbols),
        legs=len(rebuilt["legs"]),
        open_legs=open_count,
    )


def _rebuild_state(
    run_id: int,
    strategy_id: int,
    orders: list[dict[str, Any]],
    checkpoint: dict[str, Any],
    config_legs: dict[str, dict[str, Any]],
    *,
    stopping: bool = False,
) -> dict[str, Any]:
    """The run's state dict, in exactly the shape ``state.init_run_state`` builds."""
    checkpoint_legs = checkpoint.get("leg_state") or {}

    entries: dict[str, list[dict[str, Any]]] = {}
    exits: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        key = str(order.get("leg_id"))
        bucket = entries if order.get("kind") == "entry" else exits
        bucket.setdefault(key, []).append(order)

    # Every leg any source knows about. A leg with no order row at all is a leg
    # whose entry never reached the store, and the checkpoint is then its only
    # witness.
    leg_keys = list(dict.fromkeys([*entries, *exits, *checkpoint_legs]))

    legs: dict[str, dict[str, Any]] = {}
    for key in leg_keys:
        leg = _rebuild_leg(
            key,
            entries.get(key, []),
            exits.get(key, []),
            checkpoint_legs.get(key) or {},
            config_legs.get(key) or {},
        )
        legs[str(leg["leg_id"])] = leg

    lock_floor = _float(checkpoint.get("lock_floor"))
    checkpoint_realized_present = (
        bool(checkpoint) and _float(checkpoint.get("pnl_realized")) is not None
    )
    checkpoint_realized = _float(checkpoint.get("pnl_realized"), 0.0) or 0.0
    has_referenced_orders = any(order.get("position_ref") is not None for order in orders)
    derive_realized_from_legs = has_referenced_orders or not checkpoint_realized_present
    pnl_realized = (
        sum(_float(leg.get("realized_pnl"), 0.0) or 0.0 for leg in legs.values())
        if derive_realized_from_legs
        else checkpoint_realized
    )
    pnl_realized_authoritative = (
        all(leg.get("realized_pnl_authoritative", True) for leg in legs.values())
        if derive_realized_from_legs
        else True
    )
    pnl_unrealized = _float(checkpoint.get("pnl_unrealized"), 0.0) or 0.0
    return {
        "run_id": run_id,
        "strategy_id": strategy_id,
        "pnl_realized": pnl_realized,
        "pnl_realized_authoritative": pnl_realized_authoritative,
        "pnl_unrealized": pnl_unrealized,
        "pnl_total": (
            pnl_realized + pnl_unrealized
            if derive_realized_from_legs
            else (_float(checkpoint.get("pnl_total"), 0.0) or 0.0)
        ),
        "pnl_peak": _float(checkpoint.get("pnl_peak"), 0.0) or 0.0,
        "pnl_trough": _float(checkpoint.get("pnl_trough"), 0.0) or 0.0,
        # The checkpoint table has no lock_armed column, so it is inferred: a
        # floor only ever exists once the lock has armed, and the aggregate
        # evaluator re-arms it from the peak on the next tick anyway.
        "lock_armed": lock_floor is not None,
        "lock_floor": lock_floor,
        "trail_to_entry_active": bool(checkpoint.get("trail_to_entry_active", False)),
        # Re-derived by the tick feed, which knows nothing about what the feed
        # was doing before the restart.
        "tick_source_degraded": False,
        "stopping": stopping,
        "signal_entry_claims": {},
        "legs": legs,
    }


@dataclass(slots=True)
class _PositionRecovery:
    """One position incarnation folded from its exact durable order group."""

    rank: int
    leg: dict[str, Any]
    pnl_coverage_complete: bool = True


def _rebuild_leg(
    key: str,
    entries: list[dict[str, Any]],
    exits: list[dict[str, Any]],
    cp_leg: dict[str, Any],
    config_leg: dict[str, Any],
) -> dict[str, Any]:
    """One leg, using exact position groups when durable references exist."""
    all_orders = sorted([*entries, *exits], key=_order_rank)
    referenced = [order for order in all_orders if order.get("position_ref") is not None]
    if not referenced:
        return _rebuild_legacy_leg(key, entries, exits, cp_leg, config_leg)

    by_ref: dict[str, list[dict[str, Any]]] = {}
    for order in referenced:
        ref = str(order.get("position_ref"))
        if not ref:
            raise _ManagedRecoveryError(
                f"Leg {key} has an empty position reference and needs manual reconciliation"
            )
        by_ref.setdefault(ref, []).append(order)

    positions: list[_PositionRecovery] = []
    for position_ref, group in by_ref.items():
        group_entries = [order for order in group if order.get("kind") == "entry"]
        if not group_entries:
            raise _ManagedRecoveryError(
                f"Leg {key} has referenced exits for {position_ref} without its exact entry; "
                "ownership is ambiguous"
            )
        group_exits = [order for order in group if order.get("kind") != "entry"]
        positions.append(
            _rebuild_referenced_position(
                key,
                position_ref,
                group_entries,
                group_exits,
                _checkpoint_for_position(cp_leg, position_ref),
                config_leg,
            )
        )

    legacy_entries = [order for order in entries if order.get("position_ref") is None]
    legacy_exits = [order for order in exits if order.get("position_ref") is None]
    if legacy_exits and not legacy_entries:
        raise _ManagedRecoveryError(
            f"Leg {key} mixes referenced entries with legacy exits that have no legacy entry; "
            "exit ownership is ambiguous"
        )
    if len(legacy_entries) > 1:
        raise _ManagedRecoveryError(
            f"Leg {key} mixes referenced history with multiple legacy entry incarnations; "
            "their exits cannot be partitioned safely"
        )
    if legacy_entries:
        positions.append(
            _rebuild_referenced_position(
                key,
                None,
                legacy_entries,
                legacy_exits,
                _checkpoint_for_position(cp_leg, None),
                config_leg,
            )
        )

    positions.sort(key=lambda recovered: recovered.rank)
    managed = [recovered for recovered in positions if _position_requires_management(recovered.leg)]
    if len(managed) > 2:
        raise _ManagedRecoveryError(
            f"Leg {key} has more than two held position references; "
            "the run cannot be represented safely"
        )

    if managed:
        live = managed[-1].leg
        if len(managed) == 2:
            outgoing = managed[-2].leg
            if outgoing.get("status") != "open":
                raise _ManagedRecoveryError(
                    f"Leg {key} has an ambiguous older working entry that cannot be represented "
                    "as a held superseded position"
                )
            if (outgoing.get("symbol"), outgoing.get("exchange")) != (
                live.get("symbol"),
                live.get("exchange"),
            ):
                raise _ManagedRecoveryError(
                    f"Leg {key} has overlapping positions on different instruments; "
                    "one superseded leg cannot manage both safely"
                )
            live["superseded"] = _as_superseded(outgoing)
    else:
        # Retain the newest terminal incarnation so ordinary flat-run recovery
        # can finalise with its exact position and realized result.
        live = positions[-1].leg

    durable_realized = sum(float(position.leg.get("realized_pnl") or 0.0) for position in positions)
    coverage_complete = all(position.pnl_coverage_complete for position in positions)
    checkpoint_present, checkpoint_realized = _checkpoint_realized_for_recovered_shape(cp_leg, live)
    if coverage_complete:
        live["realized_pnl"] = durable_realized
        live["realized_pnl_authoritative"] = True
    elif checkpoint_present:
        live["realized_pnl"] = checkpoint_realized
        live["realized_pnl_authoritative"] = True
    else:
        live["realized_pnl"] = durable_realized
        live["realized_pnl_authoritative"] = False
    return live


def _rebuild_referenced_position(
    key: str,
    position_ref: str | None,
    entries: list[dict[str, Any]],
    exits: list[dict[str, Any]],
    cp_leg: dict[str, Any],
    config_leg: dict[str, Any],
) -> _PositionRecovery:
    """Fold every entry/exit attempt belonging to one exact position owner."""
    entry = _decisive(entries)
    if entry is None:
        raise _ManagedRecoveryError(
            f"Leg {key} position {position_ref} has no entry to establish ownership"
        )

    working = [order for order in exits if order_is_working(order.get("status"))]
    if len(working) > 1:
        raise _ManagedRecoveryError(
            f"Leg {key} position {position_ref} has multiple working exits; ownership is ambiguous"
        )

    # Reuse the established identity/risk reconstruction, then replace its
    # single-decisive-exit disposition with the cumulative owner-local fold.
    leg = _rebuild_legacy_leg(key, entries, exits, cp_leg, config_leg)
    entry_status = normalise_order_status(entry.get("status"))
    reported_entry_qty = _positive_whole(entry.get("filled_qty"))
    entry_filled = bool(
        reported_entry_qty is not None
        or order_is_filled(entry.get("status"))
        or (not order_is_dead(entry.get("status")) and _checkpoint_says_entry_filled(cp_leg))
    )
    entry_qty = int(entry.get("qty") or 0)
    if reported_entry_qty is not None:
        entry_qty = min(entry_qty or reported_entry_qty, reported_entry_qty)
    entry_qty = max(0, entry_qty)

    entry_avg = 0.0
    if entry_filled:
        entry_avg = (
            _float(entry.get("avg_fill_price"))
            or _float(cp_leg.get("entry_avg"))
            or _float(entry.get("price"), 0.0)
            or 0.0
        )

    remaining = entry_qty if entry_filled else 0
    realized = 0.0
    pnl_coverage_complete = True
    last_exit_avg: float | None = None
    for exit_order in sorted(exits, key=_order_rank):
        status = exit_order.get("status")
        # ``filled_qty`` is the durable cumulative broker fact even while the
        # attempt remains working. Recovery must restore that already-settled
        # quantity now: the next event fold compares its cumulative quantity
        # with this same durable row and emits only the additional delta. If we
        # instead restore the pre-attempt owner, that later delta is applied to
        # too much exposure and the run can over-exit on its retry.
        reported = _positive_whole(exit_order.get("filled_qty"))
        if reported is not None:
            applied = min(remaining, reported)
        elif order_is_filled(status):
            requested = _positive_whole(exit_order.get("qty")) or remaining
            applied = min(remaining, requested)
        else:
            applied = 0

        exit_price = _usable_fill_price(exit_order.get("avg_fill_price"))
        if exit_price is None and applied:
            exit_price = _usable_fill_price(exit_order.get("price"))
        if applied:
            remaining -= applied
            last_exit_avg = exit_price or last_exit_avg
            if entry_avg > 0.0 and exit_price is not None:
                sign = 1.0 if leg.get("position") == "B" else -1.0
                realized += (exit_price - entry_avg) * applied * sign
            else:
                pnl_coverage_complete = False

    if working and (not entry_filled or remaining <= 0):
        raise _ManagedRecoveryError(
            f"Leg {key} position {position_ref} has a working exit without a remaining "
            "confirmed owner; broker exposure is ambiguous"
        )

    if entry_filled and remaining > 0:
        status = "open"
        leg["qty"] = remaining
        leg["entry_status"] = "complete"
    elif entry_filled:
        status = "closed"
        leg["qty"] = entry_qty
        leg["entry_status"] = "complete"
    elif order_is_dead(entry_status):
        status = "rejected"
        leg["entry_status"] = entry_status
    else:
        status = "configured"
        leg["entry_status"] = entry_status

    active_exit = working[-1] if working else None
    leg.update(
        {
            "position_ref": position_ref,
            "entry_order_id": entry["id"],
            "entry_avg": entry_avg,
            "exit_order_id": active_exit["id"] if active_exit else None,
            "exit_claim_token": None,
            "exit_kind": active_exit.get("kind") if active_exit else None,
            "exit_avg": last_exit_avg,
            "realized_pnl": realized,
            "realized_pnl_authoritative": pnl_coverage_complete,
            "status": status,
            "mtm": 0.0 if status == "closed" else (_float(cp_leg.get("mtm"), 0.0) or 0.0),
            "superseded": None,
        }
    )
    return _PositionRecovery(
        # Position chronology is the entry chronology. A retry exit for the
        # outgoing side is expected to be newer than the replacement entry;
        # letting that retry rank the owner would swap live and superseded on
        # every restart even though the broker positions did not change.
        rank=max(_order_rank(order) for order in entries),
        leg=leg,
        pnl_coverage_complete=pnl_coverage_complete,
    )


def _checkpoint_for_position(cp_leg: dict[str, Any], position_ref: str | None) -> dict[str, Any]:
    """Checkpoint fields only when they name the exact position incarnation."""
    if not cp_leg:
        return {}
    if cp_leg.get("position_ref") == position_ref:
        return cp_leg
    superseded = cp_leg.get("superseded") or {}
    if superseded.get("position_ref") == position_ref:
        return superseded
    return {}


def _checkpoint_realized_for_recovered_shape(
    cp_leg: dict[str, Any], recovered: dict[str, Any]
) -> tuple[bool, float]:
    """A checkpoint total only when its owner shape proves it saw every fill."""
    if not _checkpoint_observed_recovered_shape(cp_leg, recovered):
        return False, 0.0
    matching = _checkpoint_for_position(cp_leg, recovered.get("position_ref"))
    if "realized_pnl" not in matching:
        return False, 0.0
    realized = _float(matching.get("realized_pnl"))
    if realized is None:
        return False, 0.0
    return True, realized


def _checkpoint_observed_recovered_shape(cp_leg: dict[str, Any], recovered: dict[str, Any]) -> bool:
    """Whether a checkpoint describes the recovered live/outgoing owners exactly."""
    if not cp_leg or cp_leg.get("position_ref") != recovered.get("position_ref"):
        return False
    if str(cp_leg.get("status") or "").lower() != str(recovered.get("status") or "").lower():
        return False
    if _positive_whole(cp_leg.get("qty")) != _positive_whole(recovered.get("qty")):
        return False

    checkpoint_outgoing = cp_leg.get("superseded") or None
    recovered_outgoing = recovered.get("superseded") or None
    if (checkpoint_outgoing is None) != (recovered_outgoing is None):
        return False
    if checkpoint_outgoing is None:
        return True
    return checkpoint_outgoing.get("position_ref") == recovered_outgoing.get(
        "position_ref"
    ) and _positive_whole(checkpoint_outgoing.get("qty")) == _positive_whole(
        recovered_outgoing.get("qty")
    )


def _position_requires_management(leg: dict[str, Any]) -> bool:
    """Whether one recovered incarnation is held or may still become held."""
    return leg.get("status") == "open" or leg.get("entry_status") in ("pending", "open")


def _as_superseded(leg: dict[str, Any]) -> dict[str, Any]:
    """Reduce one held recovered incarnation to the runtime outgoing shape."""
    return {
        "exit_order_id": leg.get("exit_order_id"),
        "exit_claim_token": None,
        "exit_kind": leg.get("exit_kind"),
        "entry_order_id": leg.get("entry_order_id"),
        "position_ref": leg.get("position_ref"),
        "position": leg.get("position"),
        "entry_avg": leg.get("entry_avg"),
        "qty": leg.get("qty"),
    }


def _order_rank(order: dict[str, Any]) -> int:
    """Stable durable order chronology for selecting position incarnations."""
    try:
        return int(order.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def _rebuild_legacy_leg(
    key: str,
    entries: list[dict[str, Any]],
    exits: list[dict[str, Any]],
    cp_leg: dict[str, Any],
    config_leg: dict[str, Any],
) -> dict[str, Any]:
    """One legacy NULL-reference leg using the established decisive heuristic."""
    entry = _decisive(entries)
    exit_order = _decisive(exits)
    identity = entry or exit_order

    # Identity: the order rows, always, when the leg has any.
    if identity is not None:
        leg_id = identity.get("leg_id", key)
        symbol = identity["symbol"]
        exchange = identity["exchange"]
        qty = int(identity.get("qty") or 0)
    elif cp_leg:
        leg_id = cp_leg.get("leg_id", key)
        symbol = cp_leg.get("symbol")
        exchange = cp_leg.get("exchange")
        qty = int(_float(cp_leg.get("qty"), 0.0) or 0)
        logger.warning("Leg %s has no order row; recovering it from the checkpoint alone", leg_id)
    else:
        raise ValueError(f"Leg {key} has neither an order nor a checkpoint to recover from")

    if not symbol or not exchange:
        raise ValueError(f"Leg {leg_id} has no instrument to recover")

    # The side comes from the action that opened the leg, never from the
    # configuration: an ATM offset resolved again names a different strike, and
    # a leg read as the wrong side is evaluated upside down.
    if entry is not None:
        position = _position_from_action(entry["action"])
    else:
        position = _normalise_position(cp_leg.get("position"))

    # Disposition. Orders decide, with one asymmetry: the checkpoint may
    # upgrade a working order to filled, because it is written from the same
    # fill the engine applies to live state and the row may not have caught up.
    # It can never downgrade, so a rejected order stays rejected.
    entry_status = normalise_order_status(entry["status"]) if entry else None
    terminal_partial = bool(
        entry is not None
        and order_is_dead(entry["status"])
        and _positive_whole(entry.get("filled_qty")) is not None
    )
    entry_dead = entry is not None and order_is_dead(entry["status"]) and not terminal_partial
    entry_filled = (
        terminal_partial
        or (entry is not None and order_is_filled(entry["status"]))
        or (not entry_dead and _checkpoint_says_entry_filled(cp_leg))
    )

    if terminal_partial:
        qty = _positive_whole(entry.get("filled_qty")) or qty

    exit_dead = exit_order is not None and order_is_dead(exit_order["status"])
    exit_working = exit_order is not None and order_is_working(exit_order["status"])
    exit_filled = (
        (exit_order is not None and order_is_filled(exit_order["status"]))
        or (exit_working and _checkpoint_says_exit_filled(cp_leg))
        # No order row at all: the checkpoint is the only witness there is.
        or (identity is None and _checkpoint_says_exit_filled(cp_leg))
    )
    reported_exit_qty = _positive_whole(exit_order.get("filled_qty")) if exit_order else None
    if exit_filled:
        applied_exit_qty = min(qty, reported_exit_qty if reported_exit_qty is not None else qty)
    elif exit_dead and reported_exit_qty is not None:
        applied_exit_qty = min(qty, reported_exit_qty)
    else:
        applied_exit_qty = 0
    remaining_qty = max(0, qty - applied_exit_qty)
    exit_applied = applied_exit_qty > 0

    if exit_applied and remaining_qty == 0:
        status = "closed"
    elif entry_filled:
        status = "open"
    elif entry_dead:
        status = "rejected"
    elif identity is None and cp_leg.get("status") == "rejected":
        # No order to judge by: the checkpoint's own verdict stands.
        status = "rejected"
    else:
        # The entry is still working, so the leg holds nothing yet. Left out of
        # open_legs (no rule may exit a position that does not exist) and out
        # of the P&L, but still subscribed, so the fill is priced the moment it
        # lands.
        status = "configured"

    if status == "open" and exit_applied:
        qty = remaining_qty

    entry_avg = 0.0
    if entry_filled:
        entry_avg = (
            _float(entry.get("avg_fill_price") if entry else None)
            or _float(cp_leg.get("entry_avg"))
            or _float(entry.get("price") if entry else None, 0.0)
            or 0.0
        )

    exit_avg = None
    if exit_applied:
        # Guarded the way `entry` is above. An exit can be known filled with no
        # order row at all: the third clause of `exit_filled` reads the
        # checkpoint as the only witness, which is exactly the case where a row
        # was never written.
        exit_avg = (
            _usable_fill_price(exit_order.get("avg_fill_price") if exit_order else None)
            or _usable_fill_price(cp_leg.get("exit_avg"))
            or _usable_fill_price(exit_order.get("price") if exit_order else None)
        )

    # Volatile, from the checkpoint, with a derivation for the one figure the
    # orders can supply on their own: a leg that exited after the last
    # checkpoint has no realized figure recorded anywhere else.
    realized = _float(cp_leg.get("realized_pnl"), 0.0) or 0.0
    if exit_applied and not realized and entry_avg and exit_avg is not None:
        sign = 1.0 if position == "B" else -1.0
        realized = (float(exit_avg) - float(entry_avg)) * applied_exit_qty * sign

    sl_pts, target_pts, trail_x, trail_y, lots = _risk_params(cp_leg, config_leg)

    # Set only while an exit is filled or still working. A dead exit must leave
    # this clear, or the engine's duplicate-exit guard would mistake the failed
    # attempt for one in flight and never retry it.
    if exit_working:
        exit_order_id = exit_order["id"]
        exit_kind = exit_order.get("kind")
    elif exit_filled and remaining_qty == 0:
        exit_order_id = None
        # The checkpoint when there is no row to read it from. `exit_filled` is
        # reachable with `exit_order` None, and reading through it raised
        # AttributeError inside recovery, which finalised the run as
        # recovery_failed rather than rebuilding it.
        exit_kind = exit_order.get("kind") if exit_order else cp_leg.get("exit_kind")
    elif exit_order is not None:
        exit_order_id = None
        exit_kind = None
    else:
        exit_order_id = cp_leg.get("exit_order_id")
        exit_kind = cp_leg.get("exit_kind")

    position_ref = None
    for source in (entry, exit_order, cp_leg):
        if source and source.get("position_ref") is not None:
            position_ref = source.get("position_ref")
            break

    return {
        "leg_id": leg_id,
        "position": position,
        "symbol": symbol,
        "exchange": exchange,
        "lots": lots,
        "qty": qty,
        # Order plumbing
        "position_ref": position_ref,
        "entry_order_id": entry["id"] if entry else cp_leg.get("entry_order_id"),
        "entry_status": _entry_status(entry_status, entry_filled, cp_leg),
        "entry_avg": entry_avg,
        "exit_order_id": exit_order_id,
        "exit_claim_token": None,
        "exit_kind": exit_kind,
        "exit_avg": exit_avg,
        # Live figures
        "ltp": _float(cp_leg.get("ltp")),
        "mtm": 0.0 if status == "closed" else (_float(cp_leg.get("mtm"), 0.0) or 0.0),
        "realized_pnl": realized,
        "realized_pnl_authoritative": bool(
            "realized_pnl" in cp_leg
            and _float(cp_leg.get("realized_pnl")) is not None
            or not exit_applied
            or (entry_avg > 0.0 and exit_avg is not None)
        ),
        "status": status,
        "tick_source": "ws",
        # Risk levels
        "sl_pts": sl_pts,
        "target_pts": target_pts,
        "trail_x": trail_x,
        "trail_y": trail_y,
        "effective_sl": _float(cp_leg.get("effective_sl")),
        "effective_target": _float(cp_leg.get("effective_target")),
        "trail_active": bool(cp_leg.get("trail_active", False)),
        "highest_price": _float(cp_leg.get("highest_price")),
        "lowest_price": _float(cp_leg.get("lowest_price")),
        # Overlapping position groups need separate reconstruction from order
        # history. A single-position recovery still carries the complete live
        # shape so exact-owner helpers have no ambiguous missing key.
        "superseded": None,
    }


def _decisive(orders: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The order that decides a leg's disposition.

    A filled order beats a working one, which beats a dead one, and the newest
    wins within a class. A leg with a rejected attempt followed by an accepted
    one is held by the accepted one; the rejection is history.
    """
    for predicate in (order_is_filled, order_is_working, order_is_dead):
        # list_orders is ascending by placed_at, so the last match is newest.
        chosen = [order for order in orders if predicate(order.get("status"))]
        if chosen:
            return chosen[-1]
    return orders[-1] if orders else None


def _entry_status(order_status: str | None, entry_filled: bool, cp_leg: dict[str, Any]) -> str:
    """The leg's ``entry_status`` field, in the vocabulary ``state`` writes."""
    if entry_filled:
        return "complete"
    if order_status is not None:
        return order_status
    return str(cp_leg.get("entry_status") or "pending")


def _positive_whole(value: Any) -> int | None:
    """A positive whole fill quantity, or None."""
    try:
        qty = int(float(value))
    except (TypeError, ValueError):
        return None
    return qty if qty > 0 else None


def _usable_fill_price(value: Any) -> float | None:
    """A positive finite durable average fill price, or None."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price > 0.0 and math.isfinite(price) else None


def _checkpoint_says_entry_filled(cp_leg: dict[str, Any]) -> bool:
    """Whether the newest checkpoint witnessed this leg's entry filling."""
    if not cp_leg:
        return False
    if str(cp_leg.get("entry_status") or "").strip().lower() == "complete":
        return True
    return cp_leg.get("status") in ("open", "closed") and bool(_float(cp_leg.get("entry_avg"), 0.0))


def _checkpoint_says_exit_filled(cp_leg: dict[str, Any]) -> bool:
    """Whether the newest checkpoint witnessed this leg's exit filling."""
    if not cp_leg:
        return False
    return cp_leg.get("status") == "closed" or cp_leg.get("exit_avg") is not None


def _risk_params(
    cp_leg: dict[str, Any], config_leg: dict[str, Any]
) -> tuple[float | None, float | None, float, float, int]:
    """A leg's configured stop, target, trail and lots.

    The checkpoint first, because it holds the run's own resolved copy, then
    the strategy configuration, which is what a run that crashed before its
    first checkpoint has to fall back on. Without these a recovered leg has no
    stop to re-derive on the next tick.
    """
    trail = config_leg.get("trail") or {}
    config_sl = _float(config_leg.get("sl_pts"))
    config_target = _float(config_leg.get("target_pts"))
    config_trail_x = _float(trail.get("x"), 0.0) or 0.0
    config_trail_y = _float(trail.get("y"), 0.0) or 0.0
    config_lots = int(_float(config_leg.get("lots"), 1.0) or 1)
    return (
        _float(cp_leg.get("sl_pts"), config_sl),
        _float(cp_leg.get("target_pts"), config_target),
        _float(cp_leg.get("trail_x"), config_trail_x) or 0.0,
        _float(cp_leg.get("trail_y"), config_trail_y) or 0.0,
        int(_float(cp_leg.get("lots"), float(config_lots)) or config_lots),
    )


def _config_legs(strategy_id: int) -> dict[str, dict[str, Any]]:
    """The strategy's configured legs, keyed by leg id as a string.

    Unscoped, for the same reason the engine reads a strategy unscoped: there
    is no user in scope at boot, and the run row is the authority on which
    strategy it belongs to.
    """
    try:
        row = store.get_strategy_unscoped(strategy_id)
    except Exception:
        logger.exception("Could not read strategy %s during recovery", strategy_id)
        return {}
    if row is None:
        logger.warning("Strategy %s is gone; recovering its run from orders alone", strategy_id)
        return {}
    legs = row.legs or []
    return {
        str(leg.get("id") or leg.get("leg_id") or index): leg
        for index, leg in enumerate(legs, start=1)
        if isinstance(leg, dict)
    }


# ---------------------------------------------------------------------------
# Finalising
# ---------------------------------------------------------------------------


def _final_pnl(checkpoint: dict[str, Any], rebuilt: dict[str, Any]) -> dict[str, Any]:
    """The figures to close a flat run with.

    Keep checkpoint-only peak/trough figures. Realized P&L comes from the legs
    when every leg has complete durable pricing, including legacy rows with no
    position reference. If any owner remains unpriced or ambiguous, retain the
    authority decision already made by ``_rebuild_state`` instead of inventing
    a complete total.
    """
    final = dict(checkpoint)
    legs = rebuilt.get("legs") or {}
    if all(leg.get("realized_pnl_authoritative", True) for leg in legs.values()):
        final["pnl_realized"] = sum(
            _float(leg.get("realized_pnl"), 0.0) or 0.0 for leg in legs.values()
        )
    else:
        final["pnl_realized"] = _float(rebuilt.get("pnl_realized"), 0.0) or 0.0
    return final


def _strategy_id_for(run_id: int) -> int | None:
    """The strategy a run belongs to, for the failure path. Never raises."""
    try:
        run_row = store.get_run(run_id)
        return run_row.strategy_id if run_row else None
    except Exception:
        logger.exception("Could not read run %s while failing its recovery", run_id)
        return None


def _finalise(
    run_id: int,
    strategy_id: int | None,
    *,
    reason: str,
    kind: str,
    severity: str,
    message: str,
    pnl: dict[str, Any] | None = None,
) -> bool:
    """Close a run, release its strategy, and drop any live state.

    The same order as ``engine._finalise``: the run row, then the strategy,
    then the audit event, then the state. Peak and trough come from the last
    checkpoint, which is the only record of them once the process is gone.
    """
    snapshot = pnl or {}
    if strategy_id is None:
        return False
    won = store.finish_run_and_release_strategy(
        run_id,
        strategy_id,
        stop_reason=reason,
        pnl_realized=_float(snapshot.get("pnl_realized"), 0.0) or 0.0,
        pnl_peak=_float(snapshot.get("pnl_peak"), 0.0) or 0.0,
        pnl_trough=_float(snapshot.get("pnl_trough"), 0.0) or 0.0,
    )
    if not won:
        won = store.finish_empty_unlinked_run_and_release_claim(
            run_id,
            strategy_id,
            stop_reason=reason,
            pnl_realized=_float(snapshot.get("pnl_realized"), 0.0) or 0.0,
            pnl_peak=_float(snapshot.get("pnl_peak"), 0.0) or 0.0,
            pnl_trough=_float(snapshot.get("pnl_trough"), 0.0) or 0.0,
        )
    if not won:
        won = store.finish_detached_run(
            run_id,
            strategy_id,
            stop_reason=reason,
            pnl_realized=_float(snapshot.get("pnl_realized"), 0.0) or 0.0,
            pnl_peak=_float(snapshot.get("pnl_peak"), 0.0) or 0.0,
            pnl_trough=_float(snapshot.get("pnl_trough"), 0.0) or 0.0,
        )
    if not won:
        return False
    _record_event(strategy_id, kind, message, run_id=run_id, severity=severity)
    state.clear_run_state(run_id)
    return True


def _record_event(
    strategy_id: int | None,
    kind: str,
    message: str,
    *,
    run_id: int | None = None,
    severity: str = "info",
) -> None:
    """Append one audit row. Never allowed to break recovery.

    A boot that fell over because it could not write an audit row would leave
    every remaining run unrecovered, which is a far worse outcome than a
    missing line in the trail.
    """
    if strategy_id is None:
        logger.warning("No strategy for run %s; not recording %s", run_id, kind)
        return
    try:
        row = store.get_strategy_unscoped(strategy_id)
        user_id = row.user_id if row else ""
        store.record_event(strategy_id, user_id, kind, message, run_id=run_id, severity=severity)
    except Exception:
        logger.exception("Could not record %s for strategy %s", kind, strategy_id)
