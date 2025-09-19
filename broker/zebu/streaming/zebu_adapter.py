"""
Zebu WebSocket Adapter for OpenAlgo
Handles market data streaming from Zebu broker
"""
import threading
import json
import logging
import time
from typing import Dict, Any, Optional, List
from enum import IntEnum

from database.auth_db import get_auth_token
from database.token_db import get_token

import sys
import os

# Add parent directory to path to allow imports FIRST
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

# CRITICAL: Import config to load .env file which sets ZMQ_PORT
# This must happen before any WebSocket server initialization
import utils.config  # This loads .env file at module level

# Ensure ZMQ_PORT is set (fallback if not in .env)
if not os.getenv('ZMQ_PORT'):
    os.environ['ZMQ_PORT'] = '5555'
    temp_logger = logging.getLogger("zebu_init")
    temp_logger.info("ZMQ_PORT not found in environment, setting to 5555")

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .zebu_mapping import ZebuExchangeMapper, ZebuCapabilityRegistry
from .zebu_websocket import ZebuWebSocket


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

    # Message types (same as Noren/Flattrade)
    MSG_AUTH = 'ck'
    MSG_TOUCHLINE_FULL = 'tf'
    MSG_TOUCHLINE_PARTIAL = 'tk'
    MSG_DEPTH_FULL = 'df'
    MSG_DEPTH_PARTIAL = 'dk'


class MarketDataCache:
    """Manages market data caching with thread safety"""

    def __init__(self):
        self._cache = {}
        self._initialized_tokens = set()
        self._lock = threading.Lock()
        self.logger = logging.getLogger("market_cache")

    def get(self, token: str) -> Dict[str, Any]:
        """Get cached data for a token"""
        with self._lock:
            return self._cache.get(token, {}).copy()

    def update(self, token: str, data: Dict[str, Any]) -> Dict[str, Any]:
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

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            return {
                'total_tokens': len(self._cache),
                'initialized_tokens': len(self._initialized_tokens),
                'tokens': list(self._cache.keys())
            }

    def _merge_data(self, cached: Dict, new: Dict, token: str) -> Dict:
        """Smart merge logic for market data"""
        merged = cached.copy()

        # Define field categories
        basic_fields = ['lp', 'o', 'h', 'l', 'c', 'v', 'ap', 'pc', 'ltq', 'ltt', 'tbq', 'tsq']
        depth_prices = ['bp1', 'bp2', 'bp3', 'bp4', 'bp5', 'sp1', 'sp2', 'sp3', 'sp4', 'sp5']
        depth_quantities = ['bq1', 'bq2', 'bq3', 'bq4', 'bq5', 'sq1', 'sq2', 'sq3', 'sq4', 'sq5']
        depth_orders = ['bo1', 'bo2', 'bo3', 'bo4', 'bo5', 'so1', 'so2', 'so3', 'so4', 'so5']

        for key, value in new.items():
            if self._should_preserve_cached_value(key, value, cached):
                continue
            merged[key] = value

        # Preserve cached values for missing fields
        self._preserve_missing_fields(merged, new, cached)
        return merged

    def _should_preserve_cached_value(self, key: str, new_value: Any, cached: Dict) -> bool:
        """Determine if cached value should be preserved over new value"""
        # Preserve non-zero OHLC values when new value is zero
        if key in ['o', 'h', 'l', 'c', 'ap'] and self._is_zero_value(new_value):
            cached_value = cached.get(key)
            return cached_value is not None and not self._is_zero_value(cached_value)
        return False

    def _preserve_missing_fields(self, merged: Dict, new: Dict, cached: Dict) -> None:
        """Preserve cached values for fields missing in new data"""
        for key, value in cached.items():
            if key not in new:
                merged[key] = value

    def _is_zero_value(self, value: Any) -> bool:
        """Check if value represents zero"""
        return value in [None, '', '0', 0, '0.0', 0.0]

    def _log_cache_initialization(self, token: str, data: Dict) -> None:
        """Log cache initialization details"""
        basic_fields = ['lp', 'o', 'h', 'l', 'c', 'v', 'ap', 'pc', 'ltq', 'ltt', 'tbq', 'tsq']
        present_fields = sum(1 for field in basic_fields if field in data)
        completeness = present_fields / len(basic_fields)

        self.logger.info(f"Initializing cache for token {token} - "
                        f"{present_fields}/{len(basic_fields)} fields present ({completeness:.1%})")


class LTPNormalizer:
    """Handles LTP mode data normalization"""

    @staticmethod
    def normalize(data: Dict[str, Any], msg_type: str) -> Dict[str, Any]:
        return {
            'mode': Config.MODE_LTP,
            'ltp': safe_float(data.get('lp')),
            'zebu_timestamp': safe_int(data.get('ft'))
        }


class QuoteNormalizer:
    """Handles Quote mode data normalization"""

    @staticmethod
    def normalize(data: Dict[str, Any], msg_type: str) -> Dict[str, Any]:
        return {
            'mode': Config.MODE_QUOTE,
            'ltp': safe_float(data.get('lp')),
            'volume': safe_int(data.get('v')),
            'open': safe_float(data.get('o')),
            'high': safe_float(data.get('h')),
            'low': safe_float(data.get('l')),
            'close': safe_float(data.get('c')),
            'average_price': safe_float(data.get('ap')),
            'percent_change': safe_float(data.get('pc')),
            'last_quantity': safe_int(data.get('ltq')),
            'last_trade_time': data.get('ltt'),
            'zebu_timestamp': safe_int(data.get('ft'))
        }


class DepthNormalizer:
    """Handles Depth mode data normalization"""

    @staticmethod
    def normalize(data: Dict[str, Any], msg_type: str) -> Dict[str, Any]:
        result = {
            'mode': Config.MODE_DEPTH,
            'ltp': safe_float(data.get('lp')),
            'volume': safe_int(data.get('v')),
            'open': safe_float(data.get('o')),
            'high': safe_float(data.get('h')),
            'low': safe_float(data.get('l')),
            'close': safe_float(data.get('c')),
            'average_price': safe_float(data.get('ap')),
            'percent_change': safe_float(data.get('pc')),
            'last_quantity': safe_int(data.get('ltq')),
            'last_trade_time': data.get('ltt'),
            'total_buy_quantity': safe_int(data.get('tbq')),
            'total_sell_quantity': safe_int(data.get('tsq')),
            'zebu_timestamp': safe_int(data.get('ft'))
        }

        # Add depth data
        if msg_type in (Config.MSG_DEPTH_FULL, Config.MSG_DEPTH_PARTIAL):
            result['depth'] = {
                'buy': [
                    {'price': safe_float(data.get('bp1')), 'quantity': safe_int(data.get('bq1')), 'orders': safe_int(data.get('bo1'))},
                    {'price': safe_float(data.get('bp2')), 'quantity': safe_int(data.get('bq2')), 'orders': safe_int(data.get('bo2'))},
                    {'price': safe_float(data.get('bp3')), 'quantity': safe_int(data.get('bq3')), 'orders': safe_int(data.get('bo3'))},
                    {'price': safe_float(data.get('bp4')), 'quantity': safe_int(data.get('bq4')), 'orders': safe_int(data.get('bo4'))},
                    {'price': safe_float(data.get('bp5')), 'quantity': safe_int(data.get('bq5')), 'orders': safe_int(data.get('bo5'))}
                ],
                'sell': [
                    {'price': safe_float(data.get('sp1')), 'quantity': safe_int(data.get('sq1')), 'orders': safe_int(data.get('so1'))},
                    {'price': safe_float(data.get('sp2')), 'quantity': safe_int(data.get('sq2')), 'orders': safe_int(data.get('so2'))},
                    {'price': safe_float(data.get('sp3')), 'quantity': safe_int(data.get('sq3')), 'orders': safe_int(data.get('so3'))},
                    {'price': safe_float(data.get('sp4')), 'quantity': safe_int(data.get('sq4')), 'orders': safe_int(data.get('so4'))},
                    {'price': safe_float(data.get('sp5')), 'quantity': safe_int(data.get('sq5')), 'orders': safe_int(data.get('so5'))}
                ]
            }
            result['depth_level'] = 5

            # Add circuit limits and additional data
            result.update({
                'upper_circuit': safe_float(data.get('uc')),
                'lower_circuit': safe_float(data.get('lc')),
                '52_week_high': safe_float(data.get('52h')),
                '52_week_low': safe_float(data.get('52l')),
                'total_traded_value': safe_int(data.get('toi'))
            })

        return result


class ZebuWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Zebu WebSocket adapter with improved structure and error handling"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("zebu_websocket")

        # Log the actual ZMQ port being used
        actual_zmq_port = os.getenv('ZMQ_PORT', '5555')
        self.logger.info(f"Zebu adapter initialized - Expected ZMQ port: {actual_zmq_port}, Actual bound port: {self.zmq_port}")

        # Warn if there's a mismatch
        if str(self.zmq_port) != str(actual_zmq_port):
            self.logger.warning(f"ZMQ port mismatch! Server expects {actual_zmq_port} but adapter bound to {self.zmq_port}")
            self.logger.warning("Data may not reach clients properly!")

        self._setup_adapter()
        self._setup_market_cache()
        self._setup_connection_management()
        self._setup_normalizers()

    def _setup_adapter(self):
        """Initialize adapter-specific settings"""
        self.user_id = None
        self.broker_name = "zebu"
        self.ws_client = None

    def _setup_market_cache(self):
        """Initialize market data caching system"""
        self.market_cache = MarketDataCache()
        self.subscriptions = {}
        self.token_to_symbol = {}
        self.ws_subscription_refs = {}  # Reference counting for WebSocket subscriptions

    def _setup_connection_management(self):
        """Initialize connection management"""
        self.running = False
        self.connected = False
        self.lock = threading.Lock()
        self.reconnect_attempts = 0

    def _setup_normalizers(self):
        """Initialize data normalizers"""
        self.normalizers = {
            Config.MODE_LTP: LTPNormalizer(),
            Config.MODE_QUOTE: QuoteNormalizer(),
            Config.MODE_DEPTH: DepthNormalizer()
        }

    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """Initialize connection with Zebu WebSocket API"""
        self.user_id = user_id
        self.broker_name = broker_name

        # Get Zebu credentials from environment
        # For Zebu, BROKER_API_KEY should contain the vendor code (e.g., 'Z56004')
        # This vendor code is used as both actid and uid in WebSocket authentication

        api_key = os.getenv('BROKER_API_KEY', '')

        if api_key:
            # Use the BROKER_API_KEY (vendor code) as the account ID
            # For Zebu, the vendor code like 'Z56004' is used as actid and uid
            self.actid = api_key
            self.logger.info(f"Using Zebu vendor code from BROKER_API_KEY: {self.actid}")
        else:
            # Fallback to user_id if no API key is set
            self.actid = user_id
            self.logger.warning(f"No BROKER_API_KEY found. Using user_id '{user_id}' as actid.")
            self.logger.warning("Please set BROKER_API_KEY=Z56004 (or your vendor code) in .env file")

        # Get auth token from database
        self.susertoken = get_auth_token(user_id)

        if not self.actid or not self.susertoken:
            self.logger.error(f"Missing Zebu credentials for user {user_id}")
            raise ValueError(f"Missing Zebu credentials for user {user_id}")

        self.logger.info(f"Using Zebu credentials - User ID: {self.actid}")

        # Initialize WebSocket client
        self.ws_client = ZebuWebSocket(
            user_id=self.actid,  # Both user_id and actid should be the Zebu account ID
            actid=self.actid,
            susertoken=self.susertoken,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open
        )

        self.running = True

    def connect(self) -> None:
        """Establish connection to Zebu WebSocket endpoint"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        self.logger.info("Connecting to Zebu WebSocket...")
        connected = self.ws_client.connect()

        if connected:
            self.connected = True
            self.reconnect_attempts = 0
            self.logger.info("Connected to Zebu WebSocket successfully")
        else:
            raise ConnectionError("Failed to connect to Zebu WebSocket")

    def disconnect(self) -> None:
        """Disconnect from Zebu WebSocket endpoint"""
        self.running = False

        if self.ws_client:
            self.ws_client.stop()

        # Clean up market data cache
        self.market_cache.clear()

        # Clean up ZeroMQ resources
        self.cleanup_zmq()

        self.connected = False
        self.logger.info("Disconnected from Zebu WebSocket")

    def subscribe(self, symbol: str, exchange: str, mode: int = Config.MODE_QUOTE, depth_level: int = 5) -> Dict[str, Any]:
        """Subscribe to market data with improved error handling"""
        try:
            self.logger.info(f"[SUBSCRIBE] Request for {symbol}.{exchange} mode={mode}")

            # Validate inputs
            if not self._validate_subscription_params(symbol, exchange, mode):
                return self._create_error_response("INVALID_PARAMS", "Invalid subscription parameters")

            # Get token information
            token_info = self._get_token_info(symbol, exchange)
            if not token_info:
                return self._create_error_response("SYMBOL_NOT_FOUND", f"Symbol {symbol} not found")

            # Create subscription
            subscription = self._create_subscription(symbol, exchange, mode, depth_level, token_info)

            # Generate a unique correlation_id for each subscription
            # This allows multiple clients to subscribe to the same symbol
            import uuid
            unique_id = str(uuid.uuid4())[:8]
            correlation_id = f"{symbol}_{exchange}_{mode}_{unique_id}"

            # Check if we need to subscribe to WebSocket
            base_correlation_id = f"{symbol}_{exchange}_{mode}"
            already_ws_subscribed = any(
                cid.startswith(base_correlation_id)
                for cid in self.subscriptions.keys()
            )

            if already_ws_subscribed:
                self.logger.info(f"[SUBSCRIBE] WebSocket already subscribed for {base_correlation_id}, adding client subscription {correlation_id}")
            else:
                self.logger.info(f"[SUBSCRIBE] New WebSocket subscription needed for {correlation_id}")

            # Always store the subscription (each client gets their own entry)
            self._store_subscription(correlation_id, subscription)

            # Subscribe via WebSocket (reference counting will handle duplicates)
            if self.connected:
                self._websocket_subscribe(subscription)
                if not already_ws_subscribed:
                    self.logger.info(f"[SUBSCRIBE] WebSocket subscription sent for {subscription['scrip']}")
            else:
                self.logger.warning(f"[SUBSCRIBE] Not connected, cannot subscribe to {subscription['scrip']}")

            # Log current ZMQ port and subscription state
            self.logger.info(f"[SUBSCRIBE] Publishing to ZMQ port: {self.zmq_port}")
            self.logger.info(f"[SUBSCRIBE] Total active subscriptions: {len(self.subscriptions)}")

            return self._create_success_response(f'Subscribed to {symbol}.{exchange}',
                                               symbol=symbol, exchange=exchange, mode=mode)

        except Exception as e:
            self.logger.error(f"Subscription error for {symbol}.{exchange}: {e}")
            return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

    def unsubscribe(self, symbol: str, exchange: str, mode: int = Config.MODE_QUOTE) -> Dict[str, Any]:
        """Unsubscribe from market data"""
        base_correlation_id = f"{symbol}_{exchange}_{mode}"

        with self.lock:
            # Find the first matching subscription for this client
            matching_subscriptions = [
                (cid, sub) for cid, sub in self.subscriptions.items()
                if cid.startswith(base_correlation_id)
            ]

            if not matching_subscriptions:
                return self._create_error_response("NOT_SUBSCRIBED",
                                                  f"Not subscribed to {symbol}.{exchange}")

            # Remove the first matching subscription
            correlation_id, subscription = matching_subscriptions[0]

            # Check if this is the last subscription for this symbol/exchange/mode
            is_last = len(matching_subscriptions) == 1

            # Remove the subscription
            del self.subscriptions[correlation_id]

            # Clean up token mapping if no other subscriptions use it
            token = subscription['token']
            if not any(sub['token'] == token for sub in self.subscriptions.values()):
                self.token_to_symbol.pop(token, None)

            # Only unsubscribe from WebSocket if this was the last subscription
            if is_last:
                scrip = subscription['scrip']
                if scrip in self.ws_subscription_refs:
                    if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
                        self.ws_subscription_refs[scrip]['touchline_count'] -= 1
                        if self.ws_subscription_refs[scrip]['touchline_count'] <= 0:
                            self._websocket_unsubscribe(subscription)
                    elif mode == Config.MODE_DEPTH:
                        self.ws_subscription_refs[scrip]['depth_count'] -= 1
                        if self.ws_subscription_refs[scrip]['depth_count'] <= 0:
                            self._websocket_unsubscribe(subscription)

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}",
            symbol=symbol, exchange=exchange, mode=mode
        )

    def _validate_subscription_params(self, symbol: str, exchange: str, mode: int) -> bool:
        """Validate subscription parameters"""
        return (symbol and exchange and
                mode in [Config.MODE_LTP, Config.MODE_QUOTE, Config.MODE_DEPTH])

    def _get_token_info(self, symbol: str, exchange: str) -> Optional[Dict]:
        """Get token information for symbol and exchange"""
        self.logger.info(f"Looking up token for {symbol}.{exchange}")
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if token_info:
            self.logger.info(f"Token found: {token_info['token']}, brexchange: {token_info['brexchange']}")
        return token_info

    def _create_subscription(self, symbol: str, exchange: str, mode: int, depth_level: int, token_info: Dict) -> Dict:
        """Create subscription object"""
        token = token_info['token']
        brexchange = token_info['brexchange']
        zebu_exchange = ZebuExchangeMapper.to_zebu_exchange(brexchange)
        scrip = f"{zebu_exchange}|{token}"

        return {
            'symbol': symbol,
            'exchange': exchange,
            'mode': mode,
            'depth_level': depth_level,
            'token': token,
            'scrip': scrip
        }

    def _store_subscription(self, correlation_id: str, subscription: Dict) -> None:
        """Store subscription and update mappings"""
        with self.lock:
            self.subscriptions[correlation_id] = subscription
            self.token_to_symbol[subscription['token']] = (subscription['symbol'], subscription['exchange'])

    def _websocket_subscribe(self, subscription: Dict) -> None:
        """Handle WebSocket subscription with reference counting"""
        scrip = subscription['scrip']
        mode = subscription['mode']

        # Initialize reference count for this scrip if not exists
        if scrip not in self.ws_subscription_refs:
            self.ws_subscription_refs[scrip] = {'touchline_count': 0, 'depth_count': 0}

        if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
            if self.ws_subscription_refs[scrip]['touchline_count'] == 0:
                self.logger.info(f"First touchline subscription for {scrip}")
                self.ws_client.subscribe_touchline(scrip)
                self.ws_subscription_refs[scrip]['touchline_count'] = 1
            else:
                # Already subscribed, just increment the count
                self.ws_subscription_refs[scrip]['touchline_count'] += 1
                self.logger.info(f"Additional touchline subscription for {scrip}, count: {self.ws_subscription_refs[scrip]['touchline_count']}")
        elif mode == Config.MODE_DEPTH:
            if self.ws_subscription_refs[scrip]['depth_count'] == 0:
                self.logger.info(f"First depth subscription for {scrip}")
                self.ws_client.subscribe_depth(scrip)
                self.ws_subscription_refs[scrip]['depth_count'] = 1
            else:
                # Already subscribed, just increment the count
                self.ws_subscription_refs[scrip]['depth_count'] += 1
                self.logger.info(f"Additional depth subscription for {scrip}, count: {self.ws_subscription_refs[scrip]['depth_count']}")

    def _websocket_unsubscribe(self, subscription: Dict) -> None:
        """Handle WebSocket unsubscription with reference counting"""
        scrip = subscription['scrip']
        mode = subscription['mode']

        if scrip not in self.ws_subscription_refs:
            return

        if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
            self.ws_subscription_refs[scrip]['touchline_count'] -= 1
            if self.ws_subscription_refs[scrip]['touchline_count'] <= 0:
                self.logger.info(f"Last touchline subscription for {scrip}")
                self.ws_client.unsubscribe_touchline(scrip)
                self.ws_subscription_refs[scrip]['touchline_count'] = 0
        elif mode == Config.MODE_DEPTH:
            self.ws_subscription_refs[scrip]['depth_count'] -= 1
            if self.ws_subscription_refs[scrip]['depth_count'] <= 0:
                self.logger.info(f"Last depth subscription for {scrip}")
                self.ws_client.unsubscribe_depth(scrip)
                self.ws_subscription_refs[scrip]['depth_count'] = 0

    def _remove_subscription(self, correlation_id: str, subscription: Dict) -> None:
        """Remove subscription and clean up mappings"""
        token = subscription['token']
        scrip = subscription['scrip']
        mode = subscription['mode']

        # Remove subscription
        del self.subscriptions[correlation_id]

        # Check if there are any other subscriptions for the same scrip and mode
        has_other_subscriptions = any(
            sub['scrip'] == scrip and sub['mode'] == mode
            for sub in self.subscriptions.values()
        )

        # Only decrement reference count if no other subscriptions exist
        if not has_other_subscriptions and scrip in self.ws_subscription_refs:
            if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
                self.ws_subscription_refs[scrip]['touchline_count'] -= 1
                if self.ws_subscription_refs[scrip]['touchline_count'] <= 0:
                    self.ws_subscription_refs[scrip]['touchline_count'] = 0
            elif mode == Config.MODE_DEPTH:
                self.ws_subscription_refs[scrip]['depth_count'] -= 1
                if self.ws_subscription_refs[scrip]['depth_count'] <= 0:
                    self.ws_subscription_refs[scrip]['depth_count'] = 0

            # Clean up reference count if both counts are 0
            if (self.ws_subscription_refs[scrip]['touchline_count'] <= 0 and
                self.ws_subscription_refs[scrip]['depth_count'] <= 0):
                del self.ws_subscription_refs[scrip]

        # Remove token mapping if no other subscriptions use it
        if not any(sub['token'] == token for sub in self.subscriptions.values()):
            self.token_to_symbol.pop(token, None)
            self.market_cache.clear(token)

    def _on_open(self, ws):
        """Handle WebSocket connection open"""
        self.logger.info("Connected to Zebu WebSocket")
        self.connected = True
        self._resubscribe_all()

    def _on_error(self, ws, error):
        """Handle WebSocket connection error"""
        self.logger.error(f"Zebu WebSocket error: {error}")
        self._handle_websocket_error(error)

    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection close"""
        self.logger.info(f"Zebu WebSocket connection closed: {close_status_code} - {close_msg}")
        self.connected = False

        if self.running:
            self._schedule_reconnection()

    def _handle_websocket_error(self, error: Exception) -> None:
        """Centralized error handling for WebSocket operations"""
        self.logger.error(f"WebSocket error: {error}")

        if self.running:
            self._schedule_reconnection()

    def _schedule_reconnection(self) -> None:
        """Schedule reconnection with exponential backoff"""
        if self.reconnect_attempts >= Config.MAX_RECONNECT_ATTEMPTS:
            self.logger.error("Maximum reconnection attempts reached")
            self.running = False
            return

        delay = min(
            Config.BASE_RECONNECT_DELAY * (2 ** self.reconnect_attempts),
            Config.MAX_RECONNECT_DELAY
        )

        self.logger.info(f"Reconnecting in {delay}s (attempt {self.reconnect_attempts + 1})")
        threading.Timer(delay, self._attempt_reconnection).start()

    def _attempt_reconnection(self) -> None:
        """Attempt to reconnect to WebSocket"""
        self.reconnect_attempts += 1

        try:
            # Recreate WebSocket client
            self.ws_client = ZebuWebSocket(
                user_id=self.actid,  # Both user_id and actid should be the Zebu account ID
                actid=self.actid,
                susertoken=self.susertoken,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_open=self._on_open
            )

            if self.ws_client.connect():
                self.connected = True
                self.reconnect_attempts = 0
                self.logger.info("Reconnected successfully")
            else:
                self.logger.error("Reconnection failed")

        except Exception as e:
            self.logger.error(f"Reconnection error: {e}")

    def _resubscribe_all(self):
        """Resubscribe to all active subscriptions after reconnect"""
        with self.lock:
            # Reset reference counts
            self.ws_subscription_refs = {}

            # Collect unique scrips for each subscription type
            touchline_scrips = set()
            depth_scrips = set()

            for subscription in self.subscriptions.values():
                scrip = subscription['scrip']
                mode = subscription['mode']

                # Initialize reference count
                if scrip not in self.ws_subscription_refs:
                    self.ws_subscription_refs[scrip] = {'touchline_count': 0, 'depth_count': 0}

                if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
                    if scrip not in touchline_scrips:
                        touchline_scrips.add(scrip)
                    self.ws_subscription_refs[scrip]['touchline_count'] += 1
                elif mode == Config.MODE_DEPTH:
                    if scrip not in depth_scrips:
                        depth_scrips.add(scrip)
                    self.ws_subscription_refs[scrip]['depth_count'] += 1

            # Resubscribe in batches
            if touchline_scrips:
                scrip_list = '#'.join(touchline_scrips)
                self.ws_client.subscribe_touchline(scrip_list)
                self.logger.info(f"Resubscribed to {len(touchline_scrips)} touchline scrips with total {sum(self.ws_subscription_refs[s]['touchline_count'] for s in touchline_scrips)} subscriptions")

            if depth_scrips:
                scrip_list = '#'.join(depth_scrips)
                self.ws_client.subscribe_depth(scrip_list)
                self.logger.info(f"Resubscribed to {len(depth_scrips)} depth scrips with total {sum(self.ws_subscription_refs[s]['depth_count'] for s in depth_scrips)} subscriptions")

    def _on_message(self, ws, message):
        """Handle incoming market data messages"""
        self.logger.debug(f"[RAW_MESSAGE] {message}")

        try:
            data = json.loads(message)
            msg_type = data.get('t')

            # Handle authentication acknowledgment
            if msg_type == Config.MSG_AUTH:
                self.logger.info(f"Authentication response: {data}")
                return

            # Process market data messages
            if msg_type in (Config.MSG_TOUCHLINE_FULL, Config.MSG_TOUCHLINE_PARTIAL,
                           Config.MSG_DEPTH_FULL, Config.MSG_DEPTH_PARTIAL):
                self._process_market_message(data)
            else:
                self.logger.debug(f"Unknown message type {msg_type}: {data}")

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e}, message: {message}")
        except Exception as e:
            self.logger.error(f"Message processing error: {e}", exc_info=True)

    def _process_market_message(self, data: Dict[str, Any]) -> None:
        """Process market data messages with better error handling"""
        try:
            msg_type = data.get('t')
            token = data.get('tk')

            if not self._is_valid_market_message(msg_type, token):
                return

            symbol, exchange = self._get_symbol_info(token)
            if not symbol:
                return

            matching_subscriptions = self._find_matching_subscriptions(token)

            for subscription in matching_subscriptions:
                if self._should_process_message(msg_type, subscription['mode']):
                    self._process_subscription_message(data, subscription, symbol, exchange)

        except Exception as e:
            self.logger.error(f"Message processing error: {e}")

    def _is_valid_market_message(self, msg_type: str, token: str) -> bool:
        """Validate market message"""
        return msg_type and token and token in self.token_to_symbol

    def _get_symbol_info(self, token: str) -> tuple:
        """Get symbol and exchange from token"""
        return self.token_to_symbol.get(token, (None, None))

    def _find_matching_subscriptions(self, token: str) -> List[Dict]:
        """Find all subscriptions matching the token"""
        with self.lock:
            return [sub for sub in self.subscriptions.values() if sub['token'] == token]

    def _should_process_message(self, msg_type: str, mode: int) -> bool:
        """Determine if message should be processed for given mode"""
        touchline_messages = {Config.MSG_TOUCHLINE_FULL, Config.MSG_TOUCHLINE_PARTIAL}
        depth_messages = {Config.MSG_DEPTH_FULL, Config.MSG_DEPTH_PARTIAL}

        if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
            return msg_type in touchline_messages
        elif mode == Config.MODE_DEPTH:
            return msg_type in depth_messages

        return False

    def _process_subscription_message(self, data: Dict, subscription: Dict, symbol: str, exchange: str) -> None:
        """Process message for a specific subscription"""
        mode = subscription['mode']
        msg_type = data.get('t')

        # Normalize data
        normalized_data = self._normalize_market_data(data, msg_type, mode)
        normalized_data.update({
            'symbol': symbol,
            'exchange': exchange,
            'timestamp': int(time.time() * 1000)
        })

        # Create topic and publish
        mode_str = {Config.MODE_LTP: 'LTP', Config.MODE_QUOTE: 'QUOTE', Config.MODE_DEPTH: 'DEPTH'}[mode]
        topic = f"{exchange}_{symbol}_{mode_str}"

        # Get client count for this subscription
        client_count = subscription.get('client_count', 1)

        self.logger.debug(f"[PUBLISH] Publishing {mode_str} data for {symbol} on topic: {topic}, ZMQ port: {self.zmq_port}, client_count: {client_count}")

        # Debug: Check if data is actually being sent
        try:
            # Track published topics
            if not hasattr(self, '_published_topics'):
                self._published_topics = set()

            if topic not in self._published_topics:
                self.logger.info(f"[PUBLISH] First publish for topic: {topic}")
                self._published_topics.add(topic)

            # Publish once - the ZMQ PUB/SUB pattern will deliver to all subscribers
            # The issue is not here but in how subscriptions are found
            self.publish_market_data(topic, normalized_data)

            # Log client count for debugging
            if client_count > 1:
                self.logger.debug(f"[PUBLISH] Published to topic {topic} for {client_count} clients")
        except Exception as e:
            self.logger.error(f"[PUBLISH] Failed to publish data: {e}")

    def _normalize_market_data(self, data: Dict[str, Any], msg_type: str, mode: int) -> Dict[str, Any]:
        """Normalize market data based on mode with improved structure"""
        token = data.get('tk')
        if token:
            # Use cache to handle partial updates
            data = self.market_cache.update(token, data)

        # Get mode-specific normalizer
        normalizer = self.normalizers.get(mode)
        if not normalizer:
            self.logger.error(f"No normalizer found for mode {mode}")
            return {}

        return normalizer.normalize(data, msg_type)

    def get_market_data_cache_stats(self) -> Dict[str, Any]:
        """Get market data cache statistics"""
        return self.market_cache.get_stats()

    def clear_market_data_cache(self, token: str = None) -> None:
        """Clear market data cache"""
        self.market_cache.clear(token)


# Utility functions
def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float with default"""
    if value is None or value == '' or value == '-':
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to int with default"""
    if value is None or value == '' or value == '-':
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default