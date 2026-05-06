"""
Subscriber registration — wires all subscribers to the event bus at app startup.

Call register_all() once during app initialization.
"""

from subscribers import (
    log_subscriber,
    socketio_subscriber,
    strategy_audit_subscriber,
    telegram_subscriber,
)
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)


# Strategy v2 + account topics — used by the audit subscriber to fan-in every
# event into a single chained-hash log row.
STRATEGY_TOPICS = (
    "strategy.signal_received",
    "strategy.signal_rejected",
    "strategy.run_started",
    "strategy.state_changed",
    "strategy.leg_resolved",
    "strategy.leg_filled",
    "strategy.rms_triggered",
    "strategy.trail_advanced",
    "strategy.exit_triggered",
    "strategy.enter_failed",
    "strategy.exit_failed",
    "strategy.run_closed",
    "strategy.engine_error",
    "strategy.webhook_secret_rotated",
    "strategy.webhook_banned",
)

ACCOUNT_TOPICS = (
    "account.locked",
    "account.unlocked",
)


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

    # --- sandbox engine-internal events (analyze mode only, UI auto-refresh) ---
    # Only the socketio subscriber is wired — these are engine-driven state
    # changes, not user API calls, so they don't belong in analyzer_logs and
    # would be noise on telegram.
    bus.subscribe(
        "sandbox.order_filled",
        socketio_subscriber.on_sandbox_order_filled,
        "socketio:sandbox_order_filled",
    )
    bus.subscribe(
        "sandbox.auto_squareoff",
        socketio_subscriber.on_sandbox_auto_squareoff,
        "socketio:sandbox_auto_squareoff",
    )
    bus.subscribe(
        "sandbox.t1_settlement",
        socketio_subscriber.on_sandbox_t1_settlement,
        "socketio:sandbox_t1_settlement",
    )

    # ------------------------------------------------------------------------
    # Strategy v2 + Account events
    # ------------------------------------------------------------------------

    # Audit subscriber — single writer of strategy_events table. Every
    # strategy.* and account.* topic fans in here for chained-hash persistence.
    for topic in STRATEGY_TOPICS + ACCOUNT_TOPICS:
        bus.subscribe(topic, strategy_audit_subscriber.on_event, f"audit:{topic}")

    # Per-topic socketio + log wiring.
    _STRATEGY_HANDLERS = {
        "strategy.signal_received":         "on_strategy_signal_received",
        "strategy.signal_rejected":         "on_strategy_signal_rejected",
        "strategy.run_started":             "on_strategy_run_started",
        "strategy.state_changed":           "on_strategy_state_changed",
        "strategy.leg_resolved":            "on_strategy_leg_resolved",
        "strategy.leg_filled":              "on_strategy_leg_filled",
        "strategy.rms_triggered":           "on_strategy_rms_triggered",
        "strategy.trail_advanced":          "on_strategy_trail_advanced",
        "strategy.exit_triggered":          "on_strategy_exit_triggered",
        "strategy.enter_failed":            "on_strategy_enter_failed",
        "strategy.exit_failed":             "on_strategy_exit_failed",
        "strategy.run_closed":              "on_strategy_run_closed",
        "strategy.engine_error":            "on_strategy_engine_error",
        "strategy.webhook_secret_rotated":  "on_strategy_webhook_secret_rotated",
        "strategy.webhook_banned":          "on_strategy_webhook_banned",
    }
    for topic, handler_name in _STRATEGY_HANDLERS.items():
        log_handler = getattr(log_subscriber, handler_name, None)
        if log_handler is not None:
            bus.subscribe(topic, log_handler, f"log:{topic}")
        sock_handler = getattr(socketio_subscriber, handler_name, None)
        if sock_handler is not None:
            bus.subscribe(topic, sock_handler, f"socketio:{topic}")

    # Telegram fires only on the loud topics — see plan §5.3.4.
    bus.subscribe(
        "strategy.run_closed",
        telegram_subscriber.on_strategy_run_closed,
        "telegram:strategy_run_closed",
    )
    bus.subscribe(
        "strategy.exit_failed",
        telegram_subscriber.on_strategy_exit_failed,
        "telegram:strategy_exit_failed",
    )
    bus.subscribe(
        "strategy.engine_error",
        telegram_subscriber.on_strategy_engine_error,
        "telegram:strategy_engine_error",
    )
    bus.subscribe(
        "strategy.webhook_banned",
        telegram_subscriber.on_strategy_webhook_banned,
        "telegram:strategy_webhook_banned",
    )

    # Account.* — log + socketio + telegram (locked only).
    bus.subscribe("account.locked",
                  log_subscriber.on_account_locked, "log:account_locked")
    bus.subscribe("account.locked",
                  socketio_subscriber.on_account_locked, "socketio:account_locked")
    bus.subscribe("account.locked",
                  telegram_subscriber.on_account_locked, "telegram:account_locked")
    bus.subscribe("account.unlocked",
                  log_subscriber.on_account_unlocked, "log:account_unlocked")
    bus.subscribe("account.unlocked",
                  socketio_subscriber.on_account_unlocked, "socketio:account_unlocked")

    # ------------------------------------------------------------------------
    # Position tracker — keeps strategy_orders / trades / positions in sync
    # with broker reality. Subscribes to the existing OrderEvent stream
    # (placed/failed/cancelled) and the new BrokerOrderUpdateEvent.
    # ------------------------------------------------------------------------
    from services.strategy import position_tracker

    bus.subscribe("order.placed", position_tracker.on_order_placed,
                  "tracker:order_placed")
    bus.subscribe("order.failed", position_tracker.on_order_failed,
                  "tracker:order_failed")
    bus.subscribe("order.cancelled", position_tracker.on_order_cancelled,
                  "tracker:order_cancelled")
    bus.subscribe("broker.order_update", position_tracker.on_broker_order_update,
                  "tracker:broker_order_update")

    logger.debug("EventBus: all subscribers registered")
