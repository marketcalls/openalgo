"""
Order-update adapter lifecycle service.

Owns the single always-on order-feed adapter per broker session (per
CLAUDE.md's multi-session invariant: one adapter per {user, broker}, NOT one
per browser tab / WS client). Adapters ingest broker push feeds (dedicated
order WebSockets, or REST polling for brokers without push) in the Flask
process, publish events.OrderUpdateEvent on the in-process event bus, and the
registered subscribers fan out to socketio + the ZMQ relay
(subscribers/wsproxy_subscriber.py) for websocket_proxy clients.

Lifecycle:
- app startup (start_order_update_adapters_on_boot): start an adapter for the
  existing non-revoked broker session, mirroring start_broker_keepalive().
- database/auth_db.upsert_auth: on a REAL token change -> restart with fresh
  credentials; on revoke -> stop. Unchanged-token multi-session resumes never
  touch the adapter (issue #1591 invariant).

FD hygiene: the registry holds at most one adapter per user; the previous
adapter is always disconnect()ed (socket closed, threads exit) before a new
one starts.

Disable with ORDER_UPDATES_ENABLED=FALSE in .env.
"""

import importlib
import os
import threading

from utils.logging import get_logger

logger = get_logger(__name__)

# broker -> (module_path, factory_name). Lazily imported so app startup does
# not pay for (or fail on) brokers that are not in use.
_BROKER_FACTORIES: dict[str, tuple[str, str]] = {
    "dhan": ("broker.dhan.streaming.dhan_order_adapter", "create_dhan_order_adapter"),
    "fyers": ("broker.fyers.streaming.fyers_order_adapter", "create_fyers_order_adapter"),
    "upstox": ("broker.upstox.streaming.upstox_order_adapter", "create_upstox_order_adapter"),
    "aliceblue": (
        "broker.aliceblue.streaming.aliceblue_order_adapter",
        "create_aliceblue_order_adapter",
    ),
    "definedge": (
        "broker.definedge.streaming.definedge_order_adapter",
        "create_definedge_order_adapter",
    ),
    "indmoney": (
        "broker.indmoney.streaming.indmoney_order_adapter",
        "create_indmoney_order_adapter",
    ),
    "angel": ("broker.angel.streaming.angel_order_adapter", "create_angel_order_adapter"),
    "zerodha": ("broker.zerodha.streaming.zerodha_order_adapter", "create_zerodha_order_adapter"),
    "nubra": ("broker.nubra.streaming.nubra_order_adapter", "create_nubra_order_adapter"),
    "arrow": ("broker.arrow.streaming.arrow_order_adapter", "create_arrow_order_adapter"),
    "iiflcapital": (
        "broker.iiflcapital.streaming.iiflcapital_order_adapter",
        "create_iiflcapital_order_adapter",
    ),
}

# Brokers with no push mechanism fall back to REST-orderbook polling.
_POLLING_BROKERS = {"groww"}

# user_id -> live adapter (BaseOrderUpdateAdapter or PollingOrderUpdateAdapter)
_ADAPTERS: dict[str, object] = {}
_LOCK = threading.Lock()


def _order_updates_enabled() -> bool:
    return os.getenv("ORDER_UPDATES_ENABLED", "TRUE").upper() != "FALSE"


def _build_adapter(user_id: str, broker: str):
    broker = (broker or "").lower()

    if broker in _POLLING_BROKERS:
        from websocket_proxy.order_adapter import PollingOrderUpdateAdapter

        return PollingOrderUpdateAdapter(broker_name=broker, user_id=user_id)

    entry = _BROKER_FACTORIES.get(broker)
    if entry is None:
        logger.info(f"No order-update adapter available for broker '{broker}' — skipping")
        return None

    module_path, factory_name = entry
    try:
        # websocket_proxy/__init__ and broker/*/streaming/__init__ import each
        # other; the cycle only resolves when websocket_proxy loads FIRST (the
        # normal app path via app.py). Force that ordering here so this service
        # also works from tests/scripts that import broker modules cold.
        importlib.import_module("websocket_proxy")
        module = importlib.import_module(module_path)
        factory = getattr(module, factory_name)
    except (ImportError, AttributeError) as e:
        logger.warning(f"Could not load order-update adapter for {broker}: {e}")
        return None

    return factory(user_id)


def start_order_update_adapter(user_id: str, broker: str) -> bool:
    """Start (or restart with fresh credentials) the order-update adapter for
    a user's broker session. Any previous adapter is disconnected first."""
    if not _order_updates_enabled():
        return False
    if not user_id or not broker:
        return False

    with _LOCK:
        _stop_locked(user_id)
        try:
            adapter = _build_adapter(user_id, broker)
        except Exception:
            logger.exception(f"Failed to build order-update adapter for {broker}/{user_id}")
            return False
        if adapter is None:
            return False
        try:
            adapter.connect()
        except Exception:
            logger.exception(f"Failed to start order-update adapter for {broker}/{user_id}")
            return False
        _ADAPTERS[user_id] = adapter
        logger.info(f"Order-update adapter started for {broker}/{user_id}")
        return True


def stop_order_update_adapter(user_id: str) -> None:
    """Stop and discard the order-update adapter for a user (logout/revoke)."""
    with _LOCK:
        _stop_locked(user_id)


def _stop_locked(user_id: str) -> None:
    adapter = _ADAPTERS.pop(user_id, None)
    if adapter is None:
        return
    try:
        adapter.disconnect()
        logger.info(f"Order-update adapter stopped for user {user_id}")
    except Exception:
        logger.exception(f"Error stopping order-update adapter for user {user_id}")


def stop_all_order_update_adapters() -> None:
    """Disconnect every adapter (app shutdown)."""
    with _LOCK:
        for user_id in list(_ADAPTERS.keys()):
            _stop_locked(user_id)


def start_order_update_adapters_on_boot(db_ready=None) -> None:
    """Start adapters for existing non-revoked broker sessions at app startup.

    Runs in a background thread; failures are logged, never raised — order
    updates are an enhancement, not a startup dependency.

    Args:
        db_ready: ``threading.Event`` set by the app once background table
            creation has finished. The boot scan waits on it before querying
            ``auth``. Without it, a fresh install races table creation and
            logs a "no such table: auth" traceback that looks fatal but is
            not (issue #1660). None skips the wait, for callers that already
            know the schema exists.
    """
    if not _order_updates_enabled():
        logger.info("Order-update adapters disabled via ORDER_UPDATES_ENABLED")
        return

    def _boot():
        # Warm up the shared ZMQ publisher NOW, long before the first order
        # event. Under gunicorn+eventlet the market-data adapters live in the
        # websocket_proxy subprocess, so nothing else connects this process'
        # publisher until the first publish — and a ZMQ PUB drops messages
        # sent before the PUB<->SUB handshake settles (slow-joiner), which
        # silently ate the first order update. Connecting at boot gives the
        # link seconds of margin. (The dev server never hit this because the
        # in-process market-data adapters connect the same singleton early.)
        try:
            from websocket_proxy.connection_manager import SharedZmqPublisher

            SharedZmqPublisher().connect()
            logger.info("Shared ZMQ publisher warmed up for order-update relay")
        except Exception:
            logger.exception("Failed to warm up shared ZMQ publisher")

        # Wait for background table creation before touching `auth`. On a
        # fresh install the tables are created by a *different* background
        # thread, so querying immediately raised "no such table: auth". The
        # timeout mirrors the request-path guard in app.py's wait_for_db_ready;
        # on expiry we fall through and let the try/except below log it.
        if db_ready is not None and not db_ready.wait(timeout=60):
            logger.warning(
                "Order-update boot scan: database not ready after 60s; skipping. "
                "Adapters will start on the next broker login."
            )
            return

        try:
            from database.auth_db import Auth

            sessions = Auth.query.filter_by(is_revoked=False).all()
            for auth_obj in sessions:
                if auth_obj.name and auth_obj.broker:
                    start_order_update_adapter(auth_obj.name, auth_obj.broker)
            if not sessions:
                logger.debug("No active broker sessions found; no order-update adapters started")
        except Exception:
            logger.exception("Order-update adapter boot scan failed")
        finally:
            # This runs on a plain daemon thread, so app.py's
            # teardown_appcontext never fires for it. Drop the scoped session
            # bound to this thread explicitly rather than orphaning it when
            # the thread exits.
            try:
                from database.auth_db import db_session as _auth_db_session

                _auth_db_session.remove()
            except Exception:
                logger.debug("Order-update boot scan: auth session cleanup skipped", exc_info=True)

    threading.Thread(
        target=_boot, daemon=True, name="order-update-adapter-boot"
    ).start()


def get_order_update_status() -> dict:
    """Diagnostics: which adapters are running and their connected state."""
    with _LOCK:
        return {
            user_id: {
                "broker": getattr(adapter, "broker_name", "unknown"),
                "connected": bool(getattr(adapter, "connected", False)),
            }
            for user_id, adapter in _ADAPTERS.items()
        }
