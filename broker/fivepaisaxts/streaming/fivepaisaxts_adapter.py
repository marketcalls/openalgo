import base64
import json
import os
import sys
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

from broker.fivepaisaxts.streaming.fivepaisaxts_websocket import FivepaisaXTSWebSocketClient
from database.auth_db import get_auth_token, get_feed_token
from database.token_db import get_token
from utils.logging import get_logger

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

from database.token_db import get_symbol
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

from .fivepaisaxts_mapping import FivepaisaXTSCapabilityRegistry, FivepaisaXTSExchangeMapper


class FivepaisaXTSWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Fivepaisa XTS specific implementation of the WebSocket adapter"""

    # Subscription batching: the XTS market-data API takes an `instruments`
    # ARRAY per request, so coalesce instruments sharing an xtsMessageCode into
    # one request instead of one request per symbol.
    #
    # This matters more here than on a pure socket broker: the client's
    # subscribe() is a BLOCKING HTTP POST with a 10s timeout, issued inline from
    # subscribe(). One request per symbol makes a 1000-symbol startup 1000
    # sequential round-trips.
    MAX_INSTRUMENTS_PER_SUBSCRIBE = 50
    # Gap between successive batch requests, applied only when more batches
    # remain, so a single-symbol subscribe is not penalised with a wait.
    SUBSCRIPTION_DELAY = 0.5
    # Collect window opened by the first queued instrument, before the first
    # request goes out.
    #
    # Callers subscribe one symbol at a time (an option chain fires ~50 separate
    # subscribe() calls), so without this the drain thread would send the very
    # first instrument immediately, find the queue momentarily empty, exit, and
    # be restarted by the next enqueue - one 1-instrument request per symbol,
    # which is the flood this batching exists to prevent. Waiting once here lets
    # the burst accumulate so it leaves as one request per mode. Matches the
    # window the sibling 5Paisa adapter opens.
    SUBSCRIPTION_COLLECT_WINDOW = 0.5

    def __init__(self):
        super().__init__()
        self.logger = get_logger("fivepaisa_xts_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "fivepaisaxts"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()
        self._reconnect_thread_active = False  # Guard against duplicate reconnect threads

        # Subscription batch queue: items are (mode, instrument_dict). A single
        # processor thread drains it into coalesced multi-instrument requests.
        self.pending_subscriptions = deque()
        self._sub_thread = None
        self._stop_event = threading.Event()
        self._batch_seq = 0  # Names each batch's correlation id

        # Log the ZMQ port being used
        self.logger.info(f"Fivepaisa XTS adapter initialized with ZMQ port: {self.zmq_port}")

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, str] | None = None
    ) -> None:
        """
        Initialize connection with Fivepaisa XTS WebSocket API

        Args:
            broker_name: Name of the broker (always 'fivepaisaxts' in this case)
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
                raise ValueError("Missing Fivepaisa XTS API credentials in environment variables")

        else:
            # Use provided tokens
            auth_token = auth_data.get("auth_token")
            feed_token = auth_data.get("feed_token")
            api_key = auth_data.get("api_key", os.getenv("BROKER_API_KEY_MARKET"))
            api_secret = auth_data.get("api_secret", os.getenv("BROKER_API_SECRET_MARKET"))

            if not auth_token or not feed_token:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data")

        self.logger.info("Using configured API key for Fivepaisa XTS connection")

        # Create Fivepaisa XTS WebSocket client with API credentials
        self.ws_client = FivepaisaXTSWebSocketClient(
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
                self.logger.info(f"Extracted client ID from token: {actual_user_id}")
                return actual_user_id
            else:
                self.logger.warning("userID not found in token payload, using fallback")
                return fallback_user_id

        except Exception as e:
            self.logger.error(f"Error extracting client ID from token: {e}")
            self.logger.info(f"Using fallback user ID: {fallback_user_id}")
            return fallback_user_id

    def connect(self) -> None:
        """Establish connection to Fivepaisa XTS WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        # A previous disconnect() left the stop event set; clear it or the batch
        # processor started by the first subscribe after this connect exits on
        # its collect window and nothing is ever sent.
        self._stop_event.clear()

        threading.Thread(target=self._connect_with_retry, daemon=True).start()

    def _connect_with_retry(self) -> None:
        """Connect to Fivepaisa XTS WebSocket with retry logic"""
        with self.lock:
            if self._reconnect_thread_active:
                self.logger.info("Reconnect thread already active, skipping")
                return
            self._reconnect_thread_active = True

        try:
            while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
                # Snapshot ws_client ref so disconnect() nulling it mid-call is safe
                client = self.ws_client
                if client is None:
                    self.logger.info("ws_client is None, aborting reconnect")
                    break

                try:
                    self.logger.info(
                        f"Connecting to Fivepaisa XTS WebSocket (attempt {self.reconnect_attempts + 1})"
                    )
                    client.connect()

                    # If disconnect() was called while connect() was in progress,
                    # tear down the orphaned connection to prevent FD leak
                    if not self.running:
                        self.logger.info(
                            "disconnect() called during connect - tearing down orphaned connection"
                        )
                        try:
                            client.disconnect()
                        except Exception:
                            pass
                        break

                    with self.lock:
                        self.reconnect_attempts = 0  # Reset attempts on successful connection
                    break

                except Exception as e:
                    with self.lock:
                        self.reconnect_attempts += 1
                        attempts = self.reconnect_attempts
                    delay = min(self.reconnect_delay * (2**attempts), self.max_reconnect_delay)
                    self.logger.error(f"Connection failed: {e}. Retrying in {delay} seconds...")
                    # Interruptible: disconnect() sets _stop_event, so teardown
                    # wakes us immediately instead of leaving this thread parked
                    # for up to max_reconnect_delay in a bare sleep.
                    if self._stop_event.wait(delay):
                        break

            if self.reconnect_attempts >= self.max_reconnect_attempts:
                self.logger.error("Max reconnection attempts reached. Giving up.")
        finally:
            with self.lock:
                self._reconnect_thread_active = False

    def disconnect(self) -> None:
        """Disconnect from Fivepaisa XTS WebSocket"""
        self.logger.info("*** DISCONNECT CALLED - Starting Fivepaisa XTS disconnect process ***")

        # Set running to False to prevent reconnection attempts
        self.running = False
        self.reconnect_attempts = self.max_reconnect_attempts  # Prevent reconnection attempts
        self.logger.info(
            "Set running=False and max reconnect attempts to prevent auto-reconnection"
        )

        # Wake the batch processor out of any inter-batch wait and drop queued
        # work, so it cannot fire a subscribe request at a client we are about
        # to release.
        self._stop_event.set()
        with self.lock:
            self.pending_subscriptions.clear()

        # Disconnect and release Socket.IO client
        if hasattr(self, "ws_client") and self.ws_client:
            try:
                self.logger.info("Disconnecting Socket.IO client...")
                self.ws_client.disconnect()
                self.logger.info("Socket.IO client disconnect call completed")
            except Exception as e:
                self.logger.error(f"Error during Socket.IO disconnect: {e}")
            finally:
                self.ws_client = None  # Release reference so socketio transport threads can be GC'd
        else:
            self.logger.warning("No WebSocket client to disconnect")

        # Set connected flag to False
        self.connected = False
        self.logger.info("Set connected flag to False")

        # Clean up ZeroMQ resources
        self.logger.info("Starting cleanup of ZeroMQ resources...")
        self.cleanup_zmq()

        self.logger.info("*** DISCONNECT PROCESS COMPLETED ***")

    # cleanup_zmq() is inherited from BaseBrokerWebSocketAdapter which handles:
    # - idempotency (_zmq_cleaned_up flag), shared-ZMQ skip, _instance_count
    #   decrement, socket nulling, and shared context lifecycle.

    @staticmethod
    def _instrument_key(instrument: dict) -> tuple:
        """Identity of an instrument, normalised to strings.

        XTS carries the segment as an int and the instrument id as a string in
        some paths and the reverse in others, so comparing the raw dicts misses
        matches that are the same instrument.
        """
        return (
            str(instrument.get("exchangeSegment")),
            str(instrument.get("exchangeInstrumentID")),
        )

    def _enqueue_subscriptions(self, items: list) -> None:
        """Queue (mode, instrument) items for batched sending and ensure the
        batch processor thread is running."""
        if not items:
            return
        with self.lock:
            self.pending_subscriptions.extend(items)
            if self._sub_thread is None or not self._sub_thread.is_alive():
                self._sub_thread = threading.Thread(
                    target=self._process_pending_subscriptions, daemon=True
                )
                self._sub_thread.start()

    def _process_pending_subscriptions(self) -> None:
        """Drain the pending queue into coalesced XTS subscribe requests.

        Instruments are grouped by mode - mode maps 1:1 onto xtsMessageCode and
        a request carries exactly one code - and sent up to
        MAX_INSTRUMENTS_PER_SUBSCRIBE per request, with a throttle between
        requests. Failed batches are re-queued. This replaces the previous
        one-request-per-symbol flood on bulk subscribe and on resubscribe.
        """
        consecutive_failures = 0

        # Collect window: let the rest of the burst land before the first
        # request goes out (see SUBSCRIPTION_COLLECT_WINDOW). Interruptible, so
        # a disconnect during the window does not stall shutdown.
        if self._stop_event.wait(self.SUBSCRIPTION_COLLECT_WINDOW):
            with self.lock:
                self._sub_thread = None
            return

        while self.running and not self._stop_event.is_set():
            # Decide whether to exit on an EMPTY queue under the same lock that
            # _enqueue_subscriptions holds when it appends work and checks our
            # liveness. Testing emptiness outside the lock is a lost-wakeup
            # race: an enqueue could add an item and observe this thread still
            # alive (so skip starting a new one) in the instant between our
            # unlocked test and our return, stranding that item until the next
            # enqueue or reconnect. Clearing _sub_thread here closes that window.
            with self.lock:
                if not self.pending_subscriptions:
                    self._sub_thread = None
                    return

            if not (self.connected and self.ws_client):
                # Not connected yet; _on_open re-queues everything on connect,
                # so back off briefly and re-check (interruptible).
                consecutive_failures += 1
                if consecutive_failures > 5:
                    self.logger.warning(
                        "Batch processor: not connected after retries; pausing queue."
                    )
                    break
                if self._stop_event.wait(min(2 * consecutive_failures, 10)):
                    break
                continue
            consecutive_failures = 0

            # Pull a batch of same-mode instruments. The mode is taken from the
            # head of the queue, but matching instruments are then gathered from
            # ANYWHERE in it: callers interleave modes freely, and a
            # front-run-only scan would alternate modes item by item and emit
            # one-instrument requests, which is the flood this exists to
            # prevent. Order within a mode is preserved.
            batch_mode = None
            batch_instruments = []
            with self.lock:
                if self.pending_subscriptions:
                    batch_mode = self.pending_subscriptions[0][0]
                    remaining = deque()
                    for mode, instrument in self.pending_subscriptions:
                        if (
                            mode == batch_mode
                            and len(batch_instruments) < self.MAX_INSTRUMENTS_PER_SUBSCRIBE
                        ):
                            batch_instruments.append(instrument)
                        else:
                            remaining.append((mode, instrument))
                    self.pending_subscriptions = remaining
                    self._batch_seq += 1
                    correlation_id = f"batch_mode_{batch_mode}_{self._batch_seq}"

            if not batch_instruments:
                continue

            # Snapshot the client ref: disconnect() nulls self.ws_client, and
            # this send is a blocking HTTP POST, so reading the attribute again
            # mid-call is a race the check above cannot cover.
            client = self.ws_client
            if client is None:
                break

            try:
                client.subscribe(correlation_id, batch_mode, batch_instruments)
                self.logger.info(
                    f"Sent batched subscription: {len(batch_instruments)} instruments "
                    f"in mode {batch_mode}"
                )
            except Exception as e:
                self.logger.error(f"Batch subscription failed (mode {batch_mode}): {e}")
                # Re-queue the failed batch (front, preserving order) for retry,
                # but not while stopping: disconnect() has just emptied the
                # queue, and _on_open re-queues the whole book on reconnect, so
                # putting these back would only plant duplicates.
                if self._stop_event.is_set() or not self.running:
                    break
                with self.lock:
                    for instrument in reversed(batch_instruments):
                        self.pending_subscriptions.appendleft((batch_mode, instrument))
                if self._stop_event.wait(self.SUBSCRIPTION_DELAY * 2):
                    break
                continue

            # Throttle only when more work remains, so a single-symbol
            # subscribe (the common UI case) is not made to wait for nothing.
            if self.pending_subscriptions:
                if self._stop_event.wait(self.SUBSCRIPTION_DELAY):
                    break

        # Loop exited via stop/pause (not the empty-queue return above): clear
        # the handle so a later _enqueue_subscriptions starts a fresh processor.
        with self.lock:
            self._sub_thread = None

    def subscribe(
        self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5
    ) -> dict[str, Any]:
        """
        Subscribe to market data with Fivepaisa XTS specific implementation

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

        self.logger.info(
            f"Token mapping result: symbol={symbol}, exchange={exchange} -> token={token}, brexchange={brexchange}"
        )

        # Check if the requested depth level is supported for this exchange
        is_fallback = False
        actual_depth = depth_level

        if mode == 3:  # Depth mode
            if not FivepaisaXTSCapabilityRegistry.is_depth_level_supported(exchange, depth_level):
                # If requested depth is not supported, use the highest available
                actual_depth = FivepaisaXTSCapabilityRegistry.get_fallback_depth_level(
                    exchange, depth_level
                )
                is_fallback = True

                self.logger.info(
                    f"Depth level {depth_level} not supported for {exchange}, "
                    f"using {actual_depth} instead"
                )

        # Log the input values for debugging
        self.logger.info(
            f"Subscription input - symbol: {symbol}, exchange: {exchange}, brexchange: {brexchange}"
        )

        # Create instrument list for Fivepaisa XTS API
        exchange_type = FivepaisaXTSExchangeMapper.get_exchange_type(brexchange)

        # Log the full mapping for debugging
        self.logger.info("Exchange mapping details:")
        self.logger.info(f"  - Input exchange: {exchange}")
        self.logger.info(f"  - Brexchange from DB: {brexchange}")
        self.logger.info(f"  - Mapped exchange type: {exchange_type}")
        self.logger.info(f"  - Symbol: {symbol}")

        # Ensure token is a string as expected by the API
        token_str = str(token) if token is not None else ""

        instruments = [{"exchangeSegment": exchange_type, "exchangeInstrumentID": token_str}]

        self.logger.info(f"Final subscription request for {symbol}.{exchange}:")
        self.logger.info(f"  - Exchange Segment: {exchange_type} (type: {type(exchange_type)})")
        self.logger.info(f"  - Instrument ID: {token_str}")
        self.logger.info(f"  - Full request: {instruments}")

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
            token_info = (
                f"type={type(token)}, len={len(str(token))}, value={str(token)[:4]}...{str(token)[-4:]}"
                if token
                else "None"
            )
            self.logger.info(
                f"Stored subscription [{correlation_id}]: symbol={symbol}, exchange={exchange}, brexchange={brexchange}, token_info={token_info}, mode={mode}"
            )

        # Queue for batched sending. When not connected we skip: _on_open
        # re-queues every stored subscription on (re)connect, so enqueuing here
        # too would send each instrument twice.
        if self.connected and self.ws_client:
            self._enqueue_subscriptions([(mode, instruments[0])])

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
        return FivepaisaXTSExchangeMapper.get_exchange_type(exchange)

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

        # Create instrument list for Fivepaisa XTS API. str() on the token to
        # match what subscribe() stores, so the queued-subscribe cancellation
        # below and the client's instrument bookkeeping both find it.
        instruments = [
            {
                "exchangeSegment": FivepaisaXTSExchangeMapper.get_exchange_type(brexchange),
                "exchangeInstrumentID": str(token) if token is not None else "",
            }
        ]

        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Remove from subscriptions, and cancel any still-queued subscribe for
        # the same (mode, instrument). Without this, a quick
        # subscribe -> unsubscribe sends Unsubscribe now but leaves the batched
        # Subscribe in the queue, which the processor then sends afterwards -
        # resurrecting a stale server-side subscription and its feed traffic.
        with self.lock:
            # subscribe() appends the depth level to a mode-3 id, so an exact
            # match never found a depth subscription and left it in the registry
            # for _resubscribe_all() to restore on the next reconnect - a symbol
            # the user had unsubscribed coming back on its own. Match on the
            # prefix instead, so the caller need not know the depth level.
            for key in [
                k
                for k in self.subscriptions
                if k == correlation_id or k.startswith(f"{correlation_id}_")
            ]:
                del self.subscriptions[key]
                self.logger.info(f"Removed {symbol}.{exchange} [{key}] from subscription registry")

            if self.pending_subscriptions:
                target = (mode, self._instrument_key(instruments[0]))
                self.pending_subscriptions = deque(
                    item
                    for item in self.pending_subscriptions
                    if (item[0], self._instrument_key(item[1])) != target
                )

        # Unsubscribe if connected
        if self.connected and self.ws_client:
            try:
                self.logger.info(
                    f"Sending unsubscribe request for {symbol}.{exchange} to XTS server"
                )
                self.ws_client.unsubscribe(correlation_id, mode, instruments)
                self.logger.info(f"Successfully sent unsubscribe request for {symbol}.{exchange}")

                # Deliberately NOT disconnecting here. This used to call
                # self.disconnect() on every unsubscribe, which closed the
                # Socket.IO client, cleared `running`, pinned reconnect_attempts
                # at the maximum and released ZMQ - so dropping ONE symbol
                # killed the feed for every other subscribed symbol, with no way
                # back: _on_close gates reconnection on `running`. The proxy
                # owns adapter teardown and disconnects us itself once the last
                # client goes away.
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
        self.logger.info("Connected to Fivepaisa XTS WebSocket")
        self.connected = True

        # Resubscribe to existing subscriptions if reconnecting
        self._resubscribe_all()

    def _resubscribe_all(self):
        """Resubscribe to all stored subscriptions via the batch queue.

        Coalesced into multi-instrument requests rather than one blocking HTTP
        POST per symbol: a reconnect with a full book was the worst case for the
        old path, since it replayed every subscription serially.

        Deduped on (mode, instrument): distinct correlation ids can name the
        same instrument in the same mode - mode 3 stores the depth level in its
        id, so two depth levels on one token are two entries - and the server
        only needs telling once.
        """
        items = []
        seen = set()
        with self.lock:
            for sub in self.subscriptions.values():
                for instrument in sub["instruments"]:
                    key = (sub["mode"], self._instrument_key(instrument))
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append((sub["mode"], instrument))

        if items:
            self.logger.info(f"Resubscribing {len(items)} instrument(s) in batches")
            self._enqueue_subscriptions(items)

    def _on_error(self, wsapp, error) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"Fivepaisa XTS WebSocket error: {error}")

    def _on_close(self, wsapp) -> None:
        """Callback when connection is closed"""
        self.logger.info("Fivepaisa XTS WebSocket connection closed")
        self.connected = False

        # Attempt to reconnect if we're still running
        if self.running:
            threading.Thread(target=self._connect_with_retry, daemon=True).start()

    def _on_message(self, wsapp, message) -> None:
        """Callback for text messages from the WebSocket"""
        self.logger.debug(f"Received message: {message}")

    def _on_data(self, wsapp, message) -> None:
        """Callback for market data from the WebSocket"""
        try:
            self.logger.info(f"RAW FIVEPAISA DATA: Type: {type(message)}, Data: {message}")
            self.logger.info(
                f"Adapter state - Connected: {self.connected}, Subscriptions count: {len(self.subscriptions)}"
            )

            # Handle different message types
            if isinstance(message, bytes):
                # Binary data - parse according to XTS protocol
                self.logger.info("Processing as binary data")
                self._process_binary_data(message)
                return
            elif isinstance(message, dict):
                # JSON data
                self.logger.info("Processing as JSON dict data")
                self._process_json_data(message)
                return
            elif isinstance(message, str):
                # String data - try to parse as JSON
                self.logger.info("Processing as string data")
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
            # Based on Fivepaisa XTS API documentation:
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

            self.logger.info(f"Mapped ExchangeSegment {exchange_segment} to exchange: {exchange}")

            # Check if this is an index token first
            token_str = str(exchange_instrument_id)
            symbol = None  # Initialize symbol to None

            # If it's a known index token, try the index exchange first
            if self._is_index_token(token_str, exchange_segment):
                if exchange_segment == 1:  # NSE segment
                    symbol = get_symbol(token_str, "NSE_INDEX")
                    if symbol:
                        exchange = "NSE_INDEX"
                        self.logger.info(
                            f"Found index symbol {symbol} in NSE_INDEX for token {exchange_instrument_id}"
                        )
                elif exchange_segment == 11:  # BSE segment
                    symbol = get_symbol(token_str, "BSE_INDEX")
                    if symbol:
                        exchange = "BSE_INDEX"
                        self.logger.info(
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
                        self.logger.info(
                            f"Found symbol {symbol} in NSE_INDEX for token {exchange_instrument_id}"
                        )
                elif exchange == "BSE" and not self._is_index_token(token_str, exchange_segment):
                    # Try BSE_INDEX for BSE segment as fallback
                    symbol = get_symbol(token_str, "BSE_INDEX")
                    if symbol:
                        exchange = "BSE_INDEX"
                        self.logger.info(
                            f"Found symbol {symbol} in BSE_INDEX for token {exchange_instrument_id}"
                        )

            if not symbol:
                self.logger.warning(
                    f"Could not find symbol for token {exchange_instrument_id} on exchange {exchange}"
                )
                return

            self.logger.info(
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

            self.logger.info(f"Determined mode {mode} ({mode_str}) from MessageCode {message_code}")

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

            self.logger.info(f"Publishing market data: {market_data}")
            self.logger.info(f"Publishing to topic: {topic} on ZMQ port: {self.zmq_port}")

            # Log the socket state before publishing
            self.logger.info(
                f"ZMQ Socket State - Port: {getattr(self, 'zmq_port', 'Unknown')}, Connected: {getattr(self, 'connected', False)}"
            )
            self.logger.info(f"Environment ZMQ_PORT: {os.environ.get('ZMQ_PORT', 'Not Set')}")

            # Publish to ZeroMQ
            self.publish_market_data(topic, market_data)
            self.logger.info(
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
            self.logger.info(
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

                self.logger.info(
                    f"Processing depth data - Bids count: {len(bids)}, Asks count: {len(asks)}"
                )

                result["depth"] = {
                    "buy": self._extract_depth_data(bids, is_buy=True),
                    "sell": self._extract_depth_data(asks, is_buy=False),
                }

                # Log first bid and ask for debugging
                if bids and len(bids) > 0:
                    self.logger.info(
                        f"First bid: Price={bids[0].get('Price')}, Size={bids[0].get('Size')}"
                    )
                if asks and len(asks) > 0:
                    self.logger.info(
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
