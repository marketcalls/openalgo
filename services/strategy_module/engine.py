"""The strategy engine: run lifecycle and the tick decision path.

Four entry points, and everything else here supports one of them:

    start_run    resolve every leg, claim the strategy, place entries
    stop_run     request exits and finalise after confirmed fills
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
from services.strategy_module.audit_messages import leg_close_requested_message
from services.strategy_module.symbol_resolver import resolve_leg
from utils.logging import get_logger

logger = get_logger(__name__)


class _PositionRefMismatch(Exception):
    """Carry ignored-fill details beyond the run lock."""


class _LateExitFillWithoutState(Exception):
    """Move durable late-fill reconciliation beyond the detached run lock."""


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


def _exit_fill_quantities(filled_qty: int | None, held_qty: Any) -> tuple[int, int]:
    """Return the applied and remaining whole quantities for one owner."""
    try:
        held = max(0, int(float(held_qty or 0)))
    except (TypeError, ValueError):
        held = 0
    if filled_qty is None:
        applied = held
    else:
        try:
            applied = max(0, int(float(filled_qty)))
        except (TypeError, ValueError):
            applied = 0
        applied = min(applied, held)
    return applied, held - applied


def _leg_requires_management(leg: dict[str, Any]) -> bool:
    """Whether a leg still owns exposure or an entry that may become exposure."""
    if leg.get("superseded") is not None:
        return True
    if leg.get("exit_order_id") is not None or leg.get("exit_claim_token") is not None:
        return True
    if leg.get("status") == "open":
        return True
    return leg.get("entry_status") in ("pending", "open")


def _managed_leg_ids(run: dict[str, Any]) -> list[Any]:
    """Leg ids whose live or superseded position still keeps a run active."""
    return [leg["leg_id"] for leg in run.get("legs", {}).values() if _leg_requires_management(leg)]


def _run_requires_management(run: dict[str, Any]) -> bool:
    """Whether any actual or still-working position keeps this run non-terminal."""
    return bool(run.get("signal_entry_claims")) or any(
        _leg_requires_management(leg) for leg in run.get("legs", {}).values()
    )


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

    # Batch only, which the public reference already states. A signal strategy
    # has no start: its run is opened by the first signal after the session
    # boundary, in signals._day_run. Running the batch lifecycle over signal
    # legs got as far as building run state and then raised, because a signal
    # leg carries the side it accepts and not a position to be entered at, and
    # the failure left the run open and the strategy claimed.
    if (strategy_row.strategy_kind or "batch") == "signal":
        return StartResult(
            ok=False,
            error=(
                "A signal strategy has no start. Its run opens on the first "
                "long_entry or short_entry signal after the session boundary."
            ),
        )

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
    for leg in resolved:
        leg["position_ref"] = state.new_position_ref()

    # One conditional UPDATE, not a read then a write. The UI, the scheduler
    # and a webhook can all fire at the same instant.
    if not store.claim_strategy_for_run(strategy_id):
        return StartResult(ok=False, error="This strategy is already running")

    run_id: int | None = None
    placement_progress: dict[str, set[str]] = {"dispatch_attempted": set()}
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

        # Synchronous fill replay removes every scoped session on this thread.
        # Capture the scalar immediately; even an ORM primary key can be
        # expired by a store commit and detached while dispatch is in flight.
        run_id = int(run.id)

        if not store.set_strategy_status(strategy_id, "running", run_id):
            cleaned = store.finish_unlinked_run_and_release_claim(
                run_id,
                strategy_id,
                "error",
            )
            if not cleaned:
                logger.critical(
                    "Run %s could not be linked to strategy %s and its empty claim "
                    "could not be fully released",
                    run_id,
                    strategy_id,
                )
            return StartResult(
                ok=False,
                run_id=None if cleaned else run_id,
                error="Could not link the new run to its strategy; no order was placed",
            )
        state.init_run_state(run_id, strategy_id, resolved)
        # Ask for prices before the entries go out. A fill can be reported
        # within milliseconds, and a leg whose instrument is not subscribed
        # would sit with no price and therefore no stop until the next
        # subscription sweep.
        _subscribe_run(run_id, resolved)
        _emit(
            strategy_id,
            user_id,
            "run_started",
            f"Run started in {mode} mode ({trigger_source})",
            run_id=run_id,
        )

        placed = _place_entries(
            run_id,
            strategy,
            resolved,
            mode,
            api_key,
            user_id,
            placement_progress=placement_progress,
        )

        # Every leg rejected means there is no position and nothing to manage.
        # Leaving the run open would show a running strategy holding nothing.
        if not any(leg["ok"] for leg in placed):
            finalised = _finalise(
                run_id,
                strategy_id,
                user_id,
                "error",
                "No entry order was accepted",
            )
            if not finalised:
                return StartResult(
                    ok=False,
                    run_id=run_id,
                    error=(
                        "Every entry order was rejected, but the flat run could not be "
                        "finalised; retry stop"
                    ),
                    legs=placed,
                )
            # The run id and the broker's own words come back with the refusal.
            # Without them the caller was told only that every entry was
            # rejected, with no run to open and no reason to read, while the
            # cause sat on the order rows all along: "MIS orders cannot be
            # placed after square-off time", "insufficient funds", whatever the
            # venue actually said. The finalised run is still the place those
            # rows live, so naming it is what makes the refusal actionable.
            return StartResult(
                ok=False,
                run_id=run_id,
                error=_rejection_summary(placed),
                legs=placed,
            )

        return StartResult(ok=True, run_id=run_id, legs=placed)
    except Exception:
        logger.exception("Start failed for strategy %s", strategy_id)
        if run_id is not None:
            return _manage_failed_start(
                run_id,
                strategy_id,
                user_id,
                resolved,
                placement_progress,
            )
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
                "risk_unit": leg.get("risk_unit") or "points",
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
    than a broken statement. If it still will not persist, exact row, run, leg,
    broker-id and accepted/rejected facts are retained in a structured critical
    event. The same call repairs only the named pending row immediately, and
    the shared scheduler revisits ordinary open runs if that first repair is
    interrupted; ambiguous ownership remains open and reserved.
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
    broker_order_id = str(result.broker_order_id) if result.broker_order_id else None
    status = "open" if result.ok else "rejected"
    _emit(
        strategy_id,
        user_id,
        "order_ack_unrecorded",
        (
            f"Broker order {broker_order_id or '(no broker id)'} was accepted for leg "
            f"{leg_id}, but order row {row_id} remains pending. Exact row and broker "
            "metadata is retained for automatic reconciliation; possible exposure remains "
            "managed until a broker fact confirms it terminal."
            if result.ok
            else (
                f"The broker rejected the order for leg {leg_id}, but rejection status could "
                f"not be written to exact order row {row_id}. Structured metadata is retained "
                "for automatic reconciliation; the rejected dispatch created no new exposure."
            )
        ),
        run_id=run_id,
        leg_id=leg_id,
        severity="critical",
        payload={
            "version": 1,
            "order_id": row_id,
            "run_id": run_id,
            "leg_id": leg_id,
            "broker_order_id": broker_order_id,
            "accepted": bool(result.ok),
            "status": status,
            "reject_reason": None if result.ok else result.error,
        },
    )
    try:
        from services.strategy_module import ack_reconciliation

        # Bind the exact row as soon as its append-only witness is durable.
        # Replay remains at the call site, after the leg's acknowledgement
        # bookkeeping, so a synchronous fill cannot be overwritten to open.
        ack_reconciliation.reconcile(run_id, replay_updates=False)
    except Exception:
        # The durable event remains retryable by the shared scheduler. An
        # acknowledgement failure must not turn into a dispatch failure after
        # the broker has already accepted the order.
        logger.exception("Immediate acknowledgement repair failed for run %s", run_id)
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


def _rejection_summary(placed: list[dict[str, Any]]) -> str:
    """Why every entry was refused, in the venue's own words.

    Each leg already carries the dispatch error; only the caller never saw it.
    One distinct reason is reported as itself, because a basket refused for one
    cause has one thing to fix. Several are listed per leg so a mixed refusal
    does not hide the leg that failed for a different reason.
    """
    reasons: dict[str, list[Any]] = {}
    for leg in placed:
        reason = str(leg.get("error") or "").strip()
        if reason:
            reasons.setdefault(reason, []).append(leg.get("leg_id"))

    if not reasons:
        return "Every entry order was rejected"
    if len(reasons) == 1:
        return f"Every entry order was rejected: {next(iter(reasons))}"
    detail = "; ".join(
        f"leg {', '.join(str(leg_id) for leg_id in legs)}: {reason}"
        for reason, legs in reasons.items()
    )
    return f"Every entry order was rejected. {detail}"


def _place_entries(
    run_id: int,
    strategy: dict[str, Any],
    resolved: list[dict[str, Any]],
    mode: str,
    api_key: str,
    user_id: str,
    *,
    placement_progress: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    """Place every leg's entry, longs first.

    Buying before selling matters on a spread: the short leg alone can be
    refused for margin the account would have had once the long leg existed.
    """
    ordered = sorted(resolved, key=lambda leg: 0 if leg["position"] == "B" else 1)
    outcomes: list[dict[str, Any]] = []
    progress = placement_progress if placement_progress is not None else {}
    dispatch_attempted = progress.setdefault("dispatch_attempted", set())

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
                "position_ref": leg.get("position_ref"),
            },
        )
        if row is None:
            # An entry that cannot be recorded is an entry that cannot be
            # managed, so it is not placed. Refusing costs one leg; placing it
            # blind costs a position with no stop and no way to find it. Exits
            # take the opposite decision, deliberately: see _exit_legs.
            state.reject_entry_intent(run_id, leg["leg_id"], leg.get("position_ref"))
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
        position_ref = str(leg.get("position_ref") or "")

        # Mark the exact incarnation immediately before the call. If arbitrary
        # adapter code raises, the send may already have reached the broker;
        # the failed-start path must retain it as possible exposure rather than
        # misclassifying it as an undispatched placeholder.
        dispatch_attempted.add(position_ref)
        result = order_dispatch.dispatch_order(mode=mode, api_key=api_key, order=order)

        acknowledged = _record_acknowledgement(
            row_id, result, strategy["id"], user_id, run_id, leg["leg_id"]
        )

        with state.run_state(run_id) as run:
            if run is not None:
                leg_state = run["legs"].get(str(leg["leg_id"]))
                if (
                    leg_state is not None
                    and leg_state.get("position_ref") == leg.get("position_ref")
                    and leg_state.get("entry_status") == "pending"
                ):
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


def _manage_failed_start(
    run_id: int,
    strategy_id: int,
    user_id: str,
    resolved: list[dict[str, Any]],
    placement_progress: dict[str, set[str]],
) -> StartResult:
    """Reject never-sent placeholders and stop every possibly sent entry."""
    attempted = placement_progress.get("dispatch_attempted", set())
    for leg in resolved:
        position_ref = str(leg.get("position_ref") or "")
        if position_ref not in attempted:
            state.reject_entry_intent(run_id, leg["leg_id"], leg.get("position_ref"))

    snapshot = state.get_run_state(run_id)

    # No dispatch was ever attempted, so nothing can be held. `dispatch_attempted`
    # is written immediately before each call precisely so a raise mid-send is
    # kept as possible exposure; an empty set is therefore proof of flatness,
    # and it holds even when run state was never built. Without this, a start
    # that failed while constructing that state left the run open and the
    # strategy stuck reading "running", with no live state for any later stop
    # to work from and nothing to reconcile against.
    if not attempted:
        _finalise(run_id, strategy_id, user_id, "error", "Start failed before any entry dispatch")
        return StartResult(ok=False, run_id=run_id, error="Could not start the strategy")

    if snapshot is not None and not _run_requires_management(snapshot):
        _finalise(run_id, strategy_id, user_id, "error", "Start failed before any entry dispatch")
        return StartResult(ok=False, run_id=run_id, error="Could not start the strategy")

    try:
        stopped = stop_run(run_id, user_id, reason="error")
    except Exception:
        logger.exception("Could not reconcile interrupted start for run %s", run_id)
        stopped = {"ok": False, "stop_pending": True}

    durable = store.get_run(run_id)
    if durable is not None and durable.stopped_at is not None:
        return StartResult(ok=False, run_id=run_id, error="Could not start the strategy")

    _emit(
        strategy_id,
        user_id,
        "run_stop_failed",
        (
            "Start failed after one or more entry dispatches became possible. "
            "Undispatched intents were rejected; accepted or uncertain entries remain "
            "managed under a durable pending stop until broker facts confirm flatness."
        ),
        run_id=run_id,
        severity="critical",
    )
    detail = stopped.get("error") if isinstance(stopped, dict) else None
    return StartResult(
        ok=False,
        run_id=run_id,
        error=(
            "Could not start the strategy; possible entry exposure remains managed"
            + (f": {detail}" if detail else "")
        ),
    )


# ---------------------------------------------------------------------------
# Fills
# ---------------------------------------------------------------------------


def apply_fill(
    run_id: int,
    leg_id: Any,
    avg_price: float | None,
    is_entry: bool,
    filled_qty: int | None = None,
    order_row_id: int | None = None,
    position_ref: str | None = None,
    cumulative_filled_qty: int | None = None,
    order_terminal: bool = True,
    allow_prior_order_correction: bool = False,
) -> bool:
    """Record a fill, logging position mismatches after the run lock releases."""
    deferred_warnings: list[tuple[str, tuple[Any, ...]]] = []
    try:
        return _apply_fill(
            run_id,
            leg_id,
            avg_price,
            is_entry,
            filled_qty,
            order_row_id,
            position_ref,
            cumulative_filled_qty,
            order_terminal,
            allow_prior_order_correction,
            deferred_warnings,
        )
    except _PositionRefMismatch as mismatch:
        logger.warning(
            "Ignoring a fill for position %s on leg %s: the live position is %s",
            *mismatch.args,
        )
        return False
    except _LateExitFillWithoutState:
        # The context manager has released the retained lock before this
        # durable repair touches the database.
        store.reconcile_run_pnl(run_id)
        return False
    finally:
        for message, args in deferred_warnings:
            logger.warning(message, *args)


def _apply_fill(
    run_id: int,
    leg_id: Any,
    avg_price: float | None,
    is_entry: bool,
    filled_qty: int | None = None,
    order_row_id: int | None = None,
    position_ref: str | None = None,
    cumulative_filled_qty: int | None = None,
    order_terminal: bool = True,
    allow_prior_order_correction: bool = False,
    deferred_warnings: list[tuple[str, tuple[Any, ...]]] | None = None,
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
    if deferred_warnings is None:
        deferred_warnings = []

    went_flat = False
    strategy_id = None
    entry_applied = False
    with state.run_state(run_id) as run:
        if run is None:
            # A duplicate or late terminal update can arrive after another
            # worker won finalisation. Reconcile from the durable order rows
            # without attempting a second terminal transition.
            if not is_entry:
                raise _LateExitFillWithoutState
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
                (position_ref is not None and superseded.get("position_ref") == position_ref)
                or (position_ref is None and superseded.get("exit_order_id") == order_row_id)
                # No order id to match on: this is an internal caller rather
                # than the order stream. An exit fill can only belong to the
                # outgoing position when the live one has no exit in flight.
                or (
                    position_ref is None
                    and order_row_id is None
                    and leg.get("exit_order_id") is None
                )
            )
        )
        if settles_superseded:
            entry = float(superseded.get("entry_avg") or 0.0)
            applied_qty, remaining_qty = _exit_fill_quantities(
                filled_qty,
                superseded.get("qty"),
            )
            sign = 1.0 if superseded.get("position") == "B" else -1.0
            if entry > 0.0 and avg_price is not None:
                leg["realized_pnl"] = float(leg.get("realized_pnl") or 0.0) + (
                    (float(avg_price) - entry) * applied_qty * sign
                )
            owns_current_order = (
                order_row_id is None or superseded.get("exit_order_id") == order_row_id
            )
            release_current_order = order_terminal and owns_current_order
            if remaining_qty > 0 or not release_current_order:
                superseded["qty"] = remaining_qty
                if release_current_order:
                    superseded["exit_order_id"] = None
                    superseded["exit_claim_token"] = None
                    superseded["exit_kind"] = None
            else:
                leg["superseded"] = None
        else:
            if position_ref is not None and leg.get("position_ref") != position_ref:
                raise _PositionRefMismatch(position_ref, leg_id, leg.get("position_ref"))

            # A fill that names an order this leg is not waiting on belongs to
            # an incarnation that has already been replaced. Applying it would
            # close or re-price the position that is live now.
            if order_row_id is not None:
                expected = leg.get("entry_order_id") if is_entry else leg.get("exit_order_id")
                if (
                    expected is not None
                    and expected != order_row_id
                    and not allow_prior_order_correction
                ):
                    deferred_warnings.append(
                        (
                            "Ignoring a fill for order %s on leg %s: the leg is waiting on %s",
                            (order_row_id, leg_id, expected),
                        )
                    )
                    return False

            if (
                not is_entry
                and order_row_id is not None
                and leg.get("exit_kind") is None
                and leg.get("exit_order_id") is None
                and not allow_prior_order_correction
            ):
                # A fill from the order stream naming an exit this leg never
                # placed cannot be closing the position that is live now.
                deferred_warnings.append(
                    (
                        "Ignoring exit fill for order %s on leg %s: it has no exit in flight",
                        (order_row_id, leg_id),
                    )
                )
                return False

            if is_entry:
                if avg_price is not None:
                    leg["entry_avg"] = float(avg_price)
                else:
                    deferred_warnings.append(
                        (
                            "Leg %s on run %s filled without a usable average price; "
                            "managing its quantity with valuation unavailable",
                            (leg_id, run_id),
                        )
                    )
                # Reconcile the size with what actually traded. A partial fill
                # whose remainder was cancelled is ordinary on an illiquid
                # strike; every later exit must use what actually filled.
                managed_entry_qty = (
                    cumulative_filled_qty if cumulative_filled_qty is not None else filled_qty
                )
                if managed_entry_qty is not None and managed_entry_qty != leg.get("qty"):
                    deferred_warnings.append(
                        (
                            "Leg %s on run %s filled %s of %s; managing the filled size",
                            (leg_id, run_id, managed_entry_qty, leg.get("qty")),
                        )
                    )
                    leg["qty"] = managed_entry_qty
                if cumulative_filled_qty is not None:
                    leg["entry_filled_qty"] = cumulative_filled_qty
                leg["entry_status"] = "complete" if order_terminal else "open"
                leg["status"] = "open"
                entry_applied = order_terminal
            else:
                if avg_price is not None:
                    leg["exit_avg"] = float(avg_price)
                entry = float(leg.get("entry_avg") or 0.0)
                applied_qty, remaining_qty = _exit_fill_quantities(
                    filled_qty,
                    leg.get("qty"),
                )
                sign = 1.0 if leg.get("position") == "B" else -1.0
                if applied_qty > 0 and entry > 0.0 and avg_price is not None:
                    leg["realized_pnl"] = float(leg.get("realized_pnl") or 0.0) + (
                        (float(avg_price) - entry) * applied_qty * sign
                    )
                elif applied_qty > 0:
                    # An entry price of zero means this incarnation contributes
                    # no valued round trip. An unavailable exit price likewise
                    # cannot be invented. Prior signal-session P&L remains intact.
                    deferred_warnings.append(
                        (
                            "Leg %s on run %s exited without complete fill pricing; "
                            "booking no realized P&L for that quantity",
                            (leg_id, run_id),
                        )
                    )
                    leg["realized_pnl"] = float(leg.get("realized_pnl") or 0.0)
                owns_current_order = (
                    order_row_id is None or leg.get("exit_order_id") == order_row_id
                )
                release_current_order = order_terminal and owns_current_order
                if remaining_qty > 0:
                    leg["qty"] = remaining_qty
                    leg["status"] = "open"
                else:
                    leg["qty"] = 0
                    leg["status"] = "closed"
                    leg["mtm"] = 0.0
                if release_current_order:
                    leg["exit_order_id"] = None
                    leg["exit_claim_token"] = None
                    leg["exit_kind"] = None

        # Recompute the run totals now, while the lock is held, so the figures
        # finalise writes are the ones this fill produced.
        realized, unrealized = risk_adapter.run_pnl(run)
        run["pnl_realized"] = realized
        run["pnl_unrealized"] = unrealized
        run["pnl_total"] = realized + unrealized
        run["pnl_peak"] = max(run.get("pnl_peak", 0.0), run["pnl_total"])
        run["pnl_trough"] = min(run.get("pnl_trough", 0.0), run["pnl_total"])

        went_flat = not _run_requires_management(run)
        strategy_id = run.get("strategy_id")

    if entry_applied:
        # The entry may have filled after stop_run reported it unfilled. The
        # durable request is read and retried only after the state lock is
        # released, so the exact filled size is claimed for exit immediately.
        reconcile_pending_stop(run_id)
        return False

    if not went_flat:
        return False

    # Outside the lock: finalising reaches the database.
    run_row = store.get_run(run_id)
    if not run_row or run_row.stopped_at is not None:
        return True
    requested_reason = run_row.stop_requested_reason
    strategy_row = store.get_strategy_unscoped(strategy_id)
    user_id = strategy_row.user_id if strategy_row else ""
    strategy_kind = strategy_row.strategy_kind if strategy_row is not None else None

    # Only a batch run ends when it goes flat without a stop request. A batch
    # is a basket entered and exited as a unit, so nothing held means it is
    # finished.
    #
    # A signal run is a trading day, not a basket. A leg exiting is an ordinary
    # mid-session event and the next alert reopens it, so finalising here would
    # end the run on the first round trip: five round trips in a day would
    # produce five runs, fragmenting the P&L, the peak and trough, and the
    # audit trail that is supposed to describe the day. A signal run is closed
    # by the scheduler's square-off, by an explicit stop, or by the session
    # boundary when the next day's first signal arrives.
    if requested_reason is None and strategy_kind == "signal":
        logger.debug("Run %s is flat but signal-mode; leaving it open for the session", run_id)
        return True

    final_reason = requested_reason or "manual"
    message = f"Run stopped ({final_reason})" if requested_reason else "All legs closed"
    _finalise(run_id, strategy_id, user_id, final_reason, message)
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
    live_targets, unfilled_legs = state.claim_legs_for_exit(run_id, leg_ids, kind)
    targets: list[tuple[dict[str, Any], str]] = [(leg, "live") for leg in live_targets]

    # A signal flip can leave the outgoing position under ``superseded`` while
    # the same leg id owns its replacement. Stop must manage both owners. The
    # exact outgoing claim is taken under the run lock and carries the durable
    # position reference assigned to that incarnation.
    for leg_id in leg_ids:
        snapshot = state.get_run_state(run_id) or {}
        live_leg = (snapshot.get("legs") or {}).get(str(leg_id)) or {}
        superseded = live_leg.get("superseded")
        if not superseded:
            continue
        claimed = state.claim_superseded_exit(
            run_id,
            leg_id,
            superseded.get("position"),
        )
        if claimed is not None:
            targets.append((claimed, "superseded"))

    unfilled = [
        {
            "leg_id": leg["leg_id"],
            "ok": False,
            "symbol": leg.get("symbol"),
            "broker_order_id": None,
            "position_ref": leg.get("position_ref"),
            "exit_owner": "live",
            "error": (
                "The entry for this leg has been accepted but not filled, so there "
                "is no confirmed quantity to exit. Retry once it fills."
            ),
        }
        for leg in unfilled_legs
    ]

    # Dispatch outside the lock. See the module docstring.
    outcomes: list[dict[str, Any]] = []
    for leg, exit_owner in targets:
        quantity = leg.get("qty") or leg.get("quantity")
        action = order_dispatch.exit_action(leg["position"])
        order = order_dispatch.build_order(
            symbol=leg["symbol"],
            exchange=leg["exchange"],
            action=action,
            quantity=quantity,
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
                "qty": quantity,
                "product": order.get("product"),
                "pricetype": order_dispatch.EXIT_PRICETYPE,
                "status": "pending",
                "position_ref": leg.get("position_ref"),
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
        claim_token = (
            leg.get("claim_token") if exit_owner == "superseded" else leg.get("exit_claim_token")
        )
        exit_claim_id = claim_token
        if row_id is not None:
            if exit_owner == "superseded":
                bound = state.bind_superseded_exit(
                    run_id,
                    leg["leg_id"],
                    claim_token,
                    row_id,
                )
            else:
                bound = state.bind_live_exit(
                    run_id,
                    leg["leg_id"],
                    claim_token,
                    row_id,
                    leg.get("position_ref"),
                )
            if not bound:
                store.update_order(
                    row_id,
                    status="rejected",
                    reject_reason=(
                        "Outgoing position exit claim changed before dispatch"
                        if exit_owner == "superseded"
                        else "Live position exit claim changed before dispatch"
                    ),
                )
                if exit_owner == "superseded":
                    state.release_superseded_exit(run_id, leg["leg_id"], claim_token)
                else:
                    state.release_leg_exit(run_id, leg["leg_id"], claim_token)
                _emit(
                    strategy["id"],
                    user_id,
                    "leg_exit_rejected",
                    (
                        f"{exit_owner.title()} exit claim changed on leg "
                        f"{leg['leg_id']} before dispatch"
                    ),
                    run_id=run_id,
                    leg_id=leg["leg_id"],
                    severity="critical",
                )
                outcomes.append(
                    {
                        "leg_id": leg["leg_id"],
                        "ok": False,
                        "position_ref": leg.get("position_ref"),
                        "exit_owner": exit_owner,
                        "error": (
                            f"The {exit_owner} position changed before its exit could be placed"
                        ),
                    }
                )
                continue
            exit_claim_id = row_id

        result = order_dispatch.dispatch_order(mode=mode, api_key=api_key, order=order)

        if row_id is not None:
            _record_acknowledgement(row_id, result, strategy["id"], user_id, run_id, leg["leg_id"])

        if not result.ok:
            # Release the claim so a later attempt is not mistaken for a
            # duplicate and skipped for the rest of the session.
            if exit_owner == "superseded":
                released = state.release_superseded_exit(run_id, leg["leg_id"], exit_claim_id)
                if released:
                    from services.strategy_module import order_events

                    order_events.report_flip_outgoing_exit_rejected(
                        run_id,
                        leg["leg_id"],
                        "refused",
                        result.broker_order_id,
                    )
            else:
                state.release_leg_exit(run_id, leg["leg_id"], exit_claim_id)

        _emit(
            strategy["id"],
            user_id,
            "leg_exit_placed" if result.ok else "leg_exit_rejected",
            (
                f"Exit {action} {quantity} {leg['symbol']} placed ({kind})"
                if result.ok
                else f"Exit rejected on leg {leg['leg_id']}: {result.error}"
            ),
            run_id=run_id,
            leg_id=leg["leg_id"],
            severity="info" if result.ok else "critical",
        )

        if result.ok and row_id is not None:
            # The accepted acknowledgement and its audit event must precede a
            # cached synchronous fill that can make the basket terminal.
            # Ownership was bound before dispatch, so replay can find the
            # exact position without publishing run_stopped before the order
            # placement that actually made it flat.
            _replay_order_update(result.broker_order_id)

        outcomes.append(
            {
                "leg_id": leg["leg_id"],
                "ok": result.ok,
                "error": result.error,
                "position_ref": leg.get("position_ref"),
                "exit_owner": exit_owner,
            }
        )

    return outcomes + unfilled


def _cancel_and_reconcile_working_entries(
    run_id: int,
    mode: str,
    api_key: str,
) -> None:
    """Cancel each accepted working entry, then fold one broker status fact.

    Cancellation is an accepted intent, never proof that the entry is dead.
    The immediate status read uses the existing orderstatus/orderbook path and
    is folded by ``order_events`` exactly like a pushed update. A missing or
    still-working fact leaves the durable stop and live ownership untouched so
    an operator or the scheduler can retry.
    """
    working_statuses = {"pending", "open", "working", "trigger pending", "trigger_pending"}
    candidates = [
        row
        for row in store.list_orders(run_id)
        if row.get("kind") == "entry"
        and str(row.get("status") or "pending").strip().lower() in working_statuses
    ]
    if not candidates:
        return

    from services.strategy_module import order_events

    for row in candidates:
        broker_order_id = str(row.get("broker_order_id") or "")
        if not broker_order_id:
            continue

        cancellation = order_dispatch.cancel_order(
            mode=mode,
            api_key=api_key,
            broker_order_id=broker_order_id,
        )
        if not cancellation.ok:
            logger.warning(
                "Working entry %s on run %s could not be cancelled: %s",
                broker_order_id,
                run_id,
                cancellation.error or "broker refusal",
            )

        status = order_dispatch.fetch_order_status(
            mode=mode,
            api_key=api_key,
            broker_order_id=broker_order_id,
        )
        if status.ok and status.order is not None:
            order_events.apply_order_snapshot(broker_order_id, status.order)
        else:
            logger.warning(
                "Working entry %s on run %s remains unconfirmed after cancellation: %s",
                broker_order_id,
                run_id,
                status.error or "status unavailable",
            )


def _reconcile_working_exits(
    run_id: int,
    mode: str,
    api_key: str,
) -> None:
    """Fold one broker fact for each accepted exit still awaiting a frame.

    A pushed terminal update can be lost while the broker orderbook already
    knows the exit completed, partially filled, or died. Polling through the
    same order-event fold releases the exact owner, applies only the cumulative
    fill delta, and lets the ordinary stop path retry only a proven remainder.
    """
    working_statuses = {"pending", "open", "working", "trigger pending", "trigger_pending"}
    candidates = [
        row
        for row in store.list_orders(run_id)
        if row.get("kind") != "entry"
        and str(row.get("status") or "pending").strip().lower() in working_statuses
    ]
    if not candidates:
        return

    from services.strategy_module import order_events

    for row in candidates:
        broker_order_id = str(row.get("broker_order_id") or "")
        if not broker_order_id:
            continue
        status = order_dispatch.fetch_order_status(
            mode=mode,
            api_key=api_key,
            broker_order_id=broker_order_id,
        )
        if status.ok and status.order is not None:
            order_events.apply_order_snapshot(broker_order_id, status.order)
        else:
            logger.warning(
                "Working exit %s on run %s remains unconfirmed: %s",
                broker_order_id,
                run_id,
                status.error or "status unavailable",
            )


def stop_run(run_id: int, user_id: str, reason: str = "manual") -> dict[str, Any]:
    """Request a stop, exit every owned position, and finalise only once flat."""
    run_row = store.get_run(run_id)
    if not run_row or run_row.stopped_at is not None:
        return {"ok": False, "error": "Run is not active"}
    strategy_id = int(run_row.strategy_id)
    run_mode = str(run_row.mode)

    strategy_row = store.get_strategy(strategy_id, user_id)
    if not strategy_row:
        return {"ok": False, "error": "Strategy not found"}
    strategy = store.strategy_to_dict(strategy_row)

    # Durable before every broker call. A process death after this write leaves
    # recovery knowing that a flat run should finish and that a held one must
    # reject new entries while its exits are retried.
    if not store.request_run_stop(run_id, reason):
        return {
            "ok": False,
            "stop_pending": False,
            "error": "Could not persist the stop request; no exit order was placed",
            "exits": [],
        }
    requested_row = store.get_run(run_id)
    if requested_row is not None and requested_row.stop_requested_reason:
        reason = str(requested_row.stop_requested_reason)
    # The live gate follows the durable write and precedes API-key lookup or
    # any other I/O. A signal that already claimed an entry is counted below;
    # a signal that has not claimed yet is refused by this flag under the same
    # run lock used to create claims.
    state.mark_stopping(run_id)
    _emit(
        strategy_id,
        user_id,
        "run_stop_requested",
        f"Stop requested ({reason}); exit orders are being attempted",
        run_id=run_id,
    )

    from services.strategy_module import ack_reconciliation

    ack_repairs = ack_reconciliation.reconcile(run_id)
    if ack_repairs.unresolved_exposure:
        _emit(
            strategy_id,
            user_id,
            "run_stop_failed",
            (
                "Stop remains pending because one or more broker acknowledgements could not "
                "be linked to their exact durable order rows. No ambiguous exposure was "
                "finalised; reconciliation will retry."
            ),
            run_id=run_id,
            severity="critical",
        )
        return {
            "ok": False,
            "stop_pending": True,
            "error": "Unresolved broker acknowledgement ownership; the run remains managed",
            "exits": [],
        }

    snapshot = state.get_run_state(run_id)
    if snapshot is None:
        _emit(
            strategy_id,
            user_id,
            "run_stop_failed",
            "Stop remains pending because the active run state is unavailable; no flatness "
            "claim was made",
            run_id=run_id,
            severity="critical",
        )
        return {
            "ok": False,
            "stop_pending": True,
            "error": "The run remains open because its live state is unavailable",
            "exits": [],
        }

    managed_ids = _managed_leg_ids(snapshot)
    still_held = _run_requires_management(snapshot)

    api_key = _api_key_for(user_id)
    if not api_key:
        if not still_held:
            persisted_reason = store.get_run(run_id).stop_requested_reason or reason
            finalised = _finalise(
                run_id,
                strategy_id,
                user_id,
                persisted_reason,
                f"Run stopped ({persisted_reason})",
            )
            if finalised:
                return {"ok": True, "stop_pending": False, "exits": []}
            return {
                "ok": False,
                "stop_pending": True,
                "error": "The run is flat but its final stop could not be persisted; retry the stop",
                "exits": [],
            }

        if run_id not in _unactionable_runs:
            _unactionable_runs.add(run_id)
            _emit(
                strategy_id,
                user_id,
                "run_stop_failed",
                "Stop remains pending because there is no broker session/API key. Positions "
                "and possible entry exposure remain managed and retryable.",
                run_id=run_id,
                severity="critical",
            )
        return {
            "ok": False,
            "stop_pending": True,
            "error": "No API key is configured for this user; the run remains managed",
            "exits": [],
        }

    _note_actionable_again(strategy_id, user_id, run_id)

    # A working entry is possible future exposure, not a position to reverse
    # with a full-size market exit. Cancel it through the immutable run mode,
    # then reconcile a broker fact before deciding what remains. Every broker,
    # database and event call here is outside the run lock.
    _reconcile_working_exits(run_id, run_mode, api_key)
    _cancel_and_reconcile_working_entries(run_id, run_mode, api_key)

    current_row = store.get_run(run_id)
    if current_row is not None and current_row.stopped_at is not None:
        return {"ok": True, "stop_pending": False, "exits": []}

    snapshot = state.get_run_state(run_id)
    if snapshot is None:
        return {
            "ok": False,
            "stop_pending": True,
            "error": "The run remains open because its live state is unavailable",
            "exits": [],
        }
    managed_ids = _managed_leg_ids(snapshot)

    kind = "exit_close_all" if reason == "manual" else f"exit_{reason}"
    if kind not in store.ORDER_KINDS:
        kind = "exit_close_all"

    exits = _exit_legs(run_id, strategy, managed_ids, kind, run_mode, api_key, user_id)

    # A synchronous sandbox fill can finish the run from replay_for() before
    # dispatch returns. That fill owns terminal completion; do not emit a
    # second run_stopped event from this caller.
    current_row = store.get_run(run_id)
    if current_row is not None and current_row.stopped_at is not None:
        return {"ok": True, "stop_pending": False, "exits": exits}

    snapshot = state.get_run_state(run_id)
    if snapshot is None:
        _emit(
            strategy_id,
            user_id,
            "run_stop_failed",
            "Stop remains pending because the active run state is unavailable; no flatness "
            "claim was made",
            run_id=run_id,
            severity="critical",
        )
        return {
            "ok": False,
            "stop_pending": True,
            "error": "The run remains open because its live state is unavailable",
            "exits": exits,
        }

    still_held = _run_requires_management(snapshot)

    # A run whose exits the broker refused is still holding those positions.
    # Finalising here would write stopped_at, release the strategy, drop the
    # live state and unsubscribe the prices, so the position would sit open for
    # the rest of the session with nothing evaluating its stop while the
    # dashboard read "stopped". A broker rate limit or a momentary auth failure
    # at 15:20 is enough to reach this, so it stays open and says why.
    refused = [outcome for outcome in exits if not outcome.get("ok")]
    if refused and still_held:
        _emit(
            strategy_id,
            user_id,
            "run_stop_failed",
            f"Stop refused for {len(refused)} position(s); the run remains open, managed, "
            "and retryable",
            run_id=run_id,
            severity="critical",
        )
        return {
            "ok": False,
            "stop_pending": True,
            "error": (
                f"{len(refused)} of {len(exits)} exit order(s) were refused. "
                "The run is still open and still managed; retry the stop."
            ),
            "exits": exits,
        }

    if still_held:
        return {"ok": True, "stop_pending": True, "exits": exits}

    # Revalidate under the live run lock immediately before the terminal
    # database CAS. This hold performs no I/O. Once ``stopping`` is true no new
    # signal claim can appear after it, and every pre-existing claim is counted
    # as possible exposure.
    with state.run_state(run_id) as live:
        if live is None:
            return {
                "ok": False,
                "stop_pending": True,
                "error": "The run remains open because its live state is unavailable",
                "exits": exits,
            }
        if _run_requires_management(live):
            return {"ok": True, "stop_pending": True, "exits": exits}

    persisted_reason = (
        current_row.stop_requested_reason
        if current_row is not None and current_row.stop_requested_reason
        else reason
    )
    finalised = _finalise(
        run_id,
        strategy_id,
        user_id,
        persisted_reason,
        f"Run stopped ({persisted_reason})",
    )
    if not finalised:
        return {
            "ok": False,
            "stop_pending": True,
            "error": "The run is flat but its final stop could not be persisted; retry the stop",
            "exits": exits,
        }
    return {"ok": True, "stop_pending": False, "exits": exits}


def reconcile_pending_stop(run_id: int) -> dict[str, Any] | None:
    """Continue a durable stop after an entry reaches a terminal fill state.

    Called by the fill/update path after releasing the run lock. ``None`` means
    no stop is pending; otherwise the ordinary stop contract is returned.
    """
    run_row = store.get_run(run_id)
    if run_row is None or run_row.stopped_at is not None or run_row.stop_requested_reason is None:
        return None
    strategy_id = int(run_row.strategy_id)
    stop_reason = str(run_row.stop_requested_reason)
    strategy_row = store.get_strategy_unscoped(strategy_id)
    if strategy_row is None:
        return {
            "ok": False,
            "stop_pending": True,
            "error": "The strategy owning this pending stop is unavailable",
            "exits": [],
        }
    user_id = str(strategy_row.user_id)
    return stop_run(
        run_id,
        user_id,
        reason=stop_reason or "manual",
    )


def manage_late_entry_correction(run_id: int) -> bool:
    """Restore and stop exposure discovered after a zero-fill finalisation.

    The broker fact is already durable before this function runs. Reopening,
    recovery, subscription and broker reconciliation all happen without a run
    lock; recovery installs a fresh managed state before the pending stop can
    dispatch an exact exit.
    """
    run_row = store.get_run(run_id)
    if run_row is None:
        return False
    strategy_id = int(run_row.strategy_id)
    strategy = store.get_strategy_unscoped(strategy_id)
    user_id = strategy.user_id if strategy is not None else ""

    if not store.reopen_run_for_late_entry_fill(run_id):
        _emit(
            strategy_id,
            user_id,
            "run_stop_failed",
            (
                "A late broker entry fill corrected a previously flat terminal fact, "
                "but the run could not be reopened. The durable fill requires immediate "
                "manual broker reconciliation."
            ),
            run_id=run_id,
            severity="critical",
        )
        return False

    from services.strategy_module import recovery

    recovered = recovery.recover_run(run_id)
    if not recovered.ok:
        _emit(
            strategy_id,
            user_id,
            "run_stop_failed",
            (
                "A late broker entry fill reopened this run, but its exposure could not "
                "be reconstructed automatically. Manual broker reconciliation is required."
            ),
            run_id=run_id,
            severity="critical",
        )
        return False

    snapshot = state.get_run_state(run_id)
    if snapshot is not None:
        _subscribe_run(run_id, list((snapshot.get("legs") or {}).values()))
    reconcile_pending_stop(run_id)
    return True


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
    strategy_id = int(run_row.strategy_id)
    run_mode = str(run_row.mode)

    strategy_row = store.get_strategy(strategy_id, user_id)
    if not strategy_row:
        return {"ok": False, "error": "Strategy not found"}
    strategy = store.strategy_to_dict(strategy_row)

    api_key = _api_key_for(user_id)
    if not api_key:
        return {"ok": False, "error": "No API key is configured for this user"}

    exits = _exit_legs(run_id, strategy, [leg_id], "exit_leg_manual", run_mode, api_key, user_id)
    if not exits:
        return {"ok": False, "error": "That leg is not open"}

    # Non-empty is not success: the per-leg flags carry whether the broker took
    # the order. Reporting a refused exit as closed tells an operator a
    # position is gone when it is still on the book.
    if not all(outcome.get("ok") for outcome in exits):
        errors = "; ".join(o.get("error") or "refused" for o in exits if not o.get("ok"))
        return {"ok": False, "error": f"Exit refused: {errors}", "exits": exits}

    _emit(
        strategy_id,
        user_id,
        "leg_close_manual",
        leg_close_requested_message(leg_id),
        run_id=run_id,
        leg_id=leg_id,
    )

    # Closing the last open leg leaves a running strategy holding nothing.
    with state.run_state(run_id) as run:
        still_open = bool(state.open_legs(run)) if run else False
    if not still_open:
        _finalise(run_id, strategy_id, user_id, "manual", "All legs closed")
        return {"ok": True, "exits": exits, "run_stopped": True}

    return {"ok": True, "exits": exits, "run_stopped": False}


def _finalise(run_id: int, strategy_id: int, user_id: str, reason: str, message: str) -> bool:
    """Close the run row, release the strategy, and drop the live state.

    Peak and trough are read out of the live state and written on every path.
    The original passes them on only one of its several stop paths, so a run
    closed by an overall stop, a target, a lock-profit floor, the scheduler or
    the kill switch recorded both as zero.
    """
    # The terminal eligibility check and figure capture are one in-memory
    # critical section. No query, emit, unsubscribe or broker work occurs
    # while the run lock is held. A durably stopping run refuses new entry
    # claims, so a flat check here remains valid until the CAS directly below.
    with state.run_state(run_id) as live:
        if live is not None and _run_requires_management(live):
            return False
        snapshot = {
            "pnl_realized": (live or {}).get("pnl_realized", 0.0) or 0.0,
            "pnl_peak": (live or {}).get("pnl_peak", 0.0) or 0.0,
            "pnl_trough": (live or {}).get("pnl_trough", 0.0) or 0.0,
        }

    finished = store.finish_run_and_release_strategy(
        run_id,
        strategy_id,
        stop_reason=reason,
        pnl_realized=snapshot["pnl_realized"],
        pnl_peak=snapshot["pnl_peak"],
        pnl_trough=snapshot["pnl_trough"],
    )
    if not finished:
        # A corrected older run can be managed beside a newer current run. It
        # owns only its run row in that case; the guarded fallback may close
        # that residual but cannot release or relabel the newer strategy.
        finished = store.finish_detached_run(
            run_id,
            strategy_id,
            stop_reason=reason,
            pnl_realized=snapshot["pnl_realized"],
            pnl_peak=snapshot["pnl_peak"],
            pnl_trough=snapshot["pnl_trough"],
        )
    if not finished:
        return False

    try:
        _emit(strategy_id, user_id, "run_stopped", message, run_id=run_id)
        # The final figures, forced past the throttle: without it the page is
        # left frozen one tick short of the truth for the rest of the day.
        _push_delta(run_id, force=True)
        try:
            from services.strategy_module import broadcast

            broadcast.push_terminal(strategy_id, run_id, reason, snapshot["pnl_realized"])
        except Exception:
            logger.exception("Could not push the terminal frame for run %s", run_id)
    finally:
        _unactionable_runs.discard(run_id)
        # Cleanup belongs only to the transactional winner, even when an
        # optional event/broadcast fails afterwards.
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
    return True


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
    strategy_id = int(run_row.strategy_id)
    run_mode = str(run_row.mode)
    # Unscoped on purpose: the engine reaches a strategy through a run it is
    # already executing, so there is no user in scope to filter by and the run
    # row is the authority on which strategy it belongs to.
    strategy_row = store.get_strategy_unscoped(strategy_id)
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
            if stop_reason == "overall_sl":
                threshold = -abs(float(strategy["overall_sl_mtm"]))
            elif stop_reason == "overall_target":
                threshold = float(strategy["overall_target_mtm"])
            else:
                # A lock-profit breach is judged against the ratcheted floor
                # returned by this exact aggregate evaluation, not merely the
                # strategy's configured starting floor.
                threshold = float(aggregate.lock_floor)
            breach_payload = {
                "trigger_total": round(float(aggregate.total_pnl), 2),
                "reason": stop_reason,
                "threshold": round(threshold, 2),
                "triggering_tick": {
                    "symbol": symbol,
                    "exchange": exchange,
                    "ltp": float(ltp),
                },
                # This is the exact latest-known mark set present during the
                # decision. It deliberately carries no invented timestamps.
                "legs": [
                    {
                        "symbol": str(leg.get("symbol") or ""),
                        "exchange": str(leg.get("exchange") or ""),
                        "ltp": (float(leg["ltp"]) if leg.get("ltp") is not None else None),
                        "mtm": round(float(leg.get("mtm") or 0.0), 2),
                        "tick_source": str(leg.get("tick_source") or ""),
                        "qty": int(leg.get("qty") or 0),
                        "position": str(leg.get("position") or ""),
                    }
                    for leg in run.get("legs", {}).values()
                    if leg.get("status") == "open" or leg.get("realized_pnl")
                ],
            }
            events.append(
                (
                    {
                        "overall_sl": "overall_sl_hit",
                        "overall_target": "overall_target_hit",
                        "lock_profit": "lock_profit_triggered",
                    }[stop_reason],
                    aggregate.detail,
                    {"severity": "warn", "payload": breach_payload},
                )
            )

    # Lock released. Everything below reaches the database or the broker.
    _push_delta(run_id)

    for kind, message, extra in events:
        severity = extra.pop("severity", "info")
        _emit(strategy["id"], user_id, kind, message, run_id=run_id, severity=severity, **extra)

    if stop_reason:
        # A strategy-level breach closes everything, so the per-leg exits it
        # would also have triggered are redundant.
        result = stop_run(run_id, user_id, reason=stop_reason)
        if result.get("ok"):
            _note_actionable_again(strategy["id"], user_id, run_id)
        return

    api_key = _api_key_for(user_id)
    if not api_key:
        _note_unactionable(strategy["id"], user_id, run_id, leg_exits, stop_reason)
        return

    _note_actionable_again(strategy["id"], user_id, run_id)

    for leg_id, kind in leg_exits:
        _exit_legs(run_id, strategy, [leg_id], kind, run_mode, api_key, user_id)
