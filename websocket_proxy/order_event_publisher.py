"""
Publishes order/trade/position events onto the shared ZeroMQ bus, under
the {broker}_{user_id}_orders / _trades / _positions topics that
websocket_proxy/server.py's zmq_listener reserves for account-level
data (previously a dead no-op skip - broker adapters only ever
published market-data topics).

Used by both the REST poller (services/order_position_poller_service.py)
for live trading, and the sandbox engine directly
(sandbox/execution_engine.py, sandbox/squareoff_manager.py) - sandbox
already knows the exact state change in real time, so it publishes here
without going through the poller/diff engine at all.
"""

from typing import Any, Protocol

from utils.logging import get_logger
from websocket_proxy.connection_manager import SharedZmqPublisher

logger = get_logger(__name__)

_TOPIC_SUFFIX = {
    "order_update": "orders",
    "trade_update": "trades",
    "position_update": "positions",
}


class ZmqPublisher(Protocol):
    def connect(self) -> Any: ...
    def publish(self, topic: str, data: dict[str, Any]) -> None: ...


def publish_order_events(
    broker: str,
    user_id: str,
    events: list[dict[str, Any]],
    publisher: ZmqPublisher | None = None,
) -> None:
    """Publish each event onto the topic matching its event_type.

    Skips (and logs) an event with an unrecognized event_type rather than
    raising - this sits on a hot path (poll cycle / sandbox fill) where
    one bad event must not block the rest of the batch.
    """
    if not events:
        return

    pub = publisher if publisher is not None else SharedZmqPublisher()
    pub.connect()

    for event in events:
        event_type = event.get("event_type", "")
        suffix = _TOPIC_SUFFIX.get(event_type)
        if suffix is None:
            logger.warning(f"Skipping event with unknown event_type: {event_type}")
            continue
        topic = f"{broker}_{user_id}_{suffix}"
        pub.publish(topic, event)


def publish_snapshot(
    broker: str,
    user_id: str,
    snapshot: dict[str, Any],
    publisher: ZmqPublisher | None = None,
) -> None:
    """Publish a full order/trade/position snapshot on a dedicated topic.

    The WebSocket proxy (websocket_proxy/server.py) and the poller
    (services/order_position_poller_service.py) run in separate processes
    in production (gunicorn+eventlet - see CLAUDE.md), so the proxy can't
    call get_last_snapshot() on the poller directly. Instead the poller
    publishes its snapshot here whenever something changes, and the proxy
    caches the latest one from the ZMQ bus to serve on subscribe/reconnect.
    """
    pub = publisher if publisher is not None else SharedZmqPublisher()
    pub.connect()
    topic = f"{broker}_{user_id}_snapshot"
    pub.publish(topic, snapshot)
