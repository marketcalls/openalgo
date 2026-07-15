"""
Bridges sandbox order fills straight onto the order_update/trade_update/
position_update WebSocket channels.

Sandbox already knows the exact state change the instant it happens
(see sandbox/execution_engine.py's _execute_order), so this skips the
REST poller/diff engine entirely for sandbox mode - lower latency, and
it reuses the same normalizer + ZMQ publisher as the live-trading
poller so clients see an identical payload shape regardless of source.

generation/sequence are fixed here rather than drawn from a poller,
since sandbox fills are a supplementary real-time push alongside the
existing analyzer_update event, not the reconnect source of truth -
get_last_snapshot() on the live poller (services/order_position_poller_service.py)
covers reconnects for live trading only.
"""

from typing import Any

from services.order_event_normalizer import (
    normalize_order_event,
    normalize_position_event,
    normalize_trade_event,
)
from utils.logging import get_logger
from websocket_proxy.order_event_publisher import publish_order_events

logger = get_logger(__name__)


def publish_sandbox_fill(
    broker: str | None,
    user_id: str,
    order: dict[str, Any],
    trade: dict[str, Any],
    position: dict[str, Any] | None = None,
) -> None:
    """order/trade/position are already normalized to the common shape
    (see services/order_event_normalizer for the expected fields) - the
    caller builds them from the sandbox ORM rows.

    Never raises: a WebSocket delivery failure must not break sandbox
    order execution, so any error here is logged and swallowed.
    """
    if not broker:
        logger.warning(f"Skipping sandbox realtime publish: no broker resolved for {user_id}")
        return

    try:
        events = [
            normalize_order_event(order, generation=0, sequence=0),
            normalize_trade_event(trade, generation=0, sequence=1),
        ]
        if position is not None:
            events.append(normalize_position_event(position, generation=0, sequence=2))

        publish_order_events(broker, user_id, events)
    except Exception:
        logger.exception(f"Failed to publish sandbox fill events for {broker}_{user_id}")
