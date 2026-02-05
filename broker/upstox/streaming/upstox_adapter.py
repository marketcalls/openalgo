# broker/upstox/streaming/upstox_adapter.py
import asyncio
import json
import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, Optional


class LRUCache:
    """
    Simple thread-safe LRU (Least Recently Used) cache implementation.

    Used for caching symbol lookups to avoid repeated database queries
    while preventing unbounded memory growth.
    """

    def __init__(self, maxsize: int = 5000):
        """
        Initialize LRU cache.

        Args:
            maxsize: Maximum number of items to cache
        """
        self._cache: OrderedDict = OrderedDict()
        self._maxsize = maxsize
        self._lock = threading.Lock()

    def get(self, key):
        """
        Get item from cache, moving it to end (most recently used).

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        with self._lock:
            if key in self._cache:
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key, value):
        """
        Put item in cache, evicting LRU item if full.

        Args:
            key: Cache key
            value: Value to cache
        """
        with self._lock:
            if key in self._cache:
                # Update existing and move to end
                self._cache.move_to_end(key)
                self._cache[key] = value
            else:
                # Add new item
                self._cache[key] = value
                # Evict LRU if over capacity
                while len(self._cache) > self._maxsize:
                    self._cache.popitem(last=False)

    def clear(self):
        """Clear all cached items."""
        with self._lock:
            self._cache.clear()

    def __contains__(self, key):
        """Check if key exists in cache."""
        with self._lock:
            return key in self._cache

    def __len__(self):
        """Return number of cached items."""
        with self._lock:
            return len(self._cache)

from database.auth_db import get_auth_token
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

from .upstox_client import UpstoxWebSocketClient


class UpstoxWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    Upstox V3 WebSocket adapter implementation.

    Features:
    - Handles all WebSocket operations through UpstoxWebSocketClient
    - Processes protobuf messages decoded to dict format
    - Manages subscriptions and market data publishing

    Enhanced with proper resource management and file descriptor cleanup
    to prevent leaks during reconnection and shutdown.
    """

    # Thread cleanup timeout
    THREAD_JOIN_TIMEOUT = 5

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("upstox_websocket")
        self.ws_client: UpstoxWebSocketClient | None = None
        self.event_loop: asyncio.AbstractEventLoop | None = None
        self.ws_thread: threading.Thread | None = None
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.market_status: dict[str, Any] = {}
        self.connected = False
        self.running = False
        self.lock = threading.Lock()  # Threading lock for subscription management
        self._reconnect_lock = threading.Lock()  # Separate lock for reconnection flag
        self._reconnecting = False  # Prevent concurrent reconnection attempts
        self._intentional_disconnect = False  # Flag to prevent double-reconnect race

        # PERFORMANCE: LRU cache for instrument key lookups to avoid repeated SymbolMapper lookups
        # Maxsize 5000 prevents unbounded memory growth while caching most symbols
        self._instrument_key_cache = LRUCache(maxsize=5000)

        # STALENESS DETECTION: Track last data received time per symbol
        self._last_data_time: dict[str, float] = {}  # correlation_id -> last data timestamp
        self._staleness_threshold = 60.0  # Seconds without data before considering stale
        self._staleness_check_interval = 10.0  # Check every 10 seconds
        self._staleness_monitor_thread: threading.Thread | None = None
        self._notified_stale: set[str] = set()  # Track which symbols we've notified as stale

        # PERFORMANCE: Feed key index for O(1) subscription lookup (replaces O(n) loop)
        # Maps instrument_key -> set of correlation_ids
        self._feed_key_index: dict[str, set[str]] = {}
        # Maps token -> set of correlation_ids (fallback for token-based matching)
        self._token_index: dict[str, set[str]] = {}

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Initialize the adapter with authentication data"""
        try:
            auth_token = self._get_auth_token(auth_data, user_id)
            if not auth_token:
                return self._create_error_response("AUTH_ERROR", "No authentication token found")

            self.ws_client = UpstoxWebSocketClient(auth_token)
            self.ws_client.callbacks = {
                "on_message": self._on_market_data,
                "on_error": self._on_error,
                "on_close": self._on_close,
            }

            self.logger.info("UpstoxWebSocketClient initialized successfully")
            return self._create_success_response("Initialized Upstox WebSocket adapter")

        except Exception as e:
            self.logger.error(f"Initialization error: {e}")
            return self._create_error_response("INIT_ERROR", str(e))

    def connect(self) -> dict[str, Any]:
        """Establish WebSocket connection"""
        try:
            if self.connected:
                return self._create_success_response("Already connected")

            if not self.ws_client:
                return self._create_error_response(
                    "NOT_INITIALIZED", "WebSocket client not initialized"
                )

            self._start_event_loop()
            success = self._connect_websocket()

            if success:
                self.connected = True
                self.running = True
                self._start_staleness_monitor()  # Start monitoring for stale data
                self.logger.info("Connected to Upstox WebSocket")
                return self._create_success_response("Connected to Upstox WebSocket")
            else:
                # Clean up event loop on connection failure to prevent FD leak
                self._stop_event_loop()
                return self._create_error_response(
                    "CONNECTION_FAILED", "Failed to connect to Upstox WebSocket"
                )

        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            # Clean up event loop on error to prevent FD leak
            self._stop_event_loop()
            return self._create_error_response("CONNECTION_ERROR", str(e))

    def subscribe(
        self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 0
    ) -> dict[str, Any]:
        """Subscribe to market data with Upstox-specific implementation following Angel's pattern"""
        # Validate mode
        if mode not in [1, 2, 3]:
            return self._create_error_response(
                "INVALID_MODE", f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)"
            )

        # Check connection status
        if not self.connected:
            return self._create_error_response("NOT_CONNECTED", "WebSocket is not connected")

        if not self.ws_client or not self.event_loop:
            return self._create_error_response(
                "NOT_INITIALIZED", "WebSocket client not initialized"
            )

        # Get token info (with caching for performance)
        cached = self._get_cached_token_info(symbol, exchange)
        if not cached:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
            )

        token_info, instrument_key = cached

        # Generate unique correlation ID like Angel does
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Check for duplicate subscriptions using correlation_id
        with self.lock:
            if correlation_id in self.subscriptions:
                self.logger.info(f"Already subscribed to {symbol} on {exchange} with mode {mode}")
                return self._create_success_response(
                    f"Already subscribed to {symbol} on {exchange}"
                )

        subscription_info = {
            "symbol": symbol,
            "exchange": exchange,
            "mode": mode,
            "depth_level": depth_level,
            "token": token_info["token"],
            "instrument_key": instrument_key,
        }

        # Store subscription before sending request (Angel pattern)
        with self.lock:
            self.subscriptions[correlation_id] = subscription_info
            # PERFORMANCE: Update feed key index for O(1) lookup
            if instrument_key not in self._feed_key_index:
                self._feed_key_index[instrument_key] = set()
            self._feed_key_index[instrument_key].add(correlation_id)
            # Also index by token for fallback matching
            token = token_info["token"]
            if token not in self._token_index:
                self._token_index[token] = set()
            self._token_index[token].add(correlation_id)
            self.logger.info(f"Stored subscription: {correlation_id} -> {subscription_info}")

        # Determine the highest mode already subscribed for this instrument.
        # Upstox only supports ONE mode per instrument - the last subscribe wins.
        # To avoid downgrading (e.g. "full" → "ltpc"), only send subscribe if
        # the new mode is higher than what's already active.
        highest_existing_mode = 0
        with self.lock:
            for cid in self._feed_key_index.get(instrument_key, set()):
                if cid != correlation_id:
                    existing_sub = self.subscriptions.get(cid)
                    if existing_sub:
                        highest_existing_mode = max(highest_existing_mode, existing_sub["mode"])

        # Determine which Upstox mode to actually send
        effective_mode = max(mode, highest_existing_mode)
        upstox_mode = self._get_upstox_mode(effective_mode, depth_level)

        # Subscribe if connected (Angel pattern)
        if self.connected and self.ws_client:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.ws_client.subscribe(
                        [instrument_key], upstox_mode
                    ),
                    self.event_loop,
                )

                # Use shorter timeout like Angel (no retry loop in subscribe method)
                if future.result(timeout=5):
                    self.logger.info(f"Subscribed to {symbol} on {exchange} (key={instrument_key})")
                    return self._create_success_response(f"Subscribed to {symbol} on {exchange}")
                else:
                    # Clean up on failure
                    with self.lock:
                        self.subscriptions.pop(correlation_id, None)
                        # Clean up indexes
                        self._remove_from_indexes(correlation_id, instrument_key, token_info["token"])
                    return self._create_error_response(
                        "SUBSCRIBE_FAILED", f"Failed to subscribe to {symbol} on {exchange}"
                    )

            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                # Clean up on error
                with self.lock:
                    self.subscriptions.pop(correlation_id, None)
                    # Clean up indexes
                    self._remove_from_indexes(correlation_id, instrument_key, token_info["token"])
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

        # Return success response (subscription will be processed when connected)
        return self._create_success_response(
            f"Subscription requested for {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
        )

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict[str, Any]:
        """Unsubscribe from market data for a symbol/exchange"""
        try:
            if not self.ws_client or not self.event_loop:
                return self._create_error_response(
                    "NOT_INITIALIZED", "WebSocket client not initialized"
                )

            # Get token info
            token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
            if not token_info:
                return self._create_error_response(
                    "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
                )

            instrument_key = self._create_instrument_key(token_info)

            # Generate unique correlation ID like Angel does
            correlation_id = f"{symbol}_{exchange}_{mode}"

            # Check for subscription and determine if Upstox unsubscribe is needed
            should_unsubscribe_from_upstox = False
            with self.lock:
                if correlation_id not in self.subscriptions:
                    self.logger.info(f"Not subscribed to {symbol} on {exchange} with mode {mode}")
                    return self._create_success_response(
                        f"Not subscribed to {symbol} on {exchange}"
                    )

                # Remove subscription and indexes FIRST
                self.subscriptions.pop(correlation_id, None)
                self._remove_from_indexes(correlation_id, instrument_key, token_info["token"])

                # Check if OTHER subscriptions (different modes) still need this instrument.
                # Upstox unsubscribe is per-instrument (not per-mode), so we must NOT
                # unsubscribe from Upstox if other modes still reference this instrument.
                remaining = self._feed_key_index.get(instrument_key, set())
                if not remaining:
                    should_unsubscribe_from_upstox = True
                else:
                    self.logger.info(
                        f"Keeping Upstox subscription for {instrument_key}: "
                        f"{len(remaining)} other mode(s) still active"
                    )

            if should_unsubscribe_from_upstox:
                self.logger.info(f"Unsubscribing {instrument_key} from Upstox (no remaining modes)")
                future = asyncio.run_coroutine_threadsafe(
                    self.ws_client.unsubscribe([instrument_key]), self.event_loop
                )
                future.result(timeout=5)

            self.logger.info(f"Unsubscribed from {symbol} on {exchange} mode {mode}")
            return self._create_success_response(f"Unsubscribed from {symbol} on {exchange}")

        except Exception as e:
            self.logger.error(f"Unsubscribe error: {e}")
            return self._create_error_response("UNSUBSCRIBE_ERROR", str(e))

    def disconnect(self) -> None:
        """Disconnect from WebSocket and cleanup resources"""
        try:
            self.running = False
            self.connected = False
            self._reconnecting = False
            self._intentional_disconnect = False

            # Stop staleness monitor first
            self._stop_staleness_monitor()

            if self.ws_client and self.event_loop:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self.ws_client.disconnect(), self.event_loop
                    )
                    future.result(timeout=self.THREAD_JOIN_TIMEOUT)
                except Exception as e:
                    self.logger.warning(f"Error disconnecting WebSocket client: {e}")

            self._stop_event_loop()

            # Clear subscriptions and performance caches
            with self.lock:
                self.subscriptions.clear()
                self._instrument_key_cache.clear()
                self._last_data_time.clear()
                self._notified_stale.clear()
                # Clear feed key indexes
                self._feed_key_index.clear()
                self._token_index.clear()

            self.cleanup_zmq()
            self.logger.info("Disconnected from Upstox WebSocket")

        except Exception as e:
            self.logger.error(f"Disconnect error: {e}")
        finally:
            # Ensure flags are reset even if cleanup fails
            self.running = False
            self.connected = False

    def cleanup(self) -> None:
        """
        Clean up all resources including WebSocket connection and ZMQ resources.
        This method should be called before discarding the adapter instance.
        """
        try:
            # Set flags BEFORE disconnect to prevent _on_close from triggering reconnect
            self.running = False
            self._intentional_disconnect = True

            # Stop staleness monitor first
            self._stop_staleness_monitor()

            # Disconnect WebSocket if connected
            if self.ws_client:
                try:
                    if self.event_loop and self.event_loop.is_running():
                        future = asyncio.run_coroutine_threadsafe(
                            self.ws_client.disconnect(), self.event_loop
                        )
                        future.result(timeout=self.THREAD_JOIN_TIMEOUT)
                except Exception as ws_err:
                    self.logger.error(f"Error stopping WebSocket client during cleanup: {ws_err}")
                finally:
                    self.ws_client = None

            # Stop event loop
            self._stop_event_loop()

            # Reset adapter state and clear caches
            with self.lock:
                self.running = False
                self.connected = False
                self._reconnecting = False
                self._intentional_disconnect = False
                self.subscriptions.clear()
                self._instrument_key_cache.clear()
                self._last_data_time.clear()
                self._notified_stale.clear()
                # Clear feed key indexes
                self._feed_key_index.clear()
                self._token_index.clear()

            # Clean up ZMQ resources
            self.cleanup_zmq()

            self.logger.info("Upstox adapter cleaned up completely")

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            # Try one last time to clean up ZMQ resources
            try:
                self.cleanup_zmq()
            except Exception as zmq_err:
                self.logger.error(f"Error cleaning up ZMQ during final cleanup attempt: {zmq_err}")

    def __del__(self):
        """
        Destructor - ensures resources are released even when adapter is garbage collected.
        This is a safety net; callers should explicitly call disconnect() or cleanup().
        """
        try:
            self.cleanup()
        except Exception:
            # Can't use logger in __del__ reliably
            pass

    # Private helper methods
    def _get_auth_token(self, auth_data: dict[str, Any] | None, user_id: str) -> str | None:
        """Get authentication token from auth_data or database"""
        if auth_data and "auth_token" in auth_data:
            return auth_data["auth_token"]
        return get_auth_token(user_id)

    def _start_event_loop(self):
        """Start event loop in a separate thread"""
        if not self.event_loop or not self.ws_thread or not self.ws_thread.is_alive():
            self.event_loop = asyncio.new_event_loop()
            self.ws_thread = threading.Thread(target=self._run_event_loop, daemon=True)
            self.ws_thread.start()
            self.logger.info("Started event loop thread")

    def _run_event_loop(self):
        """Run the event loop in a separate thread"""
        if self.event_loop:
            asyncio.set_event_loop(self.event_loop)
            self.event_loop.run_forever()

    def _connect_websocket(self) -> bool:
        """Connect to WebSocket and return success status"""
        if not self.event_loop:
            return False

        future = asyncio.run_coroutine_threadsafe(self.ws_client.connect(), self.event_loop)
        return future.result(timeout=10)

    def _stop_event_loop(self):
        """Stop event loop and wait for thread to finish"""
        if self.event_loop:
            try:
                self.event_loop.call_soon_threadsafe(self.event_loop.stop)
            except Exception as e:
                self.logger.debug(f"Error stopping event loop: {e}")

        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=self.THREAD_JOIN_TIMEOUT)
            if self.ws_thread.is_alive():
                self.logger.warning("WebSocket thread did not terminate within timeout")
                # Don't clear event_loop/ws_thread if thread is still alive
                # to prevent _start_event_loop from spawning a new loop
                return
            else:
                self.ws_thread = None

        self.event_loop = None

    def _create_instrument_key(self, token_info: dict[str, Any]) -> str:
        """Create instrument key from token info"""
        token = token_info["token"]
        brexchange = token_info["brexchange"]

        # Remove duplicate exchange prefix if present
        if "|" in token:
            token = token.split("|")[-1]

        return f"{brexchange}|{token}"

    def _get_cached_token_info(self, symbol: str, exchange: str) -> tuple[dict, str] | None:
        """
        Get token info and instrument key with LRU caching.

        PERFORMANCE: Avoids repeated SymbolMapper database lookups for the same symbol.
        Uses LRU cache (maxsize=5000) to prevent unbounded memory growth.
        Cache is cleared on disconnect.

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE')

        Returns:
            Tuple of (token_info dict, instrument_key string) or None if not found
        """
        cache_key = (symbol, exchange)

        # Fast path: check LRU cache first
        cached_result = self._instrument_key_cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        # Slow path: lookup and cache
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return None

        instrument_key = self._create_instrument_key(token_info)
        result = (token_info, instrument_key)
        self._instrument_key_cache.put(cache_key, result)
        return result

    def _remove_from_indexes(self, correlation_id: str, instrument_key: str, token: str):
        """
        Remove a subscription from the feed key indexes.

        MUST be called with self.lock held.

        Args:
            correlation_id: The subscription correlation ID
            instrument_key: The instrument key to remove from index
            token: The token to remove from index
        """
        # Remove from feed key index
        if instrument_key in self._feed_key_index:
            self._feed_key_index[instrument_key].discard(correlation_id)
            if not self._feed_key_index[instrument_key]:
                del self._feed_key_index[instrument_key]

        # Remove from token index
        if token in self._token_index:
            self._token_index[token].discard(correlation_id)
            if not self._token_index[token]:
                del self._token_index[token]

    def _update_data_time(self, correlation_id: str) -> None:
        """
        Update last data received time for staleness tracking.

        Called on every incoming feed to track whether data is flowing.
        Does NOT throttle or drop any data - every tick is delivered.

        Args:
            correlation_id: Unique subscription identifier
        """
        self._last_data_time[correlation_id] = time.time()
        self._notified_stale.discard(correlation_id)

    def _start_staleness_monitor(self):
        """Start the staleness monitoring thread"""
        if self._staleness_monitor_thread and self._staleness_monitor_thread.is_alive():
            return  # Already running

        self._staleness_monitor_thread = threading.Thread(
            target=self._staleness_monitor_loop,
            daemon=True,
            name="upstox_staleness_monitor"
        )
        self._staleness_monitor_thread.start()
        self.logger.info("Staleness monitor started")

    def _stop_staleness_monitor(self):
        """Stop the staleness monitoring thread"""
        # Thread will exit when self.running becomes False
        if self._staleness_monitor_thread:
            self._staleness_monitor_thread.join(timeout=2.0)
            self._staleness_monitor_thread = None

    def _staleness_monitor_loop(self):
        """Monitor for stale data and notify clients / trigger reconnection"""
        while self.running:
            try:
                time.sleep(self._staleness_check_interval)

                if not self.running or not self.connected:
                    continue

                current_time = time.time()
                stale_symbols = []

                with self.lock:
                    for correlation_id, sub_info in self.subscriptions.items():
                        last_data = self._last_data_time.get(correlation_id)

                        # Skip if we haven't received any data yet (just subscribed)
                        if last_data is None:
                            continue

                        elapsed = current_time - last_data

                        if elapsed > self._staleness_threshold:
                            # Only notify once per stale period
                            if correlation_id not in self._notified_stale:
                                stale_symbols.append({
                                    "correlation_id": correlation_id,
                                    "symbol": sub_info["symbol"],
                                    "exchange": sub_info["exchange"],
                                    "mode": sub_info["mode"],
                                    "elapsed": elapsed
                                })
                                self._notified_stale.add(correlation_id)

                # Notify clients about stale data (outside lock)
                for stale_info in stale_symbols:
                    self._publish_stale_data_warning(stale_info)

                # If multiple symbols are stale, likely a connection issue - trigger reconnect
                if len(stale_symbols) >= 3 and not self._reconnecting:
                    self.logger.warning(
                        f"Multiple symbols ({len(stale_symbols)}) have stale data. "
                        "Triggering reconnection..."
                    )
                    self._trigger_reconnection()

            except Exception as e:
                self.logger.error(f"Error in staleness monitor: {e}")

    def _publish_stale_data_warning(self, stale_info: dict):
        """Publish a warning message about stale data to clients"""
        symbol = stale_info["symbol"]
        exchange = stale_info["exchange"]
        mode = stale_info["mode"]
        elapsed = stale_info["elapsed"]

        warning_data = {
            "type": "data_warning",
            "warning": "STALE_DATA",
            "symbol": symbol,
            "exchange": exchange,
            "message": f"No data received for {elapsed:.1f} seconds. Connection may be interrupted.",
            "last_update_seconds_ago": elapsed,
            "timestamp": int(time.time() * 1000)
        }

        # Create topic for this symbol
        mode_map = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}
        mode_str = mode_map.get(mode, "QUOTE")
        topic = f"{exchange}_{symbol}_{mode_str}"

        self.logger.warning(
            f"STALE DATA: {symbol}.{exchange} - no update for {elapsed:.1f}s"
        )

        # Publish warning via ZMQ so proxy can forward to clients
        self.publish_market_data(topic, warning_data)

    def _trigger_reconnection(self):
        """Trigger a WebSocket reconnection (thread-safe)"""
        # Use lock to prevent race condition between check and set
        with self._reconnect_lock:
            if self._reconnecting:
                return
            self._reconnecting = True

        self.logger.info("Triggering WebSocket reconnection due to stale data...")

        try:
            # Disconnect and reconnect via the event loop
            if self.ws_client and self.event_loop and self.event_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._async_reconnect(),
                    self.event_loop
                )
            else:
                self.logger.warning(
                    "Cannot reconnect: WebSocket client or event loop not available"
                )
                with self._reconnect_lock:
                    self._reconnecting = False
        except Exception as e:
            self.logger.error(f"Error triggering reconnection: {e}")
            with self._reconnect_lock:
                self._reconnecting = False

    async def _async_reconnect(self):
        """Async reconnection handler"""
        try:
            # Set flag under lock to ensure visibility across threads
            # Prevents _on_close from triggering _attempt_reconnect during
            # intentional disconnect-reconnect cycle
            with self._reconnect_lock:
                self._intentional_disconnect = True

            self.logger.info("Disconnecting WebSocket for reconnection...")
            if self.ws_client:
                await self.ws_client.disconnect()

            # Wait a moment before reconnecting
            await asyncio.sleep(2.0)

            self.logger.info("Reconnecting WebSocket...")
            if self.ws_client:
                success = await self.ws_client.connect()
                if success:
                    self.connected = True
                    self.logger.info("Reconnection successful")

                    # Clear stale tracking
                    self._notified_stale.clear()
                    self._last_data_time.clear()
                else:
                    self.logger.error("Reconnection failed")
                    self.connected = False
        except Exception as e:
            self.logger.error(f"Reconnection error: {e}")
        finally:
            self._intentional_disconnect = False
            with self._reconnect_lock:
                self._reconnecting = False

    def _get_upstox_mode(self, mode: int, depth_level: int) -> str:
        """Convert internal mode to Upstox mode string"""
        mode_map = {1: "ltpc", 2: "full", 3: "full"}
        return mode_map.get(mode, "ltpc")

    def _find_subscription_by_feed_key(self, feed_key: str) -> dict[str, Any] | None:
        """Find subscription info by matching the feed key to stored instrument_key"""
        with self.lock:
            self.logger.debug(f"Looking for feed_key: {feed_key}")
            self.logger.debug(f"Available subscriptions: {list(self.subscriptions.keys())}")

            # Check all subscriptions to find matching instrument_key
            for correlation_id, sub_info in self.subscriptions.items():
                self.logger.debug(
                    f"Checking {correlation_id}: instrument_key={sub_info.get('instrument_key')}"
                )
                if sub_info.get("instrument_key") == feed_key:
                    self.logger.info(
                        f"Found subscription match: {correlation_id} for feed_key: {feed_key}"
                    )
                    return sub_info

            # Fallback: Extract token and try to match
            if "|" in feed_key:
                token = feed_key.split("|")[-1]
                self.logger.debug(f"Trying token fallback with token: {token}")
                for correlation_id, sub_info in self.subscriptions.items():
                    if sub_info.get("token") == token:
                        self.logger.info(f"Found token match: {correlation_id} for token: {token}")
                        return sub_info

        self.logger.warning(f"No subscription found for feed key: {feed_key}")
        return None

    def _create_topic(self, exchange: str, symbol: str, mode: int) -> str:
        """Create ZMQ topic for publishing"""
        mode_map = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}
        mode_str = mode_map.get(mode, "QUOTE")
        return f"{exchange}_{symbol}_{mode_str}"

    # WebSocket event handlers
    async def _on_open(self):
        """Callback when WebSocket connection is opened"""
        self.logger.info("Upstox WebSocket connection opened")
        self.connected = True

        # Resubscribe to existing subscriptions on reconnection (Angel pattern)
        with self.lock:
            for correlation_id, sub in self.subscriptions.items():
                try:
                    instrument_key = sub["instrument_key"]
                    mode = sub["mode"]
                    depth_level = sub["depth_level"]

                    future = asyncio.run_coroutine_threadsafe(
                        self.ws_client.subscribe(
                            [instrument_key], self._get_upstox_mode(mode, depth_level)
                        ),
                        self.event_loop,
                    )

                    if future.result(timeout=5):
                        self.logger.info(f"Resubscribed to {sub['symbol']}.{sub['exchange']}")
                    else:
                        self.logger.warning(
                            f"Failed to resubscribe to {sub['symbol']}.{sub['exchange']}"
                        )

                except Exception as e:
                    self.logger.error(
                        f"Error resubscribing to {sub['symbol']}.{sub['exchange']}: {e}"
                    )

    async def _on_error(self, error: str):
        """Handle WebSocket errors"""
        self.logger.error(f"WebSocket error: {error}")
        self.connected = False

        # Only auto-reconnect if running and not an intentional disconnect
        if self.running and not self._intentional_disconnect:
            await self._attempt_reconnect()

    async def _on_close(self):
        """Handle WebSocket closure"""
        self.logger.info("WebSocket connection closed")
        self.connected = False

        # Only auto-reconnect if running and not an intentional disconnect
        # The _intentional_disconnect flag prevents double-reconnect when
        # _async_reconnect() triggers disconnect-then-reconnect cycle
        if self.running and not self._intentional_disconnect:
            await self._attempt_reconnect()

    async def _attempt_reconnect(self):
        """Attempt to reconnect WebSocket"""
        try:
            if not self.ws_client:
                self.logger.error("Cannot reconnect: WebSocket client not initialized")
                return

            self.logger.info("Attempting to reconnect...")
            success = await self.ws_client.connect()

            if success:
                self.connected = True
                self.logger.info("Reconnected successfully")

                # Resubscribe to all instruments
                for instrument_key, sub_info in self.subscriptions.items():
                    await self.ws_client.subscribe(
                        [instrument_key],
                        self._get_upstox_mode(sub_info["mode"], sub_info["depth_level"]),
                    )
            else:
                self.logger.error("Reconnection failed")

        except Exception as e:
            self.logger.error(f"Reconnection error: {e}")

    async def _on_market_data(self, data: dict[str, Any]):
        """Handle market data messages"""
        try:
            # Handle market info messages
            if data.get("type") == "market_info":
                self._handle_market_info(data)
                return

            # Process market data feeds
            feeds = data.get("feeds", {})
            if not feeds:
                return

            current_ts = data.get("currentTs", 0)

            for feed_key, feed_data in feeds.items():
                self._process_feed(feed_key, feed_data, current_ts)

        except Exception as e:
            self.logger.error(f"Market data handler error: {e}")

    def _handle_market_info(self, data: dict[str, Any]):
        """Handle market info messages"""
        if "marketInfo" in data:
            self.market_status = data["marketInfo"]
            if "segmentStatus" in self.market_status:
                self.logger.debug(f"Market status update: {self.market_status['segmentStatus']}")

    def _process_feed(self, feed_key: str, feed_data: dict[str, Any], current_ts: int):
        """Process individual feed data using O(1) index lookup"""
        try:
            # PERFORMANCE: O(1) lookup using feed key index (replaces O(n) loop)
            matching_subscriptions = []
            with self.lock:
                self.logger.debug(f"Looking for matches for feed_key: {feed_key}")

                # First try direct instrument_key match (O(1))
                correlation_ids = self._feed_key_index.get(feed_key, set())

                # Fallback: try token-based match if no direct match
                if not correlation_ids and "|" in feed_key:
                    token = feed_key.split("|")[-1]
                    correlation_ids = self._token_index.get(token, set())
                    # Also try full feed_key as token
                    if not correlation_ids:
                        correlation_ids = self._token_index.get(feed_key, set())

                # Build matching subscriptions list from correlation IDs
                for correlation_id in correlation_ids:
                    sub_info = self.subscriptions.get(correlation_id)
                    if sub_info:
                        matching_subscriptions.append((correlation_id, sub_info))

                self.logger.debug(
                    f"Found {len(matching_subscriptions)} matching subscriptions for {feed_key}"
                )

            if not matching_subscriptions:
                self.logger.warning(f"No subscription found for feed key: {feed_key}")
                return

            # Process data for each matching subscription (different modes)
            for correlation_id, sub_info in matching_subscriptions:
                symbol = sub_info["symbol"]
                exchange = sub_info["exchange"]
                mode = sub_info["mode"]
                token = sub_info["token"]

                # Update staleness tracking (every tick, no throttling)
                self._update_data_time(correlation_id)

                topic = self._create_topic(exchange, symbol, mode)
                market_data = self._extract_market_data(feed_data, sub_info, current_ts)

                if market_data:
                    self.logger.debug(f"Publishing data for {symbol} mode {mode} on topic: {topic}")
                    if mode == 2:  # Quote mode - show the complete data structure
                        self.logger.debug(f"QUOTE DATA: {market_data}")

                    if mode == 3:  # Depth mode
                        # For depth mode, structure the data properly with LTP at top level
                        depth_data = market_data.copy()
                        depth_levels = {
                            "buy": depth_data.pop("buy", []),
                            "sell": depth_data.pop("sell", []),
                            "timestamp": depth_data.get("timestamp", current_ts),
                        }
                        # Keep LTP and other data at top level, put depth levels in 'depth' key
                        depth_data["depth"] = depth_levels
                        self.publish_market_data(topic, depth_data)
                    else:
                        self.publish_market_data(topic, market_data)

        except Exception as e:
            self.logger.error(f"Error processing feed for {feed_key}: {e}")

    def _extract_market_data(
        self, feed_data: dict[str, Any], sub_info: dict[str, Any], current_ts: int
    ) -> dict[str, Any]:
        """Extract market data based on subscription mode"""
        mode = sub_info["mode"]
        symbol = sub_info["symbol"]
        exchange = sub_info["exchange"]
        token = sub_info["token"]

        base_data = {"symbol": symbol, "exchange": exchange, "token": token}

        if mode == 1:  # LTP mode
            return self._extract_ltp_data(feed_data, base_data)
        elif mode == 2:  # QUOTE mode
            return self._extract_quote_data(feed_data, base_data, current_ts)
        elif mode == 3:  # DEPTH mode
            depth_data = self._extract_depth_data(feed_data, current_ts)
            depth_data.update(base_data)
            return depth_data

        return {}

    def _extract_ltp_data(
        self, feed_data: dict[str, Any], base_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract LTP data from feed.

        Handles both Upstox data formats:
        - "ltpc" mode: top-level {"ltpc": {...}}
        - "full" mode: {"fullFeed": {"marketFF"|"indexFF": {"ltpc": {...}, ...}}}

        When both LTP and Quote/Depth subscriptions exist for the same symbol,
        Upstox upgrades to "full" mode. This method must read LTP from both formats.
        """
        market_data = base_data.copy()

        ltpc = None

        # Primary: top-level "ltpc" key (when subscribed in ltpc mode only)
        if "ltpc" in feed_data:
            ltpc = feed_data["ltpc"]
        # Fallback: extract from fullFeed (when Upstox upgraded to full mode)
        elif "fullFeed" in feed_data:
            full_feed = feed_data["fullFeed"]
            ff = full_feed.get("marketFF") or full_feed.get("indexFF", {})
            ltpc = ff.get("ltpc")
        # Fallback: extract from firstLevelWithGreeks (option_greeks mode)
        elif "firstLevelWithGreeks" in feed_data:
            ltpc = feed_data["firstLevelWithGreeks"].get("ltpc")

        if ltpc is not None:
            market_data.update(
                {
                    "ltp": float(ltpc.get("ltp", 0)),
                    "ltq": int(ltpc.get("ltq", 0)),
                    "ltt": int(ltpc.get("ltt", 0)),
                    "cp": float(ltpc.get("cp", 0)),
                }
            )
        else:
            # No LTPC data found - log and return empty to prevent publishing
            # a message without "ltp" that clients silently drop
            self.logger.warning(
                f"No LTPC data found for {base_data.get('symbol')}. "
                f"Feed keys: {list(feed_data.keys())}"
            )
            return {}

        return market_data

    def _extract_quote_data(
        self, feed_data: dict[str, Any], base_data: dict[str, Any], current_ts: int
    ) -> dict[str, Any]:
        """Extract QUOTE data from feed"""
        if "fullFeed" not in feed_data:
            return {}

        full_feed = feed_data["fullFeed"]
        ff = full_feed.get("marketFF") or full_feed.get("indexFF", {})

        # Log the full feed structure to understand available fields
        self.logger.debug(f"Full feed structure for quote extraction: {list(ff.keys())}")

        # Extract LTP and quantity data
        ltpc = ff.get("ltpc", {})
        ltp = ltpc.get("ltp", 0)
        ltq = ltpc.get("ltq", 0)  # Last traded quantity

        # Extract OHLC data
        ohlc_list = ff.get("marketOHLC", {}).get("ohlc", [])
        ohlc = next(
            (o for o in ohlc_list if o.get("interval") == "1d"), ohlc_list[0] if ohlc_list else {}
        )

        # Extract market level data - try different possible field names
        market_level = ff.get("marketLevel", {})
        self.logger.debug(
            f"Market level keys: {list(market_level.keys()) if market_level else 'None'}"
        )

        # Also check what's in OHLC
        self.logger.debug(f"OHLC keys: {list(ohlc.keys()) if ohlc else 'None'}")

        # Check if there are other sections with volume data
        if "marketStatus" in ff:
            self.logger.info(f"Market status keys: {list(ff['marketStatus'].keys())}")
        if "optionGreeks" in ff:
            self.logger.debug(f"Option Greeks keys: {list(ff['optionGreeks'].keys())}")

        # Extract volume from OHLC (confirmed working)
        volume = ohlc.get("vol", 0) if ohlc else 0

        # Extract average price from 'atp' field (Average Traded Price)
        avg_price = float(ff.get("atp", 0))

        # Extract buy/sell quantities from 'tbq' and 'tsq' fields
        total_buy_qty = int(ff.get("tbq", 0))  # Total Buy Quantity
        total_sell_qty = int(ff.get("tsq", 0))  # Total Sell Quantity

        self.logger.debug(
            f"Extracted values - volume: {volume}, atp: {avg_price}, tbq: {total_buy_qty}, tsq: {total_sell_qty}"
        )

        market_data = base_data.copy()
        market_data.update(
            {
                "open": float(ohlc.get("open", 0)),
                "high": float(ohlc.get("high", 0)),
                "low": float(ohlc.get("low", 0)),
                "close": float(ohlc.get("close", 0)),
                "ltp": float(ltp),
                "last_trade_quantity": int(ltq),
                "volume": int(volume),
                "average_price": float(avg_price),
                "total_buy_quantity": int(total_buy_qty),
                "total_sell_quantity": int(total_sell_qty),
                "timestamp": int(ohlc.get("ts", current_ts)),
            }
        )

        return market_data

    def _extract_depth_data(self, feed_data: dict[str, Any], current_ts: int) -> dict[str, Any]:
        """Extract depth data from feed"""
        if "fullFeed" not in feed_data:
            return {"buy": [], "sell": [], "timestamp": current_ts, "ltp": 0}

        full_feed = feed_data["fullFeed"]
        market_ff = full_feed.get("marketFF") or full_feed.get("indexFF", {})
        market_level = market_ff.get("marketLevel", {})
        bid_ask = market_level.get("bidAskQuote", [])

        # Extract LTP data from ltpc field
        ltpc = market_ff.get("ltpc", {})
        ltp = float(ltpc.get("ltp", 0))

        buy_levels = []
        sell_levels = []

        for level in bid_ask:
            # Process bids
            bid_price = float(level.get("bidP", 0))
            bid_qty = int(float(level.get("bidQ", 0)))
            if bid_price > 0:
                buy_levels.append({"price": bid_price, "quantity": bid_qty, "orders": 0})

            # Process asks
            ask_price = float(level.get("askP", 0))
            ask_qty = int(float(level.get("askQ", 0)))
            if ask_price > 0:
                sell_levels.append({"price": ask_price, "quantity": ask_qty, "orders": 0})

        # Sort and ensure minimum 5 levels
        buy_levels = sorted(buy_levels, key=lambda x: x["price"], reverse=True)
        sell_levels = sorted(sell_levels, key=lambda x: x["price"])

        buy_levels.extend([{"price": 0.0, "quantity": 0, "orders": 0}] * (5 - len(buy_levels)))
        sell_levels.extend([{"price": 0.0, "quantity": 0, "orders": 0}] * (5 - len(sell_levels)))

        return {
            "buy": buy_levels[:5],
            "sell": sell_levels[:5],
            "timestamp": current_ts,
            "ltp": ltp,  # Include LTP in the depth data
        }
