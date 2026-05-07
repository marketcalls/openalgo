import json
import logging
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import zmq

from database.auth_db import get_auth_token
from database.token_db import get_token

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

from .groww_mapping import GrowwCapabilityRegistry, GrowwExchangeMapper
from .nats_websocket import GrowwNATSWebSocket


class _GrowwMarketCache:
    """Per-token merge cache for Groww.

    Groww splits market data across two NATS topics: an LTP topic that
    carries `ltp/open/high/low/close/volume/ltt`, and a Depth topic that
    carries `buy[]/sell[]` book levels. Every other broker in OpenAlgo
    delivers a unified payload on every depth tick, so the rest of the
    pipeline (proxy, frontend) implicitly assumes a Depth-mode subscriber
    sees LTP for free.

    This cache is the broker-side reconciliation: each tick from either
    topic merges its fields into the per-token entry, and the adapter
    publishes the merged snapshot on every depth-mode publish. The result
    looks identical to what Zerodha/Angel/Dhan would have published
    natively in their full/depth mode.

    Keyed by (groww_exchange, segment, token).
    """

    _LTP_FIELDS = ("ltp", "open", "high", "low", "close", "volume", "ltt")

    def __init__(self):
        self._cache: dict[tuple[str, str, str], dict] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(groww_exchange, segment, token):
        return (str(groww_exchange or ""), str(segment or ""), str(token or ""))

    def update_from_ltp(self, groww_exchange, segment, token, normalized: dict) -> dict:
        """Merge ltp_data fields into cache; return a copy of the merged entry."""
        key = self._key(groww_exchange, segment, token)
        with self._lock:
            entry = self._cache.setdefault(key, {})
            for field in self._LTP_FIELDS:
                v = normalized.get(field)
                if v is not None:
                    entry[field] = v
            return dict(entry)

    def update_from_depth(self, groww_exchange, segment, token, normalized: dict) -> dict:
        """Merge depth_data into cache; return a copy of the merged entry."""
        key = self._key(groww_exchange, segment, token)
        with self._lock:
            entry = self._cache.setdefault(key, {})
            if "depth" in normalized:
                entry["depth"] = normalized["depth"]
            if "ltt" in normalized:
                entry["ltt"] = normalized["ltt"]
            return dict(entry)

    def snapshot(self, groww_exchange, segment, token) -> dict:
        with self._lock:
            return dict(self._cache.get(self._key(groww_exchange, segment, token), {}))

    def clear(self, groww_exchange=None, segment=None, token=None) -> None:
        with self._lock:
            if groww_exchange is None:
                self._cache.clear()
            else:
                self._cache.pop(self._key(groww_exchange, segment, token), None)


class GrowwWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Groww-specific implementation of the WebSocket adapter"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("groww_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "groww"
        self.running = False
        self.lock = threading.Lock()
        self.subscription_keys = {}  # Map correlation_id to subscription keys

        # Batch subscription management — hybrid leading+trailing-edge debounce
        # (mirrors shoonya_adapter). The FIRST call after a quiet window flushes
        # immediately so a single-symbol UI click pays ~0ms of adapter overhead.
        # Subsequent calls within `batch_delay` of the last flush wait it out so
        # bursts (e.g. /optionchain) coalesce into one batch SUB frame.
        self.subscription_queue = []  # list of pending subscribe specs
        self.batch_lock = threading.Lock()
        self.batch_timer = None
        self._last_batch_flush_at = 0.0
        self.batch_delay = 0.5  # 500ms debounce window

        # Per-token LTP/Depth merge cache. See _GrowwMarketCache docstring.
        self.market_cache = _GrowwMarketCache()
        # primary_correlation_id -> shadow_correlation_id (for depth subs that
        # spawn an internal LTP sub so the cache stays fed).
        self.shadow_correlation_ids: dict[str, str] = {}

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, str] | None = None
    ) -> None:
        """
        Initialize connection with Groww WebSocket API

        Args:
            broker_name: Name of the broker (always 'groww' in this case)
            user_id: Client ID/user ID
            auth_data: If provided, use these credentials instead of fetching from DB

        Raises:
            ValueError: If required authentication tokens are not found
        """
        self.user_id = user_id
        self.broker_name = broker_name

        # Get tokens from database if not provided
        if not auth_data:
            # Fetch authentication token from database
            auth_token = get_auth_token(user_id)

            if not auth_token:
                self.logger.error(f"No authentication token found for user {user_id}")
                raise ValueError(f"No authentication token found for user {user_id}")
        else:
            # Use provided token
            auth_token = auth_data.get("auth_token")

            if not auth_token:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data")

        # Create WebSocket client with callbacks
        self.ws_client = GrowwNATSWebSocket(
            auth_token=auth_token, on_data=self._on_data, on_error=self._on_error
        )

        self.running = True

    def connect(self) -> None:
        """Establish connection to Groww WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        try:
            self.logger.info("Connecting to Groww WebSocket")
            self.ws_client.connect()
            self.connected = True
            self.logger.info("Connected to Groww WebSocket successfully")

            # Snapshot existing subscriptions, replay them in one batch.
            with self.lock:
                existing = list(self.subscriptions.items())

            if existing:
                self._resubscribe_batch(existing)

        except Exception as e:
            self.logger.error(f"Failed to connect to Groww WebSocket: {e}")
            self.connected = False
            raise

    def unsubscribe_all(self) -> dict[str, Any]:
        """
        Unsubscribe from all active subscriptions with proper cleanup

        Returns:
            Dict: Response with status and details
        """
        try:
            if not self.subscriptions:
                return self._create_success_response("No active subscriptions to unsubscribe")

            unsubscribed_count = 0
            failed_count = 0
            unsubscribed_list = []
            failed_list = []

            self.logger.info(
                f"Unsubscribing from {len(self.subscriptions)} active subscriptions..."
            )

            # Create a copy of subscriptions to iterate over
            subscriptions_copy = self.subscriptions.copy()

            for correlation_id, sub_info in subscriptions_copy.items():
                try:
                    symbol = sub_info["symbol"]
                    exchange = sub_info["exchange"]
                    mode = sub_info["mode"]

                    # Unsubscribe from the symbol
                    response = self.unsubscribe(symbol, exchange, mode)

                    if response.get("status") == "success":
                        unsubscribed_count += 1
                        unsubscribed_list.append(
                            {"symbol": symbol, "exchange": exchange, "mode": mode}
                        )
                        self.logger.debug(f"Unsubscribed: {exchange}:{symbol} mode {mode}")
                    else:
                        failed_count += 1
                        failed_list.append(
                            {
                                "symbol": symbol,
                                "exchange": exchange,
                                "mode": mode,
                                "error": response.get("message", "Unknown error"),
                            }
                        )
                        self.logger.warning(
                            f"Failed to unsubscribe: {exchange}:{symbol} mode {mode}"
                        )

                except Exception as e:
                    failed_count += 1
                    failed_list.append({"correlation_id": correlation_id, "error": str(e)})
                    self.logger.error(f"Error unsubscribing from {correlation_id}: {e}")

            # Force clear all remaining subscriptions and keys
            self.subscriptions.clear()
            self.subscription_keys.clear()

            # Cancel any pending batch flush and drop queued specs
            if self.batch_timer:
                try:
                    self.batch_timer.cancel()
                except Exception:
                    pass
                self.batch_timer = None
            with self.batch_lock:
                self.subscription_queue.clear()

            self.logger.info("Calling disconnect() to terminate Groww connection...")
            try:
                self.disconnect()
                self.logger.info("Successfully disconnected from Groww server")
            except Exception as e:
                self.logger.error(f"Error during disconnect: {e}")
                # Force cleanup even if disconnect fails
                self.running = False
                self.connected = False
                if self.ws_client:
                    try:
                        self.ws_client.disconnect()
                    except Exception:
                        pass
                    self.ws_client = None
                self.cleanup_zmq()

            # Reset message counter for next session
            if hasattr(self, "_message_count"):
                self._message_count = 0

            self.logger.info(
                f"Unsubscribe all complete: {unsubscribed_count} success, {failed_count} failed"
            )

            return self._create_success_response(
                f"Unsubscribed from {unsubscribed_count} subscriptions and disconnected from server",
                total_processed=len(subscriptions_copy),
                successful_count=unsubscribed_count,
                failed_count=failed_count,
                successful=unsubscribed_list,
                failed=failed_list if failed_list else None,
                backend_cleared=True,
                server_disconnected=True,
                zmq_cleaned=True,
            )

        except Exception as e:
            self.logger.error(f"Error in unsubscribe_all: {e}")
            return self._create_error_response("UNSUBSCRIBE_ALL_ERROR", str(e))

    def disconnect(self) -> None:
        """Disconnect from Groww WebSocket with proper cleanup"""
        self.logger.info("Starting Groww adapter disconnect sequence...")
        self.running = False

        # Cancel any pending batch flush
        if self.batch_timer:
            try:
                self.batch_timer.cancel()
            except Exception:
                pass
            self.batch_timer = None
        with self.batch_lock:
            self.subscription_queue.clear()

        try:
            # Disconnect WebSocket client
            if self.ws_client:
                try:
                    self.ws_client.disconnect()
                    self.logger.debug("WebSocket client disconnected")
                except Exception as e:
                    self.logger.error(f"Error disconnecting WebSocket client: {e}")

            # Clear all state for clean reconnection
            self.connected = False
            self.ws_client = None
            self.subscriptions.clear()
            self.subscription_keys.clear()

            # Clean up ZeroMQ resources
            self.cleanup_zmq()

            self.logger.info("Groww adapter disconnected and state cleared")

        except Exception as e:
            self.logger.error(f"Error during disconnect: {e}")
            # Force cleanup even if there were errors
            self.connected = False
            self.ws_client = None
            self.subscriptions.clear()
            self.subscription_keys.clear()
            self.cleanup_zmq()

    def subscribe(
        self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5
    ) -> dict[str, Any]:
        """
        Subscribe to market data with Groww-specific implementation

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Depth
            depth_level: Market depth level (only 5 supported for Groww)

        Returns:
            Dict: Response with status and error message if applicable
        """
        # Validate the mode
        if mode not in [1, 2, 3]:
            return self._create_error_response(
                "INVALID_MODE", f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)"
            )

        # Groww only supports depth level 5
        if mode == 3 and depth_level != 5:
            self.logger.info(f"Groww only supports depth level 5, using 5 instead of {depth_level}")
            depth_level = 5

        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
            )

        token = token_info["token"]
        brexchange = token_info["brexchange"]

        # Get instrument type from database
        instrumenttype = None
        try:
            from database.symbol import SymToken

            sym = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
            if sym:
                instrumenttype = sym.instrumenttype
                self.logger.debug(
                    f"Retrieved instrumenttype: {instrumenttype} for {symbol}.{exchange}"
                )
        except Exception as e:
            self.logger.warning(f"Could not retrieve instrumenttype: {e}")

        # For indices, handle token mapping differently
        if "INDEX" in exchange.upper():
            if exchange == "NSE_INDEX":
                # NSE indices use symbol names as tokens (NIFTY, BANKNIFTY, etc.)
                self.logger.info(
                    f"NSE Index subscription detected, using symbol {symbol} as token instead of {token}"
                )
                token = symbol
            elif exchange == "BSE_INDEX":
                # BSE indices use numeric tokens (e.g., "14" for SENSEX)
                # Keep the original token from database
                self.logger.info(
                    f"BSE Index subscription detected, keeping numeric token {token} for {symbol}"
                )

        # Get exchange and segment for Groww
        groww_exchange, segment = GrowwExchangeMapper.get_exchange_segment(exchange)

        if exchange in ["NFO", "BFO"]:
            self.logger.debug(f"F&O Subscription: {symbol}, exchange={exchange}->{groww_exchange}, segment={segment}, token={token}")

        # Generate unique correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Store subscription for reconnection. instrumenttype is stored so the
        # index→LTP redirect in subscribe_batch picks the right path on a
        # reconnect-driven resubscribe.
        with self.lock:
            self.subscriptions[correlation_id] = {
                "symbol": symbol,
                "exchange": exchange,
                "groww_exchange": groww_exchange,
                "segment": segment,
                "brexchange": brexchange,
                "token": token,
                "mode": mode,
                "depth_level": depth_level,
                "instrumenttype": instrumenttype,
            }

        # Queue subscription for batch processing if connected
        if self.connected and self.ws_client:
            # Resolve depth->LTP redirect for indices upfront so subscription mode
            # used for data matching reflects what the server will actually send.
            sub_type = "ltp"
            if mode == 3:
                if instrumenttype == "INDEX" or "INDEX" in exchange:
                    self.logger.info(
                        f"Indices don't have depth data. Converting to LTP for {symbol}"
                    )
                    with self.lock:
                        self.subscriptions[correlation_id]["mode"] = 1  # for matching
                    sub_type = "ltp"
                else:
                    sub_type = "depth"
            elif mode == 2:
                self.logger.debug(
                    f"QUOTE subscription for {symbol} - Groww only provides LTP, OHLCV will be 0"
                )

            with self.batch_lock:
                self.subscription_queue.append(
                    {
                        "correlation_id": correlation_id,
                        "sub_type": sub_type,
                        "groww_exchange": groww_exchange,
                        "segment": segment,
                        "token": token,
                        "symbol": symbol,
                        "instrumenttype": instrumenttype,
                        "exchange": exchange,
                        "mode": mode,
                    }
                )

                # Auto-shadow LTP for non-index Depth subscriptions.
                # Groww's depth NATS topic carries no LTP/OHLC/volume — without
                # this shadow, Depth-mode clients would never see those fields.
                # The shadow uses a unique sub_key so its NATS SID doesn't
                # collide with a real LTP sub on the same token.
                if (
                    sub_type == "depth"
                    and instrumenttype != "INDEX"
                    and "INDEX" not in exchange.upper()
                ):
                    shadow_correlation_id = f"_shadow_ltp_{correlation_id}"
                    shadow_sub_key = f"_shadow_ltp_{correlation_id}"
                    self.shadow_correlation_ids[correlation_id] = shadow_correlation_id
                    # Track the shadow in self.subscriptions so reconnect-driven
                    # _resubscribe_batch replays it. is_shadow=True keeps it out
                    # of the _on_data fan-out.
                    with self.lock:
                        self.subscriptions[shadow_correlation_id] = {
                            "symbol": symbol,
                            "exchange": exchange,
                            "groww_exchange": groww_exchange,
                            "segment": segment,
                            "brexchange": brexchange,
                            "token": token,
                            "mode": 1,
                            "depth_level": 0,
                            "instrumenttype": instrumenttype,
                            "is_shadow": True,
                            "primary_correlation_id": correlation_id,
                        }
                    self.subscription_queue.append(
                        {
                            "correlation_id": shadow_correlation_id,
                            "sub_type": "ltp",
                            "groww_exchange": groww_exchange,
                            "segment": segment,
                            "token": token,
                            "symbol": symbol,
                            "instrumenttype": instrumenttype,
                            "exchange": exchange,
                            "mode": 1,
                            "sub_key_override": shadow_sub_key,
                        }
                    )
                    self.logger.debug(
                        f"Auto-shadow LTP for {symbol}.{exchange} (paired with depth sub)"
                    )

                flush_now = self._schedule_batch_flush_locked()

            if flush_now:
                # Outside the lock — _process_batch_subscriptions reacquires it.
                self._process_batch_subscriptions()

            mode_name = {1: "LTP", 2: "Quote", 3: "Depth"}.get(mode, str(mode))
            self.logger.info(
                f"Queued subscription for {symbol}.{exchange} in {mode_name} mode"
            )

        mode_name = {1: "LTP", 2: "Quote", 3: "Depth"}.get(mode, str(mode))
        return self._create_success_response(
            f"Successfully subscribed to {symbol}.{exchange} in {mode_name} mode",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            depth_level=depth_level,
        )

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict[str, Any]:
        """
        Unsubscribe from market data

        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Subscription mode

        Returns:
            Dict: Response with status
        """
        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Check if subscribed
        sub_info_for_cache: dict[str, Any] | None = None
        with self.lock:
            if correlation_id not in self.subscriptions:
                return self._create_error_response(
                    "NOT_SUBSCRIBED", f"Not subscribed to {symbol}.{exchange}"
                )

            # Capture cache key fields before removing
            sub_info_for_cache = dict(self.subscriptions[correlation_id])
            # Remove from subscriptions
            del self.subscriptions[correlation_id]

        # If this primary had a shadow LTP, remove that too. The shadow
        # exists only for depth-mode primaries.
        shadow_correlation_id = self.shadow_correlation_ids.pop(correlation_id, None)
        if shadow_correlation_id is not None:
            with self.lock:
                self.subscriptions.pop(shadow_correlation_id, None)

        # Take batch_lock to either drop a still-queued spec, or pop the
        # subscription key written by an in-flight flush. Holding this lock
        # serializes us against _process_batch_subscriptions, which is what
        # closes the unsubscribe-vs-in-flight race.
        sub_key = None
        shadow_sub_key = None
        with self.batch_lock:
            self.subscription_queue = [
                item
                for item in self.subscription_queue
                if item.get("correlation_id") not in (correlation_id, shadow_correlation_id)
            ]
            sub_key = self.subscription_keys.pop(correlation_id, None)
            if shadow_correlation_id is not None:
                shadow_sub_key = self.subscription_keys.pop(shadow_correlation_id, None)

        # Network I/O outside the lock
        if sub_key is not None and self.connected and self.ws_client:
            try:
                self.ws_client.unsubscribe(sub_key)
                self.logger.info(f"Unsubscribed from {symbol}.{exchange}")
            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")

        if shadow_sub_key is not None and self.connected and self.ws_client:
            try:
                self.ws_client.unsubscribe(shadow_sub_key)
                self.logger.debug(
                    f"Unsubscribed shadow LTP for {symbol}.{exchange}"
                )
            except Exception as e:
                self.logger.error(
                    f"Error unsubscribing shadow LTP for {symbol}.{exchange}: {e}"
                )

        # Clear the cache entry — only if no other sub still uses this token.
        if sub_info_for_cache:
            self._maybe_clear_cache_entry(sub_info_for_cache)

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}", symbol=symbol, exchange=exchange, mode=mode
        )

    def _maybe_clear_cache_entry(self, sub_info: dict) -> None:
        """Drop the merge cache entry for this token if no live subscription
        still references it. Walks self.subscriptions under self.lock."""
        groww_exch = sub_info.get("groww_exchange")
        segment = sub_info.get("segment")
        token = sub_info.get("token")
        if groww_exch is None or token is None:
            return
        with self.lock:
            for sub in self.subscriptions.values():
                if (
                    sub.get("groww_exchange") == groww_exch
                    and sub.get("segment") == segment
                    and str(sub.get("token")) == str(token)
                ):
                    return  # still in use
        self.market_cache.clear(groww_exch, segment, token)

    def _schedule_batch_flush_locked(self) -> bool:
        """Decide whether to flush the subscribe queue now (leading edge) or
        schedule a timer for the end of the current debounce window.
        Caller must hold ``self.batch_lock``. Returns True if the caller
        should call ``_process_batch_subscriptions`` synchronously after
        releasing the lock.
        """
        elapsed = time.time() - self._last_batch_flush_at
        if elapsed >= self.batch_delay:
            # Quiet window — flush immediately. Mark the time now so any
            # racing call within batch_delay schedules a timer instead.
            self._last_batch_flush_at = time.time()
            if self.batch_timer:
                try:
                    self.batch_timer.cancel()
                except Exception:
                    pass
                self.batch_timer = None
            return True

        # In the debounce window — ensure a timer is scheduled to flush
        # at the end of it. Don't restart an already-running timer (that
        # would push the deadline back indefinitely under sustained load).
        if self.batch_timer is None:
            delay = max(0.0, self.batch_delay - elapsed)
            self.batch_timer = threading.Timer(delay, self._process_batch_subscriptions)
            self.batch_timer.daemon = True
            self.batch_timer.start()
        return False

    def _process_batch_subscriptions(self):
        """Drain the subscription queue and submit it as a single batch.

        The whole flush — drain, WS network call, ``subscription_keys`` write —
        runs under ``batch_lock``. That gives ``unsubscribe()`` two clean cases
        (acquired before the flush → spec still in queue, drop it; acquired
        after → ``subscription_keys`` already populated, send WS UNSUB) instead
        of a window where the spec is "in flight" with no key yet written.
        """
        with self.batch_lock:
            self.batch_timer = None
            if not self.subscription_queue:
                return
            queue = list(self.subscription_queue)
            self.subscription_queue.clear()
            self._last_batch_flush_at = time.time()

            if not self.connected or not self.ws_client:
                self.logger.warning(
                    f"Skipping batch flush of {len(queue)} subscriptions - not connected"
                )
                return

            try:
                batch_specs = []
                for item in queue:
                    spec = {
                        "type": item["sub_type"],
                        # Broker-side exchange (NSE/BSE) — used by topic gen.
                        "exchange": item["groww_exchange"],
                        # OpenAlgo-facing exchange (NFO/BFO/NSE_INDEX/...) —
                        # used by the WS dispatcher to set data["exchange"]
                        # so the adapter's match loop sees the same string
                        # the user subscribed with.
                        "openalgo_exchange": item["exchange"],
                        "segment": item["segment"],
                        "token": item["token"],
                        "symbol": item["symbol"],
                        "instrumenttype": item["instrumenttype"],
                    }
                    # sub_key_override is set for shadow LTP specs so they
                    # don't collide with a real LTP sub on the same token.
                    if item.get("sub_key_override"):
                        spec["sub_key"] = item["sub_key_override"]
                    batch_specs.append(spec)

                self.logger.info(f"📦 Batch subscribing {len(batch_specs)} symbols")
                sub_keys = self.ws_client.subscribe_batch(batch_specs)

                for item, sub_key in zip(queue, sub_keys):
                    self.subscription_keys[item["correlation_id"]] = sub_key

                    if item["exchange"] in ["NFO", "BFO"]:
                        self.logger.debug(
                            f"F&O subscription key created: {sub_key}"
                        )
            except Exception as e:
                self.logger.error(f"Batch subscription failed: {e}", exc_info=True)

    def _resubscribe_batch(self, existing: list) -> None:
        """Replay all known subscriptions to the WS in a single batch flush.

        Mirrors _process_batch_subscriptions: holds batch_lock across the WS
        round-trip and the subscription_keys writes, so a concurrent
        unsubscribe() observes a consistent state.
        """
        if not self.connected or not self.ws_client:
            return

        batch_specs: list[dict] = []
        correlation_ids: list[str] = []
        for correlation_id, sub_info in existing:
            mode = sub_info.get("mode")
            sub_type = "depth" if mode == 3 else "ltp"
            spec = {
                "type": sub_type,
                "exchange": sub_info["groww_exchange"],
                "openalgo_exchange": sub_info["exchange"],
                "segment": sub_info["segment"],
                "token": sub_info["token"],
                "symbol": sub_info["symbol"],
                "instrumenttype": sub_info.get("instrumenttype"),
            }
            # Shadow LTP subs replay with the same unique sub_key so they
            # don't collide with a real LTP sub on the same token after
            # reconnect. correlation_id `_shadow_ltp_<...>` is stable.
            if sub_info.get("is_shadow"):
                spec["sub_key"] = correlation_id
            batch_specs.append(spec)
            correlation_ids.append(correlation_id)

        if not batch_specs:
            return

        try:
            self.logger.info(
                f"📦 Reconnect: batch resubscribing {len(batch_specs)} symbols"
            )
            with self.batch_lock:
                sub_keys = self.ws_client.subscribe_batch(batch_specs)
                for cid, sub_key in zip(correlation_ids, sub_keys):
                    self.subscription_keys[cid] = sub_key
                self._last_batch_flush_at = time.time()
        except Exception as e:
            self.logger.error(f"Error in batch resubscribe: {e}", exc_info=True)

    def _on_data(self, data: dict[str, Any]) -> None:
        """Callback for market data from WebSocket"""
        try:
            self.logger.debug(f"RAW GROWW DATA: Type: {type(data)}, Data: {data}")

            # Add data validation to ensure we have the minimum required fields
            if not isinstance(data, dict):
                self.logger.error(f"Invalid data type received: {type(data)}")
                return

            # Ensure we have either market data or subscription info
            has_market_data = any(key in data for key in ["ltp_data", "depth_data", "index_data"])
            has_subscription_info = all(key in data for key in ["symbol", "exchange"])

            if not (has_market_data or has_subscription_info):
                self.logger.warning(
                    f"Received data without market data or subscription info: {data}"
                )
                return

            # Collect matching primary subscriptions (shadows skipped). One
            # tick can fan out to multiple primaries when an LTP tick lands
            # for a token that has both LTP/Quote and Depth subs active.
            matches: list[tuple[str, dict]] = []

            # Data from NATS will have symbol, exchange, and mode fields
            if "symbol" in data and "exchange" in data:
                # This is from our NATS implementation
                symbol_from_data = data["symbol"]  # This contains the actual symbol name now
                exchange = data["exchange"]
                mode = data.get("mode", "ltp")

                # Handle both numeric and string mode values
                if isinstance(mode, int):
                    # Convert numeric mode to string
                    mode = {1: "ltp", 2: "quote", 3: "depth"}.get(mode, "ltp")
                elif isinstance(mode, str) and mode.isdigit():
                    # Convert string numeric to string mode
                    mode = {1: "ltp", 2: "quote", 3: "depth"}.get(int(mode), "ltp")

                if "BSE" in exchange and mode == "depth":
                    self.logger.debug("BSE DEPTH: Looking for subscription")

                self.logger.debug(
                    f"Looking for subscription: symbol={symbol_from_data}, exchange={exchange}, mode={mode}"
                )
                self.logger.debug(f"Available subscriptions: {list(self.subscriptions.keys())}")

                # Find matching subscription(s) based on symbol, exchange, mode.
                # Multiple matches per tick are possible: an LTP tick can fan
                # out to BOTH a primary LTP/Quote sub and a primary Depth sub
                # for the same symbol (the depth sub uses the LTP via the
                # merge cache). Shadow subs are skipped — they exist only to
                # keep the LTP NATS topic subscribed.
                with self.lock:
                    for cid, sub in self.subscriptions.items():
                        if sub.get("is_shadow"):
                            continue

                        self.logger.debug(
                            f"Checking {cid}: symbol={sub.get('symbol')}, exchange={sub.get('exchange')}, groww_exchange={sub.get('groww_exchange')}, mode={sub.get('mode')}"
                        )

                        # For index subscriptions, the OpenAlgo exchange is NSE_INDEX/BSE_INDEX but Groww sends NSE/BSE
                        is_index_match = (
                            (mode == "index" or mode == "index_depth")
                            and (
                                (sub["exchange"] == "NSE_INDEX" and exchange == "NSE")
                                or (sub["exchange"] == "BSE_INDEX" and exchange == "BSE")
                            )
                            and sub["symbol"] == symbol_from_data
                        )

                        # Regular match — note that an LTP tick now matches
                        # depth-mode subs too (sub.mode in [1,2,3]) so the
                        # cache stays fed for the merged-payload publish.
                        is_regular_match = (
                            sub["symbol"] == symbol_from_data
                            and sub["exchange"] == exchange
                            and (
                                (mode == "ltp" and sub["mode"] in [1, 2, 3])
                                or (mode == "depth" and sub["mode"] == 3)
                                or (mode == "index" and sub["mode"] in [1, 2])
                                or (mode == "index_depth" and sub["mode"] == 3)
                            )
                        )

                        if is_index_match or is_regular_match:
                            matches.append((cid, sub))
                            self.logger.debug(f"Matched subscription: {cid}")

            # Token-based fallback path (non-NATS legacy callers).
            # Build a single-match `matches` list so the publish loop below
            # handles both code paths uniformly.
            elif "exchange_token" in data or "token" in data:
                token = data.get("exchange_token") or data.get("token")
                segment = data.get("segment", "CASH")
                exchange = data.get("exchange", "NSE")

                self.logger.debug(
                    f"Processing message with token: {token}, segment: {segment}, exchange: {exchange}"
                )

                with self.lock:
                    for cid, sub in self.subscriptions.items():
                        if sub.get("is_shadow"):
                            continue
                        if (
                            str(sub["token"]) == str(token)
                            and sub["segment"] == segment
                            and sub["groww_exchange"] == exchange
                        ):
                            matches.append((cid, sub))
                            break

            if not matches:
                self.logger.debug(f"Received data for unsubscribed token/symbol: {data}")
                return

            # Determine the tick type from the data shape — independent of
            # any specific match's subscription mode, since one tick can fan
            # out to multiple matches with different modes.
            if "ltp_data" in data:
                tick_kind = 1  # LTP/Quote-shaped tick
            elif "depth_data" in data:
                tick_kind = 3  # Depth-shaped tick
            elif "index_data" in data:
                tick_kind = 1  # Treat index ticks as LTP-shaped
            else:
                tick_kind = 1  # default — same as before

            # Normalize once for this tick. For ltp_data ticks we use mode=2
            # (Quote) so the normalizer keeps OHLC/volume — the cache needs
            # them to build a complete merged payload for depth-mode subs.
            # The mode arg only affects the ltp_data branch of the normalizer.
            if tick_kind == 1:
                normalized = self._normalize_market_data(data, 2)
            else:
                normalized = self._normalize_market_data(data, tick_kind)

            # Update the per-token merge cache. The cache key is
            # (groww_exchange, segment, token) — consistent across all
            # matches for the same instrument.
            sample_sub = matches[0][1]
            cache_groww_exch = sample_sub.get("groww_exchange")
            cache_segment = sample_sub.get("segment")
            cache_token = sample_sub.get("token")
            if tick_kind == 3:
                merged = self.market_cache.update_from_depth(
                    cache_groww_exch, cache_segment, cache_token, normalized
                )
            else:
                merged = self.market_cache.update_from_ltp(
                    cache_groww_exch, cache_segment, cache_token, normalized
                )

            # Track message count for periodic logging
            if not hasattr(self, "_message_count"):
                self._message_count = 0
            self._message_count += 1

            # Publish per match — each user subscription gets its own topic
            # and an appropriately shaped payload. Depth-mode users always
            # see the merged snapshot (LTP+OHLC+volume+depth); LTP/Quote-mode
            # users see the raw normalized LTP fields.
            for cid, subscription in matches:
                sub_symbol = subscription["symbol"]
                sub_exchange = subscription["exchange"]
                sub_mode = subscription["mode"]

                if sub_mode == 3:
                    # Depth user — always publish merged snapshot, regardless
                    # of which topic this tick came from. Merged contains the
                    # latest LTP/OHLC/volume from the most recent LTP tick
                    # PLUS the latest depth from the most recent Depth tick.
                    if not merged:
                        # Cache empty — nothing useful to publish yet.
                        continue
                    market_data = dict(merged)
                    actual_mode = 3
                elif sub_mode in (1, 2):
                    # LTP/Quote user — only LTP-shaped ticks apply. Skip
                    # depth ticks (they don't add anything for these subs).
                    if tick_kind == 3:
                        continue
                    market_data = dict(normalized)
                    actual_mode = sub_mode
                else:
                    continue

                mode_str = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}[actual_mode]
                topic = f"{sub_exchange}_{sub_symbol}_{mode_str}"

                market_data.update(
                    {
                        "symbol": sub_symbol,
                        "exchange": sub_exchange,
                        "mode": actual_mode,
                        "timestamp": int(time.time() * 1000),
                        "broker": "groww",
                        "topic": topic,
                        "subscription_mode": sub_mode,
                    }
                )

                # Mode-specific guarantees, lifted from the previous single-
                # publish block.
                if actual_mode == 1:
                    if "ltt" not in market_data:
                        market_data["ltt"] = int(time.time() * 1000)
                    self.logger.debug(
                        f"LTP MODE: {sub_exchange}:{sub_symbol} = {market_data.get('ltp')} at {market_data.get('ltt')}"
                    )
                elif actual_mode == 2:
                    quote_fields = ["open", "high", "low", "close", "volume", "ltp"]
                    for field in quote_fields:
                        if field not in market_data:
                            market_data[field] = 0.0 if field != "volume" else 0
                    self.logger.debug(
                        f"QUOTE MODE: {sub_exchange}:{sub_symbol} = {market_data.get('ltp')} (Vol: {market_data.get('volume', 0)})"
                    )
                elif actual_mode == 3:
                    if "depth" not in market_data:
                        market_data["depth"] = {"buy": [], "sell": []}
                        self.logger.warning(
                            f"No depth data for {sub_symbol}, creating empty structure"
                        )
                    buy_levels = market_data["depth"].get("buy", [])
                    sell_levels = market_data["depth"].get("sell", [])

                    # Lift top-of-book into flat top-level fields so consumers
                    # that don't unpack the depth array (option chain merger
                    # via bid_price fallback, snapshot endpoint, WebSocketTest
                    # UI) still see populated bid/ask/qty. Only emit fields
                    # that have real values — leaving them absent lets
                    # downstream `??` fallbacks retain previous good values
                    # instead of overwriting with 0.
                    if buy_levels:
                        top_bid = buy_levels[0]
                        bid_price = top_bid.get("price")
                        bid_qty = top_bid.get("quantity")
                        if bid_price:
                            market_data["bid"] = bid_price
                            market_data["bid_price"] = bid_price
                        if bid_qty:
                            market_data["bid_qty"] = bid_qty
                            market_data["bid_size"] = bid_qty
                            market_data["bid_quantity"] = bid_qty
                    if sell_levels:
                        top_ask = sell_levels[0]
                        ask_price = top_ask.get("price")
                        ask_qty = top_ask.get("quantity")
                        if ask_price:
                            market_data["ask"] = ask_price
                            market_data["ask_price"] = ask_price
                            market_data["offer_price"] = ask_price
                        if ask_qty:
                            market_data["ask_qty"] = ask_qty
                            market_data["ask_size"] = ask_qty
                            market_data["ask_quantity"] = ask_qty
                            market_data["offer_quantity"] = ask_qty

                    self.logger.debug(
                        f"DEPTH MODE: {sub_exchange}:{sub_symbol} = {len(buy_levels)}B/{len(sell_levels)}S levels (merged with LTP={market_data.get('ltp', 'N/A')}, bid={market_data.get('bid', 'N/A')}, ask={market_data.get('ask', 'N/A')})"
                    )

                if self._message_count == 1 or self._message_count % 500 == 0:
                    ltp_info = (
                        f"LTP: {market_data.get('ltp', 'N/A')}"
                        if actual_mode in [1, 2]
                        else f"Depth: {len(market_data.get('depth', {}).get('buy', []))}B/{len(market_data.get('depth', {}).get('sell', []))}S, LTP: {market_data.get('ltp', 'N/A')}"
                    )
                    self.logger.info(
                        f"Publishing #{self._message_count}: {topic} ({mode_str}) -> {ltp_info}"
                    )

                self.publish_market_data(topic, market_data)
                self.logger.debug(f"ZMQ Published: {topic}")

        except Exception as e:
            self.logger.error(f"Error processing market data: {e}", exc_info=True)

    def _on_error(self, error: str) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"Groww WebSocket error: {error}")

    def _normalize_market_data(self, message: dict, mode: int) -> dict[str, Any]:
        """
        Normalize Groww data format to a common format

        Args:
            message: The raw message from Groww
            mode: Subscription mode

        Returns:
            Dict: Normalized market data
        """
        # Handle data from our NATS/protobuf parser
        if "ltp_data" in message:
            # This is parsed protobuf data from our NATS implementation
            ltp_data = message["ltp_data"]

            if mode == 1:  # LTP mode
                return {
                    "ltp": ltp_data.get("ltp", 0),
                    "ltt": ltp_data.get("timestamp", int(time.time() * 1000)),
                }
            elif mode == 2:  # Quote mode
                # Groww doesn't provide proper quote data, only LTP
                # Only include fields that have actual data
                quote_data = {
                    "ltp": ltp_data.get("ltp", 0),
                    "ltt": ltp_data.get("timestamp", int(time.time() * 1000)),
                }

                # Only add OHLCV fields if they have non-zero values from Groww
                # (Groww sometimes sends these as 0, we don't include them)
                if ltp_data.get("open") and ltp_data.get("open") != 0:
                    quote_data["open"] = ltp_data.get("open")
                if ltp_data.get("high") and ltp_data.get("high") != 0:
                    quote_data["high"] = ltp_data.get("high")
                if ltp_data.get("low") and ltp_data.get("low") != 0:
                    quote_data["low"] = ltp_data.get("low")
                if ltp_data.get("close") and ltp_data.get("close") != 0:
                    quote_data["close"] = ltp_data.get("close")
                if ltp_data.get("volume") and ltp_data.get("volume") != 0:
                    quote_data["volume"] = ltp_data.get("volume")
                if ltp_data.get("value") and ltp_data.get("value") != 0:
                    quote_data["value"] = ltp_data.get("value")

                return quote_data
            else:
                # Fallback for other modes
                return {
                    "ltp": ltp_data.get("ltp", 0),
                    "ltt": ltp_data.get("timestamp", int(time.time() * 1000)),
                    "open": ltp_data.get("open", 0),
                    "high": ltp_data.get("high", 0),
                    "low": ltp_data.get("low", 0),
                    "close": ltp_data.get("close", 0),
                    "volume": ltp_data.get("volume", 0),
                }

        # Handle depth data from protobuf.
        #
        # Groww splits LTP/OHLC/volume (LTP topic) and bid/ask depth (Depth
        # topic) into separate NATS feeds, so a depth tick legitimately
        # carries no LTP/OHLC/volume. We deliberately omit those keys from
        # the published payload — emitting them as 0 here would clobber the
        # last good values cached downstream (frontend MarketDataManager,
        # WebSocket proxy, option chain merger), since their `??` fallbacks
        # only catch null/undefined.
        #
        # Same logic for empty depth levels: Groww pads buy/sell with
        # placeholder `{price:0, quantity:0}` entries when fewer than 5
        # levels exist. Filtering them out lets the frontend see
        # `depth.buy[0]` as undefined and fall back to its previous bid via
        # `??`, instead of overwriting it with 0.
        if "depth_data" in message:
            depth_data = message["depth_data"]
            result = {
                "ltt": depth_data.get("timestamp", int(time.time() * 1000)),
            }

            def _is_real_level(lvl: dict) -> bool:
                return lvl.get("price", 0) > 0 or lvl.get("quantity", 0) > 0

            result["depth"] = {
                "buy": [lvl for lvl in depth_data.get("buy", [])[:5] if _is_real_level(lvl)],
                "sell": [lvl for lvl in depth_data.get("sell", [])[:5] if _is_real_level(lvl)],
            }

            return result

        # Handle index data from protobuf
        if "index_data" in message:
            index_data = message["index_data"]
            return {
                "ltp": index_data.get("value", 0),
                "ltt": index_data.get("timestamp", int(time.time() * 1000)),
            }

        # Handle legacy formats
        # Check if it's LTP data
        if "ltp" in message:
            ltp_data = message.get("ltp", {})

            # Extract values from nested structure if present
            if isinstance(ltp_data, dict):
                # Format: {"NSE": {"CASH": {"token": {"tsInMillis": ..., "ltp": ...}}}}
                for exchange_data in ltp_data.values():
                    if isinstance(exchange_data, dict):
                        for segment_data in exchange_data.values():
                            if isinstance(segment_data, dict):
                                for token_data in segment_data.values():
                                    if isinstance(token_data, dict):
                                        return {
                                            "ltp": token_data.get("ltp", 0),
                                            "ltt": token_data.get(
                                                "tsInMillis", int(time.time() * 1000)
                                            ),
                                        }
            else:
                # Direct format
                return {"ltp": ltp_data, "ltt": message.get("tsInMillis", int(time.time() * 1000))}

        # Check if it's depth/market depth data
        if "buyBook" in message or "sellBook" in message:
            result = {
                "ltp": message.get("ltp", 0),
                "ltt": message.get("tsInMillis", int(time.time() * 1000)),
                "depth": {"buy": [], "sell": []},
            }

            # Extract buy book
            buy_book = message.get("buyBook", {})
            for i in range(1, 6):  # Groww uses 1-5 indexing
                level = buy_book.get(str(i), {})
                result["depth"]["buy"].append(
                    {
                        "price": level.get("price", 0),
                        "quantity": level.get("qty", 0),
                        "orders": level.get("orders", 0),
                    }
                )

            # Extract sell book
            sell_book = message.get("sellBook", {})
            for i in range(1, 6):  # Groww uses 1-5 indexing
                level = sell_book.get(str(i), {})
                result["depth"]["sell"].append(
                    {
                        "price": level.get("price", 0),
                        "quantity": level.get("qty", 0),
                        "orders": level.get("orders", 0),
                    }
                )

            return result

        # Default format for quote/other data
        return {
            "ltp": message.get("ltp", message.get("last_price", 0)),
            "ltt": message.get("tsInMillis", message.get("timestamp", int(time.time() * 1000))),
            "volume": message.get("volume", 0),
            "open": message.get("open", 0),
            "high": message.get("high", 0),
            "low": message.get("low", 0),
            "close": message.get("close", 0),
        }
