"""Broker connection keep-warm service.

The shared httpx client (utils/httpx_client.py) recycles idle pooled
connections after ``keepalive_expiry`` (30s). Any order placed after a longer
idle gap therefore pays a fresh TCP + TLS handshake to the broker
(~100-150ms observed) before the order is even transmitted.

This service keeps the pooled connection to the active broker's API origin
warm by sending a tiny HEAD request through the SAME shared client every
``BROKER_KEEPALIVE_INTERVAL`` seconds (default 20s, below the 30s pool
expiry) during the configured market window. The response status does not
matter — touching the origin is enough to keep the pooled connection alive.

Lifecycle and FD notes:
- One module-level daemon thread, started once via start_broker_keepalive()
  (idempotent). Under eventlet this becomes a cooperative green thread.
- No new connections are created beyond the shared client's existing pool.
- The active broker is read from the Auth table at most every
  BROKER_REFRESH_SECONDS; the scoped session is removed after every lookup
  so no read transaction (and no SQLite lock) is left open on this thread.
"""

import importlib
import os
import threading
import time
from datetime import datetime

import pytz

from utils.logging import get_logger

logger = get_logger(__name__)

_IST = pytz.timezone("Asia/Kolkata")

_ENABLED = os.getenv("BROKER_CONNECTION_KEEPALIVE", "TRUE").strip().upper() in (
    "TRUE",
    "1",
    "YES",
)
_PING_INTERVAL = max(5, int(os.getenv("BROKER_KEEPALIVE_INTERVAL", "20")))
# IST window, Mon-Fri. Default spans NSE/BSE pre-open through the MCX close.
_WINDOW = os.getenv("BROKER_KEEPALIVE_WINDOW", "09:00-23:30")

# How often to re-resolve the active broker once a base URL is known, so the
# loop notices logout or a broker switch without querying the DB every ping.
_BROKER_REFRESH_SECONDS = 300

# Attribute names brokers use for their API origin in api/baseurl.py
_URL_ATTRS = ("ROOT_URL", "BASE_URL")

_thread = None
_thread_lock = threading.Lock()


def _parse_window(spec):
    """Parse "HH:MM-HH:MM" into start/end minutes-of-day."""
    try:
        start_s, end_s = spec.split("-")
        sh, sm = (int(x) for x in start_s.strip().split(":"))
        eh, em = (int(x) for x in end_s.strip().split(":"))
        return sh * 60 + sm, eh * 60 + em
    except (ValueError, AttributeError):
        logger.warning(f"Invalid BROKER_KEEPALIVE_WINDOW '{spec}', using 09:00-23:30")
        return 9 * 60, 23 * 60 + 30


_WINDOW_START, _WINDOW_END = _parse_window(_WINDOW)


def _in_market_window():
    now = datetime.now(_IST)
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    minutes = now.hour * 60 + now.minute
    return _WINDOW_START <= minutes <= _WINDOW_END


def _resolve_base_url(broker):
    """Return the broker's API origin from broker.{broker}.api.baseurl, if it exists."""
    if not broker:
        return None
    try:
        module = importlib.import_module(f"broker.{broker}.api.baseurl")
    except ImportError:
        return None
    for attr in _URL_ATTRS:
        url = getattr(module, attr, None)
        if isinstance(url, str) and url.startswith("http"):
            return url
    return None


def _get_active_broker():
    """Read the active (non-revoked) broker from the Auth table."""
    from database.auth_db import Auth, db_session

    try:
        auth_obj = Auth.query.filter_by(is_revoked=False).first()
        return auth_obj.broker if auth_obj else None
    except Exception:
        # DB may not be initialized yet during startup; retry on a later tick
        return None
    finally:
        db_session.remove()


def _keepalive_loop():
    from utils.httpx_client import get_httpx_client

    base_url = None
    unresolved = set()
    last_refresh = 0.0

    while True:
        try:
            if not _in_market_window():
                time.sleep(60)
                continue

            now = time.monotonic()
            if base_url is None or now - last_refresh >= _BROKER_REFRESH_SECONDS:
                last_refresh = now
                broker = _get_active_broker()
                base_url = _resolve_base_url(broker)
                if broker and base_url is None and broker not in unresolved:
                    unresolved.add(broker)
                    logger.info(
                        f"Connection keep-warm idle: broker '{broker}' has no "
                        f"api/baseurl.py with {' or '.join(_URL_ATTRS)}"
                    )

            if base_url:
                client = get_httpx_client()
                response = client.head(base_url, timeout=5)
                logger.debug(f"Keep-warm ping {base_url} -> {response.status_code}")
        except Exception as e:
            # Transient network failures are expected (broker maintenance,
            # offline dev box). Log at debug so a flaky link cannot flood
            # log/errors.jsonl every ping interval.
            logger.debug(f"Keep-warm ping failed: {e}")

        time.sleep(_PING_INTERVAL)


def start_broker_keepalive():
    """Start the keep-warm daemon thread (idempotent)."""
    global _thread

    if not _ENABLED:
        logger.info("Broker connection keep-warm disabled via BROKER_CONNECTION_KEEPALIVE")
        return

    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(
            target=_keepalive_loop, daemon=True, name="broker-keepalive"
        )
        _thread.start()
        logger.info(
            f"Broker connection keep-warm started: every {_PING_INTERVAL}s, "
            f"window {_WINDOW} IST Mon-Fri"
        )
