"""The strategy engine: run lifecycle and the tick decision path.

Four entry points, and everything else here supports one of them:

    start_run    resolve every leg, claim the strategy, place entries
    stop_run     exit every open leg and finalise the run
    close_leg    exit one leg; the run continues with the rest
    process_tick evaluate risk against a price and dispatch what it decides

The rules are not here. ``risk_adapter`` translates run state into
``services/risk/`` and back, so this module never decides whether a stop was
hit; it decides what to do about the answer.

Two orderings in here are load bearing and must not be tidied away.

**Locks are released before orders are placed.** A run's lock guards in-memory
bookkeeping only. Placing an order reaches the broker over the network, and a
greenlet holding a lock cannot yield, so dispatching inside the critical
section would stall the single worker for the length of an HTTP call. The tick
path therefore evaluates under the lock, collects what it decided, releases,
and only then dispatches.

**Entries are placed BUY before SELL.** A spread whose short leg is placed
first can be rejected for margin it would have had once the long leg existed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from database import strategy_module_db as store
from services.strategy_module import order_dispatch, risk_adapter, state
from services.strategy_module.symbol_resolver import resolve_leg
from utils.logging import get_logger

logger = get_logger(__name__)


# Which exit reasons make a leg's own stop the cause. Only these trigger the
# trail-to-entry rule, because that rule is a response to the market having
# moved against the book. A manual close is an operator override, not a signal,
# and treating it as one would silently tighten every other leg's stop.
_STOP_DRIVEN_EXITS = frozenset({"exit_sl"})

# Maps a risk decision onto the order kind recorded for the exit it causes.
_EXIT_KIND_FOR_REASON = {
    "sl": "exit_sl",
    "target": "exit_target",
    "combined_sl": "exit_overall_sl",
    "combined_target": "exit_overall_target",
    "lock_profit": "exit_lock_profit",
}

# Which stop reason a run is finalised with, per aggregate breach.
_STOP_REASON_FOR_REASON = {
    "combined_sl": "overall_sl",
    "combined_target": "overall_target",
    "lock_profit": "lock_profit",
}


@dataclass
class StartResult:
    """What a start attempt produced."""

    ok: bool
    run_id: int | None = None
    error: str | None = None
    #: Per-leg outcome, so a caller can say which leg failed and why.
    legs: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _api_key_for(user_id: str) -> str | None:
    """The user's own API key, for server-side order placement."""
    try:
        from database.auth_db import get_api_key_for_tradingview

        return get_api_key_for_tradingview(user_id)
    except Exception:
        logger.exception("Could not read the API key for %s", user_id)
        return None


def _emit(strategy_id: int, user_id: str, kind: str, message: str, **fields: Any) -> None:
    """Record one audit event. Never allowed to break the caller.

    An engine that fell over because it could not write an audit row would turn
    a bookkeeping problem into an open position.
    """
    try:
        row = store.record_event(strategy_id, user_id, kind, message, **fields)
    except Exception:
        logger.exception("Could not record event %s for strategy %s", kind, strategy_id)
        return

    # Push the row that was actually stored, so the live feed and the Events
    # tab show the same thing with the same id rather than two near-copies.
    try:
        from services.strategy_module import broadcast

        if row is not None:
            broadcast.push_event(strategy_id, store.event_to_dict(row))
    except Exception:
        logger.exception("Could not push event %s for strategy %s", kind, strategy_id)


#: Runs whose risk has fired while no broker authorisation was available.
#: Bounded by the number of concurrent runs, and an entry is removed as soon as
#: authorisation returns or the run ends.
_unactionable_runs: set[int] = set()


def _note_unactionable(
    strategy_id: int, user_id: str, run_id: int, leg_exits: list, stop_reason: str | None
) -> None:
    """Record that risk fired and could not be acted on.

    This is the 3 AM window. OpenAlgo revokes broker tokens at the session
    reset because Indian broker tokens expire daily, and until the user logs in
    again there is nothing to place an order with. A positional strategy is
    still holding, and a stop reached in that window cannot be honoured.

    Refusing is correct: pretending to exit would be worse. What was missing is
    that the only record was a log line, so the operator saw a position still
    open past its stop with no explanation anywhere they would look. This
    writes it to the audit trail, at critical, so it reaches the Events tab.

    Recorded once per run per episode rather than per tick, because the tick
    that fired a stop is followed by every tick after it and the trail would be
    unreadable.
    """
    if not (leg_exits or stop_reason):
        return
    if run_id in _unactionable_runs:
        return
    _unactionable_runs.add(run_id)
    logger.warning("Run %s has risk to act on but no broker session; positions left open", run_id)
    _emit(
        strategy_id,
        user_id,
        "leg_exit_rejected",
        "Risk triggered but there is no broker session, so nothing could be exited. "
        "Positions are still open. Log in to restore the session.",
        run_id=run_id,
        severity="critical",
    )


def _note_actionable_again(strategy_id: int, user_id: str, run_id: int) -> None:
    """Record that a run can act again, having previously been unable to."""
    if run_id not in _unactionable_runs:
        return
    _unactionable_runs.discard(run_id)
    _emit(
        strategy_id,
        user_id,
        "recovery_succeeded",
        "Broker session restored; this run can act on its risk rules again.",
        run_id=run_id,
        severity="warn",
    )


def _push_delta(run_id: int, force: bool = False) -> None:
    """Send the run's live figures to any page watching it. Never raises."""
    try:
        from services.strategy_module import broadcast

        broadcast.push_delta(run_id, force=force)
    except Exception:
        logger.exception("Could not push a delta for run %s", run_id)


def _position_to_action(position: str) -> str:
    """A leg's B/S as the action that opens it."""
    return "BUY" if (position or "").upper() == "B" else "SELL"


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------


def start_run(
    strategy_id: int,
    user_id: str,
    mode: str,
    trigger_source: str = "manual",
    webhook_event_id: int | None = None,
) -> StartResult:
    """Start a strategy, or explain why it did not start."""
    strategy_row = store.get_strategy(strategy_id, user_id)
    if not strategy_row:
        return StartResult(ok=False, error="Strategy not found")

    if mode not in store.RUN_MODES:
        return StartResult(ok=False, error=f"Unknown run mode: {mode!r}")

    # Live is opt-in per strategy. Checked here as well as at every caller,
    # because this is the last point before real orders.
    if mode == "live" and not strategy_row.live_enabled:
        return StartResult(
            ok=False,
            error="This strategy is not enabled for live trading. Enable it first.",
        )

    strategy = store.strategy_to_dict(strategy_row)
    api_key = _api_key_for(user_id)
    if not api_key:
        return StartResult(ok=False, error="No API key is configured for this user")

    # Resolve everything before claiming anything. A leg that cannot be
    # resolved must not leave a half-started run behind, and resolution is the
    # step most likely to fail: an expiry that has rolled, a strike outside the
    # chain, a master contract that has not been downloaded.
    resolved, failures = _resolve_all_legs(strategy, api_key)
    if failures:
        return StartResult(ok=False, error=failures[0]["error"], legs=failures)

    # One conditional UPDATE, not a read then a write. The UI, the scheduler
    # and a webhook can all fire at the same instant.
    if not store.claim_strategy_for_run(strategy_id):
        return StartResult(ok=False, error="This strategy is already running")

    run = None
    try:
        run = store.create_run(
            strategy_id=strategy_id,
            mode=mode,
            broker=_broker_for(api_key, mode),
            trigger_source=trigger_source,
            webhook_event_id=webhook_event_id,
            resolved_expiries={
                str(leg["leg_id"]): leg.get("expiry") for leg in resolved if leg.get("expiry")
            },
        )
        if not run:
            store.release_strategy(strategy_id)
            return StartResult(ok=False, error="Could not open a run")

        store.set_strategy_status(strategy_id, "running", run.id)
        state.init_run_state(run.id, strategy_id, resolved)
        # Ask for prices before the entries go out. A fill can be reported
        # within milliseconds, and a leg whose instrument is not subscribed
        # would sit with no price and therefore no stop until the next
        # subscription sweep.
        _subscribe_run(run.id, resolved)
        _emit(
            strategy_id,
            user_id,
            "run_started",
            f"Run started in {mode} mode ({trigger_source})",
            run_id=run.id,
        )

        placed = _place_entries(run.id, strategy, resolved, mode, api_key, user_id)

        # Every leg rejected means there is no position and nothing to manage.
        # Leaving the run open would show a running strategy holding nothing.
        if not any(leg["ok"] for leg in placed):
            _finalise(run.id, strategy_id, user_id, "error", "No entry order was accepted")
            return StartResult(ok=False, error="Every entry order was rejected", legs=placed)

        return StartResult(ok=True, run_id=run.id, legs=placed)
    except Exception:
        logger.exception("Start failed for strategy %s", strategy_id)
        if run is not None:
            _finalise(run.id, strategy_id, user_id, "error", "Start failed")
        else:
            store.release_strategy(strategy_id)
        return StartResult(ok=False, error="Could not start the strategy")


def _subscribe_run(run_id: int, resolved: list[dict[str, Any]]) -> None:
    """Ask the tick feed for this run's instruments.

    Subscriptions are refcounted per run, so two strategies holding the same
    contract share one and it is released when the last one lets go. A failure
    here is logged rather than raised: the run has real positions by this point,
    and refusing to start it because a price feed is unavailable would leave
    them unmanaged rather than merely unpriced.
    """
    try:
        from services.strategy_module.tick_feed import get_risk_tick_feed

        symbols = [(leg["symbol"], leg["exchange"]) for leg in resolved]
        get_risk_tick_feed().add_run_subscriptions(run_id, symbols)
    except Exception:
        logger.exception("Could not subscribe prices for run %s", run_id)


def _unsubscribe_run(run_id: int) -> None:
    """Release this run's price subscriptions."""
    try:
        from services.strategy_module.tick_feed import get_risk_tick_feed

        get_risk_tick_feed().remove_run_subscriptions(run_id)
    except Exception:
        logger.exception("Could not release prices for run %s", run_id)


def _broker_for(api_key: str, mode: str) -> str:
    """The broker a run is bound to, snapshotted at start."""
    if mode == "sandbox":
        return "sandbox"
    try:
        from database.auth_db import get_auth_token_broker

        _token, broker = get_auth_token_broker(api_key)
        return broker or ""
    except Exception:
        logger.exception("Could not read the broker for a live run")
        return ""


def _resolve_all_legs(
    strategy: dict[str, Any], api_key: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve every leg to a contract. Returns ``(resolved, failures)``.

    The underlying is quoted once and reused for every leg. Resolving each leg
    independently would let two legs of one spread settle around different ATM
    strikes, because the underlying moves between the two quotes.
    """
    legs = strategy.get("legs") or []
    if not legs:
        return [], [{"leg_id": None, "ok": False, "error": "The strategy has no legs"}]

    underlying_ltp = None
    resolved: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for index, leg in enumerate(legs, start=1):
        leg_id = leg.get("id") or leg.get("leg_id") or index
        position = (leg.get("position") or "").upper()
        request = dict(leg)
        request["action"] = _position_to_action(position)

        outcome = resolve_leg(
            request,
            strategy["underlying"],
            strategy["underlying_exchange"],
            strategy.get("strategy_type"),
            api_key=api_key,
            underlying_ltp=underlying_ltp,
        )
        if not outcome.ok:
            failures.append(
                {
                    "leg_id": leg_id,
                    "ok": False,
                    "error": f"Leg {leg_id}: {outcome.error}",
                    "code": outcome.code,
                }
            )
            continue

        if underlying_ltp is None:
            underlying_ltp = outcome.underlying_ltp

        resolved.append(
            {
                "leg_id": leg_id,
                "position": position,
                "symbol": outcome.symbol,
                "exchange": outcome.exchange,
                "lots": outcome.lots,
                "quantity": outcome.quantity,
                "expiry": outcome.expiry,
                "sl_pts": leg.get("sl_pts"),
                "target_pts": leg.get("target_pts"),
                "trail": leg.get("trail") or {},
            }
        )

    return resolved, failures


def _place_entries(
    run_id: int,
    strategy: dict[str, Any],
    resolved: list[dict[str, Any]],
    mode: str,
    api_key: str,
    user_id: str,
) -> list[dict[str, Any]]:
    """Place every leg's entry, longs first.

    Buying before selling matters on a spread: the short leg alone can be
    refused for margin the account would have had once the long leg existed.
    """
    ordered = sorted(resolved, key=lambda leg: 0 if leg["position"] == "B" else 1)
    outcomes: list[dict[str, Any]] = []

    for leg in ordered:
        action = _position_to_action(leg["position"])
        order = order_dispatch.build_order(
            symbol=leg["symbol"],
            exchange=leg["exchange"],
            action=action,
            quantity=leg["quantity"],
            product=strategy.get("product", "NRML"),
            strategy_name=strategy.get("name", ""),
            pricetype=strategy.get("pricetype", "MARKET"),
        )
        result = order_dispatch.dispatch_order(mode=mode, api_key=api_key, order=order)

        # Written before the outcome is known, so a run can never hold a
        # position that no row records.
        row = store.record_order(
            run_id,
            leg["leg_id"],
            "entry",
            {
                "symbol": leg["symbol"],
                "exchange": leg["exchange"],
                "action": action,
                "qty": leg["quantity"],
                "pricetype": strategy.get("pricetype", "MARKET"),
                "broker_order_id": result.broker_order_id,
                "status": "open" if result.ok else "rejected",
            },
        )
        if row and not result.ok:
            store.update_order(row.id, reject_reason=result.error)

        with state.run_state(run_id) as run:
            if run is not None:
                leg_state = run["legs"].get(str(leg["leg_id"]))
                if leg_state is not None:
                    leg_state["entry_order_id"] = row.id if row else None
                    leg_state["entry_status"] = "open" if result.ok else "rejected"
                    leg_state["status"] = "open" if result.ok else "rejected"

        _emit(
            strategy["id"],
            user_id,
            "leg_entry_placed" if result.ok else "leg_entry_rejected",
            (
                f"Entry {action} {leg['quantity']} {leg['symbol']} placed"
                if result.ok
                else f"Entry rejected on leg {leg['leg_id']}: {result.error}"
            ),
            run_id=run_id,
            leg_id=leg["leg_id"],
            severity="info" if result.ok else "warn",
        )

        outcomes.append(
            {
                "leg_id": leg["leg_id"],
                "ok": result.ok,
                "symbol": leg["symbol"],
                "broker_order_id": result.broker_order_id,
                "error": result.error,
            }
        )

    return outcomes


# ---------------------------------------------------------------------------
# Fills
# ---------------------------------------------------------------------------


def apply_fill(run_id: int, leg_id: Any, avg_price: float, is_entry: bool) -> bool:
    """Record a fill against a leg. Returns whether the run went flat.

    Entry fills set the price every stop and target is measured from, so a leg
    without one cannot be evaluated. Exit fills lock in the leg's realized P&L
    and close it.

    The read-modify-write is held under the run lock for its whole length. The
    original computes the realized figure and then writes a stale snapshot over
    it from an unlocked path, losing the number it just calculated.

    A run that has gone flat is finalised here, after the lock is released. A
    leg is closed by its fill arriving, not by its exit being placed, so this
    is the only place that knows the last position is actually gone. Without
    it, a strategy whose final leg exited would sit in "running" holding
    nothing until somebody stopped it by hand.
    """
    went_flat = False
    with state.run_state(run_id) as run:
        if run is None:
            return False
        leg = run["legs"].get(str(leg_id))
        if leg is None:
            return False

        if is_entry:
            leg["entry_avg"] = float(avg_price)
            leg["entry_status"] = "complete"
            leg["status"] = "open"
            return False

        leg["exit_avg"] = float(avg_price)
        entry = float(leg.get("entry_avg") or 0.0)
        qty = float(leg.get("qty") or 0.0)
        sign = 1.0 if leg.get("position") == "B" else -1.0
        leg["realized_pnl"] = (float(avg_price) - entry) * qty * sign
        leg["status"] = "closed"
        leg["mtm"] = 0.0

        # Recompute the run totals now, while the lock is held, so the figures
        # finalise writes are the ones this fill produced.
        realized, unrealized = risk_adapter.run_pnl(run)
        run["pnl_realized"] = realized
        run["pnl_unrealized"] = unrealized
        run["pnl_total"] = realized + unrealized
        run["pnl_peak"] = max(run.get("pnl_peak", 0.0), run["pnl_total"])
        run["pnl_trough"] = min(run.get("pnl_trough", 0.0), run["pnl_total"])

        went_flat = not state.open_legs(run)
        strategy_id = run.get("strategy_id")

    if not went_flat:
        return False

    # Outside the lock: finalising reaches the database.
    run_row = store.get_run(run_id)
    if not run_row or run_row.stopped_at is not None:
        return True
    strategy_row = store.get_strategy_unscoped(strategy_id)
    user_id = strategy_row.user_id if strategy_row else ""

    # Only a batch run ends when it goes flat. A batch is a basket entered and
    # exited as a unit, so nothing held means it is finished.
    #
    # A signal run is a trading day, not a basket. A leg exiting is an ordinary
    # mid-session event and the next alert reopens it, so finalising here would
    # end the run on the first round trip: five round trips in a day would
    # produce five runs, fragmenting the P&L, the peak and trough, and the
    # audit trail that is supposed to describe the day. A signal run is closed
    # by the scheduler's square-off, by an explicit stop, or by the session
    # boundary when the next day's first signal arrives.
    if strategy_row is not None and strategy_row.strategy_kind == "signal":
        logger.debug("Run %s is flat but signal-mode; leaving it open for the session", run_id)
        return True

    _finalise(run_id, strategy_id, user_id, "manual", "All legs closed")
    return True


# ---------------------------------------------------------------------------
# Exit
# ---------------------------------------------------------------------------


def _exit_legs(
    run_id: int,
    strategy: dict[str, Any],
    leg_ids: list[Any],
    kind: str,
    mode: str,
    api_key: str,
    user_id: str,
) -> list[dict[str, Any]]:
    """Exit the named legs at market.

    The symbol comes from the leg's own recorded state, never from re-resolving
    the configuration. An ATM offset resolved again hours later can name a
    different strike, and exiting a contract the run does not hold would open a
    new position instead of closing one.
    """
    # Claim each leg under the state lock before anything is dispatched. The
    # guard used to test exit_order_id, which is not written until the order
    # comes back, so two rules firing on one leg both got through.
    targets = [
        claimed
        for leg_id in leg_ids
        if (claimed := state.claim_leg_exit(run_id, leg_id, kind)) is not None
    ]

    # Dispatch outside the lock. See the module docstring.
    outcomes: list[dict[str, Any]] = []
    for leg in targets:
        action = order_dispatch.exit_action(leg["position"])
        order = order_dispatch.build_order(
            symbol=leg["symbol"],
            exchange=leg["exchange"],
            action=action,
            quantity=leg["qty"],
            product=strategy.get("product", "NRML"),
            strategy_name=strategy.get("name", ""),
            pricetype=order_dispatch.EXIT_PRICETYPE,
        )
        result = order_dispatch.dispatch_order(mode=mode, api_key=api_key, order=order)

        row = store.record_order(
            run_id,
            leg["leg_id"],
            kind,
            {
                "symbol": leg["symbol"],
                "exchange": leg["exchange"],
                "action": action,
                "qty": leg["qty"],
                "pricetype": order_dispatch.EXIT_PRICETYPE,
                "broker_order_id": result.broker_order_id,
                "status": "open" if result.ok else "rejected",
            },
        )
        if row and not result.ok:
            store.update_order(row.id, reject_reason=result.error)

        if result.ok:
            with state.run_state(run_id) as run:
                live = run["legs"].get(str(leg["leg_id"])) if run else None
                if live is not None:
                    live["exit_order_id"] = row.id if row else None
        else:
            # Release the claim so a later attempt is not mistaken for a
            # duplicate and skipped for the rest of the session.
            state.release_leg_exit(run_id, leg["leg_id"])

        _emit(
            strategy["id"],
            user_id,
            "leg_exit_placed" if result.ok else "leg_exit_rejected",
            (
                f"Exit {action} {leg['qty']} {leg['symbol']} placed ({kind})"
                if result.ok
                else f"Exit rejected on leg {leg['leg_id']}: {result.error}"
            ),
            run_id=run_id,
            leg_id=leg["leg_id"],
            severity="info" if result.ok else "critical",
        )

        outcomes.append({"leg_id": leg["leg_id"], "ok": result.ok, "error": result.error})

    return outcomes


def stop_run(run_id: int, user_id: str, reason: str = "manual") -> dict[str, Any]:
    """Exit every open leg and finalise the run."""
    run_row = store.get_run(run_id)
    if not run_row or run_row.stopped_at is not None:
        return {"ok": False, "error": "Run is not active"}

    strategy_row = store.get_strategy(run_row.strategy_id, user_id)
    if not strategy_row:
        return {"ok": False, "error": "Strategy not found"}
    strategy = store.strategy_to_dict(strategy_row)

    api_key = _api_key_for(user_id)
    if not api_key:
        return {"ok": False, "error": "No API key is configured for this user"}

    with state.run_state(run_id) as run:
        open_ids = [leg["leg_id"] for leg in state.open_legs(run)] if run else []

    kind = "exit_close_all" if reason == "manual" else f"exit_{reason}"
    if kind not in store.ORDER_KINDS:
        kind = "exit_close_all"

    exits = _exit_legs(run_id, strategy, open_ids, kind, run_row.mode, api_key, user_id)
    _finalise(run_id, run_row.strategy_id, user_id, reason, f"Run stopped ({reason})")
    return {"ok": True, "exits": exits}


def close_leg(run_id: int, leg_id: Any, user_id: str) -> dict[str, Any]:
    """Exit one leg. The run continues with the rest.

    Deliberately does not trigger trail-to-entry. That rule answers the market
    moving against the book; an operator closing a leg by hand is an override,
    and treating it as a signal would tighten every other leg's stop without
    being asked.
    """
    run_row = store.get_run(run_id)
    if not run_row or run_row.stopped_at is not None:
        return {"ok": False, "error": "Run is not active"}

    strategy_row = store.get_strategy(run_row.strategy_id, user_id)
    if not strategy_row:
        return {"ok": False, "error": "Strategy not found"}
    strategy = store.strategy_to_dict(strategy_row)

    api_key = _api_key_for(user_id)
    if not api_key:
        return {"ok": False, "error": "No API key is configured for this user"}

    exits = _exit_legs(
        run_id, strategy, [leg_id], "exit_leg_manual", run_row.mode, api_key, user_id
    )
    if not exits:
        return {"ok": False, "error": "That leg is not open"}

    _emit(
        run_row.strategy_id,
        user_id,
        "leg_close_manual",
        f"Leg {leg_id} closed manually",
        run_id=run_id,
        leg_id=leg_id,
    )

    # Closing the last open leg leaves a running strategy holding nothing.
    with state.run_state(run_id) as run:
        still_open = bool(state.open_legs(run)) if run else False
    if not still_open:
        _finalise(run_id, run_row.strategy_id, user_id, "manual", "All legs closed")
        return {"ok": True, "exits": exits, "run_stopped": True}

    return {"ok": True, "exits": exits, "run_stopped": False}


def _finalise(run_id: int, strategy_id: int, user_id: str, reason: str, message: str) -> None:
    """Close the run row, release the strategy, and drop the live state.

    Peak and trough are read out of the live state and written on every path.
    The original passes them on only one of its several stop paths, so a run
    closed by an overall stop, a target, a lock-profit floor, the scheduler or
    the kill switch recorded both as zero.
    """
    snapshot = state.get_run_state(run_id) or {}
    try:
        store.finish_run(
            run_id,
            stop_reason=reason,
            pnl_realized=snapshot.get("pnl_realized", 0.0) or 0.0,
            pnl_peak=snapshot.get("pnl_peak", 0.0) or 0.0,
            pnl_trough=snapshot.get("pnl_trough", 0.0) or 0.0,
        )
        store.release_strategy(strategy_id)
        _emit(strategy_id, user_id, "run_stopped", message, run_id=run_id)
    finally:
        # The final figures, forced past the throttle: without it the page is
        # left frozen one tick short of the truth for the rest of the day.
        # Both happen before clear_run_state, which is what the payloads read.
        _push_delta(run_id, force=True)
        try:
            from services.strategy_module import broadcast

            broadcast.push_terminal(
                strategy_id, run_id, reason, snapshot.get("pnl_realized", 0.0) or 0.0
            )
        except Exception:
            logger.exception("Could not push the terminal frame for run %s", run_id)

        _unactionable_runs.discard(run_id)
        # Unconditional. If anything above threw, the run's state and its lock
        # would otherwise stay in the registries for the life of the worker,
        # and the strategy would be stuck reading as running with nothing
        # managing it.
        _unsubscribe_run(run_id)
        state.clear_run_state(run_id)

    # Arm the webhook cooling-off window for every stop, not just the ones a
    # webhook asked for. A strategy stopped by its own risk rules, by the
    # scheduler or by the kill switch would otherwise accept a stale alert a
    # second later and re-enter the position it just closed.
    try:
        from services.strategy_module.webhook import note_run_stopped

        note_run_stopped(strategy_id)
    except Exception:
        logger.exception("Could not arm the webhook cooling-off for strategy %s", strategy_id)


# ---------------------------------------------------------------------------
# Tick path
# ---------------------------------------------------------------------------


def process_tick(symbol: str, exchange: str, ltp: float) -> None:
    """Evaluate every run holding this instrument against one price.

    Runs are found by scanning the live states rather than by keeping a second
    symbol index. A deployment has a handful of concurrent runs, so the scan is
    cheap, and an index that drifts out of step with the state it describes is
    a class of bug worth not having.
    """
    for run_id in state.active_run_ids():
        try:
            _process_tick_for_run(run_id, symbol, exchange, ltp)
        except Exception:
            # One run's failure must not stop the others being evaluated.
            logger.exception("Tick processing failed for run %s", run_id)


def _process_tick_for_run(run_id: int, symbol: str, exchange: str, ltp: float) -> None:
    run_row = store.get_run(run_id)
    if not run_row or run_row.stopped_at is not None:
        return
    # Unscoped on purpose: the engine reaches a strategy through a run it is
    # already executing, so there is no user in scope to filter by and the run
    # row is the authority on which strategy it belongs to.
    strategy_row = store.get_strategy_unscoped(run_row.strategy_id)
    if not strategy_row:
        return
    strategy = store.strategy_to_dict(strategy_row)
    user_id = strategy_row.user_id

    leg_exits: list[tuple[Any, str]] = []
    stop_reason: str | None = None
    events: list[tuple[str, str, dict]] = []

    # Everything inside this block is in-memory arithmetic. No order is placed,
    # no broker is called, nothing is emitted.
    with state.run_state(run_id) as run:
        if run is None:
            return

        for leg in state.legs_for_symbol(run, symbol, exchange):
            decision = risk_adapter.evaluate_leg(leg, ltp)
            if decision.trail_armed:
                events.append(
                    (
                        "leg_trail_armed",
                        f"Trailing stop armed on leg {leg['leg_id']} at {decision.stop_price}",
                        {"leg_id": leg["leg_id"]},
                    )
                )
            if decision.breached and decision.reason in _EXIT_KIND_FOR_REASON:
                kind = _EXIT_KIND_FOR_REASON[decision.reason]
                leg_exits.append((leg["leg_id"], kind))
                events.append(
                    (
                        "leg_sl_hit" if decision.reason == "sl" else "leg_target_hit",
                        decision.detail,
                        {"leg_id": leg["leg_id"], "severity": "warn"},
                    )
                )

        # Trail to entry, when a stop fired and the strategy asks for it.
        if strategy.get("trail_sl_to_entry"):
            for leg_id, kind in leg_exits:
                if kind in _STOP_DRIVEN_EXITS:
                    moved = risk_adapter.trail_open_legs_to_entry(run, leg_id)
                    if moved:
                        events.append(
                            (
                                "trail_to_entry_activated",
                                f"Stop on leg {leg_id} moved {len(moved)} other legs to entry",
                                {"severity": "warn"},
                            )
                        )
                    break

        aggregate = risk_adapter.evaluate_run(run, strategy)
        if aggregate.lock_armed_now:
            events.append(
                (
                    "lock_profit_armed",
                    f"Lock profit armed with a floor of {aggregate.lock_floor}",
                    {},
                )
            )
        elif aggregate.lock_floor_raised:
            events.append(
                (
                    "lock_profit_floor_advanced",
                    f"Lock profit floor advanced to {aggregate.lock_floor}",
                    {},
                )
            )

        if aggregate.breached and aggregate.reason in _STOP_REASON_FOR_REASON:
            stop_reason = _STOP_REASON_FOR_REASON[aggregate.reason]
            events.append(
                (
                    {
                        "overall_sl": "overall_sl_hit",
                        "overall_target": "overall_target_hit",
                        "lock_profit": "lock_profit_triggered",
                    }[stop_reason],
                    aggregate.detail,
                    {"severity": "warn"},
                )
            )

    # Lock released. Everything below reaches the database or the broker.
    _push_delta(run_id)

    for kind, message, extra in events:
        severity = extra.pop("severity", "info")
        _emit(strategy["id"], user_id, kind, message, run_id=run_id, severity=severity, **extra)

    api_key = _api_key_for(user_id)
    if not api_key:
        _note_unactionable(strategy["id"], user_id, run_id, leg_exits, stop_reason)
        return

    _note_actionable_again(strategy["id"], user_id, run_id)

    if stop_reason:
        # A strategy-level breach closes everything, so the per-leg exits it
        # would also have triggered are redundant.
        stop_run(run_id, user_id, reason=stop_reason)
        return

    for leg_id, kind in leg_exits:
        _exit_legs(run_id, strategy, [leg_id], kind, run_row.mode, api_key, user_id)

    with state.run_state(run_id) as run:
        still_open = bool(state.open_legs(run)) if run else False
    if leg_exits and not still_open:
        _finalise(run_id, strategy["id"], user_id, "manual", "All legs closed by rule")
