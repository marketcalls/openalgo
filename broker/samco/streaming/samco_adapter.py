import threading
import json
import logging
import time
from typing import Dict, Any, Optional, List

from broker.samco.streaming.samcoWebSocket import SamcoWebSocket
from database.auth_db import get_auth_token

import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .samco_mapping import SamcoExchangeMapper, SamcoCapabilityRegistry


class SamcoWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Samco-specific implementation of the WebSocket adapter"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("samco_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "samco"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()

    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with Samco WebSocket API

        Args:
            broker_name: Name of the broker (always 'samco' in this case)
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
            session_token = get_auth_token(user_id)

            if not session_token:
                self.logger.error(f"No authentication token found for user {user_id}")
                raise ValueError(f"No authentication token found for user {user_id}")
        else:
            # Use provided tokens
            session_token = auth_data.get('session_token') or auth_data.get('auth_token')

            if not session_token:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data (session_token)")

        # Create SamcoWebSocket instance
        self.ws_client = SamcoWebSocket(
            session_token=session_token,
            user_id=user_id
        )

        # Set callbacks
        self.ws_client.on_open = self._on_open
        self.ws_client.on_data = self._on_data
        self.ws_client.on_error = self._on_error
        self.ws_client.on_close = self._on_close
        self.ws_client.on_message = self._on_message

        self.running = True

    def connect(self) -> None:
        """Establish connection to Samco WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        threading.Thread(target=self._connect_with_retry, daemon=True).start()

    def _connect_with_retry(self) -> None:
        """Connect to Samco WebSocket with retry logic"""
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.logger.info(f"Connecting to Samco WebSocket (attempt {self.reconnect_attempts + 1})")
                self.ws_client.connect()
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
        """Disconnect from Samco WebSocket"""
        self.running = False
        if hasattr(self, 'ws_client') and self.ws_client:
            self.ws_client.close_connection()

        # Clean up ZeroMQ resources
        self.cleanup_zmq()

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data with Samco-specific implementation

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Snap Quote (Depth)
            depth_level: Market depth level (5)

        Returns:
            Dict: Response with status and error message if applicable
        """
        # Validate the mode
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

        if mode == 3:  # Snap Quote mode (includes depth data)
            if not SamcoCapabilityRegistry.is_depth_level_supported(exchange, depth_level):
                # If requested depth is not supported, use the highest available
                actual_depth = SamcoCapabilityRegistry.get_fallback_depth_level(
                    exchange, depth_level
                )
                is_fallback = True

                self.logger.info(
                    f"Depth level {depth_level} not supported for {exchange}, "
                    f"using {actual_depth} instead"
                )

        # Create token list for Samco API
        # Samco uses symbol names with exchange
        token_list = [{
            "exchangeType": SamcoExchangeMapper.get_exchange_type(brexchange),
            "tokens": [token]
        }]

        # Generate unique correlation ID that includes mode to prevent overwriting
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
                'token_list': token_list,
                'is_fallback': is_fallback
            }

        # Subscribe if connected
        if self.connected and self.ws_client:
            try:
                self.ws_client.subscribe(correlation_id, mode, token_list)
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

        token = token_info['token']
        brexchange = token_info['brexchange']

        # Create token list for Samco API
        token_list = [{
            "exchangeType": SamcoExchangeMapper.get_exchange_type(brexchange),
            "tokens": [token]
        }]

        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Remove from subscriptions
        with self.lock:
            if correlation_id in self.subscriptions:
                del self.subscriptions[correlation_id]

        # Unsubscribe if connected
        if self.connected and self.ws_client:
            try:
                self.ws_client.unsubscribe(correlation_id, mode, token_list)
            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode
        )

    def _on_open(self, wsapp) -> None:
        """Callback when connection is established"""
        self.logger.info("Connected to Samco WebSocket")
        self.connected = True

        # Resubscribe to existing subscriptions if reconnecting
        with self.lock:
            for correlation_id, sub in self.subscriptions.items():
                try:
                    self.ws_client.subscribe(correlation_id, sub["mode"], sub["token_list"])
                    self.logger.info(f"Resubscribed to {sub['symbol']}.{sub['exchange']}")
                except Exception as e:
                    self.logger.error(f"Error resubscribing to {sub['symbol']}.{sub['exchange']}: {e}")

    def _on_error(self, wsapp, error) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"Samco WebSocket error: {error}")

    def _on_close(self, wsapp) -> None:
        """Callback when connection is closed"""
        self.logger.info("Samco WebSocket connection closed")
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
            # Debug log the raw message data
            self.logger.debug(f"RAW SAMCO DATA: Type: {type(message)}, Data: {message}")

            if not isinstance(message, dict):
                self.logger.warning(f"Received message is not a dictionary: {type(message)}")
                return

            # Extract symbol from the message
            symbol_key = message.get('symbol', '') or message.get('token', '')

            # Find the subscription that matches this symbol
            subscription = None
            with self.lock:
                for sub in self.subscriptions.values():
                    # Match by token or symbol
                    if sub['token'] == symbol_key or sub['symbol'] == symbol_key:
                        subscription = sub
                        break
                    # Try matching with exchange suffix
                    token_with_exchange = f"{sub['token']}_{sub['brexchange']}"
                    if symbol_key == token_with_exchange:
                        subscription = sub
                        break

            if not subscription:
                self.logger.warning(f"Received data for unsubscribed symbol: {symbol_key}")
                return

            # Create topic for ZeroMQ
            symbol = subscription['symbol']
            exchange = subscription['exchange']
            mode = subscription['mode']

            # Get the actual mode from the message
            actual_msg_mode = message.get('subscription_mode', mode)
            mode_str = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}.get(actual_msg_mode, 'QUOTE')
            topic = f"{exchange}_{symbol}_{mode_str}"

            # Normalize the data based on mode
            market_data = self._normalize_market_data(message, actual_msg_mode)

            # Add metadata
            market_data.update({
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'timestamp': int(time.time() * 1000)  # Current timestamp in ms
            })

            # Log the market data we're sending
            self.logger.debug(f"Publishing market data: {market_data}")

            # Publish to ZeroMQ
            self.publish_market_data(topic, market_data)

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
                'ltp': message.get('last_traded_price', 0),
                'ltt': message.get('exchange_timestamp', 0)
            }
        elif mode == 2:  # Quote mode
            return {
                'ltp': message.get('last_traded_price', 0),
                'ltt': message.get('exchange_timestamp', 0),
                'volume': message.get('volume_trade_for_the_day', 0),
                'open': message.get('open_price_of_the_day', 0),
                'high': message.get('high_price_of_the_day', 0),
                'low': message.get('low_price_of_the_day', 0),
                'close': message.get('closed_price', 0),
                'last_trade_quantity': message.get('last_traded_quantity', 0),
                'change': message.get('change', 0),
                'change_percentage': message.get('change_percentage', 0),
                'best_bid_price': message.get('best_bid_price', 0),
                'best_bid_quantity': message.get('best_bid_quantity', 0),
                'best_ask_price': message.get('best_ask_price', 0),
                'best_ask_quantity': message.get('best_ask_quantity', 0)
            }
        elif mode == 3:  # Snap Quote mode (includes depth data)
            result = {
                'ltp': message.get('last_traded_price', 0),
                'ltt': message.get('exchange_timestamp', 0),
                'volume': message.get('volume_trade_for_the_day', 0),
                'open': message.get('open_price_of_the_day', 0),
                'high': message.get('high_price_of_the_day', 0),
                'low': message.get('low_price_of_the_day', 0),
                'close': message.get('closed_price', 0),
                'last_quantity': message.get('last_traded_quantity', 0),
                'change': message.get('change', 0),
                'change_percentage': message.get('change_percentage', 0)
            }

            # Add depth data if available
            if 'best_5_buy_data' in message and 'best_5_sell_data' in message:
                result['depth'] = {
                    'buy': self._extract_depth_data(message, is_buy=True),
                    'sell': self._extract_depth_data(message, is_buy=False)
                }

            return result
        else:
            return {}

    def _extract_depth_data(self, message, is_buy: bool) -> List[Dict[str, Any]]:
        """
        Extract depth data from Samco's message format

        Args:
            message: The raw message containing depth data
            is_buy: Whether to extract buy or sell side

        Returns:
            List: List of depth levels with price, quantity, and orders
        """
        depth = []
        side_label = 'Buy' if is_buy else 'Sell'

        # Get the appropriate depth data key
        depth_key = 'best_5_buy_data' if is_buy else 'best_5_sell_data'
        depth_data = message.get(depth_key, [])

        self.logger.debug(f"Extracting {side_label} depth data: {len(depth_data)} levels")

        for level in depth_data:
            if isinstance(level, dict):
                depth.append({
                    'price': level.get('price', 0),
                    'quantity': level.get('quantity', 0),
                    'orders': level.get('no of orders', 0)
                })

        # Pad to 5 levels if needed
        while len(depth) < 5:
            depth.append({
                'price': 0.0,
                'quantity': 0,
                'orders': 0
            })

        return depth
