"""
SocketIO subscriber — emits the correct socketio event for each order event.

Reproduces the exact event names and payload structures from the original code.
All emissions use socketio.start_background_task for consistent async behavior.
"""

from extensions import socketio
from utils.logging import get_logger

logger = get_logger(__name__)


def on_order_placed(event):
    """Emit order_event (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        socketio.start_background_task(
            socketio.emit,
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
        socketio.start_background_task(
            socketio.emit,
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
        socketio.start_background_task(
            socketio.emit,
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
        socketio.start_background_task(
            socketio.emit,
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
        socketio.start_background_task(
            socketio.emit,
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
        socketio.start_background_task(
            socketio.emit,
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
        socketio.start_background_task(
            socketio.emit,
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
        socketio.start_background_task(
            socketio.emit,
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
        socketio.start_background_task(
            socketio.emit,
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
        socketio.start_background_task(
            socketio.emit,
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


def _emit_analyzer_update(event):
    """Helper to emit the analyzer_update socketio event."""
    socketio.start_background_task(
        socketio.emit,
        "analyzer_update",
        {"request": event.request_data, "response": event.response_data},
    )
