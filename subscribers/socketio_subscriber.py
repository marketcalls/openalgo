"""
SocketIO subscriber — emits the correct socketio event for each order event.

Reproduces the exact event names and payload structures from the original code.
Called directly from the EventBus thread pool — socketio.emit() is thread-safe
with async_mode="threading" and avoids greenlet errors under eventlet.
"""

from extensions import socketio
from utils.logging import get_logger

logger = get_logger(__name__)


def on_order_placed(event):
    """Emit order_event (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        socketio.emit(
            "order_event",
            {
                "symbol": event.symbol,
                "action": event.action,
                "orderid": event.orderid,
                "exchange": event.exchange,
                "price_type": event.pricetype,
                "product_type": event.product,
                "mode": "live",
            },
        )


def on_order_failed(event):
    """Emit analyzer_update (analyze) — live failures have no socketio event in original code."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)


def on_smart_order_no_action(event):
    """Emit order_notification (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        socketio.emit(
            "order_notification",
            {
                "symbol": event.symbol,
                "status": "info",
                "message": event.message,
            },
        )


def on_order_modified(event):
    """Emit modify_order_event (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        socketio.emit(
            "modify_order_event",
            {
                "status": "success",
                "orderid": event.orderid,
                "mode": "live",
            },
        )


def on_order_modify_failed(event):
    """Emit analyzer_update (analyze) — live failures have no socketio event."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)


def on_order_cancelled(event):
    """Emit cancel_order_event (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        socketio.emit(
            "cancel_order_event",
            {
                "status": event.status,
                "orderid": event.orderid,
                "mode": "live",
            },
        )


def on_order_cancel_failed(event):
    """Emit analyzer_update (analyze) — live failures have no socketio event."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)


def on_all_orders_cancelled(event):
    """Emit cancel_order_event batch (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        socketio.emit(
            "cancel_order_event",
            {
                "status": "success",
                "orderid": f"{event.canceled_count} orders canceled",
                "mode": "live",
                "batch_order": True,
                "is_last_order": True,
                "canceled_count": event.canceled_count,
                "failed_count": event.failed_count,
            },
        )


def on_position_closed(event):
    """Emit close_position_event (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        socketio.emit(
            "close_position_event",
            {
                "status": "success",
                "message": event.message or "All Open Positions Squared Off",
                "mode": "live",
            },
        )


def on_basket_completed(event):
    """Emit order_event batch summary (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        socketio.emit(
            "order_event",
            {
                "symbol": event.strategy or "Basket",
                "action": f"{event.successful}/{event.total} orders",
                "orderid": f"basket_{event.successful}",
                "exchange": "MULTI",
                "price_type": "BASKET",
                "product_type": "BASKET",
                "mode": "live",
                "batch_order": True,
                "is_last_order": True,
            },
        )


def on_split_completed(event):
    """Emit order_event batch summary (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        socketio.emit(
            "order_event",
            {
                "symbol": event.symbol or "Split",
                "action": event.action or "SPLIT",
                "orderid": f"{event.successful}/{event.total} orders",
                "exchange": event.exchange or "Unknown",
                "price_type": event.pricetype or "MARKET",
                "product_type": event.product or "MIS",
                "mode": "live",
                "batch_order": True,
                "is_last_order": True,
            },
        )


def on_options_completed(event):
    """Emit order_event batch summary (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        socketio.emit(
            "order_event",
            {
                "symbol": event.symbol,
                "action": event.action,
                "orderid": f"{event.successful}/{event.total} orders",
                "exchange": event.exchange,
                "price_type": event.pricetype or "MARKET",
                "product_type": event.product or "MIS",
                "mode": "live",
                "batch_order": True,
                "is_last_order": True,
            },
        )


def on_multiorder_completed(event):
    """Emit order_event batch summary (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        socketio.emit(
            "order_event",
            {
                "symbol": event.underlying,
                "action": event.strategy or "Multi-Order",
                "orderid": f"{event.successful_legs}/{event.total} legs",
                "exchange": event.exchange,
                "price_type": "MULTI",
                "product_type": "OPTIONS",
                "mode": "live",
                "batch_order": True,
                "is_last_order": True,
                "multiorder_summary": True,
                "successful_legs": event.successful_legs,
                "failed_legs": event.failed_legs,
            },
        )


def on_analyzer_error(event):
    """Emit analyzer_update only for analyze-mode errors."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)


def on_sandbox_order_filled(event):
    """Emit analyzer_update so OrderBook / TradeBook / Positions auto-refresh
    when a pending sandbox order fills via live LTP."""
    _emit_analyzer_update(event)


def on_sandbox_auto_squareoff(event):
    """Emit analyzer_update after the sandbox auto-square-off cycle so
    OrderBook (cancelled MIS orders) and Positions (closed MIS) refresh."""
    _emit_analyzer_update(event)


def on_sandbox_t1_settlement(event):
    """Emit analyzer_update after T+1 settlement so Positions and Holdings
    pages refresh."""
    _emit_analyzer_update(event)


def _emit_analyzer_update(event):
    """Helper to emit the analyzer_update socketio event."""
    socketio.emit(
        "analyzer_update",
        {"request": event.request_data, "response": event.response_data},
    )


# =============================================================================
# Strategy v2 + Account events
#
# These emit room-scoped to per-strategy rooms so multiple browser tabs / pages
# only receive updates for the strategies they're viewing. Every payload
# carries both ts_utc (epoch ms) and ts_ist (display string) — clients render
# ts_ist directly without timezone math.
# =============================================================================

from utils.ist_time import fmt_orderbook, now_utc, to_epoch_ms  # noqa: E402


def _strategy_room(strategy_id):
    return f"strategy_{int(strategy_id or 0)}"


def _ts_pair():
    """Return (ts_utc_epoch_ms, ts_ist_display_string) for 'now'."""
    now = now_utc()
    return to_epoch_ms(now), fmt_orderbook(now)


def on_strategy_signal_received(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_signal_received",
        {
            "strategy_id": event.strategy_id,
            "signing_method": event.signing_method,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_signal_rejected(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_signal_rejected",
        {
            "strategy_id": event.strategy_id,
            "reason": event.reason,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_run_started(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_run_started",
        {
            "strategy_id": event.strategy_id,
            "run_id": event.run_id,
            "mode": event.mode,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_state_changed(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_state_change",
        {
            "strategy_id": event.strategy_id,
            "run_id": event.run_id,
            "old_state": event.old_state,
            "new_state": event.new_state,
            "reason": event.reason,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_leg_resolved(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_leg_resolved",
        {
            "strategy_id": event.strategy_id,
            "run_id": event.run_id,
            "leg_id": event.leg_id,
            "resolved_symbol": event.resolved_symbol,
            "resolved_exchange": event.resolved_exchange,
            "tick_size": event.tick_size,
            "lot_size": event.lot_size,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_leg_filled(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_order_event",
        {
            "strategy_id": event.strategy_id,
            "run_id": event.run_id,
            "leg_id": event.leg_id,
            "orderid": event.orderid,
            "status": "complete",
            "filled_qty": event.qty,
            "avg_price": event.avg_price,
            "source": "entry_fill",
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_rms_triggered(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_rms_triggered",
        {
            "strategy_id": event.strategy_id,
            "run_id": event.run_id,
            "leg_id": event.leg_id,
            "rule": event.rule,
            "ltp": event.ltp,
            "threshold": event.threshold,
            "new_sl": event.new_sl,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_trail_advanced(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_trail_advanced",
        {
            "strategy_id": event.strategy_id,
            "run_id": event.run_id,
            "leg_id": event.leg_id,
            "advances": event.advances,
            "new_sl": event.new_sl,
            "ltp": event.ltp,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_exit_triggered(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_exit_triggered",
        {
            "strategy_id": event.strategy_id,
            "run_id": event.run_id,
            "reason": event.reason,
            "legs_exited": event.legs_exited,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_enter_failed(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_enter_failed",
        {
            "strategy_id": event.strategy_id,
            "run_id": event.run_id,
            "details": event.details,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_exit_failed(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_exit_failed",
        {
            "strategy_id": event.strategy_id,
            "run_id": event.run_id,
            "details": event.details,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_run_closed(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_run_closed",
        {
            "strategy_id": event.strategy_id,
            "run_id": event.run_id,
            "exit_reason": event.exit_reason,
            "realized_pnl": event.realized_pnl,
            "max_unrealized_pnl": event.max_unrealized_pnl,
            "max_drawdown": event.max_drawdown,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_engine_error(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_engine_error",
        {
            "strategy_id": event.strategy_id,
            "run_id": event.run_id,
            "error_type": event.error_type,
            "message": event.message,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_webhook_secret_rotated(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_webhook_rotated",
        {
            "strategy_id": event.strategy_id,
            "method": event.method,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_strategy_webhook_banned(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "strategy_webhook_banned",
        {
            "strategy_id": event.strategy_id,
            "webhook_id": event.webhook_id,
            "failures": event.failures,
            "ban_duration_seconds": event.ban_duration_seconds,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
        room=_strategy_room(event.strategy_id),
    )


def on_account_locked(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "account_locked",
        {
            "user_id": event.user_id,
            "reason": event.reason,
            "until_ts_utc": event.until_ts_utc,
            "cumulative_loss": event.cumulative_loss,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
    )


def on_account_unlocked(event):
    ts_utc, ts_ist = _ts_pair()
    socketio.emit(
        "account_unlocked",
        {
            "user_id": event.user_id,
            "cleared_by": event.cleared_by,
            "ts_utc": ts_utc,
            "ts_ist": ts_ist,
        },
    )
