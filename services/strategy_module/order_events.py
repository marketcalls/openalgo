"""Turns broker order updates into strategy state, without polling.

A strategy places an order and then needs to know when it filled and at what
price: the fill price is what every stop, target and trailing stop is measured
from, and until it arrives a leg cannot be evaluated at all.

The platform already knows. ``services/order_update_service.py`` publishes an
``OrderUpdateEvent`` on the in-process event bus for every asynchronous status
change, live or sandbox, before relaying it to the account-level websocket
stream. This module subscribes to that once and applies what it hears, which is
why nothing here polls ``getOrderStatus`` in a loop.

It follows the shape of ``services/flow_order_update_monitor_service.py``: one
singleton, one subscription, and a shared bounded pool rather than a thread per
event. A basket fills leg by leg, so updates arrive in bursts.

Two properties this module owes the rest of the engine:

**Cheap for other people's orders.** Most updates belong to another surface.
Deciding that costs one indexed lookup and nothing else.

**A fill is applied exactly once.** The same fill can arrive twice, from a
broker postback and from the order-update stream. Applying it twice would add
the leg's realized profit to the run a second time, and the strategy would then
be judged against a total it never made. The order row's own status is the
guard: a fill is applied only on the transition into a filled state.
"""

from __future__ import annotations

import atexit
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from cachetools import TTLCache

from database import strategy_module_db as store
from utils.env_config import env_int
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)

# Shared and bounded, never a thread per event. Each task touches the database
# and the run state, and a filling basket delivers a burst of updates. A
# module-level pool caps that concurrency and reuses its threads for the life
# of the worker rather than creating one per fill.
_POOL = ThreadPoolExecutor(
    max_workers=env_int("STRATEGY_ORDER_UPDATE_WORKERS", 4, minimum=1),
    thread_name_prefix="strategy-order-update",
)

# Broker vocabularies differ. These are the states that mean "this order is
# done and it traded", normalised the same way recovery normalises them.
_FILLED = frozenset({"complete", "completed", "filled", "executed", "traded"})
_DEAD = frozenset({"rejected", "cancelled", "canceled"})
_CANCELLED = frozenset({"cancelled", "canceled"})


def _usable_price(value: Any) -> float | None:
    """A strictly positive finite price, or None.

    The guard here used to be a truthiness test, which several brokers defeat
    simply by sending numerics as strings: "0" is truthy, so a fill at no price
    was applied as a fill at zero, and the leg was marked complete with an
    entry of 0.0. stop_from_points refuses a non-positive entry, so that leg
    then had no stop at all while the UI, the audit trail and the operator all
    read it as a filled, managed position. A negative was written straight on.

    services.risk.models.is_price is the same predicate the risk core applies
    to a tick, used here so a fill cannot enter by a door a tick could not.
    """
    from services.risk.models import is_price

    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if is_price(price) else None


def _whole_qty(value: Any) -> int | None:
    """A positive whole quantity, or None when the broker did not say."""
    try:
        qty = int(float(value))
    except (TypeError, ValueError):
        return None
    return qty if qty > 0 else None


_lock = threading.Lock()
_started = False


def _normalise(status: Any) -> str:
    return str(status or "").strip().lower().replace("_", " ")


def start() -> bool:
    """Subscribe to order updates. Idempotent; safe to call at every boot.

    Not called at import: a module that starts listening merely because
    something imported it makes any tool that touches the app a live consumer.
    """
    global _started
    with _lock:
        if _started:
            return False
        bus.subscribe("order.update", _on_order_update, name="StrategyOrderUpdates")
        _started = True
        atexit.register(_shutdown_pool)
        logger.info("Strategy module subscribed to order updates")
        return True


def _shutdown_pool() -> None:
    _POOL.shutdown(wait=False, cancel_futures=True)


#: Updates that arrived before their order row existed, keyed by broker order
#: id. Small and short-lived on purpose: the window this covers is the few
#: milliseconds between a dispatch returning and its row being committed.
_pending_updates: TTLCache = TTLCache(maxsize=512, ttl=120)


def replay_for(order_id: str | None) -> None:
    """Apply an update that arrived before this order's row was written.

    Called by the engine straight after it records an order, which is the
    moment the update becomes matchable. A no-op when nothing was held, which
    is the normal case for a broker that answers before it fills.
    """
    if not order_id:
        return
    event = _pending_updates.pop(str(order_id), None)
    if event is None:
        return
    logger.debug("Replaying an order update that arrived before its row: %s", order_id)
    _apply_update(str(order_id), event)


def _report_stranded_exit(run_id: int, leg_id: Any, row: Any, ended: str) -> None:
    """Legacy guard for an exit that dies after its run has already closed."""
    try:
        run = store.get_run(run_id)
        if run is None:
            return
        strategy = store.get_strategy_unscoped(run.strategy_id)
        if strategy is None:
            return
        store.record_event(
            run.strategy_id,
            strategy.user_id,
            "run_stop_failed",
            (
                f"Exit order {row.broker_order_id} for leg {leg_id} was {ended} after the run "
                f"had already closed. The {row.action} of {row.qty} {row.symbol} did not happen, "
                "so that position is still held and nothing is managing it."
            ),
            run_id=run_id,
            leg_id=leg_id,
            severity="critical",
        )
    except Exception:
        logger.exception("Could not record a stranded exit for run %s leg %s", run_id, leg_id)


def report_flip_outgoing_exit_rejected(
    run_id: int,
    leg_id: Any,
    ended: str,
    broker_order_id: str | None = None,
) -> None:
    """Record that an active flip still manages its retryable outgoing side."""
    try:
        run = store.get_run(run_id)
        if run is None or run.stopped_at is not None:
            return
        strategy = store.get_strategy_unscoped(run.strategy_id)
        if strategy is None:
            return
        store.record_event(
            run.strategy_id,
            strategy.user_id,
            "flip_outgoing_exit_rejected",
            (
                f"Outgoing exit{f' order {broker_order_id}' if broker_order_id else ''} for "
                f"leg {leg_id} was {ended}. The old side is still held, remains managed, "
                "and is retryable."
            ),
            run_id=run_id,
            leg_id=leg_id,
            severity="critical",
        )
    except Exception:
        logger.exception(
            "Could not record an outgoing flip rejection for run %s leg %s", run_id, leg_id
        )


def report_pending_stop_exit_failed(
    run_id: int,
    leg_id: Any,
    ended: str,
    broker_order_id: str | None = None,
) -> None:
    """Record that a pending stop still owns a retryable held position."""
    try:
        run = store.get_run(run_id)
        if run is None or run.stopped_at is not None or run.stop_requested_reason is None:
            return
        strategy = store.get_strategy_unscoped(run.strategy_id)
        if strategy is None:
            return
        store.record_event(
            run.strategy_id,
            strategy.user_id,
            "run_stop_failed",
            (
                f"Stop exit{f' order {broker_order_id}' if broker_order_id else ''} for leg "
                f"{leg_id} was {ended}. The position remains open and managed, and the stop "
                "is retryable."
            ),
            run_id=run_id,
            leg_id=leg_id,
            severity="critical",
        )
    except Exception:
        logger.exception("Could not record a pending-stop exit failure for run %s", run_id)


def _report_unpriced_fill(
    run_id: int,
    leg_id: Any,
    broker_order_id: str,
    filled_qty: int,
    *,
    is_entry: bool,
) -> None:
    """Record exposure whose exact quantity is known but valuation is not."""
    try:
        run = store.get_run(run_id)
        if run is None or run.stopped_at is not None:
            return
        strategy = store.get_strategy_unscoped(run.strategy_id)
        if strategy is None:
            return
        store.record_event(
            run.strategy_id,
            strategy.user_id,
            "leg_entry_placed" if is_entry else "leg_exit_placed",
            (
                f"Broker order {broker_order_id} reports {filled_qty} filled on leg {leg_id} "
                "without a usable average price. The exact remaining exposure is still "
                "managed, but risk valuation and realized P&L are unavailable; reconcile "
                "the broker fill price."
            ),
            run_id=run_id,
            leg_id=leg_id,
            severity="critical",
        )
    except Exception:
        logger.exception("Could not record an unpriced fill for run %s leg %s", run_id, leg_id)


def _exit_owner_for_row(
    run_id: int, leg_id: Any, row_id: int, position_ref: str | None
) -> str | None:
    """Identify the exact owner before a terminal partial mutates it."""
    from services.strategy_module import state

    snapshot = state.get_run_state(run_id)
    leg = (snapshot.get("legs") or {}).get(str(leg_id)) if snapshot else None
    if leg is None:
        return None
    superseded = leg.get("superseded")
    if (
        superseded
        and superseded.get("exit_order_id") == row_id
        and (position_ref is None or superseded.get("position_ref") == position_ref)
    ):
        return "superseded"
    if leg.get("exit_order_id") == row_id and (
        position_ref is None or leg.get("position_ref") == position_ref
    ):
        return "live"
    return None


def _on_order_update(event: Any) -> None:
    """Bus callback. Returns immediately; the work happens on the pool.

    Kept trivial on purpose. The bus dispatches every subscriber, so anything
    slow here delays the others, and this one is called for every order the
    platform places.
    """
    try:
        order_id = getattr(event, "orderid", "")
        if not order_id:
            return
        _POOL.submit(_apply_update, order_id, event)
    except Exception:
        logger.exception("Could not queue an order update")


def _push_fill(run_id: int, order: dict[str, Any] | None) -> None:
    """Push an order row and the figures it changed. Never raises."""
    try:
        from services.strategy_module import broadcast

        run = store.get_run(run_id)
        if run is None:
            return
        if order:
            broadcast.push_order_update(run.strategy_id, order)
        broadcast.push_delta(run_id, force=True)
    except Exception:
        logger.exception("Could not push a fill for run %s", run_id)


def _apply_update(order_id: str, event: Any) -> None:
    """Match the update to a strategy order and apply it."""
    try:
        row = store.get_order_by_broker_id(order_id)
        if row is None:
            # Either somebody else's order, which is the overwhelmingly common
            # case, or ours a moment too early. The engine dispatches and only
            # then records the row, and the sandbox executes a MARKET order
            # synchronously inside the dispatch call, so its fill is published
            # while no row carries that broker id yet. Dropping it there is not
            # a rare race in sandbox: it happens every time, and the leg keeps
            # an entry of zero, which means no stop, no target and no mark to
            # market. A live broker whose fill beats the insert lands in the
            # same place.
            #
            # Held briefly instead, and replayed by replay_for() the moment the
            # row appears. Bounded in both size and time, so the updates that
            # really do belong to other surfaces cost a capped amount of memory
            # and expire on their own.
            _pending_updates[order_id] = event
            return

        status = _normalise(getattr(event, "order_status", ""))
        filled_qty = getattr(event, "filled_quantity", None)
        avg_price = getattr(event, "average_price", None)
        rejection = getattr(event, "rejection_reason", "") or None

        # Read the row's current state before writing, so the transition can be
        # detected. Anything already terminal is left alone: a fill applied
        # twice would add its realized profit to the run a second time.
        already_terminal = _normalise(row.status) in _FILLED or _normalise(row.status) in _DEAD
        run_id = row.run_id
        leg_id = row.leg_id
        is_entry = row.kind == "entry"

        if status in _FILLED:
            if already_terminal:
                logger.debug("Ignoring a repeat fill for order %s", order_id)
                return
            if not store.transition_order_terminal(
                row.id,
                status="complete",
                avg_fill_price=avg_price,
                filled_qty=filled_qty,
            ):
                return
            price = _usable_price(avg_price)
            quantity = _whole_qty(filled_qty)
            if price is not None or quantity is not None:
                from services.strategy_module import engine

                fill_identity = {"position_ref": row.position_ref} if row.position_ref else {}
                engine.apply_fill(
                    run_id,
                    leg_id,
                    price,
                    is_entry=is_entry,
                    filled_qty=quantity,
                    # New rows name the position incarnation directly. The
                    # row id remains the fallback for legacy NULL references.
                    order_row_id=row.id,
                    **fill_identity,
                )
                if price is None and quantity is not None:
                    _report_unpriced_fill(
                        run_id,
                        leg_id,
                        order_id,
                        quantity,
                        is_entry=is_entry,
                    )
            else:
                # Neither price nor quantity supplied a usable fill fact.
                logger.warning(
                    "Order %s reported filled without usable quantity or average price %r; "
                    "leg %s not marked",
                    order_id,
                    avg_price,
                    leg_id,
                )

            # A fill is a one-off: no later frame carries it, so both go out
            # regardless of the delta throttle. Sent for a priceless fill too,
            # because the order row still changed and the page should show it.
            _push_fill(run_id, store.order_to_dict(store.get_order_by_broker_id(order_id)))
            return

        if status in _DEAD:
            if already_terminal:
                return
            # A cancel is not a rejection. store.ORDER_STATUSES carries both
            # and recovery.normalise_order_status already distinguishes them,
            # so collapsing them here only loses audit accuracy.
            ended = "cancelled" if status in _CANCELLED else "rejected"
            terminal_qty = None
            terminal_price = None
            durable_qty = filled_qty
            durable_price = avg_price
            # Terminal frames commonly send zeroes for fields already
            # reported by an earlier partial update. Preserve the durable
            # positive facts rather than overwriting real exposure or a real
            # reduction with the dead remainder's zero values.
            terminal_qty = _whole_qty(filled_qty) or _whole_qty(row.filled_qty)
            terminal_price = _usable_price(avg_price) or _usable_price(row.avg_fill_price)
            if terminal_qty is not None:
                durable_qty = terminal_qty
            if terminal_price is not None:
                durable_price = terminal_price
            if not store.transition_order_terminal(
                row.id,
                status=ended,
                avg_fill_price=durable_price,
                filled_qty=durable_qty,
                reject_reason=rejection,
            ):
                return
            logger.warning("Strategy order %s ended as %s", order_id, status)

            # An order that dies after the dispatch returned has to undo what
            # the dispatch claimed, or the leg is stranded. The synchronous
            # refusal path already does this; nothing did it for a rejection or
            # cancellation that arrived later.
            from services.strategy_module import state

            if is_entry:
                if terminal_qty is not None:
                    # A cancelled/rejected remainder does not erase what
                    # already traded. Quantity alone proves exposure; price is
                    # optional valuation metadata. Install the actual fill,
                    # then let pending-stop reconciliation claim that quantity.
                    from services.strategy_module import engine

                    fill_identity = {"position_ref": row.position_ref} if row.position_ref else {}
                    engine.apply_fill(
                        run_id,
                        leg_id,
                        terminal_price,
                        is_entry=True,
                        filled_qty=terminal_qty,
                        order_row_id=row.id,
                        **fill_identity,
                    )
                    if terminal_price is None:
                        _report_unpriced_fill(
                            run_id,
                            leg_id,
                            order_id,
                            terminal_qty,
                            is_entry=True,
                        )
                else:
                    # Zero fill: the entry will never become a position. Mark
                    # it flat under the state lock, then reconcile a pending
                    # stop after releasing the lock so its terminal CAS can run.
                    with state.run_state(run_id) as run:
                        leg = run["legs"].get(str(leg_id)) if run else None
                        owns_entry = leg is not None and (
                            row.position_ref is None or leg.get("position_ref") == row.position_ref
                        )
                        if owns_entry and leg.get("entry_status") != "complete":
                            leg["entry_status"] = ended
                            leg["status"] = "rejected"

                    from services.strategy_module import engine

                    engine.reconcile_pending_stop(run_id)
            else:
                exit_owner = _exit_owner_for_row(run_id, leg_id, row.id, row.position_ref)
                if terminal_qty is not None:
                    from services.strategy_module import engine

                    fill_identity = {"position_ref": row.position_ref} if row.position_ref else {}
                    engine.apply_fill(
                        run_id,
                        leg_id,
                        terminal_price,
                        is_entry=False,
                        filled_qty=terminal_qty,
                        order_row_id=row.id,
                        **fill_identity,
                    )
                    if terminal_price is None:
                        _report_unpriced_fill(
                            run_id,
                            leg_id,
                            order_id,
                            terminal_qty,
                            is_entry=False,
                        )
                else:
                    exit_owner = state.release_order_exit(
                        run_id,
                        leg_id,
                        row.id,
                        row.position_ref,
                    )
                if exit_owner == "superseded":
                    # This closed the outgoing side of a flip, and it was
                    # refused. Both sides are on the book now: the leg
                    # describes the new one, and the old one is held with its
                    # exit dead. Cleared so it can be retried and said out loud.
                    logger.warning(
                        "The exit for the outgoing side of a flip on leg %s was %s; that "
                        "position is still held",
                        leg_id,
                        ended,
                    )
                    report_flip_outgoing_exit_rejected(run_id, leg_id, ended, row.broker_order_id)
                report_pending_stop_exit_failed(run_id, leg_id, ended, row.broker_order_id)
                if exit_owner is None and state.get_run_state(run_id) is None:
                    # The run has already finalised. There is nothing left to
                    # release and nothing still managing this leg, so the
                    # position is real and invisible unless said out loud.
                    _report_stranded_exit(run_id, leg_id, row, ended)
            return

        # Anything else is still working. Recorded so the audit trail follows
        # the order, but it changes nothing the engine acts on.
        if not already_terminal and status:
            store.update_order(
                row.id,
                status="open",
                avg_fill_price=avg_price,
                filled_qty=filled_qty,
            )
    except Exception:
        logger.exception("Could not apply order update %s", order_id)
    finally:
        # A pool worker gets no Flask app context, so teardown_appcontext never
        # fires and the scoped sessions this touched would leak (issue #1738).
        try:
            from utils.db_sessions import remove_all_scoped_sessions

            remove_all_scoped_sessions()
        except Exception:
            logger.exception("Could not release scoped sessions after an order update")
