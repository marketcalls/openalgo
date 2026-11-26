"""
Relay that carries Flattrade order-update frames from the websocket proxy
process to the Flask process (GitHub issue #2386).

Why it exists: PiConnect allows ONE WebSocket session per {uid, accesstoken}
(broker-api-docs/flattrade-api-docs/09-websocket.md, issue #1806). Order
updates (t="o" / t="om") therefore have to ride the same socket as market data.
That socket belongs to broker/flattrade/streaming/flattrade_adapter.py, which
runs inside the websocket proxy (a subprocess under gunicorn, a separate
process on Docker, a thread on the dev server), while order-update events must
be published on the Flask process' event bus. The shared ZMQ market-data bus
cannot carry them back: its only SUB is the proxy's own.

So the market-data adapter publishes on this channel and the Flask-side order
adapter (flattrade_order_adapter.py) listens. Same topology rule as the
market-data bus: ONE binder (the Flask-side SUB), every publisher CONNECTs.

Messages are single JSON strings:
    {"kind": "claim"|"ready"|"alive"|"release"|"om",
     "user_id": <OpenAlgo user>, "actid": <Flattrade account>,
     "frame": <raw t="om" frame, only for kind="om">}

    claim    the market-data adapter is about to open the PiConnect session
             (sent before every connect, so the Flask side can step aside
             before the broker evicts anything)
    ready    connected, order-update subscribe (t="o") sent
    alive    sent every ALIVE_INTERVAL_SECONDS while the adapter is running
    release  the adapter stopped; the PiConnect session is free
    om       one order-update frame, verbatim

Port: FLATTRADE_ORDER_RELAY_PORT, else ZMQ_PORT + 100 (5655 by default).
Deriving it from ZMQ_PORT keeps install-multi.sh instances apart, because each
instance already gets its own ZMQ_PORT.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable

import zmq

from utils.logging import get_logger

logger = get_logger(__name__)

RELAY_HOST = "127.0.0.1"
ALIVE_INTERVAL_SECONDS = 5
# How long the listener waits for a queued frame before yielding. The loop uses
# non-blocking receives and a short sleep, so under eventlet (where this runs on
# a green thread) the hub is never blocked inside libzmq.
_IDLE_SLEEP_SECONDS = 0.05

KIND_CLAIM = "claim"
KIND_READY = "ready"
KIND_ALIVE = "alive"
KIND_RELEASE = "release"
KIND_ORDER = "om"


def relay_port() -> int:
    """The relay port: FLATTRADE_ORDER_RELAY_PORT, else ZMQ_PORT + 100."""
    explicit = os.getenv("FLATTRADE_ORDER_RELAY_PORT", "").strip().strip("'\"")
    if explicit:
        return int(explicit)
    return int(os.getenv("ZMQ_PORT", "5555")) + 100


def relay_endpoint() -> str:
    return f"tcp://{RELAY_HOST}:{relay_port()}"


class OrderRelayPublisher:
    """Proxy side: one per Flattrade market-data adapter. Connects, never binds."""

    def __init__(self, user_id: str, actid: str):
        self.user_id = user_id
        self.actid = actid
        self._lock = threading.Lock()
        self._socket = None
        try:
            socket = zmq.Context.instance().socket(zmq.PUB)
            socket.setsockopt(zmq.LINGER, 500)  # let a final "release" flush
            socket.setsockopt(zmq.SNDHWM, 1000)
            socket.connect(relay_endpoint())
            self._socket = socket
        except Exception:
            logger.exception("Could not open the Flattrade order-update relay")
        # A PUB that has just connected drops what it sends until the TCP
        # handshake completes (ZMQ's slow joiner). The first claim follows
        # within milliseconds of construction, so it waits this out once.
        self._fresh = True

    def publish(self, kind: str, frame: str | None = None) -> None:
        with self._lock:
            socket = self._socket
            if socket is None:
                return
            if self._fresh:
                self._fresh = False
                time.sleep(0.3)
            message = {"kind": kind, "user_id": self.user_id, "actid": self.actid}
            if frame is not None:
                message["frame"] = frame
            try:
                socket.send_string(json.dumps(message), flags=zmq.NOBLOCK)
            except zmq.Again:
                logger.debug("Flattrade order relay queue full; message dropped")
            except Exception:
                logger.debug("Flattrade order relay send failed", exc_info=True)

    def close(self) -> None:
        with self._lock:
            socket = self._socket
            self._socket = None
        if socket is not None:
            try:
                socket.close()
            except Exception:
                logger.debug("Closing the Flattrade order relay failed", exc_info=True)


class OrderRelayListener:
    """Flask side: the one binder. A process-wide singleton (see listener())."""

    def __init__(self):
        self._lock = threading.Lock()
        self._handlers: dict[int, Callable[[dict], None]] = {}
        self._next_handle = 0
        self._socket = None
        self._thread: threading.Thread | None = None
        self._closed = False
        self.bound = False
        try:
            socket = zmq.Context.instance().socket(zmq.SUB)
            socket.setsockopt(zmq.LINGER, 0)
            socket.setsockopt(zmq.SUBSCRIBE, b"")
            socket.bind(relay_endpoint())
            self._socket = socket
            self.bound = True
        except Exception as e:
            logger.warning(
                f"Flattrade order updates cannot use the WebSocket relay on "
                f"{relay_endpoint()} ({e}); falling back to polling the order book."
            )
            return
        # A plain thread: green under eventlet, which is what the handlers need
        # (they publish on the event bus), real under gthread and the dev server.
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="flattrade-order-relay"
        )
        self._thread.start()

    def add_handler(self, handler: Callable[[dict], None]) -> int:
        with self._lock:
            self._next_handle += 1
            self._handlers[self._next_handle] = handler
            return self._next_handle

    def remove_handler(self, handle: int) -> None:
        with self._lock:
            self._handlers.pop(handle, None)

    def close(self) -> None:
        """Stop the loop; the loop thread closes the socket it owns."""
        self._closed = True

    def _loop(self) -> None:
        socket = self._socket
        try:
            while not self._closed:
                try:
                    raw = socket.recv_string(flags=zmq.NOBLOCK)
                except zmq.Again:
                    time.sleep(_IDLE_SLEEP_SECONDS)
                    continue
                except Exception:
                    logger.exception("Flattrade order relay receive failed")
                    time.sleep(1)
                    continue
                self.dispatch(raw)
        finally:
            self.bound = False
            try:
                socket.close()
            except Exception:
                logger.debug("Closing the Flattrade order relay listener failed", exc_info=True)

    def dispatch(self, raw: str) -> None:
        try:
            message = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(message, dict):
            return
        with self._lock:
            handlers = list(self._handlers.values())
        for handler in handlers:
            try:
                handler(message)
            except Exception:
                logger.exception("Flattrade order relay handler failed")


_listener: OrderRelayListener | None = None
_listener_lock = threading.Lock()


def listener() -> OrderRelayListener:
    """Return the process-wide listener, binding it on first use.

    A listener that failed to bind is not kept: the port may have been held by
    a process that was still exiting, so the next login tries again.
    """
    global _listener
    with _listener_lock:
        if _listener is None or not _listener.bound:
            _listener = OrderRelayListener()
        return _listener


def is_reloader_watcher() -> bool:
    """True in the debug reloader's watcher process, which serves nothing.

    With FLASK_DEBUG on, `uv run app.py` runs app.py twice: a watcher that only
    restarts the server on file changes, and the child that serves requests
    (WERKZEUG_RUN_MAIN=true) and hosts the websocket proxy. Same test as
    websocket_proxy.app_integration's proxy start. Order updates started in the
    watcher would take the relay port from the child and publish their events
    on a process nobody is connected to.
    """
    debug = os.getenv("FLASK_DEBUG", "").strip().strip("'\"").lower() in ("1", "true", "t")
    return debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true"
