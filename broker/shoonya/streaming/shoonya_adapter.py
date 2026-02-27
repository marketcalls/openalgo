"""
Shoonya WebSocket Adapter for OpenAlgo
Handles market data streaming from Shoonya broker
"""

import json
import logging
import os
import sys
import threading
import time
import uuid
from typing import Any

from database.auth_db import get_auth_token

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

from .shoonya_mapping import ShoonyaExchangeMapper
from .shoonya_websocket import ShoonyaWebSocket


# Configuration constants
class Config:
    MAX_RECONNECT_ATTEMPTS = 10
    BASE_RECONNECT_DELAY = 5
    MAX_RECONNECT_DELAY = 60
    CACHE_COMPLETENESS_THRESHOLD = 0.3
    WEBSOCKET_TIMEOUT = 30

    # Market data modes
    MODE_LTP = 1
    MODE_QUOTE = 2
    MODE_DEPTH = 3

    # Message types
    MSG_AUTH = "ck"
    MSG_TOUCHLINE_FULL = "tf"
    MSG_TOUCHLINE_PARTIAL = "tk"
    MSG_DEPTH_FULL = "df"
    MSG_DEPTH_PARTIAL = "dk"


class MarketDataCache:
    """Manages market data caching with thread safety"""

    def __init__(self):
        self._cache = {}
        self._initialized_tokens = set()
        self._lock = threading.Lock()
        self.logger = logging.getLogger("market_cache")

    def get(self, token: str) -> dict[str, Any]:
        """Get cached data for a token"""
        with self._lock:
            return self._cache.get(token, {}).copy()

    def update(self, token: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update cache with new data and return merged result"""
        with self._lock:
            cached_data = self._cache.get(token, {})
            merged_data = self._merge_data(cached_data, data, token)
            self._cache[token] = merged_data

            if token not in self._initialized_tokens:
                self._initialized_tokens.add(token)
                self._log_cache_initialization(token, data)

            return merged_data.copy()

    def clear(self, token: str = None) -> None:
        """Clear cache for specific token or all tokens"""
        with self._lock:
            if token:
                self._cache.pop(token, None)
                self._initialized_tokens.discard(token)
                self.logger.info(f"Cleared cache for token {token}")
            else:
                cache_size = len(self._cache)
                self._cache.clear()
                self._initialized_tokens.clear()
                self.logger.info(f"Cleared all cached market data ({cache_size} tokens)")

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            return {
                "total_tokens": len(self._cache),
                "initialized_tokens": len(self._initialized_tokens),
                "tokens": list(self._cache.keys()),
            }

    # L3 fix: Removed unused depth_prices, depth_quantities, depth_orders variables
    def _merge_data(self, cached: dict, new: dict, token: str) -> dict:
        """Smart merge logic for market data"""
        merged = cached.copy()

        for key, value in new.items():
            if self._should_preserve_cached_value(key, value, cached):
                continue
            merged[key] = value

        return merged

    def _should_preserve_cached_value(self, key: str, new_value: Any, cached: dict) -> bool:
        """Determine if cached value should be preserved over new value"""
        # Preserve non-zero OHLC values when new value is zero
        if key in ["o", "h", "l", "c", "ap"] and self._is_zero_value(new_value):
            cached_value = cached.get(key)
            return cached_value is not None and not self._is_zero_value(cached_value)
        return False

    def _is_zero_value(self, value: Any) -> bool:
        """Check if value represents zero"""
        return value in [None, "", "0", 0, "0.0", 0.0]

    def _log_cache_initialization(self, token: str, data: dict) -> None:
        """Log cache initialization details"""
        basic_fields = ["lp", "o", "h", "l", "c", "v", "ap", "pc", "ltq", "ltt", "tbq", "tsq"]
        present_fields = sum(1 for field in basic_fields if field in data)
        completeness = present_fields / len(basic_fields)

        self.logger.info(
            f"Initializing cache for token {token} - "
            f"{present_fields}/{len(basic_fields)} fields present ({completeness:.1%})"
        )


class LTPNormalizer:
    """Handles LTP mode data normalization"""

    @staticmethod
    def normalize(data: dict[str, Any], msg_type: str) -> dict[str, Any]:
        return {
            "mode": Config.MODE_LTP,
            "ltp": safe_float(data.get("lp")),
            # SA-R7-6 fix: Include last_trade_time for consistency with Quote/Depth
            "last_trade_time": data.get("ltt"),
            "shoonya_timestamp": safe_int(data.get("ft")),
        }


class QuoteNormalizer:
    """Handles Quote mode data normalization"""

    @staticmethod
    def normalize(data: dict[str, Any], msg_type: str) -> dict[str, Any]:
        return {
            "mode": Config.MODE_QUOTE,
            "ltp": safe_float(data.get("lp")),
            "volume": safe_int(data.get("v")),
            "open": safe_float(data.get("o")),
            "high": safe_float(data.get("h")),
            "low": safe_float(data.get("l")),
            "close": safe_float(data.get("c")),
            "average_price": safe_float(data.get("ap")),
            "percent_change": safe_float(data.get("pc")),
            "last_quantity": safe_int(data.get("ltq")),
            "last_trade_time": data.get("ltt"),
            "shoonya_timestamp": safe_int(data.get("ft")),
        }


class DepthNormalizer:
    """Handles Depth mode data normalization"""

    @staticmethod
    def normalize(data: dict[str, Any], msg_type: str) -> dict[str, Any]:
        result = {
            "mode": Config.MODE_DEPTH,
            "ltp": safe_float(data.get("lp")),
            "volume": safe_int(data.get("v")),
            "open": safe_float(data.get("o")),
            "high": safe_float(data.get("h")),
            "low": safe_float(data.get("l")),
            "close": safe_float(data.get("c")),
            "average_price": safe_float(data.get("ap")),
            "percent_change": safe_float(data.get("pc")),
            "last_quantity": safe_int(data.get("ltq")),
            "last_trade_time": data.get("ltt"),
            "total_buy_quantity": safe_int(data.get("tbq")),
            "total_sell_quantity": safe_int(data.get("tsq")),
            "shoonya_timestamp": safe_int(data.get("ft")),
        }

        # Add depth data
        if msg_type in (Config.MSG_DEPTH_FULL, Config.MSG_DEPTH_PARTIAL):
            result["depth"] = {
                "buy": [
                    {
                        "price": safe_float(data.get("bp1")),
                        "quantity": safe_int(data.get("bq1")),
                        "orders": safe_int(data.get("bo1")),
                    },
                    {
                        "price": safe_float(data.get("bp2")),
                        "quantity": safe_int(data.get("bq2")),
                        "orders": safe_int(data.get("bo2")),
                    },
                    {
                        "price": safe_float(data.get("bp3")),
                        "quantity": safe_int(data.get("bq3")),
                        "orders": safe_int(data.get("bo3")),
                    },
                    {
                        "price": safe_float(data.get("bp4")),
                        "quantity": safe_int(data.get("bq4")),
                        "orders": safe_int(data.get("bo4")),
                    },
                    {
                        "price": safe_float(data.get("bp5")),
                        "quantity": safe_int(data.get("bq5")),
                        "orders": safe_int(data.get("bo5")),
                    },
                ],
                "sell": [
                    {
                        "price": safe_float(data.get("sp1")),
                        "quantity": safe_int(data.get("sq1")),
                        "orders": safe_int(data.get("so1")),
                    },
                    {
                        "price": safe_float(data.get("sp2")),
                        "quantity": safe_int(data.get("sq2")),
                        "orders": safe_int(data.get("so2")),
                    },
                    {
                        "price": safe_float(data.get("sp3")),
                        "quantity": safe_int(data.get("sq3")),
                        "orders": safe_int(data.get("so3")),
                    },
                    {
                        "price": safe_float(data.get("sp4")),
                        "quantity": safe_int(data.get("sq4")),
                        "orders": safe_int(data.get("so4")),
                    },
                    {
                        "price": safe_float(data.get("sp5")),
                        "quantity": safe_int(data.get("sq5")),
                        "orders": safe_int(data.get("so5")),
                    },
                ],
            }
            result["depth_level"] = 5

            # Add circuit limits and additional data
            result.update(
                {
                    "upper_circuit": safe_float(data.get("uc")),
                    "lower_circuit": safe_float(data.get("lc")),
                    "52_week_high": safe_float(data.get("52h")),
                    "52_week_low": safe_float(data.get("52l")),
                    "open_interest": safe_int(data.get("toi")),
                }
            )

        return result


class ShoonyaWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Shoonya WebSocket adapter with improved structure and error handling"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("shoonya_websocket")
        self._setup_adapter()
        self._setup_market_cache()
        self._setup_connection_management()
        self._setup_normalizers()

    def _setup_adapter(self):
        """Initialize adapter-specific settings"""
        self.user_id = None
        self.broker_name = "shoonya"
        self.ws_client = None

    def _setup_market_cache(self):
        """Initialize market data caching system"""
        self.market_cache = MarketDataCache()
        self.token_to_symbol = {}
        self.ws_subscription_refs = {}  # Reference counting for WebSocket subscriptions
        # SA-R7-10 fix: Index for O(1) subscription lookup by token on hot message path
        self._token_to_cids = {}  # token -> set of correlation_ids

    def _setup_connection_management(self):
        """Initialize connection management"""
        self.running = False
        self.connected = False
        self.lock = threading.Lock()
        self.reconnect_attempts = 0
        self._reconnecting = False
        self._reconnect_timer = None
        self._resub_thread = None

    def _setup_normalizers(self):
        """Initialize data normalizers"""
        self.normalizers = {
            Config.MODE_LTP: LTPNormalizer(),
            Config.MODE_QUOTE: QuoteNormalizer(),
            Config.MODE_DEPTH: DepthNormalizer(),
        }

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, str] | None = None
    ) -> None:
        """Initialize connection with Shoonya WebSocket API"""
        self.user_id = user_id
        self.broker_name = broker_name

        # Get Shoonya credentials
        api_key = os.getenv("BROKER_API_KEY", "")
        if api_key:
            self.actid = api_key[:-2] if len(api_key) > 2 else api_key
        else:
            self.actid = user_id

        # Get auth token from database
        self.susertoken = get_auth_token(user_id)

        if not self.actid or not self.susertoken:
            self.logger.error(f"Missing Shoonya credentials for user {user_id}")
            raise ValueError(f"Missing Shoonya credentials for user {user_id}")

        self.logger.info(f"Using Shoonya credentials - User ID: {self.actid}")

        # Initialize WebSocket client
        self.ws_client = ShoonyaWebSocket(
            user_id=self.actid,
            actid=self.actid,
            susertoken=self.susertoken,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )

        self.running = True

    def connect(self) -> None:
        """Establish connection to Shoonya WebSocket endpoint"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        self.logger.info("Connecting to Shoonya WebSocket...")
        connected = self.ws_client.connect()

        if connected:
            # connected flag is set by _on_open callback after auth succeeds
            # SA-11 fix: Set reconnect_attempts under lock for thread safety
            with self.lock:
                self.reconnect_attempts = 0
            self.logger.info("Connected to Shoonya WebSocket successfully")
        else:
            raise ConnectionError("Failed to connect to Shoonya WebSocket")

    # SA-2 fix: Join timer thread so in-flight _attempt_reconnection finishes before cleanup
    # SA-R6-1 fix: Also join resub thread to prevent races with cleanup
    def disconnect(self) -> None:
        """Disconnect from Shoonya WebSocket endpoint"""
        timer_to_join = None
        resub_to_join = None
        with self.lock:
            self.running = False
            self.connected = False
            self._reconnecting = False
            if self._reconnect_timer:
                self._reconnect_timer.cancel()
                timer_to_join = self._reconnect_timer
                self._reconnect_timer = None
            resub_to_join = self._resub_thread
            ws_to_stop = self.ws_client
            self.ws_client = None
            self.subscriptions.clear()
            self.token_to_symbol.clear()
            self.ws_subscription_refs.clear()
            self._token_to_cids.clear()

        # Wait for timer thread to finish (may be executing _attempt_reconnection)
        if timer_to_join and timer_to_join.is_alive():
            timer_to_join.join(timeout=5)

        # Wait for resub thread to finish
        if resub_to_join and resub_to_join.is_alive():
            resub_to_join.join(timeout=5)
        # SA-R8-5 fix: Null stale thread reference after join
        with self.lock:
            if self._resub_thread is resub_to_join:
                self._resub_thread = None

        try:
            if ws_to_stop:
                try:
                    ws_to_stop.stop()
                except Exception as e:
                    self.logger.error(f"Error stopping WebSocket: {e}")

            self.market_cache.clear()
        finally:
            try:
                self.cleanup_zmq()
            except Exception as e:
                self.logger.error(f"Error cleaning up ZMQ: {e}")

        self.logger.info("Disconnected from Shoonya WebSocket")

    def subscribe(
        self, symbol: str, exchange: str, mode: int = Config.MODE_QUOTE, depth_level: int = 5
    ) -> dict[str, Any]:
        """Subscribe to market data with improved error handling"""
        try:
            self.logger.info(f"[SUBSCRIBE] Request for {symbol}.{exchange} mode={mode}")

            # Validate inputs
            if not self._validate_subscription_params(symbol, exchange, mode):
                return self._create_error_response(
                    "INVALID_PARAMS", "Invalid subscription parameters"
                )

            # Get token information
            token_info = self._get_token_info(symbol, exchange)
            if not token_info:
                return self._create_error_response("SYMBOL_NOT_FOUND", f"Symbol {symbol} not found")

            # Create subscription
            subscription = self._create_subscription(
                symbol, exchange, mode, depth_level, token_info
            )

            # SA-6 fix: Use 16 chars (64 bits) to reduce collision risk at scale
            unique_id = str(uuid.uuid4())[:16]
            correlation_id = f"{symbol}_{exchange}_{mode}_{unique_id}"
            base_correlation_id = f"{symbol}_{exchange}_{mode}"

            # Collect what to do under lock, execute WS calls outside
            need_ws_subscribe = False
            with self.lock:
                # M7 fix: Use trailing underscore in prefix match to avoid false positives
                already_ws_subscribed = any(
                    cid.startswith(f"{base_correlation_id}_")
                    for cid in self.subscriptions.keys()
                )

                if already_ws_subscribed:
                    self.logger.info(
                        f"[SUBSCRIBE] WebSocket already subscribed for {base_correlation_id}, adding client subscription {correlation_id}"
                    )
                else:
                    self.logger.info(
                        f"[SUBSCRIBE] New WebSocket subscription needed for {correlation_id}"
                    )

                # Store the subscription
                self.subscriptions[correlation_id] = subscription
                self.token_to_symbol[subscription["token"]] = (
                    subscription["symbol"],
                    subscription["exchange"],
                )
                # Maintain token → correlation_id index
                token = subscription["token"]
                if token not in self._token_to_cids:
                    self._token_to_cids[token] = set()
                self._token_to_cids[token].add(correlation_id)

                if self.connected and not already_ws_subscribed:
                    need_ws_subscribe = True
                elif not self.connected:
                    self.logger.warning(
                        f"[SUBSCRIBE] Not connected, cannot subscribe to {subscription['scrip']}"
                    )

            # Network I/O outside lock
            if need_ws_subscribe:
                self._websocket_subscribe(subscription)
                self.logger.info(
                    f"[SUBSCRIBE] WebSocket subscription sent for {subscription['scrip']}"
                )

            # Log current ZMQ port and subscription state
            self.logger.info(f"[SUBSCRIBE] Publishing to ZMQ port: {self.zmq_port}")
            self.logger.info(f"[SUBSCRIBE] Total active subscriptions: {len(self.subscriptions)}")

            return self._create_success_response(
                f"Subscribed to {symbol}.{exchange}", symbol=symbol, exchange=exchange, mode=mode
            )

        except Exception as e:
            self.logger.error(f"Subscription error for {symbol}.{exchange}: {e}")
            return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

    def unsubscribe(
        self, symbol: str, exchange: str, mode: int = Config.MODE_QUOTE
    ) -> dict[str, Any]:
        """Unsubscribe from market data"""
        base_correlation_id = f"{symbol}_{exchange}_{mode}"

        # Collect state under lock, execute WS calls outside
        need_ws_unsubscribe = False
        subscription = None
        token_to_clear = None

        with self.lock:
            # M7 fix: Use trailing underscore in prefix match
            matching_subscriptions = [
                (cid, sub)
                for cid, sub in self.subscriptions.items()
                if cid.startswith(f"{base_correlation_id}_")
            ]

            if not matching_subscriptions:
                return self._create_error_response(
                    "NOT_SUBSCRIBED", f"Not subscribed to {symbol}.{exchange}"
                )

            # Remove the first matching subscription
            correlation_id, subscription = matching_subscriptions[0]

            # Check if this is the last subscription for this symbol/exchange/mode
            is_last = len(matching_subscriptions) == 1

            # Remove the subscription
            del self.subscriptions[correlation_id]

            # Maintain token → correlation_id index
            token = subscription["token"]
            if token in self._token_to_cids:
                self._token_to_cids[token].discard(correlation_id)
                if not self._token_to_cids[token]:
                    del self._token_to_cids[token]

            # Clean up token mapping if no other subscriptions use it
            if token not in self._token_to_cids:
                self.token_to_symbol.pop(token, None)
                token_to_clear = token

            # SA-R8-3 note: Only call _websocket_unsubscribe for the last
            # correlation_id. The ref count inside _websocket_unsubscribe is a
            # secondary guard; is_last is the primary decision point because
            # ref counts track unique WS subs (always 1), not correlation_ids.
            if is_last:
                need_ws_unsubscribe = True

        # Network I/O outside lock
        if need_ws_unsubscribe:
            self._websocket_unsubscribe(subscription)

        # Clear cache for removed token
        if token_to_clear:
            self.market_cache.clear(token_to_clear)

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}", symbol=symbol, exchange=exchange, mode=mode
        )

    def _validate_subscription_params(self, symbol: str, exchange: str, mode: int) -> bool:
        """Validate subscription parameters"""
        return (
            symbol and exchange and mode in [Config.MODE_LTP, Config.MODE_QUOTE, Config.MODE_DEPTH]
        )

    def _get_token_info(self, symbol: str, exchange: str) -> dict | None:
        """Get token information for symbol and exchange"""
        self.logger.info(f"Looking up token for {symbol}.{exchange}")
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if token_info:
            self.logger.info(
                f"Token found: {token_info['token']}, brexchange: {token_info['brexchange']}"
            )
        return token_info

    def _create_subscription(
        self, symbol: str, exchange: str, mode: int, depth_level: int, token_info: dict
    ) -> dict:
        """Create subscription object"""
        token = token_info["token"]
        brexchange = token_info["brexchange"]
        shoonya_exchange = ShoonyaExchangeMapper.to_shoonya_exchange(brexchange)
        # SM-R7-1 fix: Validate exchange mapping to prevent "None|token" scrip strings
        if not shoonya_exchange:
            raise ValueError(f"Unsupported exchange: {brexchange}")
        scrip = f"{shoonya_exchange}|{token}"

        return {
            "symbol": symbol,
            "exchange": exchange,
            "mode": mode,
            "depth_level": depth_level,
            "token": token,
            "scrip": scrip,
        }

    def _websocket_subscribe(self, subscription: dict) -> None:
        """Handle WebSocket subscription with lock-protected ref counting"""
        scrip = subscription["scrip"]
        mode = subscription["mode"]

        with self.lock:
            if scrip not in self.ws_subscription_refs:
                self.ws_subscription_refs[scrip] = {"touchline_count": 0, "depth_count": 0}

            ws_call = None
            if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
                if self.ws_subscription_refs[scrip]["touchline_count"] == 0:
                    ws_call = "touchline"
                self.ws_subscription_refs[scrip]["touchline_count"] += 1
            elif mode == Config.MODE_DEPTH:
                if self.ws_subscription_refs[scrip]["depth_count"] == 0:
                    ws_call = "depth"
                self.ws_subscription_refs[scrip]["depth_count"] += 1

            ws = self.ws_client

        # Network I/O outside lock
        if ws_call and ws:
            try:
                if ws_call == "touchline":
                    ws.subscribe_touchline(scrip)
                    self.logger.info(f"First touchline subscription for {scrip}")
                else:
                    ws.subscribe_depth(scrip)
                    self.logger.info(f"First depth subscription for {scrip}")
            except Exception as e:
                # SA-R7-7 fix: Log that subscription is kept in dict for retry on reconnect
                self.logger.error(
                    f"Error subscribing {ws_call} for {scrip}: {e}; "
                    f"subscription retained for retry on reconnect"
                )
                # SA-4 fix: Roll back ref count on failure so retry is possible
                with self.lock:
                    if scrip in self.ws_subscription_refs:
                        if ws_call == "touchline":
                            self.ws_subscription_refs[scrip]["touchline_count"] = max(
                                0, self.ws_subscription_refs[scrip]["touchline_count"] - 1
                            )
                        else:
                            self.ws_subscription_refs[scrip]["depth_count"] = max(
                                0, self.ws_subscription_refs[scrip]["depth_count"] - 1
                            )

    def _websocket_unsubscribe(self, subscription: dict) -> None:
        """Handle WebSocket unsubscription with lock-protected ref counting"""
        scrip = subscription["scrip"]
        mode = subscription["mode"]

        with self.lock:
            if scrip not in self.ws_subscription_refs:
                return

            # SA-R7-9 fix: Only decrement if count > 0 to prevent negative counts
            # when WS subscribe failed (rolled back) but subscription dict still has entry
            ws_call = None
            if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
                current = self.ws_subscription_refs[scrip]["touchline_count"]
                if current > 0:
                    self.ws_subscription_refs[scrip]["touchline_count"] = current - 1
                    if current - 1 == 0:
                        ws_call = "touchline"
            elif mode == Config.MODE_DEPTH:
                current = self.ws_subscription_refs[scrip]["depth_count"]
                if current > 0:
                    self.ws_subscription_refs[scrip]["depth_count"] = current - 1
                    if current - 1 == 0:
                        ws_call = "depth"

            # Clean up entry when both counts reach 0
            refs = self.ws_subscription_refs.get(scrip)
            if refs and refs["touchline_count"] <= 0 and refs["depth_count"] <= 0:
                del self.ws_subscription_refs[scrip]

            ws = self.ws_client

        # Network I/O outside lock
        if ws_call and ws:
            try:
                if ws_call == "touchline":
                    ws.unsubscribe_touchline(scrip)
                    self.logger.info(f"Last touchline subscription for {scrip}")
                else:
                    ws.unsubscribe_depth(scrip)
                    self.logger.info(f"Last depth subscription for {scrip}")
            except Exception as e:
                self.logger.error(f"Error unsubscribing {ws_call} for {scrip}: {e}")

    # SA-1 fix: Don't reset _reconnecting here — let _attempt_reconnection own that flag
    # SA-7 fix: Move _resubscribe_all to background thread to avoid blocking WS message thread
    # SA-R6-1 fix: Store thread reference so disconnect/cleanup can join it
    # SA-R7-3 fix: Join previous resub thread before starting new one
    def _on_open(self, ws):
        """Handle WebSocket connection open — set connected under lock, then resubscribe"""
        self.logger.info("Connected to Shoonya WebSocket")
        resub = threading.Thread(
            target=self._resubscribe_all, daemon=True, name="ShoonyaResub"
        )
        should_start = False
        with self.lock:
            self.connected = True
            old_resub = self._resub_thread
            if self.running:
                self._resub_thread = resub
                should_start = True
        # Wait for any previous resub thread to avoid concurrent resubscription
        if old_resub and old_resub.is_alive():
            old_resub.join(timeout=5)
        if should_start:
            resub.start()

    def _on_error(self, ws, error):
        """Handle WebSocket connection error — just log, close callback handles reconnection"""
        self.logger.error(f"Shoonya WebSocket error: {error}")

    # M1 fix: connected=False inside lock block to prevent TOCTOU
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection close with reconnection guard"""
        self.logger.info(f"Shoonya WebSocket connection closed: {close_status_code} - {close_msg}")

        with self.lock:
            self.connected = False
            if not self.running:
                return
            if self._reconnecting:
                self.logger.debug("Reconnection already in progress, skipping")
                return
            self._reconnecting = True

        self._schedule_reconnection()

    def _schedule_reconnection(self) -> None:
        """Schedule reconnection with exponential backoff"""
        with self.lock:
            if not self.running:
                self._reconnecting = False
                return
            if self.reconnect_attempts >= Config.MAX_RECONNECT_ATTEMPTS:
                self.logger.error("Maximum reconnection attempts reached")
                self.running = False
                self._reconnecting = False
                return

            delay = min(
                Config.BASE_RECONNECT_DELAY * (2 ** self.reconnect_attempts),
                Config.MAX_RECONNECT_DELAY,
            )

            self.logger.info(f"Reconnecting in {delay}s (attempt {self.reconnect_attempts + 1})")

            # Cancel existing timer before creating new one
            if self._reconnect_timer:
                self._reconnect_timer.cancel()

            self._reconnect_timer = threading.Timer(delay, self._attempt_reconnection)
            self._reconnect_timer.daemon = True
            self._reconnect_timer.start()

    def _attempt_reconnection(self) -> None:
        """Attempt to reconnect to WebSocket"""
        # C1 fix: Single atomic lock block for decision + snapshot to prevent
        # race with disconnect() between separate lock acquisitions.
        with self.lock:
            self._reconnect_timer = None
            if not self.running:
                self._reconnecting = False
                return
            self.reconnect_attempts += 1
            old_ws = self.ws_client
            self.ws_client = None

        # C2 fix: Track outcome so finally can reset _reconnecting if neither
        # success nor a retry timer was scheduled (prevents permanent blocking).
        reconnect_succeeded = False
        scheduled_retry = False
        try:
            # Stop old client outside lock (network I/O)
            if old_ws:
                try:
                    old_ws.stop()
                except Exception as e:
                    self.logger.warning(f"Error stopping old WebSocket: {e}")

            # Fetch fresh auth token from database
            fresh_token = get_auth_token(self.user_id)

            # SA-R6-5 fix: Re-check running before creating new client
            # SA-R6-4 fix: Write susertoken under lock
            # SA-R7-1 fix: Snapshot susertoken under lock to prevent stale read
            with self.lock:
                if not self.running:
                    self._reconnecting = False
                    return
                if fresh_token:
                    self.susertoken = fresh_token
                current_token = self.susertoken

            # Recreate WebSocket client using snapshotted token
            new_client = ShoonyaWebSocket(
                user_id=self.actid,
                actid=self.actid,
                susertoken=current_token,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_open=self._on_open,
            )

            # SA-R6-5 fix: Check running again before assigning and connecting
            # SA-R7-2 fix: Stop new client if running became False to prevent leak
            with self.lock:
                if not self.running:
                    self._reconnecting = False
                    try:
                        new_client.stop()
                    except Exception:
                        pass
                    return
                self.ws_client = new_client

            if new_client.connect():
                # SA-1 fix: Reset _reconnecting here (not in _on_open) to prevent
                # race where _on_close fires between _on_open and this code
                with self.lock:
                    self._reconnecting = False
                    self.reconnect_attempts = 0
                    # R9-MEDIUM-1 fix: If connection dropped between _on_open and
                    # here, _on_close was suppressed (saw _reconnecting=True).
                    # Re-check and schedule a fresh reconnection if needed.
                    connection_lost = not self.connected and self.running
                    if connection_lost:
                        self._reconnecting = True

                if connection_lost:
                    self.logger.warning(
                        "Connection lost during reconnection handoff, retrying"
                    )
                    self._schedule_reconnection()
                    scheduled_retry = True
                else:
                    reconnect_succeeded = True
                    self.logger.info("Reconnected successfully")
            else:
                self.logger.error("Reconnection failed")
                self._schedule_reconnection()
                scheduled_retry = True

        except Exception as e:
            self.logger.error(f"Reconnection error: {e}")
            try:
                self._schedule_reconnection()
                scheduled_retry = True
            except Exception as e2:
                self.logger.error(f"Failed to schedule reconnection: {e2}")
        finally:
            # Reset _reconnecting only if we failed without scheduling a retry.
            # On success, it was reset above (SA-R6-7). If a retry timer is
            # pending, keep it True so _on_close doesn't spawn a duplicate chain.
            if not reconnect_succeeded and not scheduled_retry:
                with self.lock:
                    self._reconnecting = False

    def _resubscribe_all(self):
        """Resubscribe to all active subscriptions after reconnect"""
        # SA-15 fix: Clear stale cache from before disconnect
        self.market_cache.clear()

        with self.lock:
            # SA-R6-2 fix: Use clear() to keep same dict identity
            self.ws_subscription_refs.clear()

            # Collect unique scrips for each subscription type
            touchline_scrips = set()
            depth_scrips = set()

            # SA-R8-2 note: _token_to_cids is NOT rebuilt here because this method
            # does NOT modify self.subscriptions. The index remains valid.
            for subscription in self.subscriptions.values():
                scrip = subscription["scrip"]
                mode = subscription["mode"]

                # Initialize reference count
                if scrip not in self.ws_subscription_refs:
                    self.ws_subscription_refs[scrip] = {"touchline_count": 0, "depth_count": 0}

                # SA-R8-1 fix: Set count to 1 (not +=1) — ref count reflects
                # unique WS subscriptions, not per-correlation-id count.
                # Multiple correlation IDs for the same scrip/mode share one WS sub.
                if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
                    touchline_scrips.add(scrip)
                    self.ws_subscription_refs[scrip]["touchline_count"] = 1
                elif mode == Config.MODE_DEPTH:
                    depth_scrips.add(scrip)
                    self.ws_subscription_refs[scrip]["depth_count"] = 1

            # Snapshot ws_client reference under lock
            ws = self.ws_client

        # Network I/O outside lock
        if ws and touchline_scrips:
            try:
                ws.subscribe_touchline("#".join(touchline_scrips))
                self.logger.info(f"Resubscribed to {len(touchline_scrips)} touchline scrips")
            except Exception as e:
                self.logger.error(f"Error resubscribing touchline: {e}")

        if ws and depth_scrips:
            try:
                ws.subscribe_depth("#".join(depth_scrips))
                self.logger.info(f"Resubscribed to {len(depth_scrips)} depth scrips")
            except Exception as e:
                self.logger.error(f"Error resubscribing depth: {e}")

    # L8 fix: Removed dead auth ack check (already intercepted by WS layer)
    def _on_message(self, ws, message):
        """Handle incoming market data messages"""
        self.logger.debug(f"[RAW_MESSAGE] {message}")

        try:
            data = json.loads(message)
            msg_type = data.get("t")

            # Process market data messages
            if msg_type in (
                Config.MSG_TOUCHLINE_FULL,
                Config.MSG_TOUCHLINE_PARTIAL,
                Config.MSG_DEPTH_FULL,
                Config.MSG_DEPTH_PARTIAL,
            ):
                self._process_market_message(data)
            else:
                self.logger.debug(f"Unknown message type {msg_type}: {data}")

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e}, message: {message}")
        except Exception as e:
            self.logger.error(f"Message processing error: {e}", exc_info=True)

    # SA-9 fix: Single lock acquisition for the hot message path instead of three
    def _process_market_message(self, data: dict[str, Any]) -> None:
        """Process market data messages with better error handling"""
        try:
            msg_type = data.get("t")
            token = data.get("tk")

            if not msg_type or not token:
                return

            # SA-R7-10 fix: Use _token_to_cids index for O(1) lookup instead of linear scan
            with self.lock:
                if token not in self.token_to_symbol:
                    return
                symbol, exchange = self.token_to_symbol.get(token, (None, None))
                if not symbol:
                    return
                cids = self._token_to_cids.get(token)
                if not cids:
                    return
                matching_subscriptions = [
                    self.subscriptions[cid].copy()
                    for cid in cids
                    if cid in self.subscriptions
                ]

            for subscription in matching_subscriptions:
                if self._should_process_message(msg_type, subscription["mode"]):
                    self._process_subscription_message(data, subscription, symbol, exchange)

        except Exception as e:
            self.logger.error(f"Message processing error: {e}")

    def _should_process_message(self, msg_type: str, mode: int) -> bool:
        """Determine if message should be processed for given mode"""
        touchline_messages = {Config.MSG_TOUCHLINE_FULL, Config.MSG_TOUCHLINE_PARTIAL}
        depth_messages = {Config.MSG_DEPTH_FULL, Config.MSG_DEPTH_PARTIAL}

        if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
            return msg_type in touchline_messages
        elif mode == Config.MODE_DEPTH:
            return msg_type in depth_messages

        return False

    def _process_subscription_message(
        self, data: dict, subscription: dict, symbol: str, exchange: str
    ) -> None:
        """Process message for a specific subscription"""
        mode = subscription["mode"]
        msg_type = data.get("t")

        # Normalize data
        normalized_data = self._normalize_market_data(data, msg_type, mode)
        normalized_data.update(
            {"symbol": symbol, "exchange": exchange, "timestamp": int(time.time() * 1000)}
        )

        # Create topic and publish
        mode_str = {Config.MODE_LTP: "LTP", Config.MODE_QUOTE: "QUOTE", Config.MODE_DEPTH: "DEPTH"}[
            mode
        ]
        topic = f"{exchange}_{symbol}_{mode_str}"

        self.logger.debug(f"[{mode_str}] Publishing data for {symbol}")
        self.publish_market_data(topic, normalized_data)

    def _normalize_market_data(
        self, data: dict[str, Any], msg_type: str, mode: int
    ) -> dict[str, Any]:
        """Normalize market data based on mode with improved structure"""
        token = data.get("tk")
        if token:
            # Use cache to handle partial updates
            data = self.market_cache.update(token, data)

        # Get mode-specific normalizer
        normalizer = self.normalizers.get(mode)
        if not normalizer:
            self.logger.error(f"No normalizer found for mode {mode}")
            return {}

        return normalizer.normalize(data, msg_type)

    def get_market_data_cache_stats(self) -> dict[str, Any]:
        """Get market data cache statistics"""
        return self.market_cache.get_stats()

    def clear_market_data_cache(self, token: str = None) -> None:
        """Clear market data cache"""
        self.market_cache.clear(token)

    def unsubscribe_all(self) -> dict[str, Any]:
        """
        Unsubscribe from all active data streams without disconnecting WebSocket.
        This implements the persistent session model for Shoonya to avoid
        server-side session cooldown issues.

        Returns:
            Dict: Response indicating success/failure
        """
        try:
            with self.lock:
                if not self.connected or not self.ws_client:
                    self.logger.warning("Cannot unsubscribe_all: WebSocket not connected")
                    return self._create_error_response("NOT_CONNECTED", "WebSocket not connected")

                # Collect all unique scrips for batch unsubscription
                touchline_scrips = set()
                depth_scrips = set()

                # Group subscriptions by type
                for subscription in self.subscriptions.values():
                    scrip = subscription["scrip"]
                    mode = subscription["mode"]

                    if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
                        touchline_scrips.add(scrip)
                    elif mode == Config.MODE_DEPTH:
                        depth_scrips.add(scrip)

                # Clear all subscription tracking but keep WebSocket connection alive
                subscription_count = len(self.subscriptions)
                self.subscriptions.clear()
                self.token_to_symbol.clear()
                self.ws_subscription_refs.clear()
                self._token_to_cids.clear()

                # Snapshot ws_client reference under lock
                ws = self.ws_client

            # SA-16 fix: Track partial failures in unsubscribe calls
            unsub_errors = []

            # Network I/O outside lock
            if ws and touchline_scrips:
                try:
                    scrip_list = "#".join(touchline_scrips)
                    self.logger.info(f"Unsubscribing from {len(touchline_scrips)} touchline scrips")
                    ws.unsubscribe_touchline(scrip_list)
                except Exception as e:
                    self.logger.error(f"Error unsubscribing touchline: {e}")
                    unsub_errors.append(f"touchline: {e}")

            if ws and depth_scrips:
                try:
                    scrip_list = "#".join(depth_scrips)
                    self.logger.info(f"Unsubscribing from {len(depth_scrips)} depth scrips")
                    ws.unsubscribe_depth(scrip_list)
                except Exception as e:
                    self.logger.error(f"Error unsubscribing depth: {e}")
                    unsub_errors.append(f"depth: {e}")

            if unsub_errors:
                self.logger.warning(f"Partial unsubscribe_all failure: {unsub_errors}")

            # Clear market data cache
            self.market_cache.clear()

            self.logger.info(
                f"Unsubscribed from all {subscription_count} subscriptions. "
                f"WebSocket connection remains active for fast reconnection."
            )

            # SA-R6-10 fix: Include warnings in response when partial failure occurs
            response_msg = f"Unsubscribed from all {subscription_count} subscriptions. Connection kept alive."
            if unsub_errors:
                response_msg += f" Warnings: {unsub_errors}"

            return self._create_success_response(
                response_msg,
                unsubscribed_count=subscription_count,
                connection_status="active",
            )

        except Exception as e:
            self.logger.error(f"Error in unsubscribe_all: {e}")
            return self._create_error_response("UNSUBSCRIBE_ALL_ERROR", str(e))

    # SA-3 fix: Use try/finally so cleanup_zmq is called exactly once
    # SA-R6-12 fix: Join timer and resub threads before cleanup
    def cleanup(self) -> None:
        """Clean up all resources"""
        try:
            # Set running=False BEFORE stopping WS client so any
            # _on_close callback triggered during stop() sees running=False
            # and skips reconnection scheduling.
            timer_to_join = None
            resub_to_join = None
            # R9-LOW-2 fix: Snapshot ws_client under lock for consistency
            with self.lock:
                self.running = False
                self.connected = False
                self._reconnecting = False
                if self._reconnect_timer:
                    self._reconnect_timer.cancel()
                    timer_to_join = self._reconnect_timer
                    self._reconnect_timer = None
                resub_to_join = self._resub_thread
                ws_to_stop = self.ws_client
                self.ws_client = None

            # Wait for in-flight reconnection and resub to finish
            if timer_to_join and timer_to_join.is_alive():
                timer_to_join.join(timeout=5)
            if resub_to_join and resub_to_join.is_alive():
                resub_to_join.join(timeout=5)
            # SA-R8-5 fix: Null stale thread reference after join
            with self.lock:
                if self._resub_thread is resub_to_join:
                    self._resub_thread = None

            if ws_to_stop:
                try:
                    ws_to_stop.stop()
                except Exception as e:
                    self.logger.error(f"Error stopping WebSocket during cleanup: {e}")

            with self.lock:
                self.reconnect_attempts = 0
                self.subscriptions.clear()
                self.token_to_symbol.clear()
                self.ws_subscription_refs.clear()
                self._token_to_cids.clear()

            self.market_cache.clear()
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
        finally:
            try:
                self.cleanup_zmq()
            except Exception:
                pass

    # L7 fix: Removed redundant cleanup_zmq call (cleanup() already calls it)
    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass


# Utility functions
def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float with default"""
    if value is None or value == "" or value == "-":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to int with default"""
    if value is None or value == "" or value == "-":
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default
