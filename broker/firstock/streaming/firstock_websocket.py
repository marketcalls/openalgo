import json
import logging
import os
import ssl
import threading
import time
from urllib.parse import urlencode

import websocket

from utils.logging import get_logger


class FirstockWebSocket:
    """
    Firstock WebSocket Client for real-time market data
    """

    ROOT_URI = "wss://socket.firstock.in/V2/ws"
    HEART_BEAT_INTERVAL = 30  # Send ping every 30 seconds

    # Available Actions
    SUBSCRIBE_ACTION = "subscribe"
    UNSUBSCRIBE_ACTION = "unsubscribe"

    # Connection states
    CONNECTING = 0
    CONNECTED = 1
    DISCONNECTED = 2
    ERROR = 3

    def __init__(self, user_id, auth_token, max_retry_attempt=5, retry_delay=5):
        """
        Initialize the Firstock WebSocket client

        Parameters
        ----------
        user_id : str
            User ID for Firstock account
        auth_token : str
            Authentication token (susertoken) from login API
        max_retry_attempt : int
            Maximum number of retry attempts on connection failure
        retry_delay : int
            Delay between retry attempts in seconds
        """
        self.user_id = user_id
        self.auth_token = auth_token
        self.max_retry_attempt = max_retry_attempt
        self.retry_delay = retry_delay

        # Connection management
        self.wsapp = None
        self.ws_thread = None
        self.connection_state = self.DISCONNECTED
        self.current_retry_attempt = 0
        self.is_running = False
        self.ping_thread = None
        # Per-connection stop Event. Each monitor thread is owned by the Event
        # in scope when it was started; setting the old Event guarantees the
        # old monitor exits even if a subsequent reconnect flips the state
        # back to CONNECTED before the old thread observes DISCONNECTED.
        self._ping_stop_event = None
        # Serializes the three wsapp.close() call sites (close_connection,
        # _on_message auth-fail, _monitor_connection stale-pong) and the
        # self.wsapp = None null-out so racing closers don't clobber each
        # other or double-close.
        self._close_lock = threading.Lock()
        # Wakes the supervisor loop out of its inter-retry sleep on shutdown.
        self._shutdown_event = threading.Event()
        self.last_pong_time = time.time()
        self.authenticated = False  # Track authentication status

        # Callbacks
        self.on_open = None
        self.on_data = None
        self.on_error = None
        self.on_close = None
        self.on_message = None

        # Subscriptions tracking
        self.subscriptions = set()
        self.pending_subscriptions = []  # Queue subscriptions until authenticated

        # Logger
        self.logger = get_logger("firstock_websocket")

        if not self._sanity_check():
            self.logger.error("Invalid initialization parameters")
            raise ValueError("Provide valid values for user_id and auth_token")

    def _sanity_check(self):
        """Validate initialization parameters"""
        return bool(self.user_id and self.auth_token)

    def _build_wsapp(self):
        """
        Construct a fresh WebSocketApp bound to this instance's callbacks.

        A new WebSocketApp is created for every (re)connect. Reusing a closed
        instance leaves the underlying kernel socket in CLOSE_WAIT and leaks
        file descriptors on every reconnect cycle.
        """
        params = {"userId": self.user_id, "jKey": self.auth_token, "source": "developer-api"}
        connection_url = f"{self.ROOT_URI}?{urlencode(params)}"
        self.logger.debug(f"Connection URL: {connection_url}")
        return websocket.WebSocketApp(
            connection_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_pong=self._on_pong,
        )

    def _safe_close_wsapp(self, reason=""):
        """
        Idempotent, thread-safe wsapp close. Holds _close_lock so the three
        possible closers (close_connection, _on_message auth-fail,
        _monitor_connection stale-pong) cannot race. Snapshots self.wsapp
        and nulls it atomically before calling close().
        """
        with self._close_lock:
            wsapp = self.wsapp
            self.wsapp = None

        if wsapp is None:
            return  # Already closed by another path

        try:
            if reason:
                self.logger.info(f"Closing WebSocketApp ({reason})")
            wsapp.close()
        except Exception as e:
            self.logger.error(f"Error closing WebSocketApp: {e}")

    def connect(self):
        """Establish WebSocket connection to Firstock"""
        if self.connection_state == self.CONNECTED:
            self.logger.warning("Already connected to Firstock WebSocket")
            return

        if self.ws_thread is not None and self.ws_thread.is_alive():
            self.logger.warning("Supervisor thread already running; connect() is a no-op")
            return

        try:
            self.connection_state = self.CONNECTING
            self.is_running = True
            self.current_retry_attempt = 0
            self._shutdown_event.clear()

            self.logger.info(f"Connecting to Firstock WebSocket: {self.ROOT_URI}")
            self.logger.info(f"Using userId: {self.user_id}")
            self.logger.debug(
                f"Using auth token (jKey): {self.auth_token[:10]}...{self.auth_token[-5:] if len(self.auth_token) > 15 else self.auth_token}"
            )
            self.logger.info(
                "Note: The jKey must be the 'susertoken' obtained from Firstock's login API"
            )

            # Launch the supervisor thread — it owns the WebSocketApp
            # lifecycle (build, run_forever, retry, cleanup). All retry logic
            # lives here, not in _on_close, so the dispatch thread is never
            # blocked on time.sleep.
            self.ws_thread = threading.Thread(
                target=self._run_websocket,
                daemon=True,
                name=f"firstock-ws-{self.user_id}",
            )
            self.ws_thread.start()

        except Exception as e:
            self.logger.error(f"Error connecting to Firstock WebSocket: {e}")
            self.connection_state = self.ERROR
            raise

    def _run_websocket(self):
        """
        Supervisor loop that owns the WebSocketApp lifecycle.

        Runs run_forever() to completion (on close or error), then decides
        whether to reconnect. Previously the reconnect was spawned from
        _on_close on the dispatch thread with a blocking time.sleep —
        that starved the dispatch thread and spawned anonymous worker
        threads per reconnect. Now a single supervisor thread handles
        all iterations.
        """
        self.logger.info("WebSocket supervisor started")
        try:
            while self.is_running:
                # Build a fresh WebSocketApp for each run iteration
                try:
                    self.wsapp = self._build_wsapp()
                except Exception as e:
                    self.logger.error(f"Failed to build WebSocketApp: {e}")
                    self.connection_state = self.ERROR
                    break

                # Run until close. run_forever blocks.
                try:
                    self.wsapp.run_forever(
                        ping_interval=self.HEART_BEAT_INTERVAL,
                        ping_timeout=10,
                        sslopt={"cert_reqs": ssl.CERT_NONE},
                    )
                except Exception as e:
                    self.logger.error(f"WebSocket run_forever crashed: {e}")
                    self.connection_state = self.ERROR

                self.logger.info("WebSocket run_forever returned")

                # Null out the old wsapp — next iteration will build a fresh
                # one. close_connection() may have already nulled it.
                with self._close_lock:
                    self.wsapp = None

                if not self.is_running:
                    break

                # Decide whether to retry
                self.current_retry_attempt += 1
                if self.current_retry_attempt >= self.max_retry_attempt:
                    self.logger.error(
                        f"Max retry attempts ({self.max_retry_attempt}) reached, giving up"
                    )
                    self.is_running = False
                    break

                self.logger.info(
                    f"Reconnecting in {self.retry_delay}s "
                    f"(attempt {self.current_retry_attempt + 1}/{self.max_retry_attempt})..."
                )
                # Wake immediately if shutdown is requested mid-wait.
                if self._shutdown_event.wait(self.retry_delay):
                    self.logger.info("Shutdown requested during retry wait; exiting supervisor")
                    break
        finally:
            self.connection_state = self.DISCONNECTED
            self.logger.info("WebSocket supervisor exiting")

    def close_connection(self):
        """
        Close WebSocket connection, join background threads, and null
        self.wsapp so later callers see a clean "no connection" state.
        """
        self.is_running = False

        # Wake supervisor from its inter-retry sleep (if any)
        self._shutdown_event.set()

        # Signal the monitor thread to exit (wakes it from stop_event.wait(5))
        if self._ping_stop_event is not None:
            self._ping_stop_event.set()

        # Thread-safe close — also nulls self.wsapp
        self._safe_close_wsapp(reason="close_connection")

        # Join supervisor so run_forever has fully unwound before the caller
        # (adapter.disconnect) proceeds to tear down ZMQ. Guard against
        # self-join if close_connection is ever invoked from the dispatch
        # thread itself.
        ws_thread = self.ws_thread
        if (
            ws_thread is not None
            and ws_thread.is_alive()
            and ws_thread is not threading.current_thread()
        ):
            ws_thread.join(timeout=5)
            if ws_thread.is_alive():
                self.logger.warning(
                    "ws_thread did not exit within 5s after close_connection"
                )
        self.ws_thread = None

        # Join the monitor thread (stop_event was set above; it should exit
        # almost immediately from its wait()).
        ping_thread = self.ping_thread
        self.ping_thread = None
        if (
            ping_thread is not None
            and ping_thread.is_alive()
            and ping_thread is not threading.current_thread()
        ):
            ping_thread.join(timeout=2)

        self.connection_state = self.DISCONNECTED
        self.logger.info("Firstock WebSocket connection closed")

    def subscribe(self, correlation_id, mode, token_list):
        """
        Subscribe to market data feed

        Parameters
        ----------
        correlation_id : str
            Unique identifier for this subscription
        mode : int
            Subscription mode (1=LTP, 2=Quote, 3=Depth)
        token_list : list
            List of tokens to subscribe to in format [{"exchangeType": "NSE", "tokens": ["26000"]}]
        """
        if self.connection_state != self.CONNECTED:
            self.logger.error("Cannot subscribe: WebSocket not connected")
            self.logger.error(f"Current connection state: {self.get_connection_state()}")
            return

        # If not authenticated yet, queue the subscription
        if not self.authenticated:
            self.logger.info(
                f"Queuing subscription for {correlation_id} until authentication completes"
            )
            self.logger.info(
                "WebSocket is connected but waiting for authentication response from Firstock"
            )
            self.pending_subscriptions.append((correlation_id, mode, token_list))
            return

        # Snapshot wsapp locally — close_connection() may null it concurrently.
        wsapp = self.wsapp
        if wsapp is None:
            self.logger.error(
                f"Cannot subscribe to {correlation_id}: WebSocketApp is not initialized"
            )
            return

        try:
            # Convert token_list to Firstock format
            tokens = []
            for token_info in token_list:
                exchange = token_info.get("exchangeType", "")
                for token in token_info.get("tokens", []):
                    tokens.append(f"{exchange}:{token}")

            # Create subscription message
            subscribe_msg = {
                "action": self.SUBSCRIBE_ACTION,
                "tokens": "|".join(tokens),  # Firstock uses pipe-separated tokens
            }

            # Send subscription
            wsapp.send(json.dumps(subscribe_msg))

            # Track subscription
            self.subscriptions.add(correlation_id)

            self.logger.info(f"Subscribed to {correlation_id} with tokens: {tokens}")

        except Exception as e:
            self.logger.error(f"Error subscribing to {correlation_id}: {e}")
            raise

    def unsubscribe(self, correlation_id, mode, token_list):
        """
        Unsubscribe from market data feed

        Parameters
        ----------
        correlation_id : str
            Unique identifier for this subscription
        mode : int
            Subscription mode
        token_list : list
            List of tokens to unsubscribe from
        """
        if self.connection_state != self.CONNECTED:
            self.logger.error("Cannot unsubscribe: WebSocket not connected")
            return

        # Snapshot wsapp locally — close_connection() may null it concurrently.
        wsapp = self.wsapp
        if wsapp is None:
            self.logger.error(
                f"Cannot unsubscribe from {correlation_id}: WebSocketApp is not initialized"
            )
            return

        try:
            # Convert token_list to Firstock format
            tokens = []
            for token_info in token_list:
                exchange = token_info.get("exchangeType", "")
                for token in token_info.get("tokens", []):
                    tokens.append(f"{exchange}:{token}")

            # Create unsubscription message
            unsubscribe_msg = {"action": self.UNSUBSCRIBE_ACTION, "tokens": "|".join(tokens)}

            # Send unsubscription
            wsapp.send(json.dumps(unsubscribe_msg))

            # Remove from tracking
            self.subscriptions.discard(correlation_id)

            self.logger.info(f"Unsubscribed from {correlation_id}")

        except Exception as e:
            self.logger.error(f"Error unsubscribing from {correlation_id}: {e}")
            raise

    def _on_open(self, wsapp):
        """Handle WebSocket connection open"""
        self.connection_state = self.CONNECTED
        self.current_retry_attempt = 0
        self.last_pong_time = time.time()

        self.logger.info(
            "Firstock WebSocket connection established - waiting for authentication response"
        )

        # Signal any previous monitor thread to exit before we start a new one.
        # Without this, a rapid DISCONNECT -> CONNECT cycle can leave the old
        # monitor thread still looping (it would see CONNECTED again and
        # continue), racing with the new monitor on wsapp.close().
        if self._ping_stop_event is not None:
            self._ping_stop_event.set()

        # Start a fresh ping monitor with its own stop Event.
        self._ping_stop_event = threading.Event()
        self.ping_thread = threading.Thread(
            target=self._monitor_connection,
            args=(self._ping_stop_event,),
            daemon=True,
            name=f"firstock-monitor-{self.user_id}",
        )
        self.ping_thread.start()

        # Call user callback
        if self.on_open:
            try:
                self.on_open(wsapp)
            except Exception as e:
                self.logger.error(f"Error in on_open callback: {e}")

    def _on_message(self, wsapp, message):
        """Handle WebSocket messages"""
        try:
            self.logger.debug(f"Received message: {message}")

            # Handle text messages
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                    self.logger.debug(f"Parsed JSON message: {data}")

                    # Handle authentication response
                    if "status" in data:
                        if data.get("status") == "success":
                            self.logger.info(
                                f"Authentication successful: {data.get('message', 'No message')}"
                            )
                            self.authenticated = True
                            # Process any pending subscriptions
                            self._process_pending_subscriptions()
                        elif (
                            data.get("status") == "failed"
                            or data.get("message") == "unauthenticated"
                        ):
                            # Log more details about the auth failure
                            self.logger.error(
                                f"Authentication failed: {data.get('message', 'Unknown error')}"
                            )
                            self.logger.error(f"Full response: {data}")
                            self.logger.error(f"Using userId: {self.user_id}")
                            self.logger.error(
                                f"Using jKey (first 10 chars): {self.auth_token[:10] if self.auth_token else 'None'}..."
                            )
                            self.logger.error(
                                "IMPORTANT: The jKey must be the 'susertoken' from Firstock's login API response"
                            )
                            self.logger.error("Make sure you have:")
                            self.logger.error("1. Logged in via Firstock's login API")
                            self.logger.error(
                                "2. Stored the 'susertoken' from the login response as the auth_token"
                            )
                            self.logger.error(
                                "3. The token is not expired (tokens may have limited validity)"
                            )
                            self.authenticated = False
                            # Close connection on auth failure to prevent spam.
                            # Set is_running=False and signal shutdown so the
                            # supervisor exits without retrying.
                            self.is_running = False
                            self._shutdown_event.set()
                            self._safe_close_wsapp(reason="auth failure")
                        return

                    # Handle V1-style market data (tick fields at top level)
                    if "c_symbol" in data:
                        # Per-tick — keep at debug; steady-state market feed
                        # would otherwise flood the log.
                        self.logger.debug(
                            f"Received market data for symbol: {data.get('c_symbol')} on exchange: {data.get('c_exch_seg')}"
                        )
                        if self.on_data:
                            self.on_data(wsapp, data)
                        return

                    # Handle V2-style market data: payload is {"EX:TOKEN": {...tick...}}
                    # (possibly batched for multiple symbols). Unwrap each and
                    # inject c_symbol/c_exch_seg so the existing adapter handler
                    # continues to work unchanged.
                    v2_tick_keys = [
                        k for k in data.keys()
                        if isinstance(k, str) and ":" in k and isinstance(data[k], dict)
                    ]
                    if v2_tick_keys:
                        if not getattr(self, "_v2_sample_logged", False):
                            self.logger.info(
                                f"V2 tick sample payload for {v2_tick_keys[0]}: "
                                f"{json.dumps(data[v2_tick_keys[0]])[:500]}"
                            )
                            self._v2_sample_logged = True
                        for key in v2_tick_keys:
                            tick = data[key]
                            exch, _, token = key.partition(":")
                            tick.setdefault("c_symbol", token)
                            tick.setdefault("c_exch_seg", exch)
                            if self.on_data:
                                self.on_data(wsapp, tick)
                        return

                    # Log any other message types we receive. Also dump a
                    # bounded preview of the first value (first few messages
                    # only) to help diagnose unexpected V2 payload formats.
                    first_key = next(iter(data.keys()), None)
                    if first_key is not None and not getattr(
                        self, "_unknown_payload_samples_logged", 0
                    ) >= 5:
                        val = data[first_key]
                        try:
                            val_preview = json.dumps(val)[:500]
                        except Exception:
                            val_preview = repr(val)[:500]
                        self.logger.info(
                            f"Received other message type: keys={list(data.keys())} "
                            f"first_val_type={type(val).__name__} "
                            f"first_val_preview={val_preview}"
                        )
                        self._unknown_payload_samples_logged = (
                            getattr(self, "_unknown_payload_samples_logged", 0) + 1
                        )
                    else:
                        # Steady-state unknown-type log — demote to debug so
                        # a misrouted feed can't flood the log at info.
                        self.logger.debug(
                            f"Received other message type: {list(data.keys())}"
                        )

                    # Handle other message types
                    if self.on_message:
                        self.on_message(wsapp, message)

                except json.JSONDecodeError:
                    # Handle non-JSON text messages
                    self.logger.debug(f"Received non-JSON text message: {message}")
                    if self.on_message:
                        self.on_message(wsapp, message)
            else:
                # Handle binary messages (if any) — per-message, keep at debug
                self.logger.debug(
                    f"Received binary message of length: {len(message) if hasattr(message, '__len__') else 'unknown'}"
                )
                if self.on_data:
                    self.on_data(wsapp, message)

        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    def _on_error(self, wsapp, error):
        """Handle WebSocket errors"""
        self.logger.error(f"Firstock WebSocket error: {error}")
        self.connection_state = self.ERROR

        if self.on_error:
            try:
                self.on_error(wsapp, error)
            except Exception as e:
                self.logger.error(f"Error in on_error callback: {e}")

    def _on_close(self, wsapp, close_status_code=None, close_msg=None):
        """
        Handle WebSocket connection close.

        Lightweight — just updates state and signals the monitor thread.
        The supervisor loop (_run_websocket) observes that run_forever
        returned and drives any reconnect on its own thread, so this
        callback returns immediately and never blocks the dispatch thread.
        """
        self.connection_state = self.DISCONNECTED
        self.authenticated = False  # Reset authentication status

        # Signal the current monitor thread to exit. It may be mid-sleep;
        # Event.wait() returns immediately when set.
        if self._ping_stop_event is not None:
            self._ping_stop_event.set()
        self.ping_thread = None

        self.logger.info(f"Firstock WebSocket connection closed: {close_status_code} - {close_msg}")

        if self.on_close:
            try:
                self.on_close(wsapp)
            except Exception as e:
                self.logger.error(f"Error in on_close callback: {e}")

    def _on_pong(self, wsapp, message):
        """Handle pong messages"""
        self.last_pong_time = time.time()
        self.logger.debug("Received pong from Firstock server")

    def _monitor_connection(self, stop_event):
        """
        Monitor connection health with ping-pong.

        Owned by its own stop_event — exits as soon as the event is set by
        _on_close / close_connection / the next _on_open. No state-based
        loop check, so old monitor threads can't resurrect themselves when
        a fast reconnect flips connection_state back to CONNECTED.
        """
        while not stop_event.is_set():
            try:
                # Check if we've received a pong recently
                time_since_pong = time.time() - self.last_pong_time
                if time_since_pong > 40:  # No pong for 40 seconds
                    self.logger.warning("No pong received for 40 seconds, connection may be dead")
                    # Thread-safe close — supervisor will reconnect
                    self._safe_close_wsapp(reason="stale pong")
                    return

                # Wake immediately when stop_event is set, else sleep 5s
                if stop_event.wait(5):
                    return

            except Exception as e:
                self.logger.error(f"Error in connection monitor: {e}")
                return

    def is_connected(self):
        """Check if WebSocket is connected"""
        return self.connection_state == self.CONNECTED

    def get_connection_state(self):
        """Get current connection state"""
        states = {
            self.CONNECTING: "CONNECTING",
            self.CONNECTED: "CONNECTED",
            self.DISCONNECTED: "DISCONNECTED",
            self.ERROR: "ERROR",
        }
        return states.get(self.connection_state, "UNKNOWN")

    def get_subscriptions(self):
        """Get list of active subscriptions"""
        return list(self.subscriptions)

    def _process_pending_subscriptions(self):
        """Process any subscriptions that were queued while waiting for authentication"""
        if not self.pending_subscriptions:
            return

        self.logger.info(f"Processing {len(self.pending_subscriptions)} pending subscriptions")

        # Process all pending subscriptions
        for correlation_id, mode, token_list in self.pending_subscriptions:
            try:
                self.subscribe(correlation_id, mode, token_list)
            except Exception as e:
                self.logger.error(f"Error processing pending subscription {correlation_id}: {e}")

        # Clear the pending list
        self.pending_subscriptions.clear()
