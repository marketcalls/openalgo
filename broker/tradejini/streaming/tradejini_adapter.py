import threading
import json
import logging
import time
from typing import Dict, Any, Optional, List
import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from .nxtradstream import NxtradStream
from database.auth_db import get_auth_token
from database.token_db import get_token
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .tradejini_mapping import TradejiniExchangeMapper, TradejiniCapabilityRegistry

class TradejiniWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Tradejini-specific implementation of the WebSocket adapter"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("tradejini_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "tradejini"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()
        self.ws_url = None

    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with Tradejini WebSocket API

        Args:
            broker_name: Name of the broker (always 'tradejini' in this case)
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
            # For Tradejini, the access token is used for both API and WebSocket
            auth_token = get_auth_token(user_id)

            if not auth_token:
                self.logger.error(f"No authentication token found for user {user_id}")
                raise ValueError(f"No authentication token found for user {user_id}")

            # Get API key from environment for Tradejini
            api_key = os.getenv('BROKER_API_SECRET', '')

            # Format token for Tradejini WebSocket (api_key:access_token)
            if api_key and ':' not in auth_token:
                ws_token = f"{api_key}:{auth_token}"
            else:
                ws_token = auth_token

            ws_url = 'api.tradejini.com'
        else:
            # Use provided tokens
            auth_token = auth_data.get('auth_token')
            feed_token = auth_data.get('feed_token', auth_token)  # Use auth_token if feed_token not provided
            ws_url = auth_data.get('ws_url', 'api.tradejini.com')

            if not auth_token:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data")

            # Get API key from environment or auth_data for Tradejini
            api_key = auth_data.get('api_key', os.getenv('BROKER_API_SECRET', ''))

            # Format token for Tradejini WebSocket (api_key:access_token)
            if api_key and ':' not in auth_token:
                ws_token = f"{api_key}:{auth_token}"
            else:
                ws_token = auth_token

        # Store WebSocket URL
        self.ws_url = ws_url

        # Create NxtradStream instance
        self.ws_client = NxtradStream(
            url=ws_url,
            version='3.1',
            stream_cb=self._on_data,
            connect_cb=self._on_connection_event
        )

        # Store the token for connection
        self.ws_token = ws_token
        self.running = True

    def connect(self) -> None:
        """Establish connection to Tradejini WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        threading.Thread(target=self._connect_with_retry, daemon=True).start()

    def _connect_with_retry(self) -> None:
        """Connect to Tradejini WebSocket with retry logic"""
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.logger.info(f"Connecting to Tradejini WebSocket (attempt {self.reconnect_attempts + 1})")
                self.ws_client.connect(self.ws_token)
                self.reconnect_attempts = 0  # Reset attempts on successful connection
                break

            except Exception as e:
                self.reconnect_attempts += 1
                delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts), self.max_reconnect_delay)
                self.logger.error(f"Connection failed: {e}. Retrying in {delay} seconds...")
                time.sleep(delay)

        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error("Max reconnection attempts reached. Giving up.")

    def disconnect(self) -> None:
        """Disconnect from Tradejini WebSocket"""
        self.running = False
        if hasattr(self, 'ws_client') and self.ws_client:
            self.ws_client.disconnect()

        # Clean up ZeroMQ resources
        self.cleanup_zmq()

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data with Tradejini-specific implementation

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Depth
            depth_level: Market depth level (5 for Tradejini)

        Returns:
            Dict: Response with status and error message if applicable
        """
        # Validate mode
        if mode not in [1, 2, 3]:
            return self._create_error_response("INVALID_MODE",
                                              f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)")

        # If depth mode, check if supported depth level
        if mode == 3 and depth_level not in [5]:
            return self._create_error_response("INVALID_DEPTH",
                                              f"Invalid depth level {depth_level}. Must be 5")

        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND",
                                              f"Symbol {symbol} not found for exchange {exchange}")

        token = token_info['token']
        brexchange = token_info['brexchange']

        # Check if the requested depth level is supported for this exchange
        is_fallback = False
        actual_depth = depth_level

        if mode == 3:  # Depth mode
            if not TradejiniCapabilityRegistry.is_depth_level_supported(exchange, depth_level):
                # If requested depth is not supported, use the highest available
                actual_depth = TradejiniCapabilityRegistry.get_fallback_depth_level(
                    exchange, depth_level
                )
                is_fallback = True

                self.logger.info(
                    f"Depth level {depth_level} not supported for {exchange}, "
                    f"using {actual_depth} instead"
                )

        # Generate unique correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"
        if mode == 3:
            correlation_id = f"{correlation_id}_{depth_level}"

        # Store subscription for reconnection
        with self.lock:
            self.subscriptions[correlation_id] = {
                'symbol': symbol,
                'exchange': exchange,
                'brexchange': brexchange,
                'token': token,
                'mode': mode,
                'depth_level': depth_level,
                'actual_depth': actual_depth,
                'is_fallback': is_fallback
            }

        # Subscribe if connected
        if self.connected and self.ws_client:
            try:
                # Create token string with exchange segment
                token_str = f"{token}_{brexchange}"

                self.logger.info(f"Subscribing to {symbol} with token {token} on {brexchange} (token_str: {token_str})")

                # Subscribe based on mode
                if mode == 1:
                    # LTP mode - use L1 subscription
                    self.ws_client.subscribeL1([token_str])
                elif mode == 2:
                    # Quote mode - use L1 subscription (full quote)
                    self.ws_client.subscribeL1([token_str])
                elif mode == 3:
                    # Depth mode - use L5 subscription (5 level depth)
                    self.ws_client.subscribeL2([token_str])

            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

        # Return success with capability info
        return self._create_success_response(
            'Subscription requested' if not is_fallback else f"Using depth level {actual_depth} instead of requested {depth_level}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            requested_depth=depth_level,
            actual_depth=actual_depth,
            is_fallback=is_fallback
        )

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> Dict[str, Any]:
        """
        Unsubscribe from market data

        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Subscription mode

        Returns:
            Dict: Response with status
        """
        # Map symbol to token
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND",
                                              f"Symbol {symbol} not found for exchange {exchange}")

        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Remove from subscriptions
        with self.lock:
            if correlation_id in self.subscriptions:
                del self.subscriptions[correlation_id]

        # Unsubscribe if connected
        if self.connected and self.ws_client:
            try:
                # Tradejini unsubscribes from all tokens for a given type
                if mode in [1, 2]:
                    self.ws_client.unsubscribeL1()
                elif mode == 3:
                    self.ws_client.unsubscribeL2()

            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode
        )

    def _on_connection_event(self, ws, message) -> None:
        """Callback for connection events"""
        status = message.get('s')

        if status == 'connected':
            self.logger.info("Connected to Tradejini WebSocket")
            self.connected = True

            # Resubscribe to existing subscriptions if reconnecting
            with self.lock:
                for correlation_id, sub in self.subscriptions.items():
                    try:
                        token_str = f"{sub['token']}_{sub['brexchange']}"

                        self.logger.info(f"Resubscribing to {sub['symbol']} with token {sub['token']} on {sub['brexchange']} (token_str: {token_str})")

                        if sub['mode'] in [1, 2]:
                            self.ws_client.subscribeL1([token_str])
                        elif sub['mode'] == 3:
                            self.ws_client.subscribeL2([token_str])

                        self.logger.info(f"Resubscribed to {sub['symbol']}.{sub['exchange']} with correlation_id: {correlation_id}")
                    except Exception as e:
                        self.logger.error(f"Error resubscribing to {sub['symbol']}.{sub['exchange']}: {e}")

        elif status == 'error':
            self.logger.error(f"Tradejini WebSocket error: {message.get('reason')}")

        elif status == 'closed':
            self.logger.info(f"Tradejini WebSocket connection closed: {message.get('reason')}")
            self.connected = False

            # Attempt to reconnect if we're still running
            if self.running:
                threading.Thread(target=self._connect_with_retry, daemon=True).start()

    def _on_data(self, ws, message) -> None:
        """Callback for market data from the WebSocket"""
        try:
            # Debug log the raw message data
            self.logger.debug(f"RAW TRADEJINI DATA: Type={type(message)}, Data={message}")

            # Extract message type
            msg_type = message.get('msgType')

            # Check for authentication message
            if msg_type == 'auth':
                auth_status = message.get('auth_status')
                if auth_status == 1:
                    self.logger.info("Successfully authenticated with Tradejini WebSocket")
                else:
                    self.logger.error(f"Authentication failed with Tradejini WebSocket: {message}")
                return

            # Check for ping/pong messages
            if msg_type in ['PING', 'pong']:
                self.logger.debug(f"Received {msg_type} message")
                return

            # Check for event messages
            if msg_type == 'EVENTS':
                self.logger.info(f"Received event message: {message.get('message', '')}")
                return

            if not msg_type:
                self.logger.warning(f"Received message without msgType: {message}")
                return

            # Extract symbol and exchange from the message
            symbol_str = message.get('symbol', '')
            if not symbol_str:
                self.logger.warning(f"Received message without symbol: {message}")
                return

            # Symbol format is "token_exchSeg" (e.g., "11536_NSE")
            parts = symbol_str.split('_')
            if len(parts) != 2:
                self.logger.warning(f"Invalid symbol format: {symbol_str}")
                return

            token = str(parts[0])  # Ensure token is string
            brexchange = parts[1]

            # Find ALL subscriptions that match this token
            matching_subscriptions = []
            with self.lock:
                for sub in self.subscriptions.values():
                    # Compare both as strings to ensure match
                    if str(sub['token']) == token and sub['brexchange'] == brexchange:
                        matching_subscriptions.append(sub)

            if not matching_subscriptions:
                self.logger.info(f"Received data for unsubscribed token: {token} on {brexchange}. Active subscriptions: {list(self.subscriptions.keys())}")
                return

            # Process data for each matching subscription (different modes for same symbol)
            for subscription in matching_subscriptions:
                # Create topic for ZeroMQ
                symbol = subscription['symbol']
                exchange = subscription['exchange']
                subscription_mode = subscription['mode']

                # Determine which data to send based on message type and subscription mode
                # L1 messages contain both LTP and Quote data
                # L5 messages contain depth data
                should_publish = False

                if msg_type == 'L1':
                    # L1 data can be used for both LTP and Quote modes
                    if subscription_mode in [1, 2]:  # LTP or Quote
                        should_publish = True
                elif msg_type == 'L5' or msg_type == 'L2':
                    # L5/L2 data is for depth mode
                    if subscription_mode == 3:  # Depth
                        should_publish = True

                if not should_publish:
                    continue

                # Map subscription mode to topic string
                if subscription_mode == 1:
                    mode_str = 'LTP'
                    actual_mode = 1
                elif subscription_mode == 2:
                    mode_str = 'QUOTE'
                    actual_mode = 2
                elif subscription_mode == 3:
                    mode_str = 'DEPTH'
                    actual_mode = 3
                else:
                    self.logger.warning(f"Unknown subscription mode: {subscription_mode}")
                    continue

                # Topic format: EXCHANGE_SYMBOL_MODE (like Angel adapter)
                topic = f"{exchange}_{symbol}_{mode_str}"

                # Normalize the data based on subscription mode
                market_data = self._normalize_market_data(message, actual_mode)

                # Add metadata
                market_data.update({
                    'symbol': symbol,
                    'exchange': exchange,
                    'mode': subscription_mode,
                    'timestamp': int(time.time() * 1000)  # Current timestamp in ms
                })

                # Log the market data we're sending
                self.logger.info(f"Publishing to topic '{topic}': {market_data}")

                # Publish to ZeroMQ
                try:
                    self.publish_market_data(topic, market_data)
                    # Debug: Log that we've sent the data
                    self.logger.debug(f"Data published successfully to ZeroMQ on port {self.zmq_port}")
                except Exception as zmq_error:
                    self.logger.error(f"Failed to publish to ZeroMQ: {zmq_error}")

        except Exception as e:
            self.logger.error(f"Error processing market data: {e}", exc_info=True)

    def _normalize_market_data(self, message, mode) -> Dict[str, Any]:
        """
        Normalize broker-specific data format to a common format

        Args:
            message: The raw message from the broker
            mode: Subscription mode

        Returns:
            Dict: Normalized market data
        """
        if mode == 1:  # LTP mode
            return {
                'ltp': message.get('ltp', 0),
                'ltt': message.get('ltt', '')  # Keep as string like depth mode
            }
        elif mode == 2:  # Quote mode
            result = {
                'ltp': message.get('ltp', 0),
                'ltt': message.get('ltt'),
                'volume': message.get('vol', 0),
                'open': message.get('open', 0),
                'high': message.get('high', 0),
                'low': message.get('low', 0),
                'close': message.get('close', 0),
                'last_quantity': message.get('ltq', 0),
                'average_price': message.get('atp', 0),
                'total_buy_quantity': message.get('totBuyQty', 0),
                'total_sell_quantity': message.get('totSellQty', 0),
                'oi': message.get('OI', 0),
                'change': message.get('chng', 0),
                'change_percent': message.get('chngPer', 0)
            }
            return result
        elif mode == 3:  # Depth mode
            result = {
                'ltp': message.get('ltp', 0),
                'ltt': message.get('ltt'),
                'volume': message.get('vol', 0),
                'open': message.get('open', 0),
                'high': message.get('high', 0),
                'low': message.get('low', 0),
                'close': message.get('close', 0),
                'oi': message.get('OI', 0),
                'upper_circuit': message.get('ucl', 0),
                'lower_circuit': message.get('lcl', 0),
                'total_buy_quantity': message.get('totBuyQty', 0),
                'total_sell_quantity': message.get('totSellQty', 0)
            }

            # Add depth data if available
            if 'bid' in message and 'ask' in message:
                result['depth'] = {
                    'buy': self._extract_depth_data(message.get('bid', [])),
                    'sell': self._extract_depth_data(message.get('ask', []))
                }

            return result
        else:
            return {}

    def _extract_depth_data(self, depth_list) -> List[Dict[str, Any]]:
        """
        Extract depth data from Tradejini's message format

        Args:
            depth_list: List of depth levels from the message

        Returns:
            List: List of depth levels with price, quantity, and orders
        """
        depth = []

        for level in depth_list:
            if isinstance(level, dict):
                depth.append({
                    'price': level.get('price', 0),
                    'quantity': level.get('qty', 0),
                    'orders': level.get('no', 0)
                })

        # If no depth data found, return empty levels as fallback
        if not depth:
            for i in range(5):  # Default to 5 empty levels
                depth.append({
                    'price': 0.0,
                    'quantity': 0,
                    'orders': 0
                })

        return depth