"""
WhatsApp subscriber — mirrors subscribers/telegram_subscriber.py.

Sends alerts for the same set of order events the Telegram channel covers,
preserving the same "failures don't notify" behavior so a flood of validation
rejections doesn't spam either channel.

Called directly from the EventBus thread pool. send_order_alert() internally
queues onto its own alert_executor pool, so this callback returns quickly
and doesn't block the bus worker.
"""

from services.whatsapp_alert_service import whatsapp_alert_service
from utils.logging import get_logger

logger = get_logger(__name__)


def _send(api_type, order_data, response_data, api_key):
    whatsapp_alert_service.send_order_alert(api_type, order_data, response_data, api_key)


def on_order_placed(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_failed(event):
    # Mirror telegram: failures are noisy; don't notify on this channel.
    pass


def on_smart_order_no_action(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_modified(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_modify_failed(event):
    pass


def on_order_cancelled(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_cancel_failed(event):
    pass


def on_all_orders_cancelled(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_position_closed(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_basket_completed(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_split_completed(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_options_completed(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_multiorder_completed(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_analyzer_error(event):
    # Mirror telegram: validation errors stay off the chat channels.
    pass
