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

**One bad run cannot wedge the boot.** A run that cannot be rebuilt is closed
with ``stop_reason="recovery_failed"`` and a critical event, so the operator is
told and the next start is not blocked. That deliberately abandons a position
that may still be open at the broker: saying so loudly is recoverable, and
refusing to boot is not.

Nothing here imports the tick feed. :func:`recover_all` returns the
``(symbol, exchange)`` pairs each recovered run still needs prices for, and the
caller subscribes them.
"""

from __future__ import annotations

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
    except Exception as exc:
        logger.exception("Could not recover run %s", run_id)
        strategy_id = _strategy_id_for(run_id)
        _finalise(
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
            finalised=True,
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
    strategy_id = run_row.strategy_id
    if run_row.stopped_at is not None:
        logger.debug("Run %s is already stopped; nothing to recover", run_id)
        return RecoveredRun(
            run_id=run_id, strategy_id=strategy_id, ok=False, error="Run is already stopped"
        )

    orders = store.list_orders(run_id)
    checkpoint = store.latest_checkpoint(run_id) or {}
    config_legs = _config_legs(strategy_id)

    rebuilt = _rebuild_state(run_id, strategy_id, orders, checkpoint, config_legs)
    symbols = state.subscribed_symbols(rebuilt)
    open_count = len(state.open_legs(rebuilt))

    if not symbols:
        # Every leg is closed or was refused, so the run holds nothing. It was
        # never finalised because the process died between the last exit fill
        # and the finalise that fill would have triggered. Resuming it would
        # leave a strategy reading as running while holding nothing, which is
        # exactly the state engine._finalise exists to prevent, and no tick
        # would ever arrive to close it.
        _finalise(
            run_id,
            strategy_id,
            reason="manual",
            kind="recovery_succeeded",
            severity="info",
            message="Recovered flat: every leg had already closed, so the run was finished",
            pnl=_final_pnl(checkpoint, rebuilt),
        )
        logger.info("Run %s recovered flat and was finished", run_id)
        return RecoveredRun(
            run_id=run_id,
            strategy_id=strategy_id,
            ok=False,
            finalised=True,
            legs=len(rebuilt["legs"]),
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
    return {
        "run_id": run_id,
        "strategy_id": strategy_id,
        "pnl_realized": _float(checkpoint.get("pnl_realized"), 0.0) or 0.0,
        "pnl_unrealized": _float(checkpoint.get("pnl_unrealized"), 0.0) or 0.0,
        "pnl_total": _float(checkpoint.get("pnl_total"), 0.0) or 0.0,
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
        "legs": legs,
    }


def _rebuild_leg(
    key: str,
    entries: list[dict[str, Any]],
    exits: list[dict[str, Any]],
    cp_leg: dict[str, Any],
    config_leg: dict[str, Any],
) -> dict[str, Any]:
    """One leg's state, from its orders, its checkpoint and its configuration."""
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
    entry_dead = entry is not None and order_is_dead(entry["status"])
    entry_filled = (entry is not None and order_is_filled(entry["status"])) or (
        not entry_dead and _checkpoint_says_entry_filled(cp_leg)
    )

    exit_dead = exit_order is not None and order_is_dead(exit_order["status"])
    exit_live = exit_order is not None and not exit_dead
    exit_filled = (
        (exit_order is not None and order_is_filled(exit_order["status"]))
        or (exit_live and _checkpoint_says_exit_filled(cp_leg))
        # No order row at all: the checkpoint is the only witness there is.
        or (identity is None and _checkpoint_says_exit_filled(cp_leg))
    )

    if exit_filled:
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

    entry_avg = 0.0
    if entry_filled:
        entry_avg = (
            _float(entry.get("avg_fill_price") if entry else None)
            or _float(cp_leg.get("entry_avg"))
            or _float(entry.get("price") if entry else None, 0.0)
            or 0.0
        )

    exit_avg = None
    if exit_filled:
        exit_avg = (
            _float(exit_order.get("avg_fill_price"))
            or _float(cp_leg.get("exit_avg"))
            or _float(exit_order.get("price"))
        )

    # Volatile, from the checkpoint, with a derivation for the one figure the
    # orders can supply on their own: a leg that exited after the last
    # checkpoint has no realized figure recorded anywhere else.
    realized = 0.0
    if status == "closed":
        realized = _float(cp_leg.get("realized_pnl"), 0.0) or 0.0
        if not realized and entry_avg and exit_avg is not None:
            sign = 1.0 if position == "B" else -1.0
            realized = (float(exit_avg) - float(entry_avg)) * qty * sign

    sl_pts, target_pts, trail_x, trail_y, lots = _risk_params(cp_leg, config_leg)

    # Set only while an exit is filled or still working. A dead exit must leave
    # this clear, or the engine's duplicate-exit guard would mistake the failed
    # attempt for one in flight and never retry it.
    if exit_live:
        exit_order_id = exit_order["id"]
        exit_kind = exit_order.get("kind")
    elif exit_order is not None:
        exit_order_id = None
        exit_kind = None
    else:
        exit_order_id = cp_leg.get("exit_order_id")
        exit_kind = cp_leg.get("exit_kind")

    return {
        "leg_id": leg_id,
        "position": position,
        "symbol": symbol,
        "exchange": exchange,
        "lots": lots,
        "qty": qty,
        # Order plumbing
        "entry_order_id": entry["id"] if entry else cp_leg.get("entry_order_id"),
        "entry_status": _entry_status(entry_status, entry_filled, cp_leg),
        "entry_avg": entry_avg,
        "exit_order_id": exit_order_id,
        "exit_kind": exit_kind,
        "exit_avg": exit_avg,
        # Live figures
        "ltp": _float(cp_leg.get("ltp")),
        "mtm": 0.0 if status == "closed" else (_float(cp_leg.get("mtm"), 0.0) or 0.0),
        "realized_pnl": realized,
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
    if cp_leg:
        return (
            _float(cp_leg.get("sl_pts")),
            _float(cp_leg.get("target_pts")),
            _float(cp_leg.get("trail_x"), 0.0) or 0.0,
            _float(cp_leg.get("trail_y"), 0.0) or 0.0,
            int(_float(cp_leg.get("lots"), 1.0) or 1),
        )
    trail = config_leg.get("trail") or {}
    return (
        _float(config_leg.get("sl_pts")),
        _float(config_leg.get("target_pts")),
        _float(trail.get("x"), 0.0) or 0.0,
        _float(trail.get("y"), 0.0) or 0.0,
        int(_float(config_leg.get("lots"), 1.0) or 1),
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

    The last checkpoint, except for the realized total: a run goes flat on its
    final exit fill, which is very often what the process died before
    checkpointing, so a zero there is re-derived from the legs themselves.
    """
    final = dict(checkpoint)
    if not _float(final.get("pnl_realized"), 0.0):
        final["pnl_realized"] = sum(
            _float(leg.get("realized_pnl"), 0.0) or 0.0 for leg in rebuilt["legs"].values()
        )
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
) -> None:
    """Close a run, release its strategy, and drop any live state.

    The same order as ``engine._finalise``: the run row, then the strategy,
    then the audit event, then the state. Peak and trough come from the last
    checkpoint, which is the only record of them once the process is gone.
    """
    snapshot = pnl or {}
    try:
        store.finish_run(
            run_id,
            stop_reason=reason,
            pnl_realized=_float(snapshot.get("pnl_realized"), 0.0) or 0.0,
            pnl_peak=_float(snapshot.get("pnl_peak"), 0.0) or 0.0,
            pnl_trough=_float(snapshot.get("pnl_trough"), 0.0) or 0.0,
        )
        if strategy_id is not None:
            store.release_strategy(strategy_id)
    except Exception:
        logger.exception("Could not finalise run %s during recovery", run_id)

    _record_event(strategy_id, kind, message, run_id=run_id, severity=severity)
    state.clear_run_state(run_id)


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
