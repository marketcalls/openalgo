"""
Wires OrderPositionPoller instances to real broker sessions.

start_poller_for_session / stop_poller_for_session are called from
database.auth_db.upsert_auth, gated by the same token_changed-or-revoke
check that already guards the WS market-data adapter pool teardown (see
upsert_auth) — a 2nd-device login resuming an unchanged token must not
restart the poller, for the same reason it must not tear down the
shared market-data feed (see the multi-session gating note there).

Fetch functions wrap the existing orderbook/tradebook/positionbook
services with original_data=None, which routes them straight to the
live broker (skipping analyze-mode routing) — the same internal-call
convention already used elsewhere in the codebase.
"""

import os
from typing import Any

from services.order_position_poller_service import (
    DEFAULT_FAST_MODE_TIMEOUT_SEC,
    DEFAULT_ORDER_POLL_FAST_MS,
    DEFAULT_ORDER_POLL_NORMAL_MS,
    DEFAULT_POSITION_POLL_MS,
    DEFAULT_TRADE_POLL_FAST_MS,
    DEFAULT_TRADE_POLL_NORMAL_MS,
    OrderPositionPoller,
    register_poller,
    unregister_poller,
)
from utils.logging import get_logger

logger = get_logger(__name__)


def _fetch_orders(auth_token: str, broker: str) -> list[dict[str, Any]]:
    from services.orderbook_service import get_orderbook_with_auth

    success, response, _ = get_orderbook_with_auth(auth_token, broker)
    if not success:
        return []
    data = response.get("data", {})
    if isinstance(data, dict):
        return data.get("orders", []) or []
    return data or []


def _fetch_trades(auth_token: str, broker: str) -> list[dict[str, Any]]:
    from services.tradebook_service import get_tradebook_with_auth

    success, response, _ = get_tradebook_with_auth(auth_token, broker)
    if not success:
        return []
    return response.get("data", []) or []


def _fetch_positions(auth_token: str, broker: str) -> list[dict[str, Any]]:
    from services.positionbook_service import get_positionbook_with_auth

    success, response, _ = get_positionbook_with_auth(auth_token, broker)
    if not success:
        return []
    return response.get("data", []) or []


def _make_on_events(poller: OrderPositionPoller):
    """Publish deltas plus a refreshed snapshot whenever a poll cycle
    changes something. Both go over the ZMQ bus (see order_event_publisher)
    rather than being read directly off `poller` by anything outside this
    process, since websocket_proxy/server.py runs in a separate process
    from this in production."""

    def _on_events(events: list[dict[str, Any]]) -> None:
        from websocket_proxy.order_event_publisher import publish_order_events, publish_snapshot

        try:
            publish_order_events(poller.broker, poller.user_id, events)
            publish_snapshot(poller.broker, poller.user_id, poller.get_last_snapshot())
        except Exception:
            logger.exception(
                f"Failed to publish order/position events for {poller.broker}_{poller.user_id}"
            )

    return _on_events


def start_poller_for_session(broker: str, user_id: str, auth_token: str) -> None:
    """Start (or restart) the poller for this broker session. Safe to call
    on every login — stops any existing instance for the same session
    first, so callers don't need to check for one themselves.

    Poll intervals are read from .env on every call (not cached), so an
    operator can tune ORDER_POLL_NORMAL_MS etc. and have it take effect on
    the next login without a code change. Defaults match the broker-aware
    polling strategy: conservative baseline, short fast-mode burst
    triggered by order activity (see subscribers/order_poller_subscriber.py),
    never a blanket aggressive interval — see
    services/order_position_poller_service.py's module docstring for why.
    """
    stop_poller_for_session(broker, user_id)

    poller = OrderPositionPoller(
        broker=broker,
        user_id=user_id,
        fetch_orders=lambda: _fetch_orders(auth_token, broker),
        fetch_trades=lambda: _fetch_trades(auth_token, broker),
        fetch_positions=lambda: _fetch_positions(auth_token, broker),
        order_poll_normal_ms=int(
            os.getenv("ORDER_POLL_NORMAL_MS", str(DEFAULT_ORDER_POLL_NORMAL_MS))
        ),
        order_poll_fast_ms=int(os.getenv("ORDER_POLL_FAST_MS", str(DEFAULT_ORDER_POLL_FAST_MS))),
        trade_poll_normal_ms=int(
            os.getenv("TRADE_POLL_NORMAL_MS", str(DEFAULT_TRADE_POLL_NORMAL_MS))
        ),
        trade_poll_fast_ms=int(os.getenv("TRADE_POLL_FAST_MS", str(DEFAULT_TRADE_POLL_FAST_MS))),
        position_poll_ms=int(os.getenv("POSITION_POLL_MS", str(DEFAULT_POSITION_POLL_MS))),
        fast_mode_timeout_sec=int(
            os.getenv("FAST_MODE_TIMEOUT_SEC", str(DEFAULT_FAST_MODE_TIMEOUT_SEC))
        ),
    )
    register_poller(poller)
    poller.start(_make_on_events(poller))
    logger.info(f"Started order/position poller for {broker}_{user_id}")


def stop_poller_for_session(broker: str, user_id: str) -> None:
    """Stop and unregister the poller for this session, if one is running.
    A no-op (not an error) when no poller exists — e.g. analyze mode, or a
    session that never had one started."""
    poller = unregister_poller(broker, user_id)
    if poller is not None:
        poller.stop()
        logger.info(f"Stopped order/position poller for {broker}_{user_id}")
