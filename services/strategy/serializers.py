"""Serializers — convert strategy-scoped DB rows into the same JSON shape
the global /orderbook, /tradebook, /positionbook endpoints return, so the
frontend can reuse table components with a different data source.

Shapes (verified against services/orderbook_service.py / tradebook_service /
positionbook_service):

  orderbook:    {"status": "success",
                 "data": {"orders": [<row>...], "statistics": {...}}}

  tradebook:    {"status": "success",
                 "data": [<row>...]}

  positionbook: {"status": "success",
                 "data": [<row>...]}

Strategy-only additions (events, runs) keep a similar wrapper:
  events:       {"status": "success", "data": [<event>...]}
  runs:         {"status": "success", "data": [<run>...]}

All timestamps in display fields use IST formatting via utils.ist_time.
"""

from __future__ import annotations

import json
from typing import Any

from database.strategy_v2_db import (
    StrategyEvent,
    StrategyOrder,
    StrategyPosition,
    StrategyRun,
    StrategyTrade,
)
from utils.ist_time import fmt_orderbook, fmt_tradebook


# ---------------------------------------------------------------------------
# Row → dict converters
# ---------------------------------------------------------------------------


def _order_row(o: StrategyOrder) -> dict[str, Any]:
    """Convert a strategy_orders row into a /orderbook-shape dict.

    Field names + types match the global endpoint. Strategy-only metadata
    (source, leg_id, mode, run_id) is added on top — clients that don't care
    can ignore it; the strategy detail page surfaces it.
    """
    return {
        # /orderbook columns
        "action": o.action,
        "symbol": o.symbol,
        "exchange": o.exchange,
        "orderid": o.orderid or "",
        "product": o.product,
        "quantity": str(o.quantity) if o.quantity is not None else "0",
        "price": float(o.price) if o.price is not None else 0.0,
        "pricetype": o.pricetype,
        "order_status": o.order_status,
        "trigger_price": float(o.trigger_price) if o.trigger_price is not None else 0.0,
        "timestamp": (
            o.timestamp
            or (fmt_orderbook(o.placed_at) if o.placed_at else "")
        ),
        # Strategy-only metadata
        "source": o.source,
        "mode": o.mode,
        "leg_id": o.leg_id,
        "run_id": o.run_id,
        "rms_event_id": o.rms_event_id,
    }


def _trade_row(t: StrategyTrade) -> dict[str, Any]:
    """Convert a strategy_trades row into a /tradebook-shape dict."""
    return {
        # /tradebook columns
        "action": t.action,
        "symbol": t.symbol,
        "exchange": t.exchange,
        "orderid": t.orderid or "",
        "product": t.product or "",
        "quantity": float(t.quantity) if t.quantity is not None else 0.0,
        "average_price": float(t.average_price) if t.average_price is not None else 0.0,
        "trade_value": float(t.trade_value) if t.trade_value is not None else 0.0,
        "timestamp": (
            t.timestamp
            or (fmt_tradebook(t.traded_at) if t.traded_at else "")
        ),
        # Strategy-only metadata
        "leg_id": t.leg_id,
        "run_id": t.run_id,
        "broker_tradeid": t.broker_tradeid or "",
    }


def _position_row(p: StrategyPosition) -> dict[str, Any]:
    """Convert a strategy_positions row into a /positionbook-shape dict."""
    return {
        # /positionbook columns (string types matching global format)
        "symbol": p.symbol,
        "exchange": p.exchange,
        "product": p.product,
        "quantity": p.quantity if p.quantity is not None else "0",
        "average_price": p.average_price if p.average_price is not None else "0",
        "ltp": p.ltp if p.ltp is not None else "0",
        "pnl": p.pnl if p.pnl is not None else "0",
        # Strategy-only (decimals so charts can do real math)
        "leg_id": p.leg_id,
        "run_id": p.run_id,
        "net_qty": p.net_qty,
        "avg_entry": float(p.avg_entry) if p.avg_entry is not None else None,
        "ltp_decimal": float(p.ltp_decimal) if p.ltp_decimal is not None else None,
        "unrealized_pnl": float(p.unrealized_pnl) if p.unrealized_pnl is not None else 0.0,
        "realized_pnl": float(p.realized_pnl) if p.realized_pnl is not None else 0.0,
        # Live RMS state — useful for the strategy monitor view
        "current_sl_price": (
            float(p.current_sl_price) if p.current_sl_price is not None else None
        ),
        "current_target_price": (
            float(p.current_target_price) if p.current_target_price is not None else None
        ),
        "trail_advances_count": p.trail_advances_count or 0,
        "leg_state": p.leg_state,
    }


def _event_row(e: StrategyEvent) -> dict[str, Any]:
    """Audit-log timeline row. Payload is JSON-decoded on the way out so the
    frontend doesn't have to parse a string."""
    payload: Any
    try:
        payload = json.loads(e.payload) if e.payload else None
    except (TypeError, ValueError):
        payload = e.payload  # corrupted — surface raw

    return {
        "id": e.id,
        "type": e.type,
        "ts_utc": int(e.ts.timestamp() * 1000) if e.ts else 0,
        "ts_ist": fmt_orderbook(e.ts) if e.ts else "",
        "leg_id": e.leg_id,
        "payload": payload,
        "row_hash": e.row_hash,
        # prev_hash deliberately omitted — frontend uses the audit verifier
        # endpoint (/audit/verify/<run_id>) for chain integrity, not per-row.
    }


def _run_row(r: StrategyRun) -> dict[str, Any]:
    """One row in the strategy-runs list."""
    return {
        "id": r.id,
        "strategy_id": r.strategy_id,
        "state": r.state,
        "mode": r.mode,
        "exit_reason": r.exit_reason,
        "triggered_at": fmt_orderbook(r.triggered_at) if r.triggered_at else None,
        "entered_at": fmt_orderbook(r.entered_at) if r.entered_at else None,
        "exited_at": fmt_orderbook(r.exited_at) if r.exited_at else None,
        "peak_mtm": float(r.peak_mtm) if r.peak_mtm is not None else 0.0,
        "trough_mtm": float(r.trough_mtm) if r.trough_mtm is not None else 0.0,
        "profit_locked": bool(r.profit_locked),
        "realized_pnl": float(r.realized_pnl) if r.realized_pnl is not None else 0.0,
        "max_unrealized_pnl": (
            float(r.max_unrealized_pnl) if r.max_unrealized_pnl is not None else 0.0
        ),
        "max_drawdown": float(r.max_drawdown) if r.max_drawdown is not None else 0.0,
        "signal_source": r.signal_source,
    }


# ---------------------------------------------------------------------------
# Statistics — mirrors broker-side calculate_order_statistics so the strategy
# orderbook tab feels identical to the global one.
# ---------------------------------------------------------------------------


def _compute_statistics(orders: list[dict]) -> dict[str, float]:
    """Compute the same statistics block the global /orderbook returns:
    total_buy_orders, total_sell_orders, total_completed_orders,
    total_open_orders, total_rejected_orders. All floats (matches existing
    contract).

    Canonical order_status values per docs/prompt/order-constants.md:
        open / complete / rejected / cancelled

    cancelled orders are deliberately NOT counted toward total_open_orders
    — they're terminal and shouldn't inflate the "live order" view.
    trigger_pending and pending are mapped to open (intermediate states
    a few brokers expose before the final canonical 4-state set).
    """
    stats = {
        "total_buy_orders": 0.0,
        "total_sell_orders": 0.0,
        "total_completed_orders": 0.0,
        "total_open_orders": 0.0,
        "total_rejected_orders": 0.0,
    }
    for o in orders:
        action = (o.get("action") or "").upper()
        status = (o.get("order_status") or "").lower()
        if action == "BUY":
            stats["total_buy_orders"] += 1
        elif action == "SELL":
            stats["total_sell_orders"] += 1
        if status == "complete":
            stats["total_completed_orders"] += 1
        elif status in ("open", "trigger_pending", "pending"):
            stats["total_open_orders"] += 1
        elif status == "rejected":
            stats["total_rejected_orders"] += 1
        # status == "cancelled" intentionally not counted in any bucket
    return stats


# ---------------------------------------------------------------------------
# Public format functions
# ---------------------------------------------------------------------------


def to_orderbook_format(rows: list[StrategyOrder]) -> dict[str, Any]:
    """Returns the same envelope as services.orderbook_service:get_orderbook."""
    orders = [_order_row(o) for o in rows]
    return {
        "status": "success",
        "data": {
            "orders": orders,
            "statistics": _compute_statistics(orders),
        },
    }


def to_tradebook_format(rows: list[StrategyTrade]) -> dict[str, Any]:
    """Returns the same envelope as services.tradebook_service:get_tradebook."""
    return {"status": "success", "data": [_trade_row(t) for t in rows]}


def to_positionbook_format(rows: list[StrategyPosition]) -> dict[str, Any]:
    """Returns the same envelope as services.positionbook_service:get_positionbook."""
    return {"status": "success", "data": [_position_row(p) for p in rows]}


def to_events_format(rows: list[StrategyEvent]) -> dict[str, Any]:
    """Audit-timeline list. Strategy-only — no global endpoint to mirror."""
    return {"status": "success", "data": [_event_row(e) for e in rows]}


def to_runs_format(rows: list[StrategyRun]) -> dict[str, Any]:
    """Per-strategy runs list. Strategy-only."""
    return {"status": "success", "data": [_run_row(r) for r in rows]}


def run_detail(run: StrategyRun) -> dict[str, Any]:
    """Single-run details — used by the run detail page header."""
    return {"status": "success", "data": _run_row(run)}
