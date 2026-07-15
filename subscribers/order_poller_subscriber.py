"""
Order-poller subscriber — kicks the live order/position poller into
fast mode the instant OpenAlgo places, modifies, or cancels an order.

This is the event-driven half of services/order_position_poller_service.py:
the poller never has to discover activity by polling faster
speculatively (which would waste broker REST budget shared with actual
trading calls) - it's told immediately, via the same EventBus that
already drives the socketio/telegram/whatsapp subscribers.

Analyze/sandbox mode is skipped here on purpose: it already gets
real-time order/trade/position events directly from the sandbox engine
(see sandbox/execution_engine.py), so there is no poller to fast-mode.
"""

from database.auth_db import get_auth_token_broker, verify_api_key
from services.order_position_poller_service import trigger_fast_mode
from utils.logging import get_logger

logger = get_logger(__name__)


def _trigger_for_api_key(api_key: str) -> None:
    if not api_key:
        return

    user_id = verify_api_key(api_key)
    if not user_id:
        return

    _, broker = get_auth_token_broker(api_key)
    if not broker:
        return

    trigger_fast_mode(broker, user_id)


def on_order_placed(event) -> None:
    if event.mode == "live":
        _trigger_for_api_key(event.api_key)


def on_order_modified(event) -> None:
    if event.mode == "live":
        _trigger_for_api_key(event.api_key)


def on_order_cancelled(event) -> None:
    if event.mode == "live":
        _trigger_for_api_key(event.api_key)
