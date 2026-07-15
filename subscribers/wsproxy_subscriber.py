"""
WebSocket-proxy subscriber — bridges order.update events onto the ZMQ bus so
the out-of-process websocket_proxy (port 8765) can relay them to WS/SDK
clients that sent {"action": "subscribe_orders"}.

Publishes through the same SharedZmqPublisher singleton used by
database/cache_invalidation.py: publishers CONNECT, the proxy's SUB BINDs
(fan-in topology — see websocket_proxy/server.py and CLAUDE.md). This module
owns no ZMQ socket of its own.
"""

from utils.logging import get_logger

logger = get_logger(__name__)


def on_order_update(event):
    """Publish an OrderUpdateEvent onto the ZMQ bus for websocket_proxy relay.

    Topic: "{BROKER}_{USER_ID}_orders" for live brokers, "ANALYZE_{USER_ID}_orders"
    for sandbox — matches the suffix websocket_proxy/server.py's zmq_listener
    checks for.
    """
    try:
        user_id = _resolve_user_id(event)
        if not user_id:
            logger.debug("order.update: could not resolve user_id, skipping ZMQ relay")
            return

        broker_seg = "ANALYZE" if event.mode == "analyze" else (event.broker or "unknown").upper()
        topic = f"{broker_seg}_{user_id}_orders"

        payload = {
            "type": "order_update",
            "user_id": user_id,
            "mode": event.mode,
            "broker": event.broker,
            "orderid": event.orderid,
            "symbol": event.symbol,
            "exchange": event.exchange,
            "action": event.action,
            "quantity": event.quantity,
            "price": event.price,
            "trigger_price": event.trigger_price,
            "pricetype": event.pricetype,
            "product": event.product,
            "order_status": event.order_status,
            "filled_quantity": event.filled_quantity,
            "pending_quantity": event.pending_quantity,
            "average_price": event.average_price,
            "rejection_reason": event.rejection_reason,
        }

        # Lazy import — avoids a circular dependency between subscribers and
        # websocket_proxy packages, and keeps this subscriber usable even
        # when the websocket subsystem is disabled.
        from websocket_proxy.connection_manager import SharedZmqPublisher

        publisher = SharedZmqPublisher()
        if not publisher._connected:
            publisher.connect()  # idempotent — connects to the proxy SUB once

        publisher.publish(topic, payload)

    except Exception:
        logger.exception("Failed to relay order.update onto ZMQ bus")


def _resolve_user_id(event) -> str | None:
    """Resolve the OpenAlgo user_id for this event.

    Sandbox events already carry user_id via request_data (set by the
    sandbox event publishers); live events resolve it from api_key.
    """
    user_id = event.request_data.get("user_id") if event.request_data else None
    if user_id:
        return user_id

    if not event.api_key:
        return None

    from database.auth_db import get_username_by_apikey

    return get_username_by_apikey(event.api_key)
