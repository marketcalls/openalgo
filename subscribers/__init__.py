"""
Subscriber registration — wires all subscribers to the event bus at app startup.

Call register_all() once during app initialization.
"""

from subscribers import log_subscriber, socketio_subscriber, telegram_subscriber
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)


def register_all():
    """Register all subscribers to the event bus. Call once at app startup."""

    # --- order.placed ---
    bus.subscribe("order.placed", log_subscriber.on_order_placed, "log:order_placed")
    bus.subscribe("order.placed", socketio_subscriber.on_order_placed, "socketio:order_placed")
    bus.subscribe("order.placed", telegram_subscriber.on_order_placed, "telegram:order_placed")

    # --- order.failed ---
    bus.subscribe("order.failed", log_subscriber.on_order_failed, "log:order_failed")
    bus.subscribe("order.failed", socketio_subscriber.on_order_failed, "socketio:order_failed")
    bus.subscribe("order.failed", telegram_subscriber.on_order_failed, "telegram:order_failed")

    # --- order.no_action (smart order) ---
    bus.subscribe("order.no_action", log_subscriber.on_smart_order_no_action, "log:no_action")
    bus.subscribe("order.no_action", socketio_subscriber.on_smart_order_no_action, "socketio:no_action")
    bus.subscribe("order.no_action", telegram_subscriber.on_smart_order_no_action, "telegram:no_action")

    # --- order.modified ---
    bus.subscribe("order.modified", log_subscriber.on_order_modified, "log:order_modified")
    bus.subscribe("order.modified", socketio_subscriber.on_order_modified, "socketio:order_modified")
    bus.subscribe("order.modified", telegram_subscriber.on_order_modified, "telegram:order_modified")

    # --- order.modify_failed ---
    bus.subscribe("order.modify_failed", log_subscriber.on_order_modify_failed, "log:modify_failed")
    bus.subscribe("order.modify_failed", socketio_subscriber.on_order_modify_failed, "socketio:modify_failed")
    bus.subscribe("order.modify_failed", telegram_subscriber.on_order_modify_failed, "telegram:modify_failed")

    # --- order.cancelled ---
    bus.subscribe("order.cancelled", log_subscriber.on_order_cancelled, "log:order_cancelled")
    bus.subscribe("order.cancelled", socketio_subscriber.on_order_cancelled, "socketio:order_cancelled")
    bus.subscribe("order.cancelled", telegram_subscriber.on_order_cancelled, "telegram:order_cancelled")

    # --- order.cancel_failed ---
    bus.subscribe("order.cancel_failed", log_subscriber.on_order_cancel_failed, "log:cancel_failed")
    bus.subscribe("order.cancel_failed", socketio_subscriber.on_order_cancel_failed, "socketio:cancel_failed")
    bus.subscribe("order.cancel_failed", telegram_subscriber.on_order_cancel_failed, "telegram:cancel_failed")

    # --- orders.all_cancelled ---
    bus.subscribe("orders.all_cancelled", log_subscriber.on_all_orders_cancelled, "log:all_cancelled")
    bus.subscribe("orders.all_cancelled", socketio_subscriber.on_all_orders_cancelled, "socketio:all_cancelled")
    bus.subscribe("orders.all_cancelled", telegram_subscriber.on_all_orders_cancelled, "telegram:all_cancelled")

    # --- position.closed ---
    bus.subscribe("position.closed", log_subscriber.on_position_closed, "log:position_closed")
    bus.subscribe("position.closed", socketio_subscriber.on_position_closed, "socketio:position_closed")
    bus.subscribe("position.closed", telegram_subscriber.on_position_closed, "telegram:position_closed")

    # --- basket.completed ---
    bus.subscribe("basket.completed", log_subscriber.on_basket_completed, "log:basket_completed")
    bus.subscribe("basket.completed", socketio_subscriber.on_basket_completed, "socketio:basket_completed")
    bus.subscribe("basket.completed", telegram_subscriber.on_basket_completed, "telegram:basket_completed")

    # --- split.completed ---
    bus.subscribe("split.completed", log_subscriber.on_split_completed, "log:split_completed")
    bus.subscribe("split.completed", socketio_subscriber.on_split_completed, "socketio:split_completed")
    bus.subscribe("split.completed", telegram_subscriber.on_split_completed, "telegram:split_completed")

    # --- options.completed ---
    bus.subscribe("options.completed", log_subscriber.on_options_completed, "log:options_completed")
    bus.subscribe("options.completed", socketio_subscriber.on_options_completed, "socketio:options_completed")
    bus.subscribe("options.completed", telegram_subscriber.on_options_completed, "telegram:options_completed")

    # --- multiorder.completed ---
    bus.subscribe("multiorder.completed", log_subscriber.on_multiorder_completed, "log:multiorder_completed")
    bus.subscribe("multiorder.completed", socketio_subscriber.on_multiorder_completed, "socketio:multiorder_completed")
    bus.subscribe("multiorder.completed", telegram_subscriber.on_multiorder_completed, "telegram:multiorder_completed")

    # --- analyzer.error ---
    bus.subscribe("analyzer.error", log_subscriber.on_analyzer_error, "log:analyzer_error")
    bus.subscribe("analyzer.error", socketio_subscriber.on_analyzer_error, "socketio:analyzer_error")
    bus.subscribe("analyzer.error", telegram_subscriber.on_analyzer_error, "telegram:analyzer_error")

    logger.info("EventBus: all subscribers registered")
