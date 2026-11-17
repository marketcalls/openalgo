import base64
import json
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from broker.wisdom.streaming.wisdom_websocket import WisdomWebSocketClient
from database.auth_db import get_auth_token, get_feed_token
from database.token_db import get_token
from utils.logging import get_logger

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

from database.token_db import get_symbol
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

from .wisdom_mapping import WisdomCapabilityRegistry, WisdomExchangeMapper


class WisdomWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Wisdom XTS specific implementation of the WebSocket adapter

    Connection lifecycle: connect() starts one feed thread (the only place a
    connection thread is started, decided under self.lock). That thread
    connects, waits until the connection ends, and reconnects with backoff
    until disconnect() stops it. Close callbacks only record the close; they
    start nothing. Each reconnect logs in to the market data API again, opens
    a new socket after closing the old one, and replays every stored
    subscription through the batch queue.

    Subscriptions are sent by one batch sender thread, outside the lock, as
    requests of up to MAX_INSTRUMENTS_PER_SUBSCRIBE instruments of one mode.
    """

    # Subscription batching. The XTS subscription request takes an array of
    # instruments, and each request is a blocking HTTP POST, so one request
    # per symbol made a 1000-symbol start, and every reconnect, 1000
    # sequential round trips.
    MAX_INSTRUMENTS_PER_SUBSCRIBE = WisdomWebSocketClient.MAX_INSTRUMENTS_PER_REQUEST
    # Window opened by the first queued instrument before anything is sent,
    # so a burst of single-symbol subscribes leaves as one request per mode.
    SUBSCRIPTION_COLLECT_WINDOW = 0.5
    # Gap between batch requests, only while more remain.
    SUBSCRIPTION_DELAY = 0.5
    # Consecutive failed sends after which the sender pauses. The queue is
    # kept, and the next subscribe or reconnect starts the sender again.
    MAX_SEND_FAILURES = 5
    # How often the feed thread looks at a connection's transport while
    # waiting for its close event.
    CONNECTION_CHECK_INTERVAL = 30

    def __init__(self):
        super().__init__()
        self.logger = get_logger("wisdom_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "wisdom"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()

        # Connection lifecycle: one feed thread per connect(), stopped by its
        # own event, and the event of the connection it is waiting on.
        self._stop_event = threading.Event()
        self._feed_thread = None
        self._connection_ended = None

        # Subscription batch queue: (mode, segment, instrument id) ->
        # (mode, instrument), in arrival order, drained by one sender thread.
        self.pending_subscriptions = {}
        self._sender_thread = None

        # Log the ZMQ port being used
        self.logger.debug(f"Wisdom adapter initialized with ZMQ port: {self.zmq_port}")

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, str] | None = None
    ) -> None:
        """
        Initialize connection with Wisdom XTS WebSocket API

        Args:
            broker_name: Name of the broker (always 'wisdom' in this case)
            user_id: Client ID/user ID
            auth_data: If provided, use these credentials instead of fetching from DB

        Raises:
            ValueError: If required authentication tokens are not found
        """
        self.user_id = user_id
        self.broker_name = broker_name

        # Get tokens from database if not provided
        if not auth_data:
            # Fetch authentication tokens from database
            auth_token = get_auth_token(user_id, bypass_cache=True)
            feed_token = get_feed_token(user_id)

            if not auth_token or not feed_token:
                self.logger.error(f"No authentication tokens found for user {user_id}")
                raise ValueError(f"No authentication tokens found for user {user_id}")

            # For XTS, we need API key and secret, not just tokens
            # These should be stored in environment variables or config
            api_key = os.getenv("BROKER_API_KEY_MARKET")
            api_secret = os.getenv("BROKER_API_SECRET_MARKET")

            if not api_key or not api_secret:
                self.logger.error(
                    "Missing BROKER_API_KEY_MARKET or BROKER_API_SECRET_MARKET environment variables"
                )
                raise ValueError("Missing Wisdom XTS API credentials in environment variables")

        else:
            # Use provided tokens
            auth_token = auth_data.get("auth_token")
            feed_token = auth_data.get("feed_token")
            api_key = auth_data.get("api_key", os.getenv("BROKER_API_KEY_MARKET"))
            api_secret = auth_data.get("api_secret", os.getenv("BROKER_API_SECRET_MARKET"))

            if not auth_token or not feed_token:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data")

        self.logger.debug("Using configured API key for Wisdom XTS connection")

        # Close a client left by an earlier initialize(), or its socket leaks
        previous = self.ws_client
        if previous is not None:
            try:
                previous.disconnect()
            except Exception:
                self.logger.exception("Error closing the previous Wisdom XTS client")

        # Create Wisdom WebSocket client with API credentials
        self.ws_client = WisdomWebSocketClient(
            api_key=api_key,
            api_secret=api_secret,
            user_id=user_id,  # Pass the user_id, client will get actual userID from login
        )

        # Set callbacks
        self.ws_client.on_open = self._on_open
        self.ws_client.on_data = self._on_data
        self.ws_client.on_error = self._on_error
        self.ws_client.on_close = self._on_close
        self.ws_client.on_message = self._on_message

        self.running = True

    def _is_index_token(self, token: str, exchange_segment: int) -> bool:
        """
        Check if a token represents an index based on well-known index tokens

        Args:
            token: The instrument token
            exchange_segment: The exchange segment code

        Returns:
            bool: True if the token is likely an index
        """
        # Well-known NSE index tokens (segment 1)
        nse_index_tokens = {
            "26000": "NIFTY",  # Nifty 50
            "26001": "BANKNIFTY",  # Bank Nifty
            "26008": "FINNIFTY",  # Fin Nifty
            "26037": "MIDCPNIFTY",  # Midcap Nifty
            # Add more NSE index tokens as needed
        }

        # Well-known BSE index tokens (segment 11)
        bse_index_tokens = {
            "1": "SENSEX",  # BSE Sensex
            "12": "BANKEX",  # BSE Bankex
            # Add more BSE index tokens as needed
        }

        if exchange_segment == 1 and token in nse_index_tokens:
            return True
        elif exchange_segment == 11 and token in bse_index_tokens:
            return True

        return False

    def _extract_client_id_from_token(self, feed_token: str, fallback_user_id: str) -> str:
        """
        Extract the actual client ID from the JWT feed token

        Args:
            feed_token: JWT token containing client information
            fallback_user_id: Fallback user ID if extraction fails

        Returns:
            str: Actual client ID from the token
        """
        try:
            # JWT tokens have format: header.payload.signature
            # We need to decode the payload (middle part)
            parts = feed_token.split(".")
            if len(parts) != 3:
                self.logger.warning("Invalid JWT token format, using fallback user ID")
                return fallback_user_id

            # Decode the payload (base64 encoded)
            payload = parts[1]
            # Add padding if needed
            padding = 4 - (len(payload) % 4)
            if padding != 4:
                payload += "=" * padding

            decoded_payload = base64.b64decode(payload)
            payload_json = json.loads(decoded_payload.decode("utf-8"))

            # Extract userID from the payload
            # From the log, it looks like: "userID": "1048131_856F2F2AF32542B762129"
            actual_user_id = payload_json.get("userID")
            if actual_user_id:
                self.logger.debug(f"Extracted client ID from token: {actual_user_id}")
                return actual_user_id
            else:
                self.logger.warning("userID not found in token payload, using fallback")
                return fallback_user_id

        except Exception as e:
            self.logger.error(f"Error extracting client ID from token: {e}")
            self.logger.debug(f"Using fallback user ID: {fallback_user_id}")
            return fallback_user_id

    def connect(self) -> None:
        """Establish connection to Wisdom XTS WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        self._start_feed_thread()

    def _start_feed_thread(self) -> None:
        """Start the feed thread, unless one is already running.

        The only place a connection thread is started. The check and the
        start happen under the lock, so concurrent callers start one thread.
        """
        with self.lock:
            if not self.running:
                return
            if (
                self._feed_thread is not None
                and self._feed_thread.is_alive()
                and not self._stop_event.is_set()
            ):
                self.logger.debug("Wisdom XTS feed thread already running")
                return
            # A fresh stop event per thread: a feed thread from before a
            # disconnect() keeps its own set event and cannot be revived.
            stop_event = threading.Event()
            self._stop_event = stop_event
            self.reconnect_attempts = 0
            self._feed_thread = threading.Thread(
                target=self._maintain_connection,
                args=(stop_event,),
                name="wisdom-feed",
                daemon=True,
            )
            self._feed_thread.start()

    def _reconnect_backoff(self) -> float:
        return min(self.reconnect_delay * (2**self.reconnect_attempts), self.max_reconnect_delay)

    def _maintain_connection(self, stop_event: threading.Event) -> None:
        """Connect, wait for the connection to end, and reconnect, until stopped.

        A connection that closes (a network drop, a close from the broker, or
        a transport timeout) is replaced after reconnect_delay seconds. Failed
        connects back off exponentially and give up after
        max_reconnect_attempts in a row. Every wait wakes at once on
        disconnect().
        """
        while self.running and not stop_event.is_set():
            # Snapshot ws_client ref so disconnect() nulling it mid-call is safe
            client = self.ws_client
            if client is None:
                break

            try:
                self.logger.debug(
                    f"Connecting to Wisdom XTS WebSocket (attempt {self.reconnect_attempts + 1})"
                )
                ended = client.connect()
            except Exception as e:
                with self.lock:
                    self.connected = False
                if not self.running or stop_event.is_set():
                    break
                self.reconnect_attempts += 1
                if self.reconnect_attempts >= self.max_reconnect_attempts:
                    self.logger.error(
                        f"Connection failed: {e}. Max reconnection attempts reached. Giving up."
                    )
                    break
                delay = self._reconnect_backoff()
                self.logger.error(f"Connection failed: {e}. Retrying in {delay} seconds...")
                if stop_event.wait(delay):
                    break
                continue

            # Publish the connection's end event under the lock disconnect()
            # takes, so a disconnect() racing this point either sees it and
            # sets it, or is seen here.
            with self.lock:
                stopping = not self.running or stop_event.is_set()
                if not stopping:
                    self._connection_ended = ended
            if stopping:
                # client.disconnect() has closed, or will close, the socket.
                break

            self.reconnect_attempts = 0  # Reset attempts on successful connection
            # The close event ends this wait. python-socketio raises no close
            # event for a transport that drops before its connect() has
            # returned, so look at the transport now and then as well.
            while not ended.wait(self.CONNECTION_CHECK_INTERVAL):
                if not client.transport_alive():
                    self.logger.warning("Wisdom XTS connection closed without a close event")
                    break

            with self.lock:
                if self._connection_ended is ended:
                    self._connection_ended = None
                if not self.running or stop_event.is_set():
                    break
                self.connected = False
            self.logger.warning(
                f"Wisdom XTS connection lost. Reconnecting in {self.reconnect_delay} seconds..."
            )
            if stop_event.wait(self.reconnect_delay):
                break

    def disconnect(self) -> None:
        """Disconnect from Wisdom XTS WebSocket"""
        self.logger.debug("*** DISCONNECT CALLED - Starting Wisdom disconnect process ***")

        # Stop the feed thread and the batch sender, wake whatever they are
        # waiting on, and drop queued subscribes so none is sent to a client
        # that is about to be released.
        with self.lock:
            self.running = False
            self.connected = False
            self._stop_event.set()
            ended, self._connection_ended = self._connection_ended, None
            self.pending_subscriptions.clear()
            client, self.ws_client = self.ws_client, None
        if ended is not None:
            ended.set()

        # Disconnect and release Socket.IO client
        if client is not None:
            try:
                self.logger.debug("Disconnecting Socket.IO client...")
                client.disconnect()
                self.logger.debug("Socket.IO client disconnect call completed")
            except Exception:
                self.logger.exception("Error during Socket.IO disconnect")
        else:
            self.logger.warning("No WebSocket client to disconnect")

        # Clean up ZeroMQ resources
        self.logger.info("Starting cleanup of ZeroMQ resources...")
        self.cleanup_zmq()

        self.logger.info("*** DISCONNECT PROCESS COMPLETED ***")

    # cleanup_zmq() is inherited from BaseBrokerWebSocketAdapter which handles:
    # - idempotency (_zmq_cleaned_up flag), shared-ZMQ skip, _instance_count
    #   decrement, socket nulling, and shared context lifecycle.

    @staticmethod
    def _instrument_key(instrument: dict) -> tuple:
        """Identity of an instrument, normalised to strings."""
        return (
            str(instrument.get("exchangeSegment")),
            str(instrument.get("exchangeInstrumentID")),
        )

    def _queue_subscriptions_locked(self, items: list) -> None:
        """Queue (mode, instrument) items and make sure the sender runs.

        Caller holds self.lock. An instrument already queued in the same mode
        is not queued twice: two depth levels of one token share a mode, and
        a reconnect re-queues the whole book over anything still waiting.
        """
        for mode, instrument in items:
            self.pending_subscriptions[(mode, *self._instrument_key(instrument))] = (
                mode,
                instrument,
            )
        if self._sender_thread is None and self.pending_subscriptions:
            self._sender_thread = threading.Thread(
                target=self._send_pending_subscriptions,
                args=(self._stop_event,),
                name="wisdom-subscribe",
                daemon=True,
            )
            self._sender_thread.start()

    def _take_batch_locked(self) -> tuple[int, list]:
        """Remove and return up to MAX_INSTRUMENTS_PER_SUBSCRIBE queued
        instruments of the mode at the head of the queue, in queue order.

        Matching instruments are gathered from anywhere in the queue, since
        callers interleave modes and a front-only scan would send one-item
        requests. Caller holds self.lock.
        """
        batch_mode = next(iter(self.pending_subscriptions.values()))[0]
        taken = []
        for key, (mode, instrument) in self.pending_subscriptions.items():
            if mode == batch_mode:
                taken.append((key, instrument))
                if len(taken) >= self.MAX_INSTRUMENTS_PER_SUBSCRIBE:
                    break
        for key, _ in taken:
            del self.pending_subscriptions[key]
        return batch_mode, [instrument for _, instrument in taken]

    def _wanted_locked(self) -> set:
        """(mode, segment, instrument id) of every stored subscription.
        Caller holds self.lock."""
        return {
            (sub["mode"], *self._instrument_key(instrument))
            for sub in self.subscriptions.values()
            for instrument in sub["instruments"]
        }

    def _send_pending_subscriptions(self, stop_event: threading.Event) -> None:
        """Drain the queue into batched subscribe requests, outside the lock.

        Every decision to stop happens under the lock that
        _queue_subscriptions_locked() holds when it checks whether a sender
        is running, so an instrument queued as this thread exits is never
        left behind.
        """
        me = threading.current_thread()
        failures = 0
        try:
            # Collect window: let the rest of a burst arrive (interruptible)
            stop_event.wait(self.SUBSCRIPTION_COLLECT_WINDOW)

            while True:
                with self.lock:
                    if (
                        stop_event.is_set()
                        or not self.running
                        or not self.pending_subscriptions
                        # Not connected: _on_open queues the whole book again
                        # on the next connection and starts a new sender.
                        or not (self.connected and self.ws_client)
                    ):
                        self._sender_thread = None
                        return
                    batch_mode, batch = self._take_batch_locked()
                    client = self.ws_client

                try:
                    client.subscribe_batch(batch_mode, batch)
                    failures = 0
                    self.logger.debug(
                        f"Sent batched subscription: {len(batch)} instruments in mode {batch_mode}"
                    )
                    delay = self.SUBSCRIPTION_DELAY
                except Exception as e:
                    failures += 1
                    with self.lock:
                        if stop_event.is_set() or not self.running:
                            self._sender_thread = None
                            return
                        # Back to the front, unless unsubscribed meanwhile
                        wanted = self._wanted_locked()
                        retry = {
                            key: (batch_mode, i)
                            for i in batch
                            if (key := (batch_mode, *self._instrument_key(i))) in wanted
                        }
                        self.pending_subscriptions = {**retry, **self.pending_subscriptions}
                        if failures >= self.MAX_SEND_FAILURES:
                            self._sender_thread = None
                            self.logger.error(
                                f"Batch subscription failed {failures} times in a row: {e}. "
                                f"Holding {len(self.pending_subscriptions)} instrument(s) "
                                "until the next subscribe or reconnect."
                            )
                            return
                    self.logger.error(f"Batch subscription failed (mode {batch_mode}): {e}")
                    delay = self.SUBSCRIPTION_DELAY * 2

                # Throttle only while more work remains
                with self.lock:
                    more = bool(self.pending_subscriptions)
                if more and stop_event.wait(delay):
                    continue  # the check at the top of the loop exits
        finally:
            with self.lock:
                if self._sender_thread is me:
                    self._sender_thread = None

    def subscribe(
        self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5
    ) -> dict[str, Any]:
        """
        Subscribe to market data with Wisdom XTS specific implementation

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Depth
            depth_level: Market depth level (5, 20)

        Returns:
            Dict: Response with status and error message if applicable
        """
        # Validate the mode
        if mode not in [1, 2, 3]:
            return self._create_error_response(
                "INVALID_MODE", f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)"
            )

        # If depth mode, check if supported depth level
        if mode == 3 and depth_level not in [5, 20]:
            return self._create_error_response(
                "INVALID_DEPTH", f"Invalid depth level {depth_level}. Must be 5 or 20"
            )

        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
            )

        token = token_info["token"]
        brexchange = token_info["brexchange"]

        self.logger.debug(
            f"Token mapping result: symbol={symbol}, exchange={exchange} -> token={token}, brexchange={brexchange}"
        )

        # Check if the requested depth level is supported for this exchange
        is_fallback = False
        actual_depth = depth_level

        if mode == 3:  # Depth mode
            if not WisdomCapabilityRegistry.is_depth_level_supported(exchange, depth_level):
                # If requested depth is not supported, use the highest available
                actual_depth = WisdomCapabilityRegistry.get_fallback_depth_level(
                    exchange, depth_level
                )
                is_fallback = True

                self.logger.debug(
                    f"Depth level {depth_level} not supported for {exchange}, "
                    f"using {actual_depth} instead"
                )

        # Log the input values for debugging
        self.logger.info(
            f"Subscription input - symbol: {symbol}, exchange: {exchange}, brexchange: {brexchange}"
        )

        # Create instrument list for Wisdom XTS API
        exchange_type = WisdomExchangeMapper.get_exchange_type(brexchange)

        # Log the full mapping for debugging
        self.logger.debug("Exchange mapping details:")
        self.logger.debug(f"  - Input exchange: {exchange}")
        self.logger.debug(f"  - Brexchange from DB: {brexchange}")
        self.logger.debug(f"  - Mapped exchange type: {exchange_type}")
        self.logger.debug(f"  - Symbol: {symbol}")

        # Ensure token is a string as expected by the API
        token_str = str(token) if token is not None else ""

        instruments = [{"exchangeSegment": exchange_type, "exchangeInstrumentID": token_str}]

        self.logger.debug(f"Final subscription request for {symbol}.{exchange}:")
        self.logger.debug(f"  - Exchange Segment: {exchange_type} (type: {type(exchange_type)})")
        self.logger.debug(f"  - Instrument ID: {token_str}")
        self.logger.debug(f"  - Full request: {instruments}")

        # Generate unique correlation ID that includes mode to prevent overwriting
        correlation_id = f"{symbol}_{exchange}_{mode}"
        if mode == 3:
            correlation_id = f"{correlation_id}_{depth_level}"

        # Store subscription for reconnection
        with self.lock:
            self.subscriptions[correlation_id] = {
                "symbol": symbol,
                "exchange": exchange,
                "brexchange": brexchange,
                "token": token,
                "mode": mode,
                "depth_level": depth_level,
                "actual_depth": actual_depth,
                "instruments": instruments,
                "is_fallback": is_fallback,
            }
            # Don't log the actual token value for security, but log its type and length
            token_info = f"type={type(token)}, len={len(str(token))}" if token else "None"
            self.logger.debug(
                f"Stored subscription [{correlation_id}]: symbol={symbol}, exchange={exchange}, brexchange={brexchange}, token_info={token_info}, mode={mode}"
            )

            # Queue for the batch sender. When not connected, _on_open
            # queues every stored subscription on the next connection.
            if self.connected and self.ws_client:
                self._queue_subscriptions_locked([(mode, instruments[0])])

        # Return success with capability info
        return self._create_success_response(
            "Subscription requested"
            if not is_fallback
            else f"Using depth level {actual_depth} instead of requested {depth_level}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            requested_depth=depth_level,
            actual_depth=actual_depth,
            is_fallback=is_fallback,
        )

    def _get_token(self, symbol: str, exchange: str) -> str | None:
        """Get token for a symbol from the database

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE')

        Returns:
            str: Token for the symbol or None if not found
        """
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if token_info:
            return token_info["token"]
        return None

    def _get_exchange_segment(self, exchange: str) -> str:
        """Get exchange segment code for XTS API

        Args:
            exchange: Exchange code (e.g., 'NSE', 'BSE')

        Returns:
            str: Exchange segment code for XTS API
        """
        return WisdomExchangeMapper.get_exchange_type(exchange)

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict[str, Any]:
        """
        Unsubscribe from market data and disconnect from XTS server

        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Subscription mode

        Returns:
            Dict: Response with status
        """
        self.logger.info(f"Unsubscribing from {symbol} on {exchange} with mode {mode}")

        # Map symbol to token
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            self.logger.error(f"Symbol {symbol} not found for exchange {exchange}")
            return self._create_error_response(
                "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
            )

        token = token_info["token"]
        brexchange = token_info["brexchange"]

        # Create instrument list for Wisdom XTS API. str() on the token to
        # match what subscribe() stores, so the queued subscribe is found.
        instruments = [
            {
                "exchangeSegment": WisdomExchangeMapper.get_exchange_type(brexchange),
                "exchangeInstrumentID": str(token) if token is not None else "",
            }
        ]

        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Remove from subscriptions, and cancel a subscribe still waiting in
        # the batch queue, or the sender would subscribe it after this.
        with self.lock:
            # subscribe() appends the depth level to a mode 3 id, so an exact
            # match never found a depth subscription, and every reconnect
            # resubscribed a symbol the user had dropped. Match the prefix.
            for key in [
                k
                for k, sub in self.subscriptions.items()
                if (k == correlation_id or k.startswith(f"{correlation_id}_"))
                and sub.get("symbol") == symbol
                and sub.get("exchange") == exchange
            ]:
                del self.subscriptions[key]
                self.logger.debug(f"Removed {symbol}.{exchange} [{key}] from subscription registry")
            self.pending_subscriptions.pop((mode, *self._instrument_key(instruments[0])), None)
            client = self.ws_client if self.connected else None

        # Unsubscribe if connected
        if client is not None:
            try:
                self.logger.debug(
                    f"Sending unsubscribe request for {symbol}.{exchange} to XTS server"
                )
                client.unsubscribe(mode, instruments)
                self.logger.info(f"Successfully sent unsubscribe request for {symbol}.{exchange}")

                # Deliberately not disconnecting here. This used to call
                # self.disconnect() after every unsubscribe, which stopped
                # the feed for every other symbol on this connection, and
                # nothing brought it back. The proxy disconnects the adapter
                # itself when its last client goes away.
            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))
        else:
            self.logger.warning("Not connected to XTS server, skipping unsubscribe request")

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}", symbol=symbol, exchange=exchange, mode=mode
        )

    def _on_open(self, wsapp) -> None:
        """Callback when connection is established"""
        with self.lock:
            if not self.running:
                return
            self.connected = True
        self.logger.info("Connected to Wisdom XTS WebSocket")

        # Resubscribe to existing subscriptions if reconnecting
        self._resubscribe_all()

    def _resubscribe_all(self):
        """Resubscribe to all stored subscriptions

        Copies the book under the lock and hands it to the batch sender,
        which sends the HTTP requests outside the lock. This used to send one
        blocking POST per subscription while holding the lock, on Socket.IO's
        event thread, so a slow broker stalled every subscribe, unsubscribe
        and tick lookup behind it.
        """
        with self.lock:
            if not self.connected:
                return
            items = [
                (sub["mode"], instrument)
                for sub in self.subscriptions.values()
                for instrument in sub["instruments"]
            ]
            self._queue_subscriptions_locked(items)
        if items:
            self.logger.info(f"Resubscribing {len(items)} instrument(s) in batches")

    def _on_error(self, wsapp, error) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"Wisdom XTS WebSocket error: {error}")

    def _on_close(self, wsapp) -> None:
        """Callback when connection is closed

        Only records the close. The feed thread is waiting on this
        connection and reconnects; nothing is started here, and the client
        does not deliver the close of a connection it has already replaced.
        """
        self.logger.info("Wisdom XTS WebSocket connection closed")
        with self.lock:
            self.connected = False

    def _on_message(self, wsapp, message) -> None:
        """Callback for text messages from the WebSocket"""
        self.logger.debug(f"Received message: {message}")

    def _on_data(self, wsapp, message) -> None:
        """Callback for market data from the WebSocket"""
        try:
            self.logger.debug(f"RAW WISDOM DATA: Type: {type(message)}, Data: {message}")
            self.logger.debug(
                f"Adapter state - Connected: {self.connected}, Subscriptions count: {len(self.subscriptions)}"
            )

            # Handle different message types
            if isinstance(message, bytes):
                # Binary data - parse according to XTS protocol
                self.logger.debug("Processing as binary data")
                self._process_binary_data(message)
                return
            elif isinstance(message, dict):
                # JSON data
                self.logger.debug("Processing as JSON dict data")
                self._process_json_data(message)
                return
            elif isinstance(message, str):
                # String data - try to parse as JSON
                self.logger.debug("Processing as string data")
                try:
                    data = json.loads(message)
                    self._process_json_data(data)
                    return
                except json.JSONDecodeError:
                    self.logger.warning(f"Received non-JSON string message: {message}")
                    return

            self.logger.warning(f"Received unknown message type: {type(message)}")

        except Exception as e:
            self.logger.error(f"Error processing market data: {e}", exc_info=True)

    def _process_binary_data(self, data: bytes):
        """Process binary market data from XTS"""
        # This would need to be implemented based on XTS binary protocol specification
        self.logger.debug(f"Processing binary data of length: {len(data)}")
        # For now, log and return - actual implementation would parse the binary format

    def _process_json_data(self, data: dict):
        """Process JSON market data"""
        try:
            # Extract basic information
            exchange_segment = data.get("ExchangeSegment")
            exchange_instrument_id = data.get("ExchangeInstrumentID")

            self.logger.debug(
                f"Processing market data: ExchangeSegment={exchange_segment}, ExchangeInstrumentID={exchange_instrument_id}"
            )

            # Create reverse mapping from ExchangeSegment to exchange code
            # Based on Wisdom API documentation:
            # "NSECM": 1, "NSEFO": 2, "NSECD": 3, "BSECM": 11, "BSEFO": 12, "MCXFO": 51
            segment_to_exchange = {
                1: "NSE",  # NSECM
                2: "NFO",  # NSEFO
                3: "CDS",  # NSECD
                11: "BSE",  # BSECM
                12: "BFO",  # BSEFO
                51: "MCX",  # MCXFO
            }

            # Get the exchange from segment
            exchange = segment_to_exchange.get(exchange_segment)
            if not exchange:
                self.logger.warning(f"Unknown ExchangeSegment: {exchange_segment}")
                return

            self.logger.debug(f"Mapped ExchangeSegment {exchange_segment} to exchange: {exchange}")

            # Check if this is an index token first
            token_str = str(exchange_instrument_id)
            symbol = None  # Initialize symbol to None

            # If it's a known index token, try the index exchange first
            if self._is_index_token(token_str, exchange_segment):
                if exchange_segment == 1:  # NSE segment
                    symbol = get_symbol(token_str, "NSE_INDEX")
                    if symbol:
                        exchange = "NSE_INDEX"
                        self.logger.debug(
                            f"Found index symbol {symbol} in NSE_INDEX for token {exchange_instrument_id}"
                        )
                elif exchange_segment == 11:  # BSE segment
                    symbol = get_symbol(token_str, "BSE_INDEX")
                    if symbol:
                        exchange = "BSE_INDEX"
                        self.logger.debug(
                            f"Found index symbol {symbol} in BSE_INDEX for token {exchange_instrument_id}"
                        )

            # If not found as index or not an index token, try regular exchange
            if not symbol:
                symbol = get_symbol(token_str, exchange)

            # If still not found on base exchange, try index exchange as fallback
            if not symbol:
                if exchange == "NSE" and not self._is_index_token(token_str, exchange_segment):
                    # Try NSE_INDEX for NSE segment as fallback
                    symbol = get_symbol(token_str, "NSE_INDEX")
                    if symbol:
                        exchange = "NSE_INDEX"
                        self.logger.debug(
                            f"Found symbol {symbol} in NSE_INDEX for token {exchange_instrument_id}"
                        )
                elif exchange == "BSE" and not self._is_index_token(token_str, exchange_segment):
                    # Try BSE_INDEX for BSE segment as fallback
                    symbol = get_symbol(token_str, "BSE_INDEX")
                    if symbol:
                        exchange = "BSE_INDEX"
                        self.logger.debug(
                            f"Found symbol {symbol} in BSE_INDEX for token {exchange_instrument_id}"
                        )

            if not symbol:
                self.logger.warning(
                    f"Could not find symbol for token {exchange_instrument_id} on exchange {exchange}"
                )
                return

            self.logger.debug(
                f"Found symbol: {symbol} for token {exchange_instrument_id} on exchange {exchange}"
            )

            # Determine mode based on MessageCode
            message_code = data.get("MessageCode")
            if message_code == 1512:  # LTP
                mode = 1
                mode_str = "LTP"
            elif message_code == 1501:  # Quote
                mode = 2
                mode_str = "QUOTE"
            elif message_code == 1502:  # Depth
                mode = 3
                mode_str = "DEPTH"
            else:
                self.logger.warning(f"Unknown MessageCode: {message_code}")
                return

            self.logger.debug(
                f"Determined mode {mode} ({mode_str}) from MessageCode {message_code}"
            )

            # Check if we have an active subscription for this symbol and mode (optional check)
            check_correlation_id = f"{symbol}_{exchange}_{mode}"
            if check_correlation_id not in self.subscriptions:
                self.logger.warning(
                    f"No active subscription found for {check_correlation_id}, but publishing anyway"
                )
                # We'll publish the data anyway since we received it

            # Create topic for ZeroMQ
            # Use standard topic format without broker prefix for WebSocket proxy routing
            topic = f"{exchange}_{symbol}_{mode_str}"

            # Normalize the data
            market_data = self._normalize_market_data(data, mode)

            # Add metadata
            market_data.update(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "mode": mode,
                    "timestamp": int(time.time() * 1000),
                }
            )

            self.logger.debug(f"Publishing market data: {market_data}")
            self.logger.debug(f"Publishing to topic: {topic} on ZMQ port: {self.zmq_port}")

            # Log the socket state before publishing
            self.logger.debug(
                f"ZMQ Socket State - Port: {getattr(self, 'zmq_port', 'Unknown')}, Connected: {getattr(self, 'connected', False)}"
            )
            self.logger.debug(f"Environment ZMQ_PORT: {os.environ.get('ZMQ_PORT', 'Not Set')}")

            # Publish to ZeroMQ
            self.publish_market_data(topic, market_data)
            self.logger.debug(
                f"Published data successfully to ZMQ - Topic: {topic}, Data: {market_data}"
            )

        except Exception as e:
            self.logger.error(f"Error processing JSON data: {e}", exc_info=True)

    def _normalize_market_data(self, message: dict[str, Any], mode: int) -> dict[str, Any]:
        """
        Normalize broker-specific data format to a common format

        Args:
            message: The raw message from the broker
            mode: Subscription mode

        Returns:
            Dict: Normalized market data
        """
        # For MessageCode 1502 (Depth mode), data is structured differently
        message_code = message.get("MessageCode")

        # For depth mode (MessageCode 1502), extract data from Touchline
        if message_code == 1502 and "Touchline" in message:
            touchline = message.get("Touchline", {})
            ltp = touchline.get("LastTradedPrice", 0)
            ltt = touchline.get("LastTradedTime", 0)
            volume = touchline.get("TotalTradedQuantity", 0)
            open_price = touchline.get("Open", 0)
            high = touchline.get("High", 0)
            low = touchline.get("Low", 0)
            close = touchline.get("Close", 0)
            ltq = touchline.get("LastTradedQunatity", touchline.get("LastTradedQuantity", 0))
            avg_price = touchline.get("AverageTradedPrice", 0)
            total_buy_qty = touchline.get("TotalBuyQuantity", 0)
            total_sell_qty = touchline.get("TotalSellQuantity", 0)

            # Log touchline data for debugging
            self.logger.debug(
                f"Extracted from Touchline - LTP: {ltp}, Volume: {volume}, Open: {open_price}"
            )
        else:
            # For other message codes (1512, 1501), data is at root level
            ltp = message.get("LastTradedPrice", 0)
            ltt = message.get("LastTradedTime", 0)
            volume = message.get("TotalTradedQuantity", 0)
            open_price = message.get("Open", 0)
            high = message.get("High", 0)
            low = message.get("Low", 0)
            close = message.get("Close", 0)
            ltq = message.get("LastTradedQunatity", message.get("LastTradedQuantity", 0))
            avg_price = message.get("AveragePrice", message.get("AverageTradedPrice", 0))
            total_buy_qty = message.get("TotalBuyQuantity", 0)
            total_sell_qty = message.get("TotalSellQuantity", 0)

        if mode == 1:  # LTP mode
            return {"ltp": ltp, "ltt": ltt, "ltq": ltq}
        elif mode == 2:  # Quote mode
            return {
                "ltp": ltp,
                "ltt": ltt,
                "volume": volume,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "last_quantity": ltq,
                "average_price": avg_price,
                "total_buy_quantity": total_buy_qty,
                "total_sell_quantity": total_sell_qty,
            }
        elif mode == 3:  # Depth mode
            result = {
                "ltp": ltp,
                "ltt": ltt,
                "volume": volume,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "oi": message.get("OpenInterest", 0),
                "upper_circuit": message.get("UpperCircuitLimit", 0),
                "lower_circuit": message.get("LowerCircuitLimit", 0),
            }

            # Add depth data if available
            if "Bids" in message and "Asks" in message:
                bids = message.get("Bids", [])
                asks = message.get("Asks", [])

                self.logger.debug(
                    f"Processing depth data - Bids count: {len(bids)}, Asks count: {len(asks)}"
                )

                result["depth"] = {
                    "buy": self._extract_depth_data(bids, is_buy=True),
                    "sell": self._extract_depth_data(asks, is_buy=False),
                }

                # Log first bid and ask for debugging
                if bids and len(bids) > 0:
                    self.logger.debug(
                        f"First bid: Price={bids[0].get('Price')}, Size={bids[0].get('Size')}"
                    )
                if asks and len(asks) > 0:
                    self.logger.debug(
                        f"First ask: Price={asks[0].get('Price')}, Size={asks[0].get('Size')}"
                    )
            else:
                self.logger.warning(
                    f"No depth data found in message. Keys present: {list(message.keys())}"
                )

            return result
        else:
            return {}

    def _extract_depth_data(self, depth_list: list[dict], is_buy: bool) -> list[dict[str, Any]]:
        """
        Extract depth data from XTS message format

        Args:
            depth_list: List of depth levels
            is_buy: Whether this is buy or sell side

        Returns:
            List: List of depth levels with price, quantity, and orders
        """
        depth = []

        for level in depth_list:
            if isinstance(level, dict):
                # XTS uses 'Size' instead of 'Quantity' and 'TotalOrders' instead of 'OrderCount'
                depth.append(
                    {
                        "price": level.get("Price", 0),
                        "quantity": level.get("Size", 0),
                        "orders": level.get("TotalOrders", 0),
                    }
                )

        # Ensure we have at least 5 levels
        while len(depth) < 5:
            depth.append({"price": 0.0, "quantity": 0, "orders": 0})

        return depth[:20]  # Limit to maximum 20 levels
