"""Execution service — orchestrates entry order placement.

Per plan §5.2 segment-routing matrix:

  CASH/FUT (single):     adapter.place_order
  CASH/FUT (multi):      adapter.basket_order  (single API call)
  OPT (single):          adapter.place_options_order  (strike resolved by service)
  OPT (multi):           adapter.place_options_multiorder  (BUY-first preserved)
  Mixed CASH/FUT + OPT:  basket_order for non-OPT, then place_options_multiorder for OPT

Note we already resolve OPT symbols upfront via leg_resolver_service so we
COULD use basket_order for everything. We don't, because
place_options_multiorder also handles BUY-first ordering for margin
efficiency (sell-to-open requires more margin than buy-to-open).

Every order placement writes a strategy_orders row tagged with run_id +
leg_id + source='entry'. Failures publish StrategyEnterFailedEvent and the
caller transitions the run to ENTRY_FAILED.

place_smart_order is intentionally NEVER used here — see plan §5.2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from database.strategy_v2_db import (
    StrategyLeg,
    StrategyOrder,
    StrategyV2,
    db_session,
)
from events.strategy_events import StrategyEnterFailedEvent
from services.strategy.broker_adapter import BrokerAdapter
from services.strategy.state_machine import transition_run
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Order-payload builders
# -----------------------------------------------------------------------------


def _action(leg: StrategyLeg) -> str:
    return "BUY" if leg.position == "B" else "SELL"


def _qty_for(leg: StrategyLeg) -> int:
    """Resolve the broker-side qty. CASH uses raw qty; FUT/OPT multiply lots × lot_size."""
    if leg.segment == "CASH":
        return int(leg.qty or 0)
    return int((leg.lots or 0) * (leg.lot_size_cache or 0))


def _basket_row_from_leg(leg: StrategyLeg, strategy_tag: str) -> dict:
    """Shape that basket_order_service expects."""
    return {
        "symbol": leg.resolved_symbol,
        "exchange": leg.resolved_exchange,
        "action": _action(leg),
        "quantity": _qty_for(leg),
        "pricetype": "MARKET",
        "product": leg.product,
        "strategy": strategy_tag,
    }


def _opt_leg_dict(leg: StrategyLeg) -> dict:
    """Shape that options_multiorder_service expects per-leg.

    NOTE: leg_resolver already resolved offset → concrete strike, so we pass
    the already-resolved offset back in. The multiorder service calls
    get_option_symbol again with the same offset; that's idempotent because
    Phase 1 only supports ATM and STRIKE_OFFSET strike_criteria — pure
    function of underlying LTP at signal time, which doesn't change across
    resolver call and multiorder call (sub-second window).
    """
    crit = (leg.strike_criteria or "ATM").upper()
    if crit == "ATM":
        offset = "ATM"
    elif crit == "STRIKE_OFFSET":
        try:
            n = int(leg.strike_value or 0)
        except (TypeError, ValueError):
            n = 0
        if n == 0:
            offset = "ATM"
        elif n > 0:
            offset = f"OTM{abs(n)}"
        else:
            offset = f"ITM{abs(n)}"
    else:
        offset = "ATM"  # Phase 1 fallback; PREMIUM/DELTA later

    return {
        "offset": offset,
        "option_type": leg.option_type,
        "action": _action(leg),
        "quantity": _qty_for(leg),
        "product": leg.product,
        "pricetype": "MARKET",
    }


def _strategy_tag(strategy: StrategyV2, run_id: int) -> str:
    return f"strategy_{strategy.id}_run_{run_id}"


# -----------------------------------------------------------------------------
# strategy_orders persistence
# -----------------------------------------------------------------------------


def _persist_order_row(
    *,
    strategy: StrategyV2,
    run_id: int,
    leg: StrategyLeg,
    response_row: dict,
    mode: str,
) -> None:
    """Insert a strategy_orders row from an adapter response. The response_row
    shape varies slightly between basket / options_multiorder / single-order
    services — we normalize here.
    """
    orderid = response_row.get("orderid") or response_row.get("order_id") or ""
    status = "complete" if (response_row.get("status") == "success") else (
        response_row.get("status") or "rejected"
    )
    row = StrategyOrder(
        strategy_id=strategy.id,
        run_id=run_id,
        leg_id=leg.id,
        action=_action(leg),
        symbol=leg.resolved_symbol or "",
        exchange=leg.resolved_exchange or "",
        orderid=orderid,
        product=leg.product,
        quantity=str(_qty_for(leg)),
        price=0,
        pricetype="MARKET",
        order_status=status,
        trigger_price=0,
        timestamp=response_row.get("timestamp") or "",
        source="entry",
        mode=mode,
        placed_at=datetime.now(timezone.utc),
    )
    db_session.add(row)


def _emit_enter_failed(strategy_id: int, run_id: int, details: dict) -> None:
    bus.publish(
        StrategyEnterFailedEvent(
            strategy_id=strategy_id,
            run_id=run_id,
            details=details,
        )
    )


# -----------------------------------------------------------------------------
# Public entry orchestrator
# -----------------------------------------------------------------------------


def execute_entry(
    *,
    strategy: StrategyV2,
    run_id: int,
    legs: list,
    adapter: BrokerAdapter,
) -> Tuple[bool, dict]:
    """Place all entry orders for a strategy run. Routes by segment composition
    per the matrix in plan §5.2.

    Caller must have already:
      - Created the strategy_run row (state=ARMED→ENTERING).
      - Resolved every leg via leg_resolver_service.

    On success: state transitions ENTERING → IN_TRADE happen here.
    On failure: state transitions ENTERING → ENTRY_FAILED happen here.

    Returns (success, summary). summary contains 'orders_placed', 'errors',
    'mode' for logging / API response.
    """
    cash_fut_legs = [l for l in legs if l.segment in ("CASH", "FUT")]
    opt_legs = [l for l in legs if l.segment == "OPT"]
    tag = _strategy_tag(strategy, run_id)

    orders_placed = 0
    errors: list = []

    # ---- Phase 1: CASH + FUT entry -----------------------------------------
    if cash_fut_legs:
        if len(cash_fut_legs) == 1:
            # Single — direct place_order
            leg = cash_fut_legs[0]
            order_data = {
                **_basket_row_from_leg(leg, tag),
            }
            ok, resp, _ = adapter.place_order(order_data)
            if ok:
                orders_placed += 1
                _persist_order_row(
                    strategy=strategy, run_id=run_id, leg=leg,
                    response_row=resp, mode=adapter.mode,
                )
            else:
                errors.append({
                    "leg_index": leg.leg_index, "segment": leg.segment,
                    "message": resp.get("message", "place_order failed"),
                })
        else:
            # Multi — single basket_order call
            basket = [_basket_row_from_leg(l, tag) for l in cash_fut_legs]
            ok, resp, _ = adapter.basket_order({"orders": basket, "strategy": tag})
            if ok:
                results = resp.get("results", [])
                for leg, leg_result in zip(cash_fut_legs, results):
                    if leg_result.get("status") == "success":
                        orders_placed += 1
                    else:
                        errors.append({
                            "leg_index": leg.leg_index, "segment": leg.segment,
                            "message": leg_result.get("message", "basket leg failed"),
                        })
                    _persist_order_row(
                        strategy=strategy, run_id=run_id, leg=leg,
                        response_row=leg_result, mode=adapter.mode,
                    )
            else:
                errors.append({
                    "scope": "basket_order",
                    "message": resp.get("message", "basket_order failed"),
                })

    # ---- Phase 2: OPT entry -----------------------------------------------
    if opt_legs and not errors:
        if len(opt_legs) == 1:
            leg = opt_legs[0]
            options_data = {
                "underlying": strategy.underlying,
                "exchange": strategy.underlying_exchange,
                **_opt_leg_dict(leg),
                "strategy": tag,
            }
            ok, resp, _ = adapter.place_options_order(options_data)
            if ok:
                orders_placed += 1
                _persist_order_row(
                    strategy=strategy, run_id=run_id, leg=leg,
                    response_row=resp, mode=adapter.mode,
                )
            else:
                errors.append({
                    "leg_index": leg.leg_index, "segment": leg.segment,
                    "message": resp.get("message", "place_options_order failed"),
                })
        else:
            multiorder_data = {
                "underlying": strategy.underlying,
                "exchange": strategy.underlying_exchange,
                "strategy": tag,
                "legs": [_opt_leg_dict(l) for l in opt_legs],
            }
            ok, resp, _ = adapter.place_options_multiorder(multiorder_data)
            if ok:
                results = resp.get("results", [])
                # results in the multiorder response are per-leg (1-indexed in
                # 'leg' field). Match by index.
                results_by_idx = {r.get("leg", i + 1): r for i, r in enumerate(results)}
                for i, leg in enumerate(opt_legs, start=1):
                    leg_result = results_by_idx.get(i, {})
                    if leg_result.get("status") == "success":
                        orders_placed += 1
                    else:
                        errors.append({
                            "leg_index": leg.leg_index, "segment": leg.segment,
                            "message": leg_result.get("message", "multiorder leg failed"),
                        })
                    _persist_order_row(
                        strategy=strategy, run_id=run_id, leg=leg,
                        response_row=leg_result, mode=adapter.mode,
                    )
            else:
                errors.append({
                    "scope": "options_multiorder",
                    "message": resp.get("message", "options_multiorder failed"),
                })

    db_session.commit()

    summary = {
        "orders_placed": orders_placed,
        "total_legs": len(legs),
        "errors": errors,
        "mode": adapter.mode,
    }

    if errors:
        # Best-effort exit transition. Caller handles cleanup of partially
        # placed orders (Phase 5 fill-watcher will reconcile).
        transition_run(
            run_id, expected_old="ENTERING", new_state="ENTRY_FAILED",
            reason="entry orders rejected",
            strategy_id=strategy.id,
        )
        _emit_enter_failed(strategy.id, run_id, summary)
        return False, summary

    transition_run(
        run_id, expected_old="ENTERING", new_state="IN_TRADE",
        reason="all entries filled",
        strategy_id=strategy.id,
    )
    return True, summary
