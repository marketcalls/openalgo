"""
Internal WebSocket client wrapper for connecting to the OpenAlgo WebSocket server.
This client handles authentication and provides a simple interface for services.
"""

import asyncio
import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from queue import Queue
from typing import Any

import websockets
from dotenv import load_dotenv

# The asyncio event loop needs a real OS thread: eventlet's monkey-patching
# turns threading.Thread into a green thread, where asyncio.new_event_loop()
# cannot work. Anything that thread shares with the greenlets has to be real
# too, which is what this module is for.
from utils import real_threading as _original_threading
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

_MODE_LABELS = {1: "LTP", 2: "Quote", 3: "Depth"}
_MODE_VALUES = {label.upper(): label for label in _MODE_LABELS.values()}


def _canonical_mode(value: Any) -> str:
    """Canonical client-side mode label without importing the proxy package.

    Importing ``websocket_proxy.mode_utils`` executes that package's broad
    ``__init__`` and eagerly imports every broker adapter.  This internal
    client needs only the three stable public labels, so keep the normalization
    local and side-effect free.
    """
    if isinstance(value, bool):
        raise TypeError("Mode must be LTP, Quote, or Depth")
    if isinstance(value, int):
        if value in _MODE_LABELS:
            return _MODE_LABELS[value]
        raise ValueError("Mode must be 1 (LTP), 2 (Quote), or 3 (Depth)")
    if isinstance(value, str):
        label = _MODE_VALUES.get(value.strip().upper())
        if label is not None:
            return label
    raise ValueError("Mode must be LTP, Quote, or Depth")


class WebSocketClient:
    """
    Internal WebSocket client for connecting to OpenAlgo WebSocket server.
    Handles authentication, subscriptions, and data routing.
    """

    #: Bound on callback payloads queued for the hub. The producer is a feed
    #: that never blocks, so an unbounded queue would grow until the worker is
    #: OOM-killed if a subscriber stalled. Shedding the newest is the right
    #: trade for market data: the next tick supersedes it anyway.
    DISPATCH_QUEUE_MAX = 10000

    #: Idle poll gap for the dispatcher. It drains everything available before
    #: sleeping, so this only bounds latency when the queue is empty.
    DISPATCH_POLL_SECONDS = 0.005

    def __init__(self, api_key: str, host: str = "localhost", port: int = 8765):
        """
        Initialize the WebSocket client

        Args:
            api_key: API key for authentication
            host: WebSocket server host
            port: WebSocket server port
        """
        self.ws_url = f"ws://{host}:{port}"
        self.api_key = api_key
        self.ws = None
        self.loop = None
        self.thread = None
        self.connected = False
        self.authenticated = False
        self.running = False

        # Message handling
        self.message_queue = Queue()
        self.callbacks = {
            "market_data": [],
            "auth": [],
            "subscribe": [],
            "unsubscribe": [],
            "error": [],
        }

        # Callbacks are handed to the hub, never run on the loop thread.
        # _handle_message() runs on the asyncio loop's real OS thread, and the
        # callbacks registered here reach SocketIO, the event bus and the
        # sandbox engine, all of which use eventlet primitives. Touching one
        # from a foreign thread raises "greenlet.error: Cannot switch to a
        # different thread" inside the hub and wedges that thread for good
        # (issues #1402, #1473, #1569). So the loop thread only enqueues, and a
        # green thread does the calling.
        self._dispatch_queue = _original_threading.Queue(maxsize=self.DISPATCH_QUEUE_MAX)
        self._dispatch_thread = None
        self._dispatch_dropped = 0

        # Subscription tracking.
        #
        # A REAL lock, never eventlet's green semaphore. _handle_message()
        # takes it on the asyncio loop's OS thread while subscribe(),
        # unsubscribe() and get_market_data() take it from greenlets.
        # Contended across that boundary a green semaphore raises
        # "greenlet.error: Cannot switch to a different thread" inside the
        # hub and leaves the loop thread blocked forever: acks stop
        # resolving, ping/pong goes unanswered, and every later subscribe
        # burns its full timeout. The feed dies silently, and only under
        # gunicorn+eventlet. Each section this guards is a dict update, so
        # a real lock costs microseconds.
        self.active_subscriptions = {}
        self.lock = _original_threading.Lock()

        # Market data cache
        self.market_data_cache = {}

        # Pending request acks — issue #1376. Maps request_id -> asyncio.Future.
        # Populated by subscribe()/unsubscribe() right before the WS send,
        # resolved by _handle_message() when a matching {type,request_id}
        # response arrives. Both producer and consumer run inside the
        # asyncio loop thread, so no extra locking is needed.
        self._pending_acks: dict[str, asyncio.Future] = {}

    def connect(self) -> bool:
        """
        Connect to the WebSocket server and authenticate

        Returns:
            bool: True if connected and authenticated successfully
        """
        if self.connected:
            logger.info("Already connected to WebSocket server")
            return True

        try:
            self.running = True

            # Start the asyncio event loop in a separate thread
            self.thread = _original_threading.Thread(target=self._run_event_loop)
            self.thread.daemon = True
            self.thread.start()

            # Green thread (threading is monkey-patched under eventlet), so
            # callbacks run on the hub and never on self.thread.
            self._dispatch_thread = threading.Thread(
                target=self._run_dispatch_loop,
                daemon=True,
                name="openalgo-ws-dispatch",
            )
            self._dispatch_thread.start()

            # Wait for connection
            timeout = 10
            start_time = time.time()
            while not self.connected and time.time() - start_time < timeout:
                time.sleep(0.1)

            if not self.connected:
                logger.error("Failed to connect to WebSocket server")
                return False

            # Wait for authentication
            start_time = time.time()
            while not self.authenticated and time.time() - start_time < timeout:
                time.sleep(0.1)

            if not self.authenticated:
                logger.error("Failed to authenticate with WebSocket server")
                return False

            logger.info("Successfully connected and authenticated")
            return True

        except Exception as e:
            logger.exception(f"Error connecting to WebSocket: {e}")
            return False

    def disconnect(self):
        """Disconnect from the WebSocket server"""
        self.running = False

        if self.loop and self.ws:
            # Scheduled, not awaited: the thread join below is what waits.
            # call_soon_threadsafe avoids building a concurrent Future whose
            # condition would belong to the wrong world.
            coro = self._disconnect()
            self.loop.call_soon_threadsafe(lambda: self.loop.create_task(coro))

        # Wait for thread to finish
        if self.thread and self.thread.is_alive():
            # Cooperative: this is a real OS thread, and disconnect() is
            # called from greenlets (scalping teardown, close_all_clients),
            # where a blocking join would stop the worker for 5s.
            _original_threading.join(self.thread, timeout=5)

        self.connected = False
        self.authenticated = False
        with self.lock:
            self.active_subscriptions.clear()
            self.market_data_cache.clear()
        logger.info("Disconnected from WebSocket server")

    def _run_on_loop(self, coro, timeout: float):
        """Run a coroutine on the client's asyncio loop and wait for its result.

        ``asyncio.run_coroutine_threadsafe`` hands back a
        ``concurrent.futures.Future`` whose ``result()`` waits on a
        ``threading.Condition``. Under eventlet that condition is green while
        the loop thread resolving it is a real OS thread, and the two cannot
        pass a waiter between them: the waiting greenlet is simply never woken.
        Measured, an ack that arrived in 0.3s still cost the caller the whole
        10s timeout, and when the hub does try to switch into that waiter it
        raises ``greenlet.error: Cannot switch to a different thread`` instead.
        That is why a subscribe used to take its full 12 seconds whenever it
        had to wait at all.

        So nothing is handed across the boundary except one plain boolean: a
        real Event the loop thread sets, polled here with a sleep that eventlet
        turns into a yield. ``call_soon_threadsafe`` is used rather than
        ``run_coroutine_threadsafe`` so no concurrent Future is built at all.

        Raises TimeoutError if the coroutine has not finished in ``timeout``,
        and re-raises whatever the coroutine raised.
        """
        done = _original_threading.Event()
        box: dict[str, Any] = {}

        async def runner():
            try:
                box["value"] = await coro
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                box["error"] = exc
            finally:
                done.set()

        self.loop.call_soon_threadsafe(lambda: self.loop.create_task(runner()))

        if not _original_threading.wait_for(done, timeout):
            raise TimeoutError("timed out waiting for the websocket proxy")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    async def _send_and_await_ack(
        self, message: dict, request_id: str, timeout: float
    ) -> dict:
        """Send a message and await the proxy's matching response.

        Runs inside the asyncio loop thread (called via run_coroutine_threadsafe).
        Registers a future under request_id, sends the JSON, then awaits the
        future — which _handle_message() resolves when the proxy's response
        arrives carrying the same request_id.
        """
        fut: asyncio.Future = self.loop.create_future()
        self._pending_acks[request_id] = fut
        try:
            await self.ws.send(json.dumps(message))
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending_acks.pop(request_id, None)

    def subscribe(self, symbols: list[dict[str, str]], mode: str = "Quote") -> dict[str, Any]:
        """
        Subscribe to market data for symbols.

        Now awaits the proxy's per-symbol ack (issue #1376) so partial
        failures (invalid tokens, broker capacity, expired F&O strikes)
        surface to the caller rather than being silently swallowed.
        ``active_subscriptions`` is updated only for symbols the broker
        actually accepted.

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
            mode: Subscription mode - "LTP", "Quote", or "Depth"

        Returns:
            Dict with overall ``status`` ("success" / "partial" / "error"),
            a per-symbol ``subscriptions`` list each carrying its own
            status, and the originating ``mode``.
        """
        if not self.connected or not self.authenticated:
            return {"status": "error", "message": "Not connected or authenticated"}
        if not self.loop or not self.ws:
            return {"status": "error", "message": "WebSocket connection not available"}

        try:
            canonical_mode = _canonical_mode(mode)
        except (TypeError, ValueError) as exc:
            return {"status": "error", "message": str(exc)}

        try:
            request_id = str(uuid.uuid4())
            subscription_msg = {
                "action": "subscribe",
                "symbols": symbols,
                "mode": canonical_mode,
                "request_id": request_id,
            }
            # Outer timeout slightly longer than the inner ack timeout so the
            # asyncio.wait_for fires first and produces a clean error.
            ack = self._run_on_loop(
                self._send_and_await_ack(subscription_msg, request_id, timeout=10),
                timeout=12,
            )
        except TimeoutError:
            logger.warning(
                f"Subscribe timed out waiting for proxy ack (mode={mode}, "
                f"symbols={len(symbols)})"
            )
            return {
                "status": "error",
                "message": "Timed out waiting for proxy subscribe response",
                "mode": canonical_mode,
            }
        except Exception as e:
            logger.exception(f"Error subscribing to symbols: {e}")
            return {"status": "error", "message": str(e)}

        # Mark only the symbols the proxy/broker actually accepted.
        per_symbol = ack.get("subscriptions", []) or []
        with self.lock:
            for entry in per_symbol:
                if entry.get("status") != "success":
                    continue
                sym = entry.get("symbol")
                exch = entry.get("exchange")
                if not sym or not exch:
                    continue
                key = f"{exch}:{sym}"
                if key not in self.active_subscriptions:
                    self.active_subscriptions[key] = set()
                try:
                    accepted_mode = _canonical_mode(
                        entry.get("mode", canonical_mode)
                    )
                except (TypeError, ValueError):
                    continue
                self.active_subscriptions[key].add(accepted_mode)

        return {
            "status": ack.get("status", "success"),
            "message": ack.get("message", f"Subscribed to {len(symbols)} symbols"),
            "subscriptions": per_symbol,
            "broker": ack.get("broker"),
            "mode": canonical_mode,
        }

    def _remove_acknowledged_modes(
        self,
        successful: list[dict[str, Any]],
        requested_modes: dict[tuple[str, str], set[str]],
    ) -> None:
        """Apply exact successful acks, conservatively supporting old proxies."""
        removals: list[tuple[str, str, str]] = []
        missing = object()
        for entry in successful:
            sym = entry.get("symbol")
            exch = entry.get("exchange")
            if not sym or not exch:
                continue
            candidates = requested_modes.get((exch, sym), set())
            raw_mode = entry.get("mode", missing)
            if raw_mode is missing:
                # A legacy proxy did not identify which same-symbol mode it
                # acknowledged.  One candidate is safe; two are ambiguous.
                if len(candidates) != 1:
                    continue
                acknowledged_mode = next(iter(candidates))
            else:
                try:
                    acknowledged_mode = _canonical_mode(raw_mode)
                except (TypeError, ValueError):
                    continue
                if acknowledged_mode not in candidates:
                    continue
            removals.append((exch, sym, acknowledged_mode))

        with self.lock:
            for exch, sym, acknowledged_mode in removals:
                key = f"{exch}:{sym}"
                if key not in self.active_subscriptions:
                    continue
                self.active_subscriptions[key].discard(acknowledged_mode)
                if not self.active_subscriptions[key]:
                    del self.active_subscriptions[key]
                    self.market_data_cache.pop(key, None)

    def unsubscribe(self, symbols: list[dict[str, str]], mode: str = "Quote") -> dict[str, Any]:
        """
        Unsubscribe from market data. Awaits the proxy's ack (issue #1376) so
        callers see real per-symbol success/failure instead of an unconditional
        "success" returned the moment bytes leave the local socket.

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
            mode: Subscription mode - "LTP", "Quote", or "Depth"

        Returns:
            Dict with unsubscription status
        """
        if not self.connected or not self.authenticated:
            return {"status": "error", "message": "Not connected or authenticated"}
        if not self.loop or not self.ws:
            return {"status": "error", "message": "WebSocket connection not available"}

        try:
            canonical_mode = _canonical_mode(mode)
            wire_symbols = []
            requested_modes: dict[tuple[str, str], set[str]] = {}
            for symbol_info in symbols:
                item_mode = _canonical_mode(
                    symbol_info["mode"]
                    if "mode" in symbol_info
                    else canonical_mode
                )
                wire_symbol = {**symbol_info, "mode": item_mode}
                wire_symbols.append(wire_symbol)
                sym = wire_symbol.get("symbol")
                exch = wire_symbol.get("exchange")
                if sym and exch:
                    requested_modes.setdefault((exch, sym), set()).add(item_mode)
        except (TypeError, ValueError) as exc:
            return {"status": "error", "message": str(exc)}

        try:
            request_id = str(uuid.uuid4())
            unsubscription_msg = {
                "action": "unsubscribe",
                "symbols": wire_symbols,
                "mode": canonical_mode,
                "request_id": request_id,
            }
            ack = self._run_on_loop(
                self._send_and_await_ack(unsubscription_msg, request_id, timeout=10),
                timeout=12,
            )
        except TimeoutError:
            logger.warning(
                f"Unsubscribe timed out waiting for proxy ack (mode={mode}, "
                f"symbols={len(symbols)})"
            )
            return {
                "status": "error",
                "message": "Timed out waiting for proxy unsubscribe response",
                "mode": canonical_mode,
            }
        except Exception as e:
            logger.exception(f"Error unsubscribing from symbols: {e}")
            return {"status": "error", "message": str(e)}

        # Update local tracking only for symbols the proxy confirmed.
        successful = ack.get("successful", []) or []
        self._remove_acknowledged_modes(successful, requested_modes)

        return {
            "status": ack.get("status", "success"),
            "message": ack.get("message", f"Unsubscribed from {len(symbols)} symbols"),
            "successful": successful,
            "failed": ack.get("failed", []),
            "broker": ack.get("broker"),
            "mode": canonical_mode,
        }

    def unsubscribe_all(self) -> dict[str, Any]:
        """Unsubscribe from all symbols, retaining any broker-refused owners."""
        if not self.connected or not self.authenticated:
            return {"status": "error", "message": "Not connected or authenticated"}
        if not self.loop or not self.ws:
            return {"status": "error", "message": "WebSocket connection not available"}

        try:
            with self.lock:
                requested_modes: dict[tuple[str, str], set[str]] = {}
                for symbol_key, modes in self.active_subscriptions.items():
                    exchange, symbol = symbol_key.split(":", 1)
                    canonical_modes = {
                        _canonical_mode(item_mode) for item_mode in modes
                    }
                    requested_modes[(exchange, symbol)] = canonical_modes

            request_id = str(uuid.uuid4())
            unsubscription_msg = {
                "action": "unsubscribe_all",
                "request_id": request_id,
            }
            ack = self._run_on_loop(
                self._send_and_await_ack(unsubscription_msg, request_id, timeout=10),
                timeout=12,
            )
        except TimeoutError:
            return {
                "status": "error",
                "message": "Timed out waiting for proxy unsubscribe response",
            }
        except Exception as e:
            logger.exception(f"Error unsubscribing from all symbols: {e}")
            return {"status": "error", "message": str(e)}

        successful = ack.get("successful", []) or []
        self._remove_acknowledged_modes(successful, requested_modes)
        return {
            "status": ack.get("status", "success"),
            "message": ack.get("message", "Unsubscription processing complete"),
            "successful": successful,
            "failed": ack.get("failed", []),
            "broker": ack.get("broker"),
        }

    def get_subscriptions(self) -> dict[str, Any]:
        """Get current active subscriptions"""
        with self.lock:
            subscriptions = []
            for symbol_key, modes in self.active_subscriptions.items():
                exchange, symbol = symbol_key.split(":")
                for mode in modes:
                    subscriptions.append({"exchange": exchange, "symbol": symbol, "mode": mode})

            return {
                "status": "success",
                "subscriptions": subscriptions,
                "count": len(subscriptions),
            }

    def get_market_data(
        self, symbol: str | None = None, exchange: str | None = None
    ) -> dict[str, Any]:
        """
        Get cached market data

        Args:
            symbol: Symbol to get data for (optional)
            exchange: Exchange to get data for (optional)

        Returns:
            Market data dictionary
        """
        with self.lock:
            if symbol and exchange:
                key = f"{exchange}:{symbol}"
                return self.market_data_cache.get(key, {})
            else:
                return dict(self.market_data_cache)

    def _dispatch(self, event_type: str, data: dict) -> None:
        """Hand a callback payload to the hub. Runs on the loop thread."""
        try:
            self._dispatch_queue.put_nowait((event_type, data))
        except Exception:
            self._dispatch_dropped += 1
            if self._dispatch_dropped == 1 or self._dispatch_dropped % 1000 == 0:
                logger.warning(
                    f"WebSocket dispatch queue full ({self.DISPATCH_QUEUE_MAX}); "
                    f"dropped {self._dispatch_dropped} callback payload(s). A "
                    f"subscriber is slower than the feed."
                )

    def _run_dispatch_loop(self) -> None:
        """Call subscriber callbacks, on the hub rather than the loop thread.

        A plain threading.Thread runs this, which under eventlet is a green
        thread owned by the hub. That is the whole point: everything a callback
        touches (SocketIO, the event bus, the sandbox engine, the database) is
        then reached from the world those primitives belong to.

        The queue is real, so get_nowait() plus a yield is the only safe way to
        read it; a blocking get() from a green thread would freeze the worker.
        """
        while self.running:
            try:
                event_type, data = self._dispatch_queue.get_nowait()
            except _original_threading.Empty:
                time.sleep(self.DISPATCH_POLL_SECONDS)
                continue
            for callback in list(self.callbacks.get(event_type, ())):
                try:
                    callback(data)
                except Exception as e:
                    logger.exception(f"Error in {event_type} callback: {e}")

    def register_callback(self, event_type: str, callback: Callable):
        """
        Register a callback for specific event types

        Args:
            event_type: Type of event ('market_data', 'auth', 'subscribe', 'unsubscribe', 'error')
            callback: Function to call when event occurs
        """
        if event_type in self.callbacks:
            self.callbacks[event_type].append(callback)
            logger.info(f"Registered callback for {event_type} events")

    def unregister_callback(self, event_type: str, callback: Callable):
        """
        Unregister a callback

        Args:
            event_type: Type of event
            callback: Function to remove
        """
        if event_type in self.callbacks and callback in self.callbacks[event_type]:
            self.callbacks[event_type].remove(callback)
            logger.info(f"Unregistered callback for {event_type} events")

    def _run_event_loop(self):
        """Run the asyncio event loop in a separate thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_until_complete(self._connect_and_run())
        except Exception as e:
            logger.exception(f"Error in event loop: {e}")
        finally:
            self.loop.close()

    async def _connect_and_run(self):
        """Connect to WebSocket and handle messages"""
        retry_count = 0
        max_retries = 5

        while self.running and retry_count < max_retries:
            try:
                async with websockets.connect(self.ws_url) as websocket:
                    self.ws = websocket
                    self.connected = True
                    logger.info(f"Connected to WebSocket server at {self.ws_url}")

                    # Authenticate immediately after connection
                    await self._authenticate()

                    # Handle messages
                    async for message in websocket:
                        if not self.running:
                            break
                        await self._handle_message(message)

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}")
                self.connected = False
                self.authenticated = False

                if self.running:
                    retry_count += 1
                    wait_time = min(2**retry_count, 30)  # Exponential backoff
                    logger.info(
                        f"Reconnecting in {wait_time} seconds... (attempt {retry_count}/{max_retries})"
                    )
                    await asyncio.sleep(wait_time)

            except Exception as e:
                logger.exception(f"Error in WebSocket connection: {e}")
                self.connected = False
                self.authenticated = False

                if self.running:
                    retry_count += 1
                    await asyncio.sleep(5)

    async def _authenticate(self):
        """Send authentication message"""
        auth_msg = {"action": "authenticate", "api_key": self.api_key}

        await self.ws.send(json.dumps(auth_msg))
        logger.info("Sent authentication request")

    async def _disconnect(self):
        """Disconnect from WebSocket"""
        if self.ws:
            await self.ws.close()

    async def _handle_message(self, message: str):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(message)
            msg_type = data.get("type", data.get("status"))

            # Handle authentication response
            if msg_type == "auth":
                if data.get("status") == "success":
                    self.authenticated = True
                    logger.info("Authentication successful")
                else:
                    logger.error(f"Authentication failed: {data.get('message')}")

                # Trigger auth callbacks
                self._dispatch("auth", data)

            # Handle market data
            elif msg_type == "market_data":
                symbol = data.get("symbol")
                exchange = data.get("exchange")

                if symbol and exchange:
                    # Subscription cleanup and cache ownership share this
                    # real OS-thread lock. Whichever wins the race, a frame
                    # arriving after the final acknowledged unsubscribe cannot
                    # recreate a cache entry with no remaining owner.
                    with self.lock:
                        key = f"{exchange}:{symbol}"
                        if self.active_subscriptions.get(key):
                            self.market_data_cache[key] = data

                    # Trigger market data callbacks
                    self._dispatch("market_data", data)

            # Handle subscription responses
            elif msg_type == "subscribe":
                # Resolve the pending ack future for the originating request, if any
                # (issue #1376 — callers waiting on subscribe() will unblock here).
                rid = data.get("request_id")
                if rid:
                    fut = self._pending_acks.get(rid)
                    if fut is not None and not fut.done():
                        fut.set_result(data)
                # Generic subscribe-event callbacks still fire (backward compat).
                self._dispatch("subscribe", data)

            # Handle unsubscription responses
            elif msg_type == "unsubscribe":
                rid = data.get("request_id")
                if rid:
                    fut = self._pending_acks.get(rid)
                    if fut is not None and not fut.done():
                        fut.set_result(data)
                self._dispatch("unsubscribe", data)

            # Handle errors
            elif data.get("status") == "error":
                logger.error(f"Error from server: {data.get('message')}")
                # Settle the request this error answers, if it names one.
                # The proxy refuses a subscribe outright when the user has
                # no broker adapter; without this the ack future stayed
                # pending and the caller waited its whole timeout for a
                # reply that had already arrived.
                rid = data.get("request_id")
                if rid:
                    fut = self._pending_acks.get(rid)
                    if fut is not None and not fut.done():
                        fut.set_result(data)
                self._dispatch("error", data)

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON message: {message}")
        except Exception as e:
            logger.exception(f"Error handling message: {e}")


# Singleton instance management
_client_instances = {}
_client_lock = threading.Lock()


def get_websocket_client(
    api_key: str, host: str = "localhost", port: int = 8765
) -> WebSocketClient:
    """
    Get or create a WebSocket client instance for the given API key.
    Uses singleton pattern to reuse connections.

    Args:
        api_key: API key for authentication
        host: WebSocket server host
        port: WebSocket server port

    Returns:
        WebSocketClient instance
    """
    with _client_lock:
        if api_key not in _client_instances:
            client = WebSocketClient(api_key, host, port)
            if client.connect():
                _client_instances[api_key] = client
            else:
                raise ConnectionError("Failed to connect to WebSocket server")

        return _client_instances[api_key]


def close_all_clients():
    """Close all WebSocket client connections"""
    with _client_lock:
        for _api_key, client in _client_instances.items():
            try:
                client.disconnect()
            except Exception as e:
                logger.exception(f"Error closing client: {e}")
        _client_instances.clear()
