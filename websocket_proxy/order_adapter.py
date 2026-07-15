"""
Base class for broker order-update adapters.

Unlike market-data adapters (base_adapter.py, out-of-process under the
websocket_proxy subprocess), order-update adapters run **in the Flask/
gunicorn process** as a background thread — see the architecture note in
subscribers/wsproxy_subscriber.py and the plan at
.claude/plans/peaceful-gathering-lightning.md. Each normalizes broker-specific
order-update push messages into events.OrderUpdateEvent and publishes them on
the in-process event bus (utils/event_bus.py); subscribers/wsproxy_subscriber.py
then re-publishes onto the ZMQ bus for websocket_proxy to relay to WS clients.

One instance per user_id/broker session (see order_update_service.py for
lifecycle), not per WS client — independent of how many WS clients are
subscribed to order updates.
"""

import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

import websocket

from utils.event_bus import bus
from utils.logging import get_logger

# Reconnect backoff schedule (seconds), capped — mirrors the Python SDK's
# feed.py::_reconnect_loop pattern for consistency across the codebase.
_RECONNECT_BACKOFFS = [1, 2, 5, 10, 30, 60]


class BaseOrderUpdateAdapter(ABC):
    """
    Base class for a broker's dedicated order-update WebSocket connection.

    Subclasses implement:
        get_ws_url() -> str
        get_headers() -> dict | None
        normalize(raw_message) -> dict | None   (kwargs for OrderUpdateEvent)

    And may override:
        on_open_extra(ws)          — post-connect subscribe handshake
        heartbeat_interval()       — seconds between app-level heartbeats, or None
        send_heartbeat(ws)         — the broker-specific heartbeat payload
    """

    def __init__(self, broker_name: str, user_id: str):
        self.broker_name = broker_name
        self.user_id = user_id
        self.logger = get_logger(f"order_adapter_{broker_name}")

        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._running = False
        self._shutting_down = False
        self._lock = threading.Lock()

    # -- broker-specific hooks -------------------------------------------------

    @abstractmethod
    def get_ws_url(self) -> str:
        """Return the broker's order-update WebSocket URL for this user."""

    @abstractmethod
    def get_headers(self) -> dict | None:
        """Return headers for the WS handshake (e.g. Authorization), or None."""

    @abstractmethod
    def normalize(self, raw_message: Any) -> dict | None:
        """
        Parse one raw broker message into kwargs for OrderUpdateEvent.
        Return None to ignore the message (e.g. heartbeats, acks).

        Use OpenAlgo's common field names/vocabulary (see
        docs/prompt/order-constants.md and docs/prompt/services_documentation.md
        "Payload rules"), not broker-native ones:
            orderid, symbol (OpenAlgo format — map broker symbol via
            database.token_db.get_oa_symbol), exchange (canonical exchange
            code), action ("BUY"/"SELL"), quantity, price, trigger_price,
            pricetype ("MARKET"/"LIMIT"/"SL"/"SL-M" — no underscore, matches
            OrderPlacedEvent), product ("CNC"/"NRML"/"MIS"), order_status
            ("open"/"complete"/"rejected"/"cancelled"/"trigger_pending" —
            sandbox's lowercase vocabulary), filled_quantity,
            pending_quantity, average_price, rejection_reason.
        """

    def on_open_extra(self, ws: websocket.WebSocketApp) -> None:  # noqa: B027
        """Optional post-connect subscribe handshake. Default: no-op."""

    def heartbeat_interval(self) -> int | None:
        """Seconds between app-level heartbeats, or None to rely on WS
        ping/pong alone. Default: None."""
        return None

    def send_heartbeat(self, ws: websocket.WebSocketApp) -> None:  # noqa: B027
        """Broker-specific heartbeat payload. Default: no-op."""

    def ws_ping_interval(self) -> int:
        """Seconds between WS protocol-level pings. Angel's docs require a
        ~10s ping/pong cadence; most brokers are fine with the 20s default."""
        return 20

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> None:
        """Start the background connection thread. Idempotent."""
        with self._lock:
            if self._running:
                return
            self._shutting_down = False
            self._running = True
            self._thread = threading.Thread(
                target=self._run_forever,
                daemon=True,
                name=f"order-adapter-{self.broker_name}-{self.user_id}",
            )
            self._thread.start()

    def disconnect(self) -> None:
        """Stop the adapter and close the socket. FD-safe: close-before-reconnect,
        idempotent."""
        with self._lock:
            self._shutting_down = True
            self._running = False
            if self._ws is not None:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None

    @property
    def connected(self) -> bool:
        return self._running and self._ws is not None

    # -- internals -----------------------------------------------------------

    def _run_forever(self) -> None:
        attempt = 0
        while not self._shutting_down:
            try:
                self._connect_once()
            except Exception as e:
                self.logger.warning(
                    f"Order-update connection error ({self.broker_name}/{self.user_id}): {e}"
                )
            if self._shutting_down:
                break
            delay = _RECONNECT_BACKOFFS[min(attempt, len(_RECONNECT_BACKOFFS) - 1)]
            attempt += 1
            self.logger.info(
                f"Order-update reconnect attempt {attempt} in {delay}s "
                f"({self.broker_name}/{self.user_id})"
            )
            slept = 0.0
            while slept < delay and not self._shutting_down:
                time.sleep(0.2)
                slept += 0.2
        self.logger.info(
            f"Order-update adapter stopped for {self.broker_name}/{self.user_id}"
        )

    def _connect_once(self) -> None:
        url = self.get_ws_url()
        headers = self.get_headers()
        header_list = [f"{k}: {v}" for k, v in headers.items()] if headers else None

        def on_message(ws, message):
            self._handle_message(message)

        def on_open(ws):
            self.logger.info(
                f"Order-update WS connected: {self.broker_name}/{self.user_id}"
            )
            self.on_open_extra(ws)
            interval = self.heartbeat_interval()
            if interval:
                self._start_heartbeat_thread(interval)

        def on_error(ws, error):
            self.logger.warning(
                f"Order-update WS error ({self.broker_name}/{self.user_id}): {error}"
            )

        def on_close(ws, close_status_code, close_reason):
            self.logger.info(
                f"Order-update WS closed ({self.broker_name}/{self.user_id}): "
                f"{close_status_code} {close_reason}"
            )

        self._ws = websocket.WebSocketApp(
            url,
            header=header_list,
            on_message=on_message,
            on_open=on_open,
            on_error=on_error,
            on_close=on_close,
        )

        # Blocks until the connection closes or errors; on_close/on_error above
        # return control to _run_forever's reconnect loop. ping_timeout must be
        # strictly less than ping_interval (websocket-client requirement).
        ping_interval = max(2, int(self.ws_ping_interval()))
        ping_timeout = min(10, max(1, ping_interval - 1))
        try:
            self._ws.run_forever(ping_interval=ping_interval, ping_timeout=ping_timeout)
        finally:
            # The socket is dead once run_forever returns — clear the handle so
            # `connected` reads False between reconnect attempts and the old
            # heartbeat thread (generation-guarded on this object) exits.
            self._ws = None

    def _start_heartbeat_thread(self, interval: int) -> None:
        # Generation guard: bind this thread to the ws it was started for, so
        # a reconnect (which replaces self._ws and spawns a fresh heartbeat
        # thread via on_open) makes the previous thread exit instead of
        # leaking one thread per reconnect.
        ws_at_start = self._ws

        def loop():
            while self._running and self._ws is ws_at_start:
                slept = 0.0
                while slept < interval and self._running and self._ws is ws_at_start:
                    time.sleep(0.5)
                    slept += 0.5
                if not self._running or self._ws is not ws_at_start:
                    break
                try:
                    self.send_heartbeat(ws_at_start)
                except Exception as e:
                    self.logger.debug(f"Heartbeat send failed: {e}")

        self._heartbeat_thread = threading.Thread(
            target=loop,
            daemon=True,
            name=f"order-adapter-hb-{self.broker_name}-{self.user_id}",
        )
        self._heartbeat_thread.start()

    def _handle_message(self, raw_message: Any) -> None:
        try:
            fields = self.normalize(raw_message)
        except Exception as e:
            self.logger.debug(f"Failed to normalize order-update message: {e}")
            return
        if not fields:
            return
        self._publish_event_fields(fields)

    def _publish_event_fields(self, fields: dict) -> None:
        """Publish normalized OrderUpdateEvent kwargs onto the event bus."""
        fields.setdefault("mode", "live")
        fields.setdefault("broker", self.broker_name)
        fields.setdefault("request_data", {"user_id": self.user_id})
        fields.setdefault("api_type", f"{self.broker_name}.order_update")

        try:
            from events import OrderUpdateEvent

            bus.publish(OrderUpdateEvent(**fields))
        except Exception:
            self.logger.exception("Failed to publish OrderUpdateEvent")


class PollingOrderUpdateAdapter:
    """
    REST-polling fallback for brokers with no push mechanism (webhook or
    order-WebSocket) — e.g. Groww, whose public API documents only REST
    live-data endpoints (see broker-api-docs groww docs; the reverse-
    engineered NATS feed carries market-data subjects only).

    Same connect()/disconnect()/connected surface as BaseOrderUpdateAdapter
    so services/order_update_service.py can manage both uniformly. Polls the
    normalized orderbook via services.orderbook_service.get_orderbook
    (auth_token + broker direct-auth path — already returns OpenAlgo common
    field names) every ORDER_POLL_INTERVAL seconds, diffs per-orderid
    (order_status, filled_quantity), and publishes an OrderUpdateEvent for
    each change. The first successful poll seeds the baseline silently so a
    restart doesn't replay the whole book as fresh updates.
    """

    def __init__(self, broker_name: str, user_id: str, poll_interval: int | None = None):
        self.broker_name = broker_name
        self.user_id = user_id
        self.poll_interval = poll_interval or int(os.getenv("ORDER_POLL_INTERVAL", "5"))
        self.logger = get_logger(f"order_poller_{broker_name}")

        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

    def connect(self) -> None:
        """Start the polling thread. Idempotent."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._poll_loop,
                daemon=True,
                name=f"order-poller-{self.broker_name}-{self.user_id}",
            )
            self._thread.start()

    def disconnect(self) -> None:
        """Stop the polling thread. Idempotent; no sockets held between polls."""
        with self._lock:
            self._running = False

    @property
    def connected(self) -> bool:
        return self._running

    def _poll_loop(self) -> None:
        from database.auth_db import get_auth_token
        from services.orderbook_service import get_orderbook

        baseline: dict[str, tuple] | None = None
        self.logger.info(
            f"Order-update poller started for {self.broker_name}/{self.user_id} "
            f"(interval {self.poll_interval}s)"
        )

        while self._running:
            try:
                auth_token = get_auth_token(self.user_id)
                if not auth_token:
                    self.logger.debug("No auth token available; skipping poll cycle")
                else:
                    success, response, _ = get_orderbook(
                        auth_token=auth_token, broker=self.broker_name
                    )
                    if success:
                        orders = (response.get("data") or {}).get("orders") or []
                        snapshot: dict[str, tuple] = {}
                        by_id: dict[str, dict] = {}
                        for order in orders:
                            orderid = str(order.get("orderid", ""))
                            if not orderid:
                                continue
                            snapshot[orderid] = (
                                order.get("order_status", ""),
                                int(order.get("filled_quantity") or 0),
                            )
                            by_id[orderid] = order

                        if baseline is None:
                            baseline = snapshot  # seed silently
                        else:
                            for orderid, state in snapshot.items():
                                if baseline.get(orderid) != state:
                                    self._publish_order(by_id[orderid])
                            baseline = snapshot
                    else:
                        self.logger.debug(
                            f"Orderbook poll failed: {response.get('message', 'unknown error')}"
                        )
            except Exception as e:
                self.logger.debug(f"Order poll cycle error: {e}")

            slept = 0.0
            while slept < self.poll_interval and self._running:
                time.sleep(0.5)
                slept += 0.5

        self.logger.info(f"Order-update poller stopped for {self.broker_name}/{self.user_id}")

    def _publish_order(self, order: dict) -> None:
        try:
            from events import OrderUpdateEvent

            raw_status = str(order.get("order_status", "")).strip().lower()
            bus.publish(
                OrderUpdateEvent(
                    mode="live",
                    api_type=f"{self.broker_name}.order_update",
                    request_data={"user_id": self.user_id},
                    broker=self.broker_name,
                    orderid=str(order.get("orderid", "")),
                    symbol=order.get("symbol", ""),
                    exchange=order.get("exchange", ""),
                    action=str(order.get("action", "")).upper(),
                    quantity=int(order.get("quantity") or 0),
                    price=float(order.get("price") or 0),
                    trigger_price=float(order.get("trigger_price") or 0),
                    pricetype=order.get("pricetype", ""),
                    product=order.get("product", ""),
                    order_status=raw_status,
                    filled_quantity=int(order.get("filled_quantity") or 0),
                    pending_quantity=int(order.get("pending_quantity") or 0),
                    average_price=float(order.get("average_price") or 0),
                    rejection_reason=order.get("rejection_reason", "")
                    if raw_status == "rejected"
                    else "",
                )
            )
        except Exception:
            self.logger.exception("Failed to publish polled OrderUpdateEvent")
