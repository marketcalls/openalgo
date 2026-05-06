"""Position tracker — event-driven reconciler that keeps strategy_orders /
strategy_trades / strategy_positions in sync with broker reality.

Subscribes to two event streams:

  1. order.placed / order.failed / order.cancelled  (existing OrderEvent)
       Fired by services/place_order_service.py et al. when the broker
       accepts/rejects/cancels an order. The orderid links back to the
       strategy_orders row written by execution_service.py.

  2. broker.order_update  (new BrokerOrderUpdateEvent)
       Fired by order_update_channel (Phase 5) when the broker pushes a
       state change via WS or when poll-fallback reconciles. Carries
       fill quantity + average price, so this is where strategy_trades
       rows are inserted.

When a fill lands:
  - strategy_orders.order_status updated to 'complete'
  - strategy_trades row inserted with fill details
  - strategy_positions recomputed: net_qty, avg_entry, realized_pnl
  - StrategyLegFilledEvent published — the engine subscribes to advance the
    leg state PENDING_ENTRY -> OPEN

The engine NEVER inserts into strategy_orders / strategy_trades /
strategy_positions directly — execution_service writes the initial
strategy_orders row at place-time; everything after that flows through
this module.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import update

from database.strategy_v2_db import (
    StrategyOrder,
    StrategyPosition,
    StrategyTrade,
    db_session,
)
from events.strategy_events import StrategyLegFilledEvent
from utils.event_bus import bus
from utils.ist_time import fmt_tradebook, now_utc
from utils.logging import get_logger

logger = get_logger(__name__)


# ----------------------------------------------------------------------------
# Status canonicalisation
# ----------------------------------------------------------------------------

# Map broker-supplied status strings into our canonical set used in
# strategy_orders.order_status and the global /orderbook output.
_STATUS_MAP = {
    "complete": "complete",
    "completed": "complete",
    "filled": "complete",
    "executed": "complete",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "rejected": "rejected",
    "open": "open",
    "trigger pending": "trigger_pending",
    "trigger_pending": "trigger_pending",
    "pending": "pending",
    "modified": "open",
    "after market order req received": "open",
}


def _canon_status(s: Optional[str]) -> str:
    if not s:
        return "open"
    return _STATUS_MAP.get(s.strip().lower(), s.strip().lower())


# ----------------------------------------------------------------------------
# Subscriber callbacks (wired in subscribers/__init__.py:register_all)
# ----------------------------------------------------------------------------


def on_order_placed(event) -> None:
    """OrderPlacedEvent — broker accepted the order (status varies; could be
    OPEN/COMPLETE/TRIGGER_PENDING). We don't have the broker's status string
    here, so just stamp 'open' as a placeholder. Broker WS or poll fallback
    will deliver the real status via broker.order_update.

    Idempotent — uses orderid to find the row; no-op if not a strategy order.
    """
    orderid = getattr(event, "orderid", None)
    if not orderid:
        return
    try:
        result = db_session.execute(
            update(StrategyOrder)
            .where(
                StrategyOrder.orderid == str(orderid),
                StrategyOrder.order_status.in_(["pending", ""]),
            )
            .values(order_status="open", last_status_update_at=now_utc())
        )
        db_session.commit()
        if result.rowcount:
            logger.debug("position_tracker: marked order %s as 'open'", orderid)
    except Exception:
        db_session.rollback()
        logger.exception("position_tracker.on_order_placed failed for %s", orderid)
    finally:
        db_session.remove()


def on_order_failed(event) -> None:
    """OrderFailedEvent — broker rejected. Mark strategy_orders.order_status."""
    request = getattr(event, "request_data", {}) or {}
    orderid = request.get("orderid") or getattr(event, "orderid", None)
    symbol = getattr(event, "symbol", "")
    if not orderid and not symbol:
        return
    try:
        # Best-effort: orderid is often missing on rejection; fall back to
        # symbol+exchange+pending status as a heuristic. Engine attribution
        # by run_id keeps the search tight.
        q = db_session.query(StrategyOrder).filter(StrategyOrder.order_status == "pending")
        if orderid:
            q = q.filter(StrategyOrder.orderid == str(orderid))
        elif symbol:
            q = q.filter(StrategyOrder.symbol == symbol)
        for row in q.all():
            row.order_status = "rejected"
            row.last_status_update_at = now_utc()
        db_session.commit()
    except Exception:
        db_session.rollback()
        logger.exception("position_tracker.on_order_failed failed")
    finally:
        db_session.remove()


def on_order_cancelled(event) -> None:
    """OrderCancelledEvent — user cancelled."""
    orderid = getattr(event, "orderid", None)
    if not orderid:
        return
    try:
        db_session.execute(
            update(StrategyOrder)
            .where(StrategyOrder.orderid == str(orderid))
            .values(order_status="cancelled", last_status_update_at=now_utc())
        )
        db_session.commit()
    except Exception:
        db_session.rollback()
        logger.exception("position_tracker.on_order_cancelled failed for %s", orderid)
    finally:
        db_session.remove()


def on_broker_order_update(event) -> None:
    """BrokerOrderUpdateEvent — broker WS push or poll-fallback delivers the
    canonical status + fill details. This is where strategy_trades rows are
    written (only on 'complete'; partial fills are aggregated since most
    Indian brokers report final fill state, not per-trade).

    Looks up the strategy_orders row by broker orderid; if not found this is
    not one of our orders → no-op.

    Retry note: the event bus is async (ThreadPoolExecutor), so a sandbox
    fill event can race execution_service's db commit — the handler arrives
    here before the strategy_orders row is visible. We retry the lookup a
    handful of times with a short backoff before deciding "not our order."
    Live broker fills don't hit this race in practice (network round-trip
    >> commit time) but the retry is harmless on those too.
    """
    import time as _time

    orderid = getattr(event, "orderid", None) or ""
    if not orderid:
        return

    status = _canon_status(getattr(event, "status", None))
    filled_qty = int(getattr(event, "filled_qty", 0) or 0)
    avg_price = Decimal(str(getattr(event, "average_price", 0) or 0))

    try:
        order = None
        for _attempt in range(5):
            order = (
                db_session.query(StrategyOrder)
                .filter(StrategyOrder.orderid == str(orderid))
                .first()
            )
            if order:
                break
            # Release the scoped session so the next iteration sees fresh
            # commits from execution_service's worker.
            db_session.remove()
            _time.sleep(0.05)

        if not order:
            # Genuinely not a strategy-attributed order — give up.
            return

        # Update strategy_orders row.
        order.order_status = status
        order.last_status_update_at = now_utc()

        if status == "complete" and filled_qty > 0:
            _record_fill(order, filled_qty, avg_price)

        db_session.commit()

    except Exception:
        db_session.rollback()
        logger.exception("position_tracker.on_broker_order_update failed for %s", orderid)
    finally:
        db_session.remove()


def on_sandbox_order_filled(event) -> None:
    """Bridge from `sandbox.order_filled` -> the position tracker.

    Sandbox fills publish `SandboxOrderFilledEvent` directly from the
    sandbox engine (sandbox/execution_engine.py:_publish_fill_event).
    Live fills go through the broker's order-update channel which
    eventually publishes `BrokerOrderUpdateEvent`. Both paths must
    converge on the same `_record_fill` codepath so strategy_orders /
    strategy_trades / strategy_positions get written, the leg state
    advances PENDING_ENTRY -> OPEN, and the engine starts monitoring.

    Without this bridge, sandbox-mode strategies see their orders go
    to status='complete' but never accumulate positions or MTM — the
    UI stays at zero because the engine has no leg in its registry.

    The translation is straightforward — sandbox always fires on full
    fills, so we synthesize a status='complete' BrokerOrderUpdateEvent
    and dispatch through the same handler used for live fills.
    """
    # Use a duck-typed shim instead of importing BrokerOrderUpdateEvent
    # to avoid coupling this module to the events package twice. The
    # downstream handler reads attributes via getattr so any object with
    # the right shape works.
    class _Shim:
        def __init__(self, src):
            self.orderid = getattr(src, "orderid", "") or ""
            self.status = "complete"
            self.filled_qty = int(getattr(src, "quantity", 0) or 0)
            self.average_price = float(getattr(src, "price", 0) or 0)
            self.raw = {
                "source": "sandbox.order_filled",
                "tradeid": getattr(src, "tradeid", None),
                "symbol": getattr(src, "symbol", None),
                "exchange": getattr(src, "exchange", None),
            }

    on_broker_order_update(_Shim(event))


# ----------------------------------------------------------------------------
# Fill handling
# ----------------------------------------------------------------------------


def _record_fill(order: StrategyOrder, filled_qty: int, avg_price: Decimal) -> None:
    """Insert a strategy_trades row, recompute strategy_positions, publish
    StrategyLegFilledEvent. Caller commits.
    """
    # Idempotency guard — if a trade already exists for this orderid, skip.
    # Most brokers send the final-state update once; this handles double-deliveries
    # from WS+poll overlap during fallback resume.
    existing = (
        db_session.query(StrategyTrade)
        .filter(StrategyTrade.orderid == order.orderid)
        .first()
    )
    if existing is not None:
        logger.debug(
            "position_tracker: trade for orderid=%s already recorded; skipping",
            order.orderid,
        )
        return

    trade = StrategyTrade(
        order_id=order.id,
        strategy_id=order.strategy_id,
        run_id=order.run_id,
        leg_id=order.leg_id,
        action=order.action,
        symbol=order.symbol,
        exchange=order.exchange,
        orderid=order.orderid,
        product=order.product,
        quantity=Decimal(filled_qty),
        average_price=avg_price,
        trade_value=avg_price * Decimal(filled_qty),
        timestamp=fmt_tradebook(now_utc()),
        traded_at=now_utc(),
    )
    db_session.add(trade)
    db_session.flush()  # so the recompute below sees the new row

    _recompute_position(
        strategy_id=order.strategy_id,
        run_id=order.run_id,
        leg_id=order.leg_id,
        symbol=order.symbol,
        exchange=order.exchange,
        product=order.product,
    )

    bus.publish(
        StrategyLegFilledEvent(
            strategy_id=order.strategy_id,
            run_id=order.run_id,
            leg_id=order.leg_id or 0,
            avg_price=float(avg_price),
            qty=filled_qty,
            orderid=order.orderid or "",
        )
    )


def _recompute_position(
    *,
    strategy_id: int,
    run_id: int,
    leg_id: Optional[int],
    symbol: str,
    exchange: str,
    product: str,
) -> None:
    """Aggregate strategy_trades for a (run_id, leg_id) and write/update the
    strategy_positions row. Reads inside the same session so the trade just
    inserted is visible.
    """
    if leg_id is None:
        # Manual / cleanup orders without a leg_id → no position aggregation.
        return

    trades = (
        db_session.query(StrategyTrade)
        .filter(
            StrategyTrade.run_id == run_id,
            StrategyTrade.leg_id == leg_id,
        )
        .all()
    )

    net_qty = 0
    gross_buy_qty = 0
    gross_buy_value = Decimal(0)
    gross_sell_qty = 0
    gross_sell_value = Decimal(0)

    for t in trades:
        qty = int(t.quantity or 0)
        price = Decimal(str(t.average_price or 0))
        if (t.action or "").upper() == "BUY":
            net_qty += qty
            gross_buy_qty += qty
            gross_buy_value += qty * price
        else:
            net_qty -= qty
            gross_sell_qty += qty
            gross_sell_value += qty * price

    # avg_entry = weighted average of opening leg (the side that opened the
    # position). For long entries: BUYs first, then SELLs are exits.
    # We pick the dominant side and average over its trades.
    if net_qty > 0 and gross_buy_qty > 0:
        avg_entry = gross_buy_value / Decimal(gross_buy_qty)
    elif net_qty < 0 and gross_sell_qty > 0:
        avg_entry = gross_sell_value / Decimal(gross_sell_qty)
    else:
        # Flat — no entry to track. Realised P&L below captures the round-trip.
        avg_entry = Decimal(0)

    # Realised P&L = closed-quantity × (sell_avg - buy_avg) (long convention;
    # for shorts the sign flips because gross_sell_avg > gross_buy_avg when
    # profitable). Closed qty is the smaller of buy/sell volumes.
    closed_qty = min(gross_buy_qty, gross_sell_qty)
    realized_pnl = Decimal(0)
    if closed_qty > 0:
        buy_avg = gross_buy_value / Decimal(gross_buy_qty) if gross_buy_qty else Decimal(0)
        sell_avg = gross_sell_value / Decimal(gross_sell_qty) if gross_sell_qty else Decimal(0)
        realized_pnl = (sell_avg - buy_avg) * Decimal(closed_qty)

    pos = (
        db_session.query(StrategyPosition)
        .filter(
            StrategyPosition.run_id == run_id,
            StrategyPosition.leg_id == leg_id,
        )
        .first()
    )
    if pos is None:
        pos = StrategyPosition(
            strategy_id=strategy_id,
            run_id=run_id,
            leg_id=leg_id,
            symbol=symbol,
            exchange=exchange,
            product=product,
            net_qty=net_qty,
            avg_entry=avg_entry if avg_entry else None,
            realized_pnl=realized_pnl,
            quantity=str(net_qty),
            average_price=f"{avg_entry:.4f}" if avg_entry else "0",
            ltp="0",
            pnl=f"{realized_pnl:.2f}",
            leg_state="OPEN" if net_qty != 0 else "CLOSED",
            updated_at=now_utc(),
        )
        # Initialize current_sl_price + last_trail_anchor for the RMS engine.
        if avg_entry:
            pos.last_trail_anchor = avg_entry
        db_session.add(pos)
    else:
        pos.net_qty = net_qty
        if avg_entry:
            pos.avg_entry = avg_entry
            pos.average_price = f"{avg_entry:.4f}"
            if pos.last_trail_anchor is None:
                pos.last_trail_anchor = avg_entry
        pos.realized_pnl = realized_pnl
        pos.quantity = str(net_qty)
        pos.pnl = f"{realized_pnl:.2f}"
        # Leg state transitions on flat → CLOSED. Engine's exit flow handles
        # the EXITING_LEG -> CLOSED transition explicitly via state_machine;
        # we only flip here on a clean reopen-then-flat lifecycle.
        if net_qty == 0 and pos.leg_state in ("OPEN", "EXITING_LEG"):
            pos.leg_state = "CLOSED"
        elif net_qty != 0 and pos.leg_state == "PENDING_ENTRY":
            pos.leg_state = "OPEN"
        pos.updated_at = now_utc()

    logger.info(
        "position_tracker: recomputed run_id=%s leg_id=%s net_qty=%s avg_entry=%s realized=%s",
        run_id, leg_id, net_qty, avg_entry, realized_pnl,
    )
