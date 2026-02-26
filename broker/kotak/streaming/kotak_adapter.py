"""
High-level, AliceBlue-style adapter for Kotak broker WebSocket streaming.
Each instance is fully isolated and safe for multi-client use.
"""

import threading
import time

from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

from .kotak_websocket import KotakWebSocket

logger = get_logger(__name__)


class KotakWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    Adapter for Kotak WebSocket streaming, suitable for OpenAlgo or similar frameworks.
    Each instance is isolated and manages its own KotakWebSocket client.
    """

    # Thread cleanup timeout
    THREAD_JOIN_TIMEOUT = 5

    def __init__(self):
        super().__init__()  # ← Initialize base adapter (sets up ZMQ)
        self._ws_client = None
        self._user_id = None
        self._broker_name = "kotak"
        self._auth_config = None
        self._connected = False
        self._lock = threading.RLock()

        # Reconnection state
        self._running = False
        self._reconnecting = False
        self._reconnect_timer = None
        self._reconnect_delay = 5        # base delay in seconds
        self._max_reconnect_delay = 60   # maximum delay in seconds
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10

        # Cache structures - following AliceBlue pattern exactly
        self._ltp_cache = {}  # {(exchange, symbol): ltp_value}
        self._quote_cache = {}  # {(exchange, symbol): full_quote_dict}
        self._depth_cache = {}  # {(exchange, symbol): depth_dict}
        self._symbol_state = {}  # {broker_exchange|token: data} for partial update merging
        self._depth_poll_state = {}  # {exchange|symbol: data} for depth polling state

        # Mapping from Kotak format to OpenAlgo format - critical for data flow
        self._kotak_to_openalgo = {}  # {(kotak_exchange, token): (exchange, symbol)}

        # Track active subscription modes per symbol - CRITICAL FOR MULTI-CLIENT SUPPORT
        self._symbol_modes = {}  # {(kotak_exchange, token): set of active modes}

    def initialize(self, broker_name: str, user_id: str, auth_data=None):
        """Initialize adapter for a specific user/session - following AliceBlue pattern."""
        self._broker_name = broker_name.lower()
        self._user_id = user_id

        # Load authentication from DB
        auth_string = get_auth_token(user_id)
        if not auth_string:
            logger.error(f"No authentication token found for user {user_id}")
            raise ValueError(f"No authentication token found for user {user_id}")

        auth_parts = auth_string.split(":::")
        if len(auth_parts) != 4:
            logger.error("Invalid authentication token format")
            raise ValueError("Invalid authentication token format")

        self._auth_config = dict(
            zip(["auth_token", "sid", "hs_server_id", "access_token"], auth_parts)
        )

        # Create websocket client
        self._ws_client = KotakWebSocket(self._auth_config)

        # Set up internal callbacks - this MUST happen during initialization like AliceBlue
        self._setup_internal_callbacks()

        logger.debug(f"Initialized KotakWebSocketAdapter for user {user_id}")

    def _setup_internal_callbacks(self):
        """Setup internal callbacks - following AliceBlue's _on_data_received pattern."""

        def on_quote_internal(quote):
            """Internal callback - mirrors AliceBlue's _on_data_received method."""
            try:
                logger.debug(f"Internal quote callback received: {quote}")
                self._on_data_received(quote)
            except Exception as e:
                logger.error(f"Error in internal quote handler: {e}")

        def on_depth_internal(depth):
            """Internal callback for depth data."""
            try:
                logger.debug(f"Internal depth callback received: {depth}")
                self._on_data_received(depth)
            except Exception as e:
                logger.error(f"Error in internal depth handler: {e}")

        def on_open_internal():
            """Internal callback when WebSocket transport opens."""
            logger.info("Kotak WebSocket transport opened")
            # Reset reconnection state only when connection actually succeeds
            with self._lock:
                self._connected = True
                self._reconnect_attempts = 0
                self._reconnecting = False

        def on_close_internal():
            """Internal callback when WebSocket connection closes."""
            logger.info("Kotak WebSocket connection closed")

            with self._lock:
                self._connected = False
                if not self._running:
                    logger.debug("Not reconnecting - adapter stopped")
                    return

                if self._reconnecting:
                    logger.debug("Reconnection already in progress, skipping")
                    return

                self._reconnecting = True

            self._schedule_reconnection()

        def on_error_internal(error):
            """Internal callback for WebSocket errors."""
            logger.error(f"Kotak WebSocket error: {error}")

        # Set callbacks on the websocket client - this is crucial
        if self._ws_client:
            logger.debug("Setting up internal callbacks on KotakWebSocket client")
            self._ws_client.set_callbacks(
                on_quote=on_quote_internal,
                on_depth=on_depth_internal,
                on_open=on_open_internal,
                on_close=on_close_internal,
                on_error=on_error_internal,
            )

    def _on_data_received(self, parsed_data):
        """Handle received and parsed market data - FIXED for partial updates like AliceBlue."""
        try:
            logger.debug(f"Data received: {parsed_data}")

            # --- FIX: Handle list of dicts (multi-script update) ---
            if isinstance(parsed_data, list):
                for item in parsed_data:
                    self._on_data_received(item)
                return

            # Work on a copy to avoid mutating the caller's dict
            parsed_data = parsed_data.copy()

            # Extract key identifiers - following AliceBlue pattern
            token = str(parsed_data.get("tk", ""))
            broker_exchange = parsed_data.get("e", "UNKNOWN")
            ltp = parsed_data.get("ltp")

            # **CRITICAL FIX**: Check if this is depth data (has bids/asks) or LTP data
            has_depth_data = "bids" in parsed_data and "asks" in parsed_data
            has_ltp_data = ltp and float(ltp) > 0

            # Create symbol key - following AliceBlue pattern
            symbol_key = f"{broker_exchange}|{token}"

            # --- Lock section 1: State merging and write-back ---
            with self._lock:
                # Check if this is a partial update by detecting missing expected fields
                is_partial_update = self._is_partial_update(parsed_data)

                # --- CRITICAL: If partial update and no previous state, initialize state ---
                if is_partial_update and symbol_key not in self._symbol_state:
                    logger.debug(f"Initializing state for partial update: {symbol_key}")
                    # Create initial state with proper default values
                    initial_state = {
                        "tk": parsed_data.get("tk", ""),
                        "e": parsed_data.get("e", ""),
                        "ts": parsed_data.get("ts", ""),
                        "ltp": 0.0,
                        "open": 0.0,
                        "high": 0.0,
                        "low": 0.0,
                        "prev_close": 0.0,
                        "volume": 0.0,
                        "bid": 0.0,
                        "ask": 0.0,
                        "bids": [],
                        "asks": [],
                    }

                    # **CRITICAL**: Copy any non-zero/non-empty values from the partial update
                    for key, value in parsed_data.items():
                        if key in initial_state:
                            # Don't overwrite with zero values for price fields
                            if key in ["open", "high", "low", "prev_close", "bid", "ask"]:
                                if value != 0.0 and value != 21474836.48:  # Kotak's invalid value
                                    initial_state[key] = value
                            elif key in ["ltp"]:
                                # **CRITICAL FIX**: Only update LTP if it's a valid positive value
                                if value and float(value) > 0:
                                    initial_state[key] = value
                            elif key in ["volume"]:
                                if value != 0.0 and value != 2147483648:  # Kotak's invalid volume
                                    initial_state[key] = value
                            elif key in ["ts"]:
                                if value:  # Non-empty symbol name
                                    initial_state[key] = value
                            else:
                                initial_state[key] = value

                    self._symbol_state[symbol_key] = initial_state

                # --- CRITICAL: Merge depth levels per level, not just per side ---
                if has_depth_data:
                    prev_state = self._symbol_state.get(symbol_key, {})
                    prev_bids = prev_state.get("bids", []) if prev_state else []
                    prev_asks = prev_state.get("asks", []) if prev_state else []
                    new_bids = parsed_data.get("bids", [])
                    new_asks = parsed_data.get("asks", [])
                    merged_bids = []
                    merged_asks = []
                    for i in range(5):
                        # --- BUY SIDE ---
                        if i < len(new_bids):
                            b = new_bids[i]
                            prev_b = (
                                prev_bids[i]
                                if i < len(prev_bids)
                                else {"price": 0, "quantity": 0, "orders": 0}
                            )
                            merged_bids.append(
                                {
                                    "price": b.get("price", 0)
                                    if b.get("price", 0) != 0
                                    else prev_b.get("price", 0),
                                    "quantity": b.get("quantity", 0)
                                    if b.get("quantity", 0) != 0
                                    else prev_b.get("quantity", 0),
                                    "orders": b.get("orders", 0)
                                    if b.get("orders", 0) != 0
                                    else prev_b.get("orders", 0),
                                }
                            )
                        elif i < len(prev_bids):
                            merged_bids.append(prev_bids[i])
                        else:
                            merged_bids.append({"price": 0, "quantity": 0, "orders": 0})

                        # --- SELL SIDE ---
                        if i < len(new_asks):
                            a = new_asks[i]
                            prev_a = (
                                prev_asks[i]
                                if i < len(prev_asks)
                                else {"price": 0, "quantity": 0, "orders": 0}
                            )
                            merged_asks.append(
                                {
                                    "price": a.get("price", 0)
                                    if a.get("price", 0) != 0
                                    else prev_a.get("price", 0),
                                    "quantity": a.get("quantity", 0)
                                    if a.get("quantity", 0) != 0
                                    else prev_a.get("quantity", 0),
                                    "orders": a.get("orders", 0)
                                    if a.get("orders", 0) != 0
                                    else prev_a.get("orders", 0),
                                }
                            )
                        elif i < len(prev_asks):
                            merged_asks.append(prev_asks[i])
                        else:
                            merged_asks.append({"price": 0, "quantity": 0, "orders": 0})
                    # Update parsed_data with merged depth
                    parsed_data["bids"] = merged_bids
                    parsed_data["asks"] = merged_asks

                # **CRITICAL FIX FOR PARTIAL UPDATES**: Implement AliceBlue-style state merging
                if is_partial_update and symbol_key in self._symbol_state:
                    logger.debug(f"Partial update detected for {symbol_key}")
                    merged_data = self._symbol_state[symbol_key].copy()
                    for key, value in parsed_data.items():
                        if key not in ["tk", "e"]:
                            # Skip zero values for price fields (preserve previous known value)
                            if (
                                key in ["open", "high", "low", "prev_close", "bid", "ask", "ltp"]
                                and value == 0.0
                            ):
                                continue
                            elif key == "volume" and value == 0.0:
                                continue
                            elif key == "ts" and not value:
                                continue
                            else:
                                merged_data[key] = value
                        else:
                            merged_data[key] = value
                    parsed_data = merged_data
                    logger.debug(
                        f"Merged data: {dict((k, v) for k, v in parsed_data.items() if k not in ['tk'])}"
                    )
                    ltp = parsed_data.get("ltp")
                    has_depth_data = "bids" in parsed_data and "asks" in parsed_data
                    has_ltp_data = ltp and float(ltp) > 0

                # Store the complete data only for mapped symbols (avoids unbounded growth
                # from unsolicited broker data for symbols we're not subscribed to)
                if (broker_exchange, token) in self._kotak_to_openalgo:
                    self._symbol_state[symbol_key] = {
                        **parsed_data,
                        "bids": parsed_data.get("bids", []),
                        "asks": parsed_data.get("asks", []),
                    }

            # Skip if neither LTP nor depth data is present (after merging)
            if not has_ltp_data and not has_depth_data:
                logger.debug("No LTP or depth data after merging")
                return

            # --- Lock section 2: Mapping lookup, cache updates, publish queue building ---
            mapping_key = (broker_exchange, token)
            publish_queue = []

            with self._lock:
                if mapping_key in self._kotak_to_openalgo:
                    exchange, symbol = self._kotak_to_openalgo[mapping_key]
                    cache_key = (exchange, symbol)

                    # For LTP data, update LTP cache
                    if has_ltp_data:
                        self._ltp_cache[cache_key] = float(ltp)

                    # For depth data, update depth cache
                    # Use cached LTP as fallback when current packet has no LTP
                    # (Kotak sends depth and LTP as separate packets)
                    cached_ltp = self._ltp_cache.get(cache_key, 0.0)

                    if has_depth_data:
                        depth_data = {
                            "buy": parsed_data.get("bids", []),
                            "sell": parsed_data.get("asks", []),
                            "totalbuyqty": parsed_data.get("totalbuyqty", 0),
                            "totalsellqty": parsed_data.get("totalsellqty", 0),
                            "ltp": float(ltp) if has_ltp_data else cached_ltp,
                        }
                        self._depth_cache[cache_key] = depth_data

                    # Always update quote cache with complete merged data
                    self._quote_cache[cache_key] = parsed_data.copy()

                    # Snapshot active modes and cached depth for publish queue building
                    active_modes = set(self._symbol_modes.get(mapping_key, set()))
                    effective_ltp = float(ltp) if has_ltp_data else cached_ltp
                    local_depth_cache = self._depth_cache.get(cache_key, {}).copy() if not has_depth_data else None
                else:
                    exchange = symbol = cache_key = None
                    active_modes = set()
                    effective_ltp = 0.0
                    local_depth_cache = None

            # --- Build publish queue outside lock (pure computation on local data) ---
            if exchange and symbol:
                for mode in active_modes:
                    mode_map = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}
                    mode_str = mode_map.get(mode, "LTP")
                    topic = f"{exchange}_{symbol}_{mode_str}"

                    if mode == 1 and has_ltp_data:
                        publish_data = {
                            "ltp": float(ltp),
                            "ltt": parsed_data.get("timestamp", int(time.time() * 1000)),
                        }
                    elif mode == 2 and effective_ltp > 0:
                        publish_data = {
                            "ltp": effective_ltp,
                            "ltt": parsed_data.get("timestamp", int(time.time() * 1000)),
                            "volume": parsed_data.get("volume", 0),
                            "open": parsed_data.get("open", 0.0),
                            "high": parsed_data.get("high", 0.0),
                            "low": parsed_data.get("low", 0.0),
                            "close": parsed_data.get("prev_close", 0.0),
                        }
                    elif mode == 3:
                        # Use current depth data or fall back to cached depth
                        # (Kotak sends depth and LTP as separate packets)
                        if has_depth_data:
                            depth_buy = parsed_data.get("bids", [])
                            depth_sell = parsed_data.get("asks", [])
                            depth_total_buy = parsed_data.get("totalbuyqty", 0)
                            depth_total_sell = parsed_data.get("totalsellqty", 0)
                        elif local_depth_cache:
                            depth_buy = local_depth_cache.get("buy", [])
                            depth_sell = local_depth_cache.get("sell", [])
                            depth_total_buy = local_depth_cache.get("totalbuyqty", 0)
                            depth_total_sell = local_depth_cache.get("totalsellqty", 0)
                        else:
                            continue  # No depth data available at all

                        publish_data = {
                            "timestamp": int(time.time() * 1000),
                            "depth": {
                                "buy": depth_buy,
                                "sell": depth_sell,
                            },
                            "totalbuyqty": depth_total_buy,
                            "totalsellqty": depth_total_sell,
                        }
                        # Only include LTP if valid; omitting it lets
                        # the frontend fall back to polled REST data
                        if effective_ltp > 0:
                            publish_data["ltp"] = effective_ltp
                    else:
                        continue
                    publish_data.update(
                        {
                            "symbol": symbol,
                            "exchange": exchange,
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                    publish_queue.append((topic, publish_data))

                if has_ltp_data:
                    logger.debug(f"Updated LTP cache: {exchange}:{symbol} = {ltp}")
                if has_depth_data:
                    logger.debug(f"Updated depth cache: {exchange}:{symbol}")
            else:
                logger.debug(f"No mapping found for {mapping_key}")

            # Publish outside lock to avoid blocking other adapter operations
            for topic, publish_data in publish_queue:
                logger.debug(f"Publishing to ZMQ topic: {topic}")
                self.publish_market_data(topic, publish_data)

        except Exception as e:
            logger.error(f"Error processing received data: {e}")

    def _is_partial_update(self, parsed_data):
        """
        Determine if this is a partial update based on missing expected fields.
        Less aggressive detection to avoid skipping valid updates.
        """
        # If we have LTP and symbol name, treat as valid update
        ltp = parsed_data.get("ltp", 0.0)
        symbol_name = parsed_data.get("ts", "")

        if ltp and float(ltp) > 0 and symbol_name:
            return False  # Complete enough to process

        # Check for quote mode partial updates
        quote_fields = ["open", "high", "low", "prev_close"]
        has_quote_fields = any(
            field in parsed_data and parsed_data[field] != 0.0 for field in quote_fields
        )

        if not has_quote_fields and not symbol_name:
            return True  # Definitely partial

        return False  # Default to processing the update

    def connect(self):
        """Connect to WebSocket - following AliceBlue pattern."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        # Guard against double-connect
        if self._ws_client.is_connected():
            logger.debug("WebSocket already connected, skipping")
            return

        try:
            self._running = True
            self._ws_client.connect()
            # Don't set _connected = True here; the on_close_internal/on_open
            # callbacks handle the _connected flag based on actual connection state.
            # connect() only starts the async connection thread.
            logger.debug("Kotak WebSocket connection initiated")
        except Exception as e:
            logger.error(f"Error connecting to Kotak WebSocket: {e}")
            self._connected = False

    def disconnect(self):
        """
        Disconnect from WebSocket and clean up all resources.
        Uses try/finally to ensure ZMQ cleanup even if WebSocket close fails.
        """
        with self._lock:
            self._running = False
            self._reconnecting = False

            # Cancel any pending reconnection timer
            if self._reconnect_timer:
                self._reconnect_timer.cancel()
                self._reconnect_timer = None
                logger.debug("Cancelled pending reconnection timer")

        try:
            if self._ws_client:
                try:
                    self._ws_client.close()
                except Exception as e:
                    logger.error(f"Error closing WebSocket client: {e}")
                finally:
                    self._ws_client = None

            # Clear all internal caches to release memory
            with self._lock:
                self._connected = False
                self._ltp_cache.clear()
                self._quote_cache.clear()
                self._depth_cache.clear()
                self._symbol_state.clear()
                self._depth_poll_state.clear()
                self._kotak_to_openalgo.clear()
                self._symbol_modes.clear()
                self.subscriptions.clear()
                self._reconnect_attempts = 0

        finally:
            # Always clean up ZeroMQ resources - CRITICAL for multi-instance support
            try:
                self.cleanup_zmq()
            except Exception as e:
                logger.error(f"Error cleaning up ZMQ resources: {e}")

        logger.debug("Kotak WebSocket disconnected")

    def _schedule_reconnection(self):
        """Schedule reconnection with exponential backoff."""
        with self._lock:
            if not self._running:
                logger.debug("Skipping reconnection schedule - adapter stopped")
                self._reconnecting = False
                return

            if self._reconnect_attempts >= self._max_reconnect_attempts:
                logger.error("Maximum reconnection attempts reached, cleaning up")
                self._running = False
                self._reconnecting = False
                # Release ZMQ resources since we're giving up
                try:
                    self.cleanup_zmq()
                except Exception as e:
                    logger.error(f"Error cleaning up ZMQ after max reconnect attempts: {e}")
                return

            delay = min(
                self._reconnect_delay * (2 ** self._reconnect_attempts),
                self._max_reconnect_delay,
            )

            logger.info(
                f"Reconnecting in {delay}s (attempt {self._reconnect_attempts + 1})"
            )

            # Cancel any existing timer before creating new one
            if self._reconnect_timer:
                self._reconnect_timer.cancel()

            self._reconnect_timer = threading.Timer(delay, self._attempt_reconnection)
            self._reconnect_timer.daemon = True
            self._reconnect_timer.start()

    def _attempt_reconnection(self):
        """Attempt to reconnect to WebSocket."""
        with self._lock:
            # Clear timer reference since we're now executing
            self._reconnect_timer = None

            if not self._running:
                logger.debug("Reconnection cancelled - adapter no longer running")
                self._reconnecting = False
                return

            self._reconnect_attempts += 1

        try:
            # Save current subscriptions before cleanup
            with self._lock:
                saved_subs = dict(self.subscriptions)

            # Clean up old WebSocket client
            if self._ws_client:
                logger.debug("Cleaning up old WebSocket client before reconnection")
                try:
                    self._ws_client.close()
                    # Verify old thread actually stopped
                    self._ws_client.wait_until_closed(timeout=5)
                except Exception as cleanup_err:
                    logger.warning(f"Error cleaning up old WebSocket: {cleanup_err}")

            # Recreate WebSocket client with fresh credentials
            self._recreate_ws_client()

            if self._ws_client:
                # Clear stale state from old session before reconnecting
                with self._lock:
                    self._symbol_state.clear()

                # Connect the new client (async — _connected is set by on_open callback,
                # which also resets _reconnect_attempts and _reconnecting)
                self._ws_client.connect()
                logger.info("Kotak WebSocket reconnection initiated")

                # Re-subscribe saved symbols
                failed_resubs = []
                for sub_key, sub_info in saved_subs.items():
                    try:
                        self.subscribe(
                            sub_info["symbol"],
                            sub_info["exchange"],
                            sub_info["mode"],
                        )
                        logger.info(
                            f"Resubscribed to {sub_info['exchange']}:{sub_info['symbol']}"
                        )
                    except Exception as e:
                        failed_resubs.append(f"{sub_info['exchange']}:{sub_info['symbol']}")
                        logger.error(
                            f"Error resubscribing to {sub_info['exchange']}:{sub_info['symbol']}: {e}"
                        )
                if failed_resubs:
                    logger.error(
                        f"Failed to resubscribe {len(failed_resubs)} symbols after reconnection: "
                        f"{', '.join(failed_resubs)}"
                    )
            else:
                logger.error("Failed to recreate WebSocket client")
                with self._lock:
                    self._reconnecting = False
                self._schedule_reconnection()

        except Exception as e:
            logger.error(f"Reconnection error: {e}")
            with self._lock:
                self._reconnecting = False
            self._schedule_reconnection()

    def _recreate_ws_client(self):
        """Recreate the WebSocket client with current credentials from DB."""
        try:
            auth_string = get_auth_token(self._user_id)
            if not auth_string:
                logger.error(
                    f"Cannot recreate client - no auth token for user {self._user_id}"
                )
                self._ws_client = None
                return

            auth_parts = auth_string.split(":::")
            if len(auth_parts) != 4:
                logger.error("Invalid authentication token format during reconnection")
                self._ws_client = None
                return

            self._auth_config = dict(
                zip(
                    ["auth_token", "sid", "hs_server_id", "access_token"],
                    auth_parts,
                )
            )

            # Create new WebSocket client
            self._ws_client = KotakWebSocket(self._auth_config)

            # Restore internal callbacks
            self._setup_internal_callbacks()

            logger.debug("WebSocket client recreated successfully")

        except Exception as e:
            logger.error(f"Error recreating WebSocket client: {e}")
            self._ws_client = None

    def cleanup(self):
        """
        Clean up all resources including WebSocket connection and ZMQ resources.
        Should be called before discarding the adapter instance.
        """
        try:
            # Cancel any pending reconnection timer
            with self._lock:
                if self._reconnect_timer:
                    self._reconnect_timer.cancel()
                    self._reconnect_timer = None

            # Disconnect WebSocket if connected
            if self._ws_client:
                try:
                    self._ws_client.close()
                except Exception as ws_err:
                    logger.error(
                        f"Error closing WebSocket client during cleanup: {ws_err}"
                    )
                finally:
                    self._ws_client = None

            # Reset adapter state
            with self._lock:
                self._running = False
                self._connected = False
                self._reconnecting = False
                self._reconnect_attempts = 0
                self._ltp_cache.clear()
                self._quote_cache.clear()
                self._depth_cache.clear()
                self._symbol_state.clear()
                self._depth_poll_state.clear()
                self._kotak_to_openalgo.clear()
                self._symbol_modes.clear()
                self.subscriptions.clear()

            # Clean up ZMQ resources
            self.cleanup_zmq()

            logger.info("Kotak adapter cleaned up completely")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            # Try one last time to clean up ZMQ resources
            try:
                self.cleanup_zmq()
            except Exception as zmq_err:
                logger.error(
                    f"Error cleaning up ZMQ during final cleanup attempt: {zmq_err}"
                )

    def __del__(self):
        """
        Destructor - ensures resources are released even when adapter is garbage collected.
        This is a safety net; callers should explicitly call disconnect() or cleanup().
        """
        try:
            try:
                self.cleanup()
            except Exception:
                pass
            try:
                self.cleanup_zmq()
            except Exception:
                pass
        except Exception:
            pass

    def subscribe(self, symbol, exchange, mode, depth_level=0):
        """Subscribe to a symbol - FIXED for multi-client support."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized.")
            return self._create_error_response(
                "NOT_INITIALIZED", "WebSocket client not initialized."
            )

        try:
            logger.debug(f"Subscribing to {exchange}:{symbol} with mode {mode}")

            if mode in (1, 2):
                # Quote/LTP subscription
                success = self.subscribe_quote(exchange, symbol, mode)
            elif mode == 3:
                # Depth subscription + quote subscription for LTP updates
                # (Kotak sends depth and LTP as separate streams;
                # "dps" only sends bid/ask, "mws" sends LTP)
                success = self.subscribe_depth(exchange, symbol, mode)
                quote_success = self.subscribe_quote(exchange, symbol, mode)
                if not quote_success:
                    logger.warning(f"Depth subscribed but quote (LTP) subscription failed for {exchange}:{symbol}")
            else:
                logger.error(f"Unknown subscribe mode: {mode}")
                return self._create_error_response(
                    "INVALID_MODE", f"Unknown subscribe mode: {mode}"
                )

            if success:
                # Track subscription - following AliceBlue pattern with detailed tracking
                sub_key = f"{exchange}|{symbol}|{mode}"
                with self._lock:
                    self.subscriptions[sub_key] = {
                        "symbol": symbol,
                        "exchange": exchange,
                        "mode": mode,
                        "depth_level": depth_level,
                    }
                return self._create_success_response(
                    f"Subscribed to {exchange}:{symbol} mode {mode}"
                )
            else:
                return self._create_error_response(
                    "SUBSCRIPTION_FAILED", f"Failed to subscribe to {exchange}:{symbol}"
                )

        except Exception as e:
            logger.error(f"Error in subscribe: {e}")
            return self._create_error_response("SUBSCRIPTION_ERROR", f"Error subscribing: {str(e)}")

    def unsubscribe(self, symbol, exchange, mode):
        """Unsubscribe from a symbol - FIXED for multi-client support."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized.")
            return self._create_error_response(
                "NOT_INITIALIZED", "WebSocket client not initialized."
            )

        try:
            logger.debug(f"Unsubscribing from {exchange}:{symbol} with mode {mode}")

            if mode in (1, 2):
                self.unsubscribe_quote(exchange, symbol, mode)
            elif mode == 3:
                self.unsubscribe_depth(exchange, symbol, mode)
                self.unsubscribe_quote(exchange, symbol, mode)

            # Clean up tracking and cache - following AliceBlue pattern
            sub_key = f"{exchange}|{symbol}|{mode}"
            with self._lock:
                self.subscriptions.pop(sub_key, None)

                # Only clean up caches if NO modes are active for this symbol
                from broker.kotak.streaming.kotak_mapping import get_kotak_exchange
                from database.token_db import get_token

                kotak_exchange = get_kotak_exchange(exchange)
                token = get_token(symbol, exchange)
                mapping_key = (kotak_exchange, str(token))

                # Clean up caches if no modes remain (mapping_key already removed
                # by unsubscribe_quote/unsubscribe_depth, or still present but empty)
                modes_empty = mapping_key not in self._symbol_modes or not self._symbol_modes.get(mapping_key)
                if modes_empty:
                    cache_key = (exchange, symbol)
                    self._ltp_cache.pop(cache_key, None)
                    self._quote_cache.pop(cache_key, None)
                    self._depth_cache.pop(cache_key, None)
                    # Also clean up the depth polling state used by get_depth()
                    self._depth_poll_state.pop(f"{exchange}|{symbol}", None)

            return self._create_success_response(f"Unsubscribed from {exchange}:{symbol}")

        except Exception as e:
            logger.error(f"Error in unsubscribe: {e}")
            return self._create_error_response(
                "UNSUBSCRIPTION_ERROR", f"Error unsubscribing: {str(e)}"
            )

    def subscribe_quote(self, exchange, symbol, mode):
        """Subscribe to quote (LTP) - FIXED for multi-client support."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized.")
            return False

        try:
            from broker.kotak.streaming.kotak_mapping import get_kotak_exchange
            from database.token_db import get_token

            kotak_exchange = get_kotak_exchange(exchange)
            token = get_token(symbol, exchange)

            if not token:
                logger.error(f"No token found for {symbol} on {exchange}")
                return False

            logger.debug(f"Mapping: {exchange}:{symbol} -> {kotak_exchange}:{token}")

            # Store mapping and track mode - CRITICAL FOR MULTI-CLIENT SUPPORT
            with self._lock:
                mapping_key = (kotak_exchange, str(token))
                self._kotak_to_openalgo[mapping_key] = (exchange, symbol)

                # Track active modes for this symbol
                if mapping_key not in self._symbol_modes:
                    self._symbol_modes[mapping_key] = set()
                self._symbol_modes[mapping_key].add(mode)

                logger.debug(f"Stored mapping: {mapping_key} -> ({exchange}, {symbol})")
                logger.debug(f"Active modes for {mapping_key}: {self._symbol_modes[mapping_key]}")

            # Subscribe using Kotak's market watch streaming
            # Re-check ws_client after releasing lock to avoid race with disconnect()
            ws = self._ws_client
            if not ws:
                logger.error("WebSocket client became None during subscribe_quote")
                return False
            ws.subscribe(kotak_exchange, token, sub_type="mws")
            logger.debug(
                f"Subscribed to quote: {exchange}:{symbol} (kotak: {kotak_exchange}|{token})"
            )
            return True

        except Exception as e:
            logger.error(f"Error subscribing to quote for {exchange}:{symbol}: {e}")
            return False

    def unsubscribe_quote(self, exchange, symbol, mode):
        """Unsubscribe from quote - FIXED for multi-client support."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized.")
            return

        try:
            from broker.kotak.streaming.kotak_mapping import get_kotak_exchange
            from database.token_db import get_token

            kotak_exchange = get_kotak_exchange(exchange)
            token = get_token(symbol, exchange)

            if not token:
                logger.error(f"No token found for {symbol} on {exchange}")
                return

            # **CRITICAL FIX**: Only unsubscribe from broker if no other modes are active
            should_unsub_broker = False
            with self._lock:
                mapping_key = (kotak_exchange, str(token))

                # Remove this mode from active modes
                if mapping_key in self._symbol_modes:
                    self._symbol_modes[mapping_key].discard(mode)

                    # Only unsubscribe from broker if no LTP/QUOTE modes are active
                    ltp_quote_modes = {1, 2}
                    active_ltp_quote_modes = self._symbol_modes[mapping_key] & ltp_quote_modes

                    if not active_ltp_quote_modes:
                        should_unsub_broker = True

                    # Clean up mapping and cached state only if NO modes are active
                    if not self._symbol_modes[mapping_key]:
                        self._kotak_to_openalgo.pop(mapping_key, None)
                        self._symbol_modes.pop(mapping_key, None)
                        # Clean up symbol state to prevent unbounded memory growth
                        symbol_key = f"{kotak_exchange}|{token}"
                        self._symbol_state.pop(symbol_key, None)
                        logger.debug(f"Cleaned up mapping for: {exchange}:{symbol}")

            # Send unsubscribe outside lock to avoid deadlock
            if should_unsub_broker:
                ws = self._ws_client
                if ws:
                    ws.unsubscribe(kotak_exchange, token, sub_type="mwu")
                    logger.debug(f"Unsubscribed from broker: {exchange}:{symbol}")

        except Exception as e:
            logger.error(f"Error unsubscribing from quote for {exchange}:{symbol}: {e}")

    def subscribe_depth(self, exchange, symbol, mode):
        """Subscribe to market depth - FIXED for multi-client support."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized.")
            return False

        try:
            from broker.kotak.streaming.kotak_mapping import get_kotak_exchange
            from database.token_db import get_token

            kotak_exchange = get_kotak_exchange(exchange)
            token = get_token(symbol, exchange)

            if not token:
                logger.error(f"No token found for {symbol} on {exchange}")
                return False

            # Store mapping and track mode
            with self._lock:
                mapping_key = (kotak_exchange, str(token))
                self._kotak_to_openalgo[mapping_key] = (exchange, symbol)

                # Track active modes for this symbol
                if mapping_key not in self._symbol_modes:
                    self._symbol_modes[mapping_key] = set()
                self._symbol_modes[mapping_key].add(mode)

            # Re-check ws_client after releasing lock to avoid race with disconnect()
            ws = self._ws_client
            if not ws:
                logger.error("WebSocket client became None during subscribe_depth")
                return False
            ws.subscribe(kotak_exchange, token, sub_type="dps")
            logger.debug(
                f"Subscribed to depth: {exchange}:{symbol} (kotak: {kotak_exchange}|{token})"
            )
            return True

        except Exception as e:
            logger.error(f"Error subscribing to depth for {exchange}:{symbol}: {e}")
            return False

    def unsubscribe_depth(self, exchange, symbol, mode):
        """Unsubscribe from market depth - FIXED for multi-client support."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized.")
            return

        try:
            from broker.kotak.streaming.kotak_mapping import get_kotak_exchange
            from database.token_db import get_token

            kotak_exchange = get_kotak_exchange(exchange)
            token = get_token(symbol, exchange)

            if not token:
                logger.error(f"No token found for {symbol} on {exchange}")
                return

            # **CRITICAL FIX**: Only unsubscribe from broker if no other modes are active
            should_unsub_broker = False
            with self._lock:
                mapping_key = (kotak_exchange, str(token))

                # Remove this mode from active modes
                if mapping_key in self._symbol_modes:
                    self._symbol_modes[mapping_key].discard(mode)

                    # Only unsubscribe from broker if no DEPTH modes are active
                    if 3 not in self._symbol_modes[mapping_key]:
                        should_unsub_broker = True

                    # Clean up mapping and cached state only if NO modes are active
                    if not self._symbol_modes[mapping_key]:
                        self._kotak_to_openalgo.pop(mapping_key, None)
                        self._symbol_modes.pop(mapping_key, None)
                        # Clean up symbol state to prevent unbounded memory growth
                        symbol_key = f"{kotak_exchange}|{token}"
                        self._symbol_state.pop(symbol_key, None)
                        logger.debug(f"Cleaned up mapping for: {exchange}:{symbol}")

            # Send unsubscribe outside lock to avoid deadlock
            if should_unsub_broker:
                ws = self._ws_client
                if ws:
                    ws.unsubscribe(kotak_exchange, token, sub_type="dpu")
                    logger.debug(f"Unsubscribed from broker depth: {exchange}:{symbol}")

        except Exception as e:
            logger.error(f"Error unsubscribing from depth for {exchange}:{symbol}: {e}")

    def get_ltp(self):
        """Return LTP data in the format expected by the WebSocket server."""
        with self._lock:
            # Create the expected nested format that matches AliceBlue/Angel response
            ltp_dict = {}

            # Convert cache format to client-expected nested format
            for (exchange, symbol), ltp_value in self._ltp_cache.items():
                if exchange not in ltp_dict:
                    ltp_dict[exchange] = {}

                ltp_dict[exchange][symbol] = {
                    "ltp": ltp_value,
                    "timestamp": int(time.time() * 1000),
                }

            logger.debug(f"get_ltp returning: {ltp_dict}")
            return ltp_dict  # Return nested dict format

    def get_quote(self):
        """Return quote data in the format expected by the WebSocket server."""
        with self._lock:
            quote_dict = {}

            # Convert quote cache to client-expected nested format
            for (exchange, symbol), quote_data in self._quote_cache.items():
                if exchange not in quote_dict:
                    quote_dict[exchange] = {}

                # Build complete quote data from cached state
                quote_dict[exchange][symbol] = {
                    "timestamp": int(time.time() * 1000),
                    "ltp": quote_data.get("ltp", 0.0),
                    "open": quote_data.get("open", 0.0),
                    "high": quote_data.get("high", 0.0),
                    "low": quote_data.get("low", 0.0),
                    "close": quote_data.get("prev_close", 0.0),
                    "volume": quote_data.get("volume", 0),
                }

            logger.debug(f"get_quote returning: {quote_dict}")
            return quote_dict

    def get_depth(self):
        """Return depth data in the format expected by the WebSocket server."""
        with self._lock:
            depth_dict = {}

            for (exchange, symbol), depth_data in self._depth_cache.items():
                if exchange not in depth_dict:
                    depth_dict[exchange] = {}

                prev_depth = self._depth_poll_state.get(f"{exchange}|{symbol}", {})
                prev_buy = prev_depth.get("buyBook", {}) if prev_depth else {}
                prev_sell = prev_depth.get("sellBook", {}) if prev_depth else {}

                buy_book = {}
                for i, level in enumerate(depth_data.get("buy", [])[:5], 1):
                    # If this level is all zero, use previous value if available
                    if (
                        level.get("price", 0) == 0
                        and level.get("quantity", 0) == 0
                        and level.get("orders", 0) == 0
                    ):
                        prev = prev_buy.get(str(i), {"price": "0", "qty": "0", "orders": "0"})
                        buy_book[str(i)] = prev
                    else:
                        buy_book[str(i)] = {
                            "price": str(level.get("price", 0)),
                            "qty": str(level.get("quantity", 0)),
                            "orders": str(level.get("orders", 0)),
                        }

                sell_book = {}
                for i, level in enumerate(depth_data.get("sell", [])[:5], 1):
                    if (
                        level.get("price", 0) == 0
                        and level.get("quantity", 0) == 0
                        and level.get("orders", 0) == 0
                    ):
                        prev = prev_sell.get(str(i), {"price": "0", "qty": "0", "orders": "0"})
                        sell_book[str(i)] = prev
                    else:
                        sell_book[str(i)] = {
                            "price": str(level.get("price", 0)),
                            "qty": str(level.get("quantity", 0)),
                            "orders": str(level.get("orders", 0)),
                        }

                # Save merged state for next poll
                self._depth_poll_state[f"{exchange}|{symbol}"] = {
                    "buyBook": buy_book,
                    "sellBook": sell_book,
                }

                depth_dict[exchange][symbol] = {
                    "timestamp": int(time.time() * 1000),
                    "ltp": depth_data.get("ltp", 0.0),
                    "buyBook": buy_book,
                    "sellBook": sell_book,
                }

            logger.debug(f"get_depth returning: {depth_dict}")
            return depth_dict

    def get_last_quote(self):
        """Return the last quote data."""
        with self._lock:
            return dict(self._quote_cache)

    def get_last_depth(self):
        """Return last depth data."""
        with self._lock:
            if self._ws_client:
                return self._ws_client.get_last_depth()
        return {}

    def is_connected(self):
        """Check if WebSocket is connected."""
        return self._ws_client.is_connected() if self._ws_client else False

    def set_callbacks(
        self,
        on_quote=None,
        on_depth=None,
        on_index=None,
        on_error=None,
        on_open=None,
        on_close=None,
    ):
        """Set additional user callbacks - following AliceBlue pattern."""
        # Internal callbacks are already set up during initialization
        # This method is for additional user callbacks if needed
        logger.debug("set_callbacks called - internal callbacks remain active")
        # Don't override internal callbacks - they handle the cache updates
        pass
