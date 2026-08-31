"""Turns broker order updates and targeted reconciliation facts into strategy state.

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


def apply_order_snapshot(broker_order_id: str, order: dict[str, Any]) -> None:
    """Fold one targeted order-status/orderbook response through the push path.

    Pending-stop reconciliation calls this after a cancellation attempt. The
    common event shape keeps the durable CAS, cumulative quantity fold and
    state mutation in one place rather than introducing another broker-status
    implementation inside the engine.
    """
    from events import OrderUpdateEvent

    def value(*keys: str, default: Any = None) -> Any:
        for key in keys:
            if key in order and order.get(key) is not None:
                return order.get(key)
        return default

    order_id = str(value("orderid", "order_id", default=broker_order_id) or broker_order_id)
    event = OrderUpdateEvent(
        orderid=order_id,
        symbol=str(value("symbol", default="") or ""),
        exchange=str(value("exchange", default="") or ""),
        action=str(value("action", default="") or ""),
        quantity=int(value("quantity", "qty", default=0) or 0),
        order_status=str(value("order_status", "orderstatus", "status", default="") or ""),
        filled_quantity=int(
            value("filled_quantity", "filledqty", "filled_qty", default=0) or 0
        ),
        pending_quantity=int(
            value("pending_quantity", "pendingqty", "pending_qty", default=0) or 0
        ),
        average_price=float(
            value("average_price", "averageprice", "avg_fill_price", default=0) or 0
        ),
        rejection_reason=str(
            value("rejection_reason", "reject_reason", default="") or ""
        ),
    )
    _apply_update(order_id, event)


def _report_stranded_exit(
    run_id: int,
    leg_id: Any,
    ended: str,
    *,
    broker_order_id: str | None,
    action: str,
    qty: int,
    symbol: str,
) -> None:
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
                f"Exit order {broker_order_id} for leg {leg_id} was {ended} after the run "
                f"had already closed. The {action} of {qty} {symbol} did not happen, "
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
    """Record a durable broker quantity whose valuation cannot be verified."""
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
            "leg_entry_placed" if is_entry else "leg_exit_placed",
            (
                f"Broker order {broker_order_id} reports {filled_qty} filled on leg {leg_id} "
                "without a usable average price. The broker-reported quantity is durable "
                "and must be managed as authoritative, but valuation and realized P&L for "
                "this fill are unverifiable; reconcile the broker fill price."
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


def _exit_owner_still_held(
    run_id: int,
    leg_id: Any,
    exit_owner: str | None,
    position_ref: str | None,
) -> bool:
    """Whether the exact pre-fill owner still has a positive managed quantity."""
    if exit_owner not in {"live", "superseded"}:
        return False

    from services.strategy_module import state

    snapshot = state.get_run_state(run_id)
    leg = (snapshot.get("legs") or {}).get(str(leg_id)) if snapshot else None
    if leg is None:
        return False
    owner = leg if exit_owner == "live" else leg.get("superseded")
    if owner is None:
        return False
    if position_ref is not None and owner.get("position_ref") != position_ref:
        return False
    if exit_owner == "live" and owner.get("status") != "open":
        return False
    try:
        return int(float(owner.get("qty") or 0)) > 0
    except (TypeError, ValueError):
        return False


def _incremental_fill_price(fold: store.OrderFactFold) -> float | None:
    """Derive the price of only the newly reported cumulative fill delta."""
    if fold.fill_delta <= 0:
        return None
    cumulative_price = _usable_price(fold.average_fill_price)
    if cumulative_price is None:
        return None
    previous_price = _usable_price(fold.previous_average_fill_price)
    if fold.previous_filled_qty <= 0 or previous_price is None:
        return cumulative_price
    incremental_notional = (
        cumulative_price * fold.cumulative_filled_qty
        - previous_price * fold.previous_filled_qty
    )
    return _usable_price(incremental_notional / fold.fill_delta)


def _working_retry_for_position(
    run_id: int,
    leg_id: Any,
    position_ref: str | None,
    source_order_id: int,
) -> int | None:
    """Return a different in-flight exit row now owning this position."""
    if position_ref is None:
        return None
    from services.strategy_module import state

    snapshot = state.get_run_state(run_id)
    leg = (snapshot.get("legs") or {}).get(str(leg_id)) if snapshot else None
    if leg is None:
        return None
    owners = [leg, leg.get("superseded")]
    for owner in owners:
        if not owner or owner.get("position_ref") != position_ref:
            continue
        retry_id = owner.get("exit_order_id")
        if retry_id is not None and retry_id != source_order_id:
            return int(retry_id)
    return None


def _cancel_working_retry(run_id: int, retry_order_id: int) -> bool:
    """Cancel a retry made unsafe by a higher fill correction.

    All database, credential and broker work happens after the state snapshot
    and therefore outside the run lock. Ownership remains armed until the
    broker's terminal cancellation frame arrives.
    """
    retry = store.get_order(retry_order_id)
    run = store.get_run(run_id)
    if retry is None or run is None or not retry.broker_order_id:
        return False
    broker_order_id = str(retry.broker_order_id)
    leg_id = retry.leg_id
    strategy_id = int(run.strategy_id)
    run_mode = str(run.mode)
    stop_pending = run.stop_requested_reason is not None
    strategy = store.get_strategy_unscoped(strategy_id)
    if strategy is None:
        return False
    user_id = str(strategy.user_id)

    from services.strategy_module import engine

    api_key = engine._api_key_for(user_id)
    if not api_key:
        result = None
        error = "the OpenAlgo API key is unavailable"
    else:
        result = engine.order_dispatch.cancel_exit_order(
            mode=run_mode,
            api_key=api_key,
            broker_order_id=broker_order_id,
        )
        error = result.error or "the broker refused cancellation"
    if result is not None and result.ok:
        return True

    try:
        store.record_event(
            strategy_id,
            user_id,
            "run_stop_failed" if stop_pending else "leg_exit_rejected",
            (
                f"A higher fill correction made retry order {broker_order_id} too large, "
                f"but it could not be cancelled because {error}. Its position remains managed; "
                "verify the broker order immediately to prevent reversal."
            ),
            run_id=run_id,
            leg_id=leg_id,
            severity="critical",
        )
    except Exception:
        logger.exception("Could not record failed correction cancellation for run %s", run_id)
    return False


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

        broker_status = _normalise(getattr(event, "order_status", ""))
        if broker_status in _FILLED:
            canonical_status = "complete"
        elif broker_status in _CANCELLED:
            canonical_status = "cancelled"
        elif broker_status in _DEAD:
            canonical_status = "rejected"
        else:
            canonical_status = "open"
        incoming_qty = _whole_qty(getattr(event, "filled_quantity", None))
        incoming_price = _usable_price(getattr(event, "average_price", None))
        rejection = getattr(event, "rejection_reason", "") or None

        run_id = row.run_id
        leg_id = row.leg_id
        is_entry = row.kind == "entry"
        row_id = row.id
        position_ref = row.position_ref
        broker_order_id = row.broker_order_id
        order_action = str(row.action)
        order_qty = int(row.qty)
        order_symbol = str(row.symbol)

        fold = store.fold_order_broker_frame(
            row_id,
            status=canonical_status,
            avg_fill_price=incoming_price,
            filled_qty=incoming_qty,
            reject_reason=rejection,
        )
        if fold is None or not fold.changed:
            return

        from services.strategy_module import engine, state

        exit_owner = (
            None
            if is_entry
            else _exit_owner_for_row(run_id, leg_id, row_id, position_ref)
        )
        should_apply = fold.fill_delta > 0 or (
            fold.terminal and fold.cumulative_filled_qty > 0
        )
        run_row = store.get_run(run_id) if is_entry and fold.fill_delta > 0 else None
        late_entry_correction = bool(run_row is not None and run_row.stopped_at is not None)
        if should_apply:
            price = (
                _usable_price(fold.average_fill_price)
                if is_entry
                else _incremental_fill_price(fold)
            )
            fill_identity = {"position_ref": position_ref} if position_ref else {}
            fill_options: dict[str, Any] = {}
            if is_entry and (not fold.terminal or fold.previous_filled_qty > 0):
                fill_options["cumulative_filled_qty"] = fold.cumulative_filled_qty
            if not fold.terminal:
                fill_options["order_terminal"] = False
            if fold.was_terminal:
                fill_options["allow_prior_order_correction"] = True
            if late_entry_correction:
                engine.manage_late_entry_correction(run_id)
            else:
                engine.apply_fill(
                    run_id,
                    leg_id,
                    price,
                    is_entry=is_entry,
                    filled_qty=fold.fill_delta,
                    order_row_id=row_id,
                    **fill_identity,
                    **fill_options,
                )
            if fold.fill_delta > 0 and price is None:
                _report_unpriced_fill(
                    run_id,
                    leg_id,
                    order_id,
                    fold.cumulative_filled_qty,
                    is_entry=is_entry,
                )

            if not is_entry and fold.was_terminal and fold.fill_delta > 0:
                retry_id = _working_retry_for_position(
                    run_id,
                    leg_id,
                    position_ref,
                    row_id,
                )
                if retry_id is not None:
                    _cancel_working_retry(run_id, retry_id)

        incoming_dead_transition = canonical_status in {"cancelled", "rejected"} and (
            not fold.was_terminal
        )
        if incoming_dead_transition:
            ended = canonical_status
            logger.warning("Strategy order %s ended as %s", order_id, ended)
            if is_entry and fold.cumulative_filled_qty <= 0:
                # Zero fill: the entry will never become a position. Mark it
                # flat under the state lock, then reconcile the pending stop
                # only after releasing the lock.
                with state.run_state(run_id) as run:
                    leg = run["legs"].get(str(leg_id)) if run else None
                    owns_entry = leg is not None and (
                        position_ref is None or leg.get("position_ref") == position_ref
                    )
                    if owns_entry and leg.get("entry_status") != "complete":
                        leg["entry_status"] = ended
                        leg["status"] = "rejected"
                engine.reconcile_pending_stop(run_id)
            elif not is_entry:
                if not should_apply:
                    exit_owner = state.release_order_exit(
                        run_id,
                        leg_id,
                        row_id,
                        position_ref,
                    )
                owner_still_held = _exit_owner_still_held(
                    run_id,
                    leg_id,
                    exit_owner,
                    position_ref,
                )
                if exit_owner == "superseded" and owner_still_held:
                    logger.warning(
                        "The exit for the outgoing side of a flip on leg %s was %s; that "
                        "position is still held",
                        leg_id,
                        ended,
                    )
                    report_flip_outgoing_exit_rejected(
                        run_id,
                        leg_id,
                        ended,
                        broker_order_id,
                    )
                if owner_still_held:
                    report_pending_stop_exit_failed(
                        run_id,
                        leg_id,
                        ended,
                        broker_order_id,
                    )
                if (
                    fold.cumulative_filled_qty <= 0
                    and exit_owner is None
                    and state.get_run_state(run_id) is None
                ):
                    _report_stranded_exit(
                        run_id,
                        leg_id,
                        ended,
                        broker_order_id=broker_order_id,
                        action=order_action,
                        qty=order_qty,
                        symbol=order_symbol,
                    )

        if fold.fill_delta > 0 or fold.terminal:
            durable = store.get_order_by_broker_id(order_id)
            _push_fill(run_id, store.order_to_dict(durable) if durable is not None else None)
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
