"""
Telegram subscriber — sends alerts for all order events.

Uses the existing telegram_alert_service.send_order_alert() which already
handles mode detection (ANALYZE vs LIVE prefix) and message formatting.
Called directly from the EventBus thread pool — send_order_alert() handles
its own async dispatch via alert_executor internally.
"""

from services.telegram_alert_service import telegram_alert_service
from utils.logging import get_logger

logger = get_logger(__name__)


def _send_alert(api_type, order_data, response_data, api_key):
    """Wrapper that matches the original dispatch pattern."""
    telegram_alert_service.send_order_alert(
        api_type,
        order_data,
        response_data,
        api_key,
    )


def on_order_placed(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_failed(event):
    # Original code does NOT send telegram on order failure — preserve that behavior
    pass


def on_smart_order_no_action(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_modified(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_modify_failed(event):
    # Original code does NOT send telegram on modify failure
    pass


def on_order_cancelled(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_cancel_failed(event):
    # Original code does NOT send telegram on cancel failure
    pass


def on_all_orders_cancelled(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_position_closed(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_basket_completed(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_split_completed(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_options_completed(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_multiorder_completed(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_analyzer_error(event):
    # Original code does NOT send telegram on validation errors — preserve behavior
    pass


# -----------------------------------------------------------------------------
# Strategy v2 + Account events
#
# Telegram only on the loud topics — too many alerts would be noise. The full
# audit lives in strategy_events; the dashboard timeline is the primary view.
# -----------------------------------------------------------------------------

from utils.ist_time import fmt_orderbook, now_utc  # noqa: E402


def _broadcast(message: str) -> None:
    """Send a strategy alert to all linked telegram users (single-user platform
    means this fans out to the operator's account).
    """
    try:
        telegram_alert_service.send_broadcast_alert(message)
    except Exception:
        logger.exception("telegram_subscriber: failed to dispatch strategy alert")


def _strategy_header(event, label: str) -> str:
    sid = getattr(event, "strategy_id", "?")
    rid = getattr(event, "run_id", "?")
    return f"[{label}] strategy={sid} run={rid} at {fmt_orderbook(now_utc())} IST"


def on_strategy_run_closed(event):
    msg = (
        f"{_strategy_header(event, 'Strategy CLOSED')}\n"
        f"Reason: {event.exit_reason}\n"
        f"Realized P&L: ₹{event.realized_pnl:+.2f}\n"
        f"Peak unrealized: ₹{event.max_unrealized_pnl:+.2f}\n"
        f"Max drawdown: ₹{event.max_drawdown:+.2f}"
    )
    _broadcast(msg)


def on_strategy_exit_failed(event):
    msg = (
        f"{_strategy_header(event, 'Strategy EXIT FAILED')}\n"
        f"Operator action required — broker exit rejected or partial.\n"
        f"Details: {event.details}"
    )
    _broadcast(msg)


def on_strategy_engine_error(event):
    msg = (
        f"{_strategy_header(event, 'Strategy ENGINE ERROR')}\n"
        f"Error type: {event.error_type}\n"
        f"Message: {event.message}\n"
        f"Run dropped from dispatcher; other strategies unaffected."
    )
    _broadcast(msg)


def on_strategy_webhook_banned(event):
    msg = (
        f"[Webhook BANNED] strategy={event.strategy_id} at {fmt_orderbook(now_utc())} IST\n"
        f"Failures: {event.failures}, ban duration: {event.ban_duration_seconds}s\n"
        f"Source IP: {event.source_ip or '?'}\n"
        f"Possible causes: leaked URL + brute-force attempt, "
        f"or your TradingView alert payload is misconfigured. "
        f"Verify your alert JSON and rotate the secret if needed."
    )
    _broadcast(msg)


def on_account_locked(event):
    until = ""
    if event.until_ts_utc:
        until = f" until {fmt_orderbook(event.until_ts_utc)} IST"
    msg = (
        f"[ACCOUNT LOCKED]{until}\n"
        f"User: {event.user_id}\n"
        f"Reason: {event.reason}\n"
        f"Cumulative loss: ₹{event.cumulative_loss:+.2f}\n"
        f"New strategy signals will be rejected until cleared."
    )
    _broadcast(msg)
