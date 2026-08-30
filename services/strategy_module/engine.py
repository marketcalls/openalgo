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
from services.strategy_module import order_dispatch, risk_adapter, session, state
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
                # The chain did not list the rank that was asked for, so a
                # nearer expiry was used. Carried out of the resolver so the
                # run can say so: next_week silently becoming the current week
                # is a different trade from the one that was configured, and
                # nothing recorded it anywhere.
                "expiry_fallback": bool((outcome.detail or {}).get("expiry_fallback")),
                "expiry_rank": (outcome.detail or {}).get("expiry_rank"),
                "sl_pts": leg.get("sl_pts"),
                "target_pts": leg.get("target_pts"),
                "trail": leg.get("trail") or {},
            }
        )

    return resolved, failures


def _record_acknowledgement(
    row_id: int,
    result: Any,
    strategy_id: int,
    user_id: str,
    run_id: int,
    leg_id: Any,
) -> bool:
    """Write what the broker answered onto the order row. Says whether it stuck.

    update_order swallows its own failure and returns False, and ignoring that
    is how a position ends up unattributable: the row stays "pending" with no
    broker order id, so no fill can ever be matched to it, the leg is never
    seeded, and nothing evaluates a stop for a position that exists. The
    in-memory replay buffer does not cover this, because the id it would match
    on is exactly what was lost.

    Retried once, since the common failure is a transient write lock rather
    than a broken statement. If it still will not persist, the broker order id
    is put somewhere durable the operator can find, which is the event log, at
    critical severity: the position is real and now has to be reconciled by
    hand.
    """
    fields = {
        "status": "open" if result.ok else "rejected",
        "broker_order_id": result.broker_order_id,
        "reject_reason": None if result.ok else result.error,
    }
    if store.update_order(row_id, **fields) or store.update_order(row_id, **fields):
        return True

    logger.error(
        "Could not record the broker acknowledgement for order row %s (broker id %s)",
        row_id,
        result.broker_order_id,
    )
    if result.ok:
        _emit(
            strategy_id,
            user_id,
            "order_ack_unrecorded",
            (
                f"Broker order {result.broker_order_id} was accepted for leg {leg_id} but its "
                f"acknowledgement could not be written to order row {row_id}. The position "
                "exists and is not attributable from the database; reconcile it by hand."
            ),
            run_id=run_id,
            leg_id=leg_id,
            severity="critical",
        )
    return False


def _replay_order_update(broker_order_id: str | None) -> None:
    """Let the fill that arrived before this row existed be applied now.

    Imported here rather than at module scope: order_events imports the engine
    to apply a fill, so binding it the other way round at import time would be
    circular.
    """
    if not broker_order_id:
        return
    try:
        from services.strategy_module import order_events

        order_events.replay_for(broker_order_id)
    except Exception:
        logger.exception("Could not replay a held order update for %s", broker_order_id)


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
        if leg.get("expiry_fallback"):
            # Said out loud, on the run, before the order goes out. The
            # resolver computes this and the engine used to drop it, so a
            # next_week leg quietly trading the current week left no record at
            # all: not an event, not a run row, not the leg state.
            _emit(
                strategy["id"],
                user_id,
                "leg_expiry_fallback",
                (
                    f"Leg {leg['leg_id']} asked for the {leg.get('expiry_rank')} expiry; "
                    f"the chain lists only {leg.get('expiry')}, which was used"
                ),
                run_id=run_id,
                leg_id=leg["leg_id"],
                severity="warn",
            )

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
        # The intent is durable BEFORE the broker is called, not after. It used
        # to be recorded from the dispatch result, which meant a crash or a
        # database failure in the window between broker acceptance and the
        # insert left a real position that no row described: invisible to the
        # operator, to recovery and to every later exit. The row carries no
        # broker id yet, because there is not one yet.
        row = store.record_order(
            run_id,
            leg["leg_id"],
            "entry",
            {
                "symbol": leg["symbol"],
                "exchange": leg["exchange"],
                "action": action,
                "qty": leg["quantity"],
                # From the order, not from the strategy: build_order
                # translates the product to the venue, so these can differ.
                "product": order.get("product"),
                "pricetype": strategy.get("pricetype", "MARKET"),
                "status": "pending",
            },
        )
        if row is None:
            # An entry that cannot be recorded is an entry that cannot be
            # managed, so it is not placed. Refusing costs one leg; placing it
            # blind costs a position with no stop and no way to find it. Exits
            # take the opposite decision, deliberately: see _exit_legs.
            _emit(
                strategy["id"],
                user_id,
                "leg_entry_rejected",
                f"Entry for leg {leg['leg_id']} not placed: its order row could not be written",
                run_id=run_id,
                leg_id=leg["leg_id"],
                severity="critical",
            )
            outcomes.append(
                {
                    "leg_id": leg["leg_id"],
                    "ok": False,
                    "symbol": leg["symbol"],
                    "broker_order_id": None,
                    "error": "Could not record the order before placing it",
                }
            )
            continue

        # The id, not the instance. Dispatch runs arbitrary code between here
        # and the update: the sandbox executes and publishes the fill inline,
        # and the handler for that clears its scoped session, which detaches
        # any ORM object still being held across the call.
        row_id = row.id

        result = order_dispatch.dispatch_order(mode=mode, api_key=api_key, order=order)

        acknowledged = _record_acknowledgement(
            row_id, result, strategy["id"], user_id, run_id, leg["leg_id"]
        )

        with state.run_state(run_id) as run:
            if run is not None:
                leg_state = run["legs"].get(str(leg["leg_id"]))
                if leg_state is not None:
                    leg_state["entry_order_id"] = row_id
                    leg_state["entry_status"] = "open" if result.ok else "rejected"
                    leg_state["status"] = "open" if result.ok else "rejected"

        # After the leg's own bookkeeping, never before it: the sandbox fills a
        # MARKET order inside the dispatch above, so the fill was published
        # before this row existed and was held rather than applied. Replaying it
        # first would have the block above write "open" back over the fill it
        # had just recorded.
        if row_id is not None and result.ok:
            _replay_order_update(result.broker_order_id)

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
                # False when the broker accepted the order but its
                # acknowledgement could not be persisted, so the caller can see
                # that this leg is live without being attributable from the
                # database. The position is real either way.
                "acknowledged": acknowledged,
            }
        )

    return outcomes


# ---------------------------------------------------------------------------
# Fills
# ---------------------------------------------------------------------------


def apply_fill(
    run_id: int,
    leg_id: Any,
    avg_price: float,
    is_entry: bool,
    filled_qty: int | None = None,
    order_row_id: int | None = None,
) -> bool:
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
            # The run has already finalised, which is the ordinary case for
            # the exit fills of a stop: stop_run places them and closes the run
            # without waiting, because the position is on its way out. The
            # figure it wrote was whatever live state held at that instant,
            # which is zero. Reconcile it from the order rows so the fill that
            # arrives afterwards is not simply dropped.
            if not is_entry:
                store.reconcile_run_pnl(run_id)
            return False
        leg = run["legs"].get(str(leg_id))
        if leg is None:
            return False

        # A signal leg is flipped by squaring the held side and opening the
        # other immediately, so until the closing order fills this leg id names
        # two positions. Settle the outgoing one from what add_leg kept, and
        # leave the position that is now live untouched.
        superseded = leg.get("superseded")
        settles_superseded = bool(
            not is_entry
            and superseded
            and (
                superseded.get("exit_order_id") == order_row_id
                # No order id to match on: this is an internal caller rather
                # than the order stream. An exit fill can only belong to the
                # outgoing position when the live one has no exit in flight.
                or (order_row_id is None and leg.get("exit_order_id") is None)
            )
        )
        if settles_superseded:
            entry = float(superseded.get("entry_avg") or 0.0)
            qty = float(superseded.get("qty") or 0.0)
            sign = 1.0 if superseded.get("position") == "B" else -1.0
            if entry > 0.0:
                leg["realized_pnl"] = float(leg.get("realized_pnl") or 0.0) + (
                    (float(avg_price) - entry) * qty * sign
                )
            leg["superseded"] = None
            realized, unrealized = risk_adapter.run_pnl(run)
            run["pnl_realized"] = realized
            run["pnl_unrealized"] = unrealized
            run["pnl_total"] = realized + unrealized
            return False

        # A fill that names an order this leg is not waiting on belongs to an
        # incarnation that has already been replaced. Applying it would close
        # or re-price the position that is live now.
        if order_row_id is not None:
            expected = leg.get("entry_order_id") if is_entry else leg.get("exit_order_id")
            if expected is not None and expected != order_row_id:
                logger.warning(
                    "Ignoring a fill for order %s on leg %s: the leg is waiting on %s",
                    order_row_id,
                    leg_id,
                    expected,
                )
                return False

        if (
            not is_entry
            and order_row_id is not None
            and leg.get("exit_kind") is None
            and leg.get("exit_order_id") is None
        ):
            # A fill from the order stream naming an exit this leg never placed
            # cannot be closing the position that is live now. Closing anyway
            # is how a flip's squaring order used to close the position it had
            # just opened, leaving a live short invisible to open_legs: no stop
            # evaluated, no square-off reaching it, and the broker still
            # holding it. exit_kind rather than exit_order_id, because a
            # successful exit whose audit row could not be written has the
            # first and not the second.
            logger.warning(
                "Ignoring exit fill for order %s on leg %s: it has no exit in flight",
                order_row_id,
                leg_id,
            )
            return False

        if is_entry:
            leg["entry_avg"] = float(avg_price)
            # Reconcile the size with what actually traded. A partial fill
            # whose remainder was cancelled is ordinary on an illiquid strike,
            # and the leg used to keep the size it asked for: every later exit
            # was then for the full amount, so squaring off a 25 that filled
            # out of a 75 requested sent a 75 the other way and left the
            # account holding 50 of a contract nobody chose, with no stop.
            if filled_qty is not None and filled_qty != leg.get("qty"):
                logger.warning(
                    "Leg %s on run %s filled %s of %s; managing the filled size",
                    leg_id,
                    run_id,
                    filled_qty,
                    leg.get("qty"),
                )
                leg["qty"] = filled_qty
            leg["entry_status"] = "complete"
            leg["status"] = "open"
            return False

        leg["exit_avg"] = float(avg_price)
        entry = float(leg.get("entry_avg") or 0.0)
        qty = float(leg.get("qty") or 0.0)
        sign = 1.0 if leg.get("position") == "B" else -1.0
        if entry > 0.0:
            leg["realized_pnl"] = (float(avg_price) - entry) * qty * sign
        else:
            # An entry price of zero means the leg never traded, so there is no
            # round trip to book. Deriving from it books the entire notional as
            # profit or loss: an exit at 90 on 75 units used to record 6750 the
            # account never made, and that figure is what the combined stop,
            # the combined target and the lock-profit floor are judged against.
            logger.warning(
                "Leg %s on run %s exited with no entry price; booking no realized P&L",
                leg_id,
                run_id,
            )
            leg["realized_pnl"] = 0.0
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
    # Claimed and classified in one hold of the run lock. Legs the broker
    # accepted but has not filled cannot be squared off: there is no confirmed
    # quantity to close, and sending the configured size the other way would be
    # a naked position if that entry later cancels. They are reported as
    # refusals rather than silently skipped, so stop_run keeps the run open and
    # managed and the stop can be retried once the fill arrives.
    #
    # Doing this in two passes left a window a fill could land in, and a leg
    # that filled inside it appeared in neither list: the run then finalised
    # with the position still open.
    targets, unfilled_legs = state.claim_legs_for_exit(run_id, leg_ids, kind)
    unfilled = [
        {
            "leg_id": leg["leg_id"],
            "ok": False,
            "symbol": leg.get("symbol"),
            "broker_order_id": None,
            "error": (
                "The entry for this leg has been accepted but not filled, so there "
                "is no confirmed quantity to exit. Retry once it fills."
            ),
        }
        for leg in unfilled_legs
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
        # Recorded before dispatch, as entries are, so an exit that reaches the
        # broker is never invisible afterwards.
        row = store.record_order(
            run_id,
            leg["leg_id"],
            kind,
            {
                "symbol": leg["symbol"],
                "exchange": leg["exchange"],
                "action": action,
                "qty": leg["qty"],
                "product": order.get("product"),
                "pricetype": order_dispatch.EXIT_PRICETYPE,
                "status": "pending",
            },
        )
        if row is None:
            # The opposite decision to an entry, and deliberately so. An entry
            # that cannot be recorded is not placed, because the cost of
            # refusing is one leg not opened. An exit that cannot be recorded
            # is placed anyway, because the cost of refusing is a position that
            # stays open with a database outage between it and every attempt to
            # close it. Getting flat wins; the audit row is what is lost.
            _emit(
                strategy["id"],
                user_id,
                "leg_exit_placed",
                (
                    f"Exit for leg {leg['leg_id']} is being placed without an order row: "
                    "it could not be written"
                ),
                run_id=run_id,
                leg_id=leg["leg_id"],
                severity="critical",
            )

        # See the note in _place_entries: the id survives the dispatch, the
        # instance may not.
        row_id = row.id if row is not None else None

        result = order_dispatch.dispatch_order(mode=mode, api_key=api_key, order=order)

        if row_id is not None:
            _record_acknowledgement(row_id, result, strategy["id"], user_id, run_id, leg["leg_id"])

        if result.ok:
            with state.run_state(run_id) as run:
                live = run["legs"].get(str(leg["leg_id"])) if run else None
                if live is not None:
                    live["exit_order_id"] = row_id
            if row_id is not None:
                # See the note in _place_entries: after the bookkeeping.
                _replay_order_update(result.broker_order_id)
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

    return outcomes + unfilled


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

    # A run whose exits the broker refused is still holding those positions.
    # Finalising here would write stopped_at, release the strategy, drop the
    # live state and unsubscribe the prices, so the position would sit open for
    # the rest of the session with nothing evaluating its stop while the
    # dashboard read "stopped". A broker rate limit or a momentary auth failure
    # at 15:20 is enough to reach this, so it stays open and says why.
    refused = [outcome for outcome in exits if not outcome.get("ok")]
    if refused:
        with state.run_state(run_id) as run:
            still_held = bool(state.open_legs(run)) if run else False
        if still_held:
            _emit(
                run_row.strategy_id,
                user_id,
                "run_stop_failed",
                f"Stop refused for {len(refused)} leg(s); the run is still holding them",
                run_id=run_id,
                severity="critical",
            )
            return {
                "ok": False,
                "error": (
                    f"{len(refused)} of {len(exits)} exit order(s) were refused. "
                    "The run is still open and still managed; retry the stop."
                ),
                "exits": exits,
            }

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

    # Non-empty is not success: the per-leg flags carry whether the broker took
    # the order. Reporting a refused exit as closed tells an operator a
    # position is gone when it is still on the book.
    if not all(outcome.get("ok") for outcome in exits):
        errors = "; ".join(o.get("error") or "refused" for o in exits if not o.get("ok"))
        return {"ok": False, "error": f"Exit refused: {errors}", "exits": exits}

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


def _daily_loss_limit(strategy: dict[str, Any]) -> float | None:
    """The strategy's daily loss limit as a positive number, or None."""
    limit = strategy.get("daily_loss_limit_inr")
    if not limit:
        return None
    try:
        limit_value = abs(float(limit))
    except (TypeError, ValueError):
        return None
    return limit_value if limit_value > 0 else None


def _session_banked_pnl(strategy: dict[str, Any], run_id: int) -> float | None:
    """What earlier runs banked this session, read outside the run lock.

    This is the only part of the daily-loss check that can touch the database,
    and a cache miss is a real connection under NullPool. Held inside the run
    lock it would stall the hub for the length of that query, and a greenlet
    waiting on the lock cannot yield, so exits and socket work for every other
    run would wait behind it. The module's own rule is that a critical section
    holds in-memory bookkeeping only; this is how that rule is kept here.

    None when the strategy has no limit, which is also the signal to skip the
    read entirely rather than pay for it on every tick.
    """
    if _daily_loss_limit(strategy) is None:
        return None
    return store.realized_pnl_since(
        strategy["id"], session.session_started_at(), exclude_run_id=run_id
    )


def _daily_loss_breached(
    strategy: dict[str, Any], banked: float | None, run: dict[str, Any]
) -> str | None:
    """Whether this session's loss has reached the strategy's daily limit.

    The session is the one that began at SESSION_EXPIRY_TIME, not at midnight,
    so a limit resets when the platform's own day rolls over. Runs that have
    already finished contribute ``banked``, read before the lock was taken; the
    live run contributes what it is worth right now, marked, because a limit
    that only counted closed runs would let an open one exceed it unnoticed.

    Pure arithmetic on values already in memory. Safe to call under the lock.
    """
    limit_value = _daily_loss_limit(strategy)
    if limit_value is None or banked is None:
        return None

    live = float(run.get("pnl_total") or 0.0)
    day_total = banked + live
    if day_total > -limit_value:
        return None
    return (
        f"Daily loss limit reached: the session is down {abs(day_total):.2f} "
        f"against a limit of {limit_value:.2f}"
    )


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

    # Read before the lock is taken, never inside it. This is the one input to
    # the tick evaluation that can reach the database, and only on a cache
    # miss; a query held under the run lock stalls the hub, and a greenlet
    # waiting on that lock cannot yield. None when the strategy has no daily
    # limit, in which case no read happens at all.
    banked_pnl = _session_banked_pnl(strategy, run_id)

    # Everything inside this block is in-memory arithmetic. No order is placed,
    # no broker is called, nothing is emitted, and nothing reaches the database.
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

        # The daily loss limit, which is a limit on the session rather than on
        # this run. It was validated, stored and displayed and then read by
        # nothing, so a strategy that lost its whole budget in three runs
        # started a fourth. overall_sl_mtm cannot express it: that one is reset
        # every time a run opens, which for a signal or scheduled strategy is
        # several times a day.
        day_loss_reason = _daily_loss_breached(strategy, banked_pnl, run)
        if day_loss_reason is not None:
            stop_reason = "daily_loss_limit"
            events.append(
                (
                    "overall_sl_hit",
                    day_loss_reason,
                    {"severity": "critical"},
                )
            )
        elif aggregate.breached and aggregate.reason in _STOP_REASON_FOR_REASON:
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
