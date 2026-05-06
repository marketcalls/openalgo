"""Exit service — places close orders for legs / strategies.

Per plan §5.2 + §5.3, ALL exit orders use explicit symbols read from
strategy_positions. No re-resolution. No placesmartorder. The engine has
already cached the symbol at arm-time in the resolved_* fields; by the time
we exit, strategy_position.symbol is the same row that was traded.

close_leg flow (called by the RMS engine on a per-leg trigger):
  1. Read strategy_position for (run_id, leg_id) — must exist + net_qty != 0
  2. Compute reverse-side close: long → SELL, short → BUY; qty = abs(net_qty)
  3. Transition leg state OPEN → EXITING_LEG (atomic, race-protected)
  4. Place via BrokerAdapter.place_order (live or sandbox per run.mode)
  5. Write strategy_orders row tagged with source=<reason>, mode=<run.mode>
  6. Publish StrategyExitTriggeredEvent

The position tracker handles the fill (broker.order_update) and transitions
the leg state EXITING_LEG → CLOSED once net_qty hits zero.

close_all (multi-leg basket exit) is plan §5.2 territory but isn't in Phase 3.
Lands with strategy-level RMS in Phase 4.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Tuple

from database.auth_db import get_api_key_for_tradingview
from database.strategy_v2_db import (
    StrategyOrder,
    StrategyPosition,
    StrategyRun,
    StrategyV2,
    db_session,
)
from events.strategy_events import (
    StrategyExitFailedEvent,
    StrategyExitTriggeredEvent,
)
from services.strategy.broker_adapter_impls import get_adapter
from services.strategy.state_machine import transition_leg
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)


def close_leg(
    *,
    run_id: int,
    leg_id: int,
    reason: str,
    rms_event_id: Optional[int] = None,
) -> Tuple[bool, dict]:
    """Place an exit order for a single leg.

    Args:
        run_id:        the active run (must be IN_TRADE; engine ensures this)
        leg_id:        the leg whose position we're closing
        reason:        why — propagated to strategy_orders.source and the
                       StrategyExitTriggeredEvent. Examples:
                         exit_leg_sl, exit_leg_target, exit_trail,
                         manual_close_leg, squareoff
        rms_event_id:  optional — the strategy_events row that triggered this
                       exit (for audit-chain back-reference)

    Returns:
        (success, summary). On success summary contains the placed orderid
        and the close action/qty/price. On failure the run is marked
        EXIT_FAILED via StrategyExitFailedEvent (engine handles the run
        state transition).
    """
    # ---- Look up position + run + strategy --------------------------------
    pos = (
        db_session.query(StrategyPosition)
        .filter(
            StrategyPosition.run_id == run_id,
            StrategyPosition.leg_id == leg_id,
        )
        .first()
    )
    if pos is None:
        return False, _fail(run_id, "POSITION_NOT_FOUND", reason=reason)
    if pos.net_qty == 0:
        # Already flat — caller raced with the position tracker. Treat as
        # success (idempotent close).
        return True, {"status": "already_flat", "leg_id": leg_id}
    if pos.leg_state == "CLOSED":
        return True, {"status": "already_closed", "leg_id": leg_id}

    run = db_session.query(StrategyRun).filter(StrategyRun.id == run_id).first()
    if run is None:
        return False, _fail(run_id, "RUN_NOT_FOUND", reason=reason)

    strategy = (
        db_session.query(StrategyV2).filter(StrategyV2.id == run.strategy_id).first()
    )
    if strategy is None:
        return False, _fail(run_id, "STRATEGY_NOT_FOUND", reason=reason)

    # ---- Atomic leg-state transition (idempotent against double-fire) -----
    if pos.leg_state == "OPEN":
        if not transition_leg(pos.id, "OPEN", "EXITING_LEG"):
            # Race lost — another caller already started the exit. Bail clean.
            logger.info(
                "exit_service.close_leg race-lost: position_id=%s already advanced",
                pos.id,
            )
            return True, {"status": "already_exiting", "leg_id": leg_id}

    # ---- Build the reverse-side order with explicit symbol ----------------
    is_long = pos.net_qty > 0
    close_action = "SELL" if is_long else "BUY"
    close_qty = abs(pos.net_qty)

    api_key = get_api_key_for_tradingview(strategy.user_id)
    if not api_key:
        return False, _fail(
            run_id,
            "NO_BROKER_SESSION",
            reason=reason,
            detail="No active broker session for strategy owner",
        )

    adapter = get_adapter(run.mode, api_key)
    order_data = {
        "strategy": f"strategy_{strategy.id}_run_{run_id}_exit_leg_{leg_id}",
        "symbol": pos.symbol,
        "exchange": pos.exchange,
        "action": close_action,
        "quantity": close_qty,
        "pricetype": "MARKET",
        "product": pos.product,
    }

    ok, resp, _http = adapter.place_order(order_data)

    # ---- Write strategy_orders row -- ALWAYS, even on failure ------------
    # The audit trail must show the attempted exit; the position tracker
    # later updates order_status when broker.order_update arrives.
    placed_orderid = (resp or {}).get("orderid", "") if ok else ""
    initial_status = "open" if ok else "rejected"

    order_row = StrategyOrder(
        strategy_id=strategy.id,
        run_id=run_id,
        leg_id=leg_id,
        action=close_action,
        symbol=pos.symbol,
        exchange=pos.exchange,
        orderid=placed_orderid or None,
        product=pos.product,
        quantity=str(close_qty),
        price=Decimal(0),
        pricetype="MARKET",
        order_status=initial_status,
        trigger_price=Decimal(0),
        timestamp="",
        source=reason,
        mode=run.mode,
        rms_event_id=rms_event_id,
        placed_at=datetime.now(timezone.utc),
    )
    db_session.add(order_row)
    db_session.commit()

    if not ok:
        # Broker rejected the exit — flag it loudly. The engine listening on
        # this event will mark the run EXIT_FAILED and stop monitoring.
        details = {
            "leg_id": leg_id,
            "symbol": pos.symbol,
            "exchange": pos.exchange,
            "action": close_action,
            "quantity": close_qty,
            "broker_message": (resp or {}).get("message", "unknown broker error"),
        }
        bus.publish(
            StrategyExitFailedEvent(
                strategy_id=strategy.id,
                run_id=run_id,
                details=details,
            )
        )
        return False, {"status": "error", **details}

    # Success — engine receives the StrategyExitTriggeredEvent and continues.
    bus.publish(
        StrategyExitTriggeredEvent(
            strategy_id=strategy.id,
            run_id=run_id,
            reason=reason,
            legs_exited=1,
            exit_orders=[
                {"leg_id": leg_id, "orderid": placed_orderid, "action": close_action,
                 "quantity": close_qty}
            ],
        )
    )

    return True, {
        "status": "success",
        "leg_id": leg_id,
        "orderid": placed_orderid,
        "action": close_action,
        "quantity": close_qty,
        "reason": reason,
    }


def _fail(run_id: int, code: str, *, reason: str = "", detail: str = "") -> dict:
    """Helper — publish StrategyExitFailedEvent and return the error dict."""
    payload = {"code": code, "reason": reason, "detail": detail}
    bus.publish(
        StrategyExitFailedEvent(
            strategy_id=0,  # caller-side — unknown when run not found
            run_id=run_id,
            details=payload,
        )
    )
    return {"status": "error", **payload}


# ===========================================================================
# Strategy-level exit — cancels pending + basket-closes all open legs
# ===========================================================================


def exit_strategy(
    *,
    run_id: int,
    reason: str,
    rms_event_id: Optional[int] = None,
) -> Tuple[bool, dict]:
    """Flatten an entire run.

    Step 1: cancel any open / trigger-pending strategy_orders for the run
            (otherwise an SL-LIMIT sitting at the broker could fill AFTER
            our market-close lands, opening a new position outside the
            strategy — see plan §11 'Cancel-pending vs close-position').
    Step 2: build a basket exit for all OPEN legs with explicit symbols
            (no re-resolution; same convention as close_leg).
    Step 3: transition run IN_TRADE -> EXITING (idempotent — if already
            EXITING the engine has dropped it; we still proceed with the
            basket so a second-call exit is safe).

    Used by:
      - RMS engine on overall SL / overall target / profit lock fire
      - squareoff scheduler on configured exit time
      - manual UI close-all button (Phase 5)

    Return: (success, summary). summary["legs_exited"] is the count of
    legs we successfully placed close orders for.
    """
    from services.strategy.state_machine import transition_run

    run = db_session.query(StrategyRun).filter(StrategyRun.id == run_id).first()
    if run is None:
        return False, _fail(run_id, "RUN_NOT_FOUND", reason=reason)

    strategy = (
        db_session.query(StrategyV2).filter(StrategyV2.id == run.strategy_id).first()
    )
    if strategy is None:
        return False, _fail(run_id, "STRATEGY_NOT_FOUND", reason=reason)

    api_key = get_api_key_for_tradingview(strategy.user_id)
    if not api_key:
        return False, _fail(
            run_id, "NO_BROKER_SESSION", reason=reason,
            detail="No active broker session for strategy owner",
        )

    adapter = get_adapter(run.mode, api_key)

    # ---- Step 1: cancel pending orders ------------------------------------
    cancellations = _cancel_pending_orders(run_id=run_id, adapter=adapter)

    # ---- Step 2: snapshot open positions ----------------------------------
    open_positions = (
        db_session.query(StrategyPosition)
        .filter(
            StrategyPosition.run_id == run_id,
            StrategyPosition.leg_state == "OPEN",
        )
        .all()
    )

    if not open_positions and not cancellations:
        # Nothing to do — already flat. Still transition to EXITING so the
        # caller can move the run to CLOSED via the fill watcher.
        transition_run(
            run.id, expected_old="IN_TRADE", new_state="EXITING",
            reason=reason, strategy_id=strategy.id,
        )
        return True, {
            "status": "already_flat",
            "legs_exited": 0,
            "cancellations": cancellations,
        }

    # ---- Step 3: state transition -----------------------------------------
    # Atomic — race-protected against concurrent close-all attempts. If we
    # lose the race, another caller is already exiting; bail clean.
    if not transition_run(
        run.id, expected_old="IN_TRADE", new_state="EXITING",
        reason=reason, strategy_id=strategy.id,
    ):
        logger.info(
            "exit_strategy race-lost or run already exiting: run_id=%s", run_id
        )
        # Still try to place the basket exit — better double-flatten than
        # leave positions open. The fill watcher will reconcile duplicates.

    # ---- Step 4: basket exit for all open legs ----------------------------
    basket_orders = []
    leg_lookup = {}
    for pos in open_positions:
        is_long = (pos.net_qty or 0) > 0
        if pos.net_qty == 0:
            continue
        order = {
            "symbol": pos.symbol,
            "exchange": pos.exchange,
            "action": "SELL" if is_long else "BUY",
            "quantity": abs(pos.net_qty),
            "pricetype": "MARKET",
            "product": pos.product,
            "strategy": f"strategy_{strategy.id}_run_{run_id}_exit",
        }
        basket_orders.append(order)
        leg_lookup[(pos.symbol, pos.exchange)] = pos

    if not basket_orders:
        return True, {
            "status": "already_flat",
            "legs_exited": 0,
            "cancellations": cancellations,
        }

    # Mark legs as EXITING_LEG before placing — so the engine sees them
    # transitioning and the close_leg path doesn't double-fire.
    for pos in open_positions:
        if pos.leg_state == "OPEN":
            pos.leg_state = "EXITING_LEG"
            pos.updated_at = datetime.now(timezone.utc)
    db_session.commit()

    ok, resp, _http = adapter.basket_order(
        {"orders": basket_orders, "strategy": f"strategy_{strategy.id}_run_{run_id}_exit"}
    )

    legs_exited = 0
    placed_summaries: list = []
    if ok:
        results = (resp or {}).get("results", []) or []
        for order_payload, leg_result in zip(basket_orders, results):
            pos = leg_lookup.get((order_payload["symbol"], order_payload["exchange"]))
            if pos is None:
                continue
            placed_orderid = leg_result.get("orderid", "") if isinstance(leg_result, dict) else ""
            status = (
                "open" if (isinstance(leg_result, dict) and leg_result.get("status") == "success")
                else "rejected"
            )
            row = StrategyOrder(
                strategy_id=strategy.id,
                run_id=run_id,
                leg_id=pos.leg_id,
                action=order_payload["action"],
                symbol=order_payload["symbol"],
                exchange=order_payload["exchange"],
                orderid=placed_orderid or None,
                product=order_payload["product"],
                quantity=str(order_payload["quantity"]),
                price=Decimal(0),
                pricetype="MARKET",
                order_status=status,
                trigger_price=Decimal(0),
                timestamp="",
                source=reason,
                mode=run.mode,
                rms_event_id=rms_event_id,
                placed_at=datetime.now(timezone.utc),
            )
            db_session.add(row)
            if status == "open":
                legs_exited += 1
                placed_summaries.append(
                    {
                        "leg_id": pos.leg_id,
                        "orderid": placed_orderid,
                        "action": order_payload["action"],
                        "quantity": order_payload["quantity"],
                    }
                )
        db_session.commit()
    else:
        # Basket call failed wholesale — emit failure event.
        details = {
            "scope": "basket_order",
            "broker_message": (resp or {}).get("message", "unknown broker error"),
            "legs_attempted": len(basket_orders),
        }
        bus.publish(
            StrategyExitFailedEvent(
                strategy_id=strategy.id, run_id=run_id, details=details,
            )
        )
        return False, {"status": "error", **details}

    bus.publish(
        StrategyExitTriggeredEvent(
            strategy_id=strategy.id,
            run_id=run_id,
            reason=reason,
            legs_exited=legs_exited,
            exit_orders=placed_summaries,
        )
    )

    return True, {
        "status": "success",
        "legs_exited": legs_exited,
        "cancellations": cancellations,
        "exit_orders": placed_summaries,
    }


def _cancel_pending_orders(*, run_id: int, adapter) -> list:
    """Cancel every strategy_orders row for the run that's still pending /
    trigger_pending. Returns the list of orderids successfully cancelled.
    Failures are logged but don't block the basket-exit step — better to
    flatten positions than abort because of a stale pending order."""
    pending = (
        db_session.query(StrategyOrder)
        .filter(
            StrategyOrder.run_id == run_id,
            StrategyOrder.order_status.in_(("open", "trigger_pending", "pending")),
            StrategyOrder.orderid.isnot(None),
        )
        .all()
    )
    cancelled = []
    for o in pending:
        if not o.orderid:
            continue
        try:
            ok, _resp, _ = adapter.cancel_order(o.orderid)
            if ok:
                cancelled.append(o.orderid)
                o.order_status = "cancelled"
                o.last_status_update_at = datetime.now(timezone.utc)
        except Exception:
            logger.exception(
                "exit_strategy: cancel failed for orderid=%s run=%s",
                o.orderid, run_id,
            )
    if cancelled:
        db_session.commit()
    return cancelled
