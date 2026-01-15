import threading
import json
import logging
import time
import os
import re
from datetime import datetime
from typing import Dict, Any, Optional, List

from broker.fivepaisa.streaming.fivepaisa_websocket import FivePaisaWebSocket
from database.auth_db import get_auth_token
from database.token_db import get_token

import sys

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .fivepaisa_mapping import FivePaisaExchangeMapper, FivePaisaCapabilityRegistry


class FivepaisaWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """5Paisa-specific implementation of the WebSocket adapter"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("fivepaisa_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "fivepaisa"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()
        self.last_snapshot = {}  # Store last known values for each token

    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with 5Paisa WebSocket API

        Args:
            broker_name: Name of the broker (always 'fivepaisa' in this case)
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
            access_token = get_auth_token(user_id)

            if not access_token:
                self.logger.error(f"No authentication token found for user {user_id}")
                raise ValueError(f"No authentication token found for user {user_id}")

            # Get client_id from BROKER_API_KEY environment variable
            # Format: api_key:::user_id:::client_id
            broker_api_key = os.getenv('BROKER_API_KEY')
            if broker_api_key:
                try:
                    parts = broker_api_key.split(':::')
                    if len(parts) >= 3:
                        client_code = parts[2]  # client_id is the third part
                        self.logger.debug(f"Using client_code from BROKER_API_KEY: {client_code}")
                    else:
                        client_code = user_id
                        self.logger.warning(f"BROKER_API_KEY format incorrect, using user_id as client_code")
                except Exception as e:
                    self.logger.error(f"Error parsing BROKER_API_KEY: {e}")
                    client_code = user_id
            else:
                client_code = user_id
                self.logger.warning("BROKER_API_KEY not found, using user_id as client_code")
        else:
            # Use provided tokens
            access_token = auth_data.get('access_token')
            client_code = auth_data.get('client_code', user_id)

            if not access_token:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data")

        # Create FivePaisaWebSocket instance
        self.ws_client = FivePaisaWebSocket(
            access_token=access_token,
            client_code=client_code
        )

        # Set callbacks
        self.ws_client.on_open = self._on_open
        self.ws_client.on_data = self._on_data
        self.ws_client.on_error = self._on_error
        self.ws_client.on_close = self._on_close
        self.ws_client.on_message = self._on_message

        self.running = True

    def connect(self) -> None:
        """Establish connection to 5Paisa WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        threading.Thread(target=self._connect_with_retry, daemon=True).start()

    def _connect_with_retry(self) -> None:
        """Connect to 5Paisa WebSocket with retry logic"""
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.logger.info(f"Connecting to 5Paisa WebSocket (attempt {self.reconnect_attempts + 1})")
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
        """Disconnect from 5Paisa WebSocket"""
        self.running = False
        if hasattr(self, 'ws_client') and self.ws_client:
            self.ws_client.close_connection()

        # Clean up ZeroMQ resources
        self.cleanup_zmq()

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data with 5Paisa-specific implementation

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Depth
            depth_level: Market depth level (5 for 5Paisa)

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
                                              f"Invalid depth level {depth_level}. 5Paisa only supports 5 levels")

        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND",
                                              f"Symbol {symbol} not found for exchange {exchange}")

        token = token_info['token']
        brexchange = token_info['brexchange']

        # Get 5Paisa-specific exchange code and type
        exch_code = FivePaisaExchangeMapper.get_exchange_code(brexchange)
        exch_type = FivePaisaExchangeMapper.get_exchange_type(brexchange)

        # Create scrip data for 5Paisa API
        scrip_data = [{
            "Exch": exch_code,
            "ExchType": exch_type,
            "ScripCode": int(token)
        }]

        # Get the appropriate method for the mode
        method = FivePaisaCapabilityRegistry.get_method_for_mode(mode)

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
                'method': method,
                'scrip_data': scrip_data
            }

        # Subscribe if connected
        if self.connected and self.ws_client:
            try:
                self.logger.info(f"Subscribing to {symbol} ({exchange}/{brexchange}) - Token: {token}, Method: {method}, Exch: {exch_code}, Type: {exch_type}")
                self.ws_client.subscribe(method, scrip_data)
                self.logger.info(f"Successfully sent subscription request for {symbol}.{exchange}")
            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

        # Return success
        return self._create_success_response(
            'Subscription requested',
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            depth_level=depth_level
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

        # Get 5Paisa-specific exchange code and type
        exch_code = FivePaisaExchangeMapper.get_exchange_code(brexchange)
        exch_type = FivePaisaExchangeMapper.get_exchange_type(brexchange)

        # Create scrip data
        scrip_data = [{
            "Exch": exch_code,
            "ExchType": exch_type,
            "ScripCode": int(token)
        }]

        # Get the appropriate method for the mode
        method = FivePaisaCapabilityRegistry.get_method_for_mode(mode)

        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Remove from subscriptions
        with self.lock:
            if correlation_id in self.subscriptions:
                del self.subscriptions[correlation_id]

        # Unsubscribe if connected
        if self.connected and self.ws_client:
            try:
                self.ws_client.unsubscribe(method, scrip_data)
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
        self.logger.info("Connected to 5Paisa WebSocket")
        self.connected = True

        # Resubscribe to existing subscriptions if reconnecting
        with self.lock:
            for correlation_id, sub in self.subscriptions.items():
                try:
                    self.ws_client.subscribe(sub["method"], sub["scrip_data"])
                    self.logger.info(f"Resubscribed to {sub['symbol']}.{sub['exchange']}")
                except Exception as e:
                    self.logger.error(f"Error resubscribing to {sub['symbol']}.{sub['exchange']}: {e}")

    def _on_error(self, wsapp, error) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"5Paisa WebSocket error: {error}")

    def _on_close(self, wsapp) -> None:
        """Callback when connection is closed"""
        self.logger.info("5Paisa WebSocket connection closed")
        self.connected = False

        # Attempt to reconnect if we're still running
        if self.running:
            threading.Thread(target=self._connect_with_retry, daemon=True).start()

    def _on_message(self, wsapp, message) -> None:
        """Callback for text messages from the WebSocket"""
        self.logger.debug(f"Received message: {message}")

    def _on_data(self, wsapp, message: Dict) -> None:
        """Callback for market data from the WebSocket"""
        try:
            self.logger.debug(f"RAW 5PAISA DATA: {message}")

            # Extract token from message
            token = str(message.get('Token'))

            # Find ALL subscriptions that match this token
            # Fivepaisa sends one message that should update all modes subscribed to that token
            matching_subscriptions = []
            with self.lock:
                for sub in self.subscriptions.values():
                    if str(sub['token']) == token:
                        matching_subscriptions.append(sub)

            if not matching_subscriptions:
                self.logger.warning(f"Received data for unsubscribed token: {token}")
                return

            # Publish data to ALL matching subscriptions
            for subscription in matching_subscriptions:
                # Create topic for ZeroMQ
                symbol = subscription['symbol']
                exchange = subscription['exchange']
                mode = subscription['mode']

                mode_str = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}[mode]
                topic = f"{exchange}_{symbol}_{mode_str}"

                # Apply snapshot logic - merge current message with last known values
                token_key = f"{token}_{mode}"
                message_with_snapshot = self._apply_snapshot(message, token_key)

                # Normalize the data based on the mode
                market_data = self._normalize_market_data(message_with_snapshot, mode)

                # Add metadata
                market_data.update({
                    'symbol': symbol,
                    'exchange': exchange,
                    'mode': mode,
                    'timestamp': int(time.time() * 1000)  # Current timestamp in ms
                })

                # Log the market data we're sending
                self.logger.debug(f"Publishing to topic '{topic}': symbol={symbol}, exchange={exchange}, mode={mode}, ltp={market_data.get('ltp', 'N/A')}")
                self.logger.debug(f"Full market data: {market_data}")

                # Publish to ZeroMQ
                self.publish_market_data(topic, market_data)

        except Exception as e:
            self.logger.error(f"Error processing market data: {e}", exc_info=True)

    def _apply_snapshot(self, message: Dict, token_key: str) -> Dict[str, Any]:
        """
        Apply snapshot logic - merge current message with last known values.
        If current value is 0, use the last known non-zero value.

        Args:
            message: Current market data message
            token_key: Unique key for this token and mode combination

        Returns:
            Dict: Message with snapshot values applied
        """
        # Fields that should use snapshot logic (hold last value if current is 0)
        snapshot_fields = [
            'LastRate', 'OpenRate', 'High', 'Low', 'PClose',
            'BidRate', 'OffRate', 'AvgRate'
        ]

        # Get last snapshot for this token
        last_snapshot = self.last_snapshot.get(token_key, {})

        # Create new message with snapshot values
        merged_message = message.copy()

        for field in snapshot_fields:
            current_value = message.get(field, 0)

            # If current value is 0 or None, use last known value
            if current_value == 0 or current_value is None:
                if field in last_snapshot and last_snapshot[field] != 0:
                    merged_message[field] = last_snapshot[field]
                    self.logger.debug(f"Using snapshot value for {field}: {last_snapshot[field]}")
            else:
                # Update snapshot with new non-zero value
                last_snapshot[field] = current_value

        # Store updated snapshot
        self.last_snapshot[token_key] = last_snapshot

        return merged_message

    def _normalize_market_data(self, message: Dict, mode: int) -> Dict[str, Any]:
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
                'ltp': message.get('LastRate', 0),
                'ltt': self._parse_fivepaisa_time(message.get('TickDt', ''))
            }
        elif mode == 2:  # Quote mode
            return {
                'ltp': message.get('LastRate', 0),
                'ltt': self._parse_fivepaisa_time(message.get('TickDt', '')),
                'volume': message.get('TotalQty', 0),
                'open': message.get('OpenRate', 0),
                'high': message.get('High', 0),
                'low': message.get('Low', 0),
                'close': message.get('PClose', 0),
                'last_trade_quantity': message.get('LastQty', 0),
                'average_price': message.get('AvgRate', 0),
                'total_buy_quantity': message.get('TBidQ', 0),
                'total_sell_quantity': message.get('TOffQ', 0),
                'bid_price': message.get('BidRate', 0),
                'bid_quantity': message.get('BidQty', 0),
                'ask_price': message.get('OffRate', 0),
                'ask_quantity': message.get('OffQty', 0)
            }
        elif mode == 3:  # Depth mode (MarketDepthService)
            result = {
                'ltp': message.get('LastRate', 0),
                'total_buy_quantity': message.get('TBidQ', 0),
                'total_sell_quantity': message.get('TOffQ', 0),
                'timestamp': message.get('Time', '')
            }

            # Add depth data if available
            if 'Details' in message:
                result['depth'] = self._extract_depth_data(message['Details'])

            return result
        else:
            return {}

    def _extract_depth_data(self, details: List[Dict]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract depth data from 5Paisa's message format

        Args:
            details: List of market depth details

        Returns:
            Dict: Dictionary with 'buy' and 'sell' depth arrays
        """
        buy_depth = []
        sell_depth = []

        for detail in details:
            flag = detail.get('BbBuySellFlag', 0)
            depth_item = {
                'price': detail.get('Price', 0),
                'quantity': detail.get('Quantity', 0),
                'orders': detail.get('NumberOfOrders', 0)
            }

            # BbBuySellFlag: 66 (ASCII 'B') = Buy, 83 (ASCII 'S') = Sell
            if flag == 66:  # Buy
                buy_depth.append(depth_item)
            elif flag == 83:  # Sell
                sell_depth.append(depth_item)

        return {
            'buy': buy_depth[:5],  # Limit to 5 levels
            'sell': sell_depth[:5]  # Limit to 5 levels
        }

    def _parse_fivepaisa_time(self, time_str: str) -> int:
        """
        Parse Fivepaisa's Microsoft JSON date format to Unix timestamp in milliseconds

        Args:
            time_str: Time string in format '/Date(1759900055000)/' or '/Date(1759900055000+0530)/'

        Returns:
            int: Unix timestamp in milliseconds, or 0 if parsing fails
        """
        if not time_str:
            return 0

        try:
            # Extract timestamp from /Date(timestamp)/ format
            match = re.search(r'/Date\((\d+)', time_str)
            if match:
                return int(match.group(1))
            return 0
        except Exception as e:
            self.logger.error(f"Error parsing time {time_str}: {e}")
            return 0
