"""
High-level DefinedGe Securities adapter for WebSocket streaming.
Each instance is fully isolated and safe for multi-client use.
"""
import threading
import time
import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from .definedge_websocket import DefinedGeWebSocket
from database.auth_db import get_auth_token
from utils.logging import get_logger

logger = get_logger(__name__)

class DefinedGeWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    Adapter for DefinedGe WebSocket streaming, suitable for OpenAlgo or similar frameworks.
    Each instance is isolated and manages its own DefinedGeWebSocket client.
    """
    def __init__(self):
        super().__init__()  # Initialize base adapter (sets up ZMQ)
        self._ws_client = None
        self._user_id = None
        self._broker_name = "definedge"
        self._auth_config = None
        self._connected = False
        self._lock = threading.RLock()

        # Cache structures - following AliceBlue pattern exactly
        self._ltp_cache = {}  # {(exchange, symbol): ltp_value}
        self._quote_cache = {}  # {(exchange, symbol): full_quote_dict}
        self._depth_cache = {}  # {(exchange, symbol): depth_dict}
        self._symbol_state = {}  # Store last known state for each symbol

        # Mapping from DefinedGe format to OpenAlgo format
        self._definedge_to_openalgo = {}  # {(exchange, token): (exchange, symbol)}

        # Track active subscription modes per symbol
        self._symbol_modes = {}  # {(exchange, token): set of active modes}

    def initialize(self, broker_name: str, user_id: str, auth_data=None):
        """Initialize adapter for a specific user/session."""
        self._broker_name = broker_name.lower()
        self._user_id = user_id

        logger.info(f"Initializing DefinedGe WebSocket adapter for user: {user_id}")

        # Get auth token
        auth_token = get_auth_token()
        if not auth_token:
            logger.error("No auth token found for DefinedGe WebSocket")
            return False

        self._auth_config = auth_token
        return True

    def connect(self):
        """Connect to DefinedGe WebSocket."""
        with self._lock:
            if self._connected:
                logger.info("DefinedGe WebSocket already connected")
                return True

            try:
                # Create WebSocket client
                self._ws_client = DefinedGeWebSocket(self._auth_config)

                # Set up callbacks
                self._ws_client.on_connect = self._on_connect
                self._ws_client.on_disconnect = self._on_disconnect
                self._ws_client.on_error = self._on_error
                self._ws_client.on_tick = self._on_tick
                self._ws_client.on_order_update = self._on_order_update
                self._ws_client.on_depth = self._on_depth

                # Connect
                if self._ws_client.connect():
                    self._connected = True
                    logger.info("DefinedGe WebSocket connected successfully")
                    return True
                else:
                    logger.error("Failed to connect to DefinedGe WebSocket")
                    return False

            except Exception as e:
                logger.error(f"Error connecting to DefinedGe WebSocket: {e}")
                return False

    def disconnect(self):
        """Disconnect from DefinedGe WebSocket."""
        with self._lock:
            if self._ws_client:
                self._ws_client.disconnect()
                self._ws_client = None
            self._connected = False
            logger.info("DefinedGe WebSocket disconnected")

    def _on_connect(self, ws_client):
        """Handle WebSocket connection."""
        logger.info("DefinedGe WebSocket connection established")
        self._connected = True

    def _on_disconnect(self, ws_client, code, reason):
        """Handle WebSocket disconnection."""
        logger.info(f"DefinedGe WebSocket disconnected: {code} - {reason}")
        self._connected = False

    def _on_error(self, ws_client, error):
        """Handle WebSocket error."""
        logger.error(f"DefinedGe WebSocket error: {error}")

    def _on_tick(self, ws_client, tick_data):
        """Handle tick data from DefinedGe WebSocket."""
        try:
            # Transform DefinedGe tick data to OpenAlgo format
            exchange = tick_data.get('e', '')
            token = tick_data.get('tk', '')
            ltp = float(tick_data.get('lp', 0))

            # Get symbol from token mapping
            symbol = self._get_symbol_from_token(exchange, token)
            if not symbol:
                return

            # Update LTP cache
            cache_key = (exchange, symbol)
            self._ltp_cache[cache_key] = ltp

            # Create OpenAlgo format tick
            openalgo_tick = {
                'exchange': exchange,
                'symbol': symbol,
                'ltp': ltp,
                'volume': tick_data.get('v', 0),
                'open': tick_data.get('o', 0),
                'high': tick_data.get('h', 0),
                'low': tick_data.get('l', 0),
                'close': tick_data.get('c', 0),
                'timestamp': tick_data.get('ft', int(time.time()))
            }

            # Update quote cache
            self._quote_cache[cache_key] = openalgo_tick

            # Send via ZMQ
            self._send_tick_data(openalgo_tick)

        except Exception as e:
            logger.error(f"Error processing tick data: {e}")

    def _on_order_update(self, ws_client, order_data):
        """Handle order update from DefinedGe WebSocket."""
        try:
            # Transform DefinedGe order data to OpenAlgo format
            openalgo_order = {
                'order_id': order_data.get('order_id', ''),
                'status': order_data.get('order_status', ''),
                'symbol': order_data.get('tradingsymbol', ''),
                'exchange': order_data.get('exchange', ''),
                'quantity': order_data.get('quantity', '0'),
                'price': order_data.get('price', '0'),
                'filled_qty': order_data.get('filled_qty', '0'),
                'average_price': order_data.get('average_price', '0'),
                'timestamp': int(time.time())
            }

            # Send via ZMQ
            self._send_order_update(openalgo_order)

        except Exception as e:
            logger.error(f"Error processing order update: {e}")

    def _on_depth(self, ws_client, depth_data):
        """Handle market depth data from DefinedGe WebSocket."""
        try:
            exchange = depth_data.get('e', '')
            token = depth_data.get('tk', '')

            # Get symbol from token mapping
            symbol = self._get_symbol_from_token(exchange, token)
            if not symbol:
                return

            # Transform to OpenAlgo depth format
            openalgo_depth = {
                'exchange': exchange,
                'symbol': symbol,
                'bids': [],
                'asks': [],
                'timestamp': int(time.time())
            }

            # Parse bid/ask data (DefinedGe format: bp1, bq1, sp1, sq1, etc.)
            for i in range(1, 6):  # 5 levels of depth
                bid_price = depth_data.get(f'bp{i}')
                bid_qty = depth_data.get(f'bq{i}')
                ask_price = depth_data.get(f'sp{i}')
                ask_qty = depth_data.get(f'sq{i}')

                if bid_price and bid_qty:
                    openalgo_depth['bids'].append({
                        'price': float(bid_price),
                        'quantity': int(bid_qty)
                    })

                if ask_price and ask_qty:
                    openalgo_depth['asks'].append({
                        'price': float(ask_price),
                        'quantity': int(ask_qty)
                    })

            # Update depth cache
            cache_key = (exchange, symbol)
            self._depth_cache[cache_key] = openalgo_depth

            # Send via ZMQ
            self._send_depth_data(openalgo_depth)

        except Exception as e:
            logger.error(f"Error processing depth data: {e}")

    def _get_symbol_from_token(self, exchange, token):
        """Get symbol from token using database lookup."""
        try:
            from database.token_db import get_symbol
            return get_symbol(token, exchange)
        except Exception as e:
            logger.error(f"Error getting symbol for token {token}: {e}")
            return None

    def _get_token_from_symbol(self, symbol, exchange):
        """Get token from symbol using database lookup."""
        try:
            from database.token_db import get_token
            return get_token(symbol, exchange)
        except Exception as e:
            logger.error(f"Error getting token for symbol {symbol}: {e}")
            return None

    def subscribe_symbols(self, symbols, mode='ltp'):
        """Subscribe to symbols for real-time data."""
        if not self._connected or not self._ws_client:
            logger.error("WebSocket not connected. Cannot subscribe.")
            return False

        try:
            # Convert symbols to tokens
            tokens = []
            for symbol_data in symbols:
                exchange = symbol_data['exchange']
                symbol = symbol_data['symbol']

                token = self._get_token_from_symbol(symbol, exchange)
                if token:
                    tokens.append((exchange, token))
                    # Store mapping for reverse lookup
                    self._definedge_to_openalgo[(exchange, token)] = (exchange, symbol)
                else:
                    logger.warning(f"Token not found for {symbol} on {exchange}")

            if not tokens:
                logger.warning("No valid tokens to subscribe")
                return False

            # Subscribe based on mode
            if mode == 'ltp':
                subscription_type = self._ws_client.SUBSCRIPTION_TYPE_TICK
            elif mode == 'depth':
                subscription_type = self._ws_client.SUBSCRIPTION_TYPE_DEPTH
            else:
                subscription_type = self._ws_client.SUBSCRIPTION_TYPE_TICK

            success = self._ws_client.subscribe(subscription_type, tokens)

            if success:
                # Track subscriptions
                for exchange, token in tokens:
                    key = (exchange, token)
                    if key not in self._symbol_modes:
                        self._symbol_modes[key] = set()
                    self._symbol_modes[key].add(mode)

                logger.info(f"Subscribed to {len(tokens)} symbols in {mode} mode")

            return success

        except Exception as e:
            logger.error(f"Error subscribing to symbols: {e}")
            return False

    def unsubscribe_symbols(self, symbols, mode='ltp'):
        """Unsubscribe from symbols."""
        if not self._connected or not self._ws_client:
            logger.error("WebSocket not connected. Cannot unsubscribe.")
            return False

        try:
            # Convert symbols to tokens
            tokens = []
            for symbol_data in symbols:
                exchange = symbol_data['exchange']
                symbol = symbol_data['symbol']

                token = self._get_token_from_symbol(symbol, exchange)
                if token:
                    tokens.append((exchange, token))

            if not tokens:
                logger.warning("No valid tokens to unsubscribe")
                return False

            # Unsubscribe based on mode
            if mode == 'ltp':
                subscription_type = self._ws_client.SUBSCRIPTION_TYPE_TICK
            elif mode == 'depth':
                subscription_type = self._ws_client.SUBSCRIPTION_TYPE_DEPTH
            else:
                subscription_type = self._ws_client.SUBSCRIPTION_TYPE_TICK

            success = self._ws_client.unsubscribe(subscription_type, tokens)

            if success:
                # Update subscription tracking
                for exchange, token in tokens:
                    key = (exchange, token)
                    if key in self._symbol_modes:
                        self._symbol_modes[key].discard(mode)
                        if not self._symbol_modes[key]:
                            del self._symbol_modes[key]

                logger.info(f"Unsubscribed from {len(tokens)} symbols in {mode} mode")

            return success

        except Exception as e:
            logger.error(f"Error unsubscribing from symbols: {e}")
            return False

    def get_ltp(self, exchange, symbol):
        """Get last traded price from cache."""
        cache_key = (exchange, symbol)
        return self._ltp_cache.get(cache_key)

    def get_quote(self, exchange, symbol):
        """Get full quote from cache."""
        cache_key = (exchange, symbol)
        return self._quote_cache.get(cache_key)

    def get_depth(self, exchange, symbol):
        """Get market depth from cache."""
        cache_key = (exchange, symbol)
        return self._depth_cache.get(cache_key)

    def is_connected(self):
        """Check if WebSocket is connected."""
        return self._connected and self._ws_client and self._ws_client.is_connected()

    def get_subscriptions(self):
        """Get current subscriptions."""
        return dict(self._symbol_modes)

    def cleanup(self):
        """Cleanup resources."""
        self.disconnect()
        super().cleanup()
