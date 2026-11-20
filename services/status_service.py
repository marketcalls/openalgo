"""What is active right now, for the status API.

Gathers numbers that already exist elsewhere into one answer: the broker feed
connections and subscribed symbols the Health Monitor shows, the open streams
and threads the System page shows, and how often each kind of broker data
request was made in the last few minutes (``utils.request_counter``).
Everything is read from memory or the proxy's stats file; nothing here calls
the broker or writes anything.
"""

from __future__ import annotations

import threading
from typing import Any

from database.auth_db import verify_api_key
from utils import request_counter, stream_registry
from utils.health_monitor import read_websocket_connections
from utils.logging import get_logger

logger = get_logger(__name__)


def get_active_status() -> dict[str, Any]:
    """The status payload, without the API key check."""
    connections, total_connections, total_symbols = read_websocket_connections()
    budget = stream_registry.thread_budget()
    streams = stream_registry.stream_counts()
    return {
        "broker_feed": {
            "connections": total_connections,
            "subscribed_symbols": total_symbols,
            "pools": connections,
        },
        "streams": {
            "open": streams["total_active"],
            "by_kind": streams["active"],
        },
        "threads": {
            "active": threading.active_count(),
            "web_server_threads": budget["threads"],
            "browser_connections": budget["socketio"],
            "headroom": budget["headroom"],
        },
        "requests": request_counter.counts(),
    }


def get_status(api_key: str) -> tuple[bool, dict[str, Any], int]:
    """Check the key, then return what is active.

    Returns:
        Tuple of (success, response body, HTTP status code).
    """
    if verify_api_key(api_key) is None:
        return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403
    return True, {"status": "success", "data": get_active_status()}, 200
