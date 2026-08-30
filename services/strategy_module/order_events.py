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
    """Record that an exit died after its run closed, so a held position is not silent.

    A stop finalises as soon as the broker accepts its exits rather than
    waiting for the fills, so a rejection arriving afterwards finds no run
    state to put right. Nothing can be retried automatically from here: the
    event log is the one place left that an operator reads.
    """
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
            store.update_order(
                row.id,
                status="complete",
                avg_fill_price=avg_price,
                filled_qty=filled_qty,
            )
            price = _usable_price(avg_price)
            if price is not None:
                from services.strategy_module import engine

                engine.apply_fill(
                    run_id,
                    leg_id,
                    price,
                    is_entry=is_entry,
                    filled_qty=_whole_qty(filled_qty),
                    # Which order this fill is for. A signal flip leaves one
                    # leg id naming two positions for as long as the closing
                    # order is unfilled, and only the order id separates them.
                    order_row_id=row.id,
                )
            else:
                # A fill with no usable price cannot seed a stop or a realized
                # figure. Recorded, but deliberately not applied to the run.
                logger.warning(
                    "Order %s reported filled with an unusable average price %r; leg %s not marked",
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
            store.update_order(row.id, status=ended, reject_reason=rejection)
            logger.warning("Strategy order %s ended as %s", order_id, status)

            # An order that dies after the dispatch returned has to undo what
            # the dispatch claimed, or the leg is stranded. The synchronous
            # refusal path already does this; nothing did it for a rejection or
            # cancellation that arrived later.
            from services.strategy_module import state

            if is_entry:
                # The entry will never fill, so the leg is not a position. Left
                # as "open" it is exited by the next square-off, which sends a
                # full-size order against nothing.
                with state.run_state(run_id) as run:
                    leg = run["legs"].get(str(leg_id)) if run else None
                    if leg is not None and leg.get("entry_status") != "complete":
                        leg["entry_status"] = ended
                        leg["status"] = "rejected"
            elif state.release_superseded_exit(run_id, leg_id, row.id):
                # This closed the outgoing side of a flip, and it was refused.
                # Both sides are on the book now: the leg describes the new
                # one, and the old one is held with its exit dead. Cleared so
                # it can be closed again, and said out loud because nothing
                # else will notice.
                logger.warning(
                    "The exit for the outgoing side of a flip on leg %s was %s; that position "
                    "is still held",
                    leg_id,
                    ended,
                )
                _report_stranded_exit(run_id, leg_id, row, ended)
            elif state.get_run_state(run_id) is not None:
                # Release the exit claim so the position stays exitable. Held,
                # its stop loss, its target, the scheduler's square-off and the
                # operator's Close button all pass over a position the broker
                # still holds, for the rest of the session.
                state.release_leg_exit(run_id, leg_id)
            else:
                # The run has already finalised, which is what a stop does as
                # soon as its exits are accepted. There is nothing left to
                # release and nothing still managing this leg, so the position
                # is real, uncovered, and invisible unless it is said out loud.
                _report_stranded_exit(run_id, leg_id, row, ended)
            return

        # Anything else is still working. Recorded so the audit trail follows
        # the order, but it changes nothing the engine acts on.
        if not already_terminal and status:
            store.update_order(row.id, status="open", filled_qty=filled_qty)
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
