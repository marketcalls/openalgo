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
