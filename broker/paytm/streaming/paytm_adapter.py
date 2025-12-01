import threading
import json
import logging
import time
from typing import Dict, Any, Optional, List

from broker.paytm.streaming.paytm_websocket import PaytmWebSocket
from database.auth_db import get_auth_token, get_feed_token
from database.token_db import get_token, get_symbol, get_br_symbol

import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .paytm_mapping import PaytmExchangeMapper, PaytmCapabilityRegistry


class PaytmWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Paytm-specific implementation of the WebSocket adapter"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("paytm_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "paytm"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()
        # Map to track scripId -> (symbol, exchange) for reverse lookup
        self.token_map = {}

    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with Paytm WebSocket API

        Args:
            broker_name: Name of the broker (always 'paytm' in this case)
            user_id: Client ID/user ID
            auth_data: If provided, use these credentials instead of fetching from DB

        Raises:
            ValueError: If required authentication tokens are not found
        """
        self.user_id = user_id
        self.broker_name = broker_name

        # Get tokens from database if not provided
        if not auth_data:
            # Fetch public_access_token from feed_token in database
            # Paytm stores public_access_token as feed_token for WebSocket streaming
            public_access_token = get_feed_token(user_id)

            if not public_access_token:
                self.logger.error(f"No public access token (feed_token) found for user {user_id}")
                raise ValueError(f"No public access token found for user {user_id}. Please re-authenticate.")
        else:
            # Use provided token (can be either public_access_token or access_token)
            public_access_token = auth_data.get('public_access_token') or auth_data.get('feed_token')

            if not public_access_token:
                self.logger.error("Missing required public access token")
                raise ValueError("Missing required public access token")

        # Create PaytmWebSocket instance
        self.ws_client = PaytmWebSocket(
            public_access_token=public_access_token,
            max_retry_attempt=5
        )

        # Set callbacks
        self.ws_client.on_open = self._on_open
        self.ws_client.on_data = self._on_data
        self.ws_client.on_error = self._on_error
        self.ws_client.on_close = self._on_close
        self.ws_client.on_message = self._on_message

        self.running = True

    def connect(self) -> None:
        """Establish connection to Paytm WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        threading.Thread(target=self._connect_with_retry, daemon=True).start()

    def _connect_with_retry(self) -> None:
        """Connect to Paytm WebSocket with retry logic"""
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.logger.info(f"Connecting to Paytm WebSocket (attempt {self.reconnect_attempts + 1})")
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
        """Disconnect from Paytm WebSocket"""
        self.running = False
        if hasattr(self, 'ws_client') and self.ws_client:
            self.ws_client.close_connection()

        # Clean up ZeroMQ resources
        self.cleanup_zmq()

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data with Paytm-specific implementation

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Full (Depth)
            depth_level: Market depth level (only 5 supported for Paytm)

        Returns:
            Dict: Response with status and error message if applicable
        """
        # Validate the mode
        if mode not in [1, 2, 3]:
            return self._create_error_response("INVALID_MODE",
                                              f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Full)")

        # If depth mode, check if supported depth level
        if mode == 3 and depth_level not in [5]:
            return self._create_error_response("INVALID_DEPTH",
                                              f"Invalid depth level {depth_level}. Paytm supports only 5 levels")

        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND",
                                              f"Symbol {symbol} not found for exchange {exchange}")

        token = token_info['token']
        brexchange = token_info['brexchange']

        # Map mode to Paytm mode type
        mode_map = {
            1: PaytmWebSocket.MODE_LTP,
            2: PaytmWebSocket.MODE_QUOTE,
            3: PaytmWebSocket.MODE_FULL
        }
        mode_type = mode_map.get(mode)

        # Determine scrip type based on exchange and instrument
        # This is a simplified approach - you may need to enhance this based on your token database
        scrip_type = self._determine_scrip_type(symbol, exchange)

        # Create preference for Paytm API
        preference = {
            "actionType": PaytmWebSocket.ADD_ACTION,
            "modeType": mode_type,
            "scripType": scrip_type,
            "exchangeType": PaytmExchangeMapper.get_exchange_type(brexchange),
            "scripId": str(token)
        }

        # Generate unique correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Store subscription for reconnection and reverse lookup
        with self.lock:
            self.subscriptions[correlation_id] = {
                'symbol': symbol,
                'exchange': exchange,
                'brexchange': brexchange,
                'token': token,
                'mode': mode,
                'depth_level': depth_level,
                'preference': preference
            }
            # Store token mapping for reverse lookup
            self.token_map[str(token)] = (symbol, exchange, mode)
            self.logger.info(f"Subscribed: token={token}, symbol={symbol}, exchange={exchange}, preference={preference}")

        # Subscribe if connected
        if self.connected and self.ws_client:
            try:
                self.ws_client.subscribe([preference])
            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

        # Return success
        return self._create_success_response(
            f'Subscribed to {symbol}.{exchange}',
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

        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Get the stored subscription
        with self.lock:
            subscription = self.subscriptions.get(correlation_id)
            if not subscription:
                return self._create_error_response("NOT_SUBSCRIBED",
                                                  f"Not subscribed to {symbol}.{exchange}")

            # Create unsubscribe preference
            preference = subscription['preference'].copy()
            preference['actionType'] = PaytmWebSocket.REMOVE_ACTION

            # Remove from subscriptions
            del self.subscriptions[correlation_id]
            # Remove from token map
            if str(token) in self.token_map:
                del self.token_map[str(token)]

        # Unsubscribe if connected
        if self.connected and self.ws_client:
            try:
                self.ws_client.unsubscribe([preference])
            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode
        )

    def _determine_scrip_type(self, symbol: str, exchange: str) -> str:
        """
        Determine Paytm scrip type based on symbol and exchange

        Args:
            symbol: Trading symbol
            exchange: Exchange code

        Returns:
            str: Paytm scrip type (INDEX, EQUITY, ETF, FUTURE, OPTION)
        """
        # Index exchange - all symbols on these exchanges are indices
        if exchange in ['NSE_INDEX', 'BSE_INDEX']:
            return PaytmWebSocket.SCRIP_INDEX

        # Index symbols on NSE/BSE
        if exchange in ['NSE', 'BSE'] and (symbol.startswith('NIFTY') or symbol.startswith('SENSEX') or
                                           symbol.startswith('BANKNIFTY') or symbol.startswith('FINNIFTY')):
            return PaytmWebSocket.SCRIP_INDEX

        # Derivatives
        if exchange in ['NFO', 'BFO']:
            # Check if it's an option or future
            # This is a simplified check - enhance based on your symbol naming convention
            if 'CE' in symbol or 'PE' in symbol:
                return PaytmWebSocket.SCRIP_OPTION
            else:
                return PaytmWebSocket.SCRIP_FUTURE

        # ETF check - you may need to enhance this based on your database
        if 'ETF' in symbol.upper():
            return PaytmWebSocket.SCRIP_ETF

        # Default to equity
        return PaytmWebSocket.SCRIP_EQUITY

    def _on_open(self, wsapp) -> None:
        """Callback when connection is established"""
        self.logger.info("Connected to Paytm WebSocket")
        self.connected = True

        # Resubscribe to existing subscriptions if reconnecting
        with self.lock:
            if self.subscriptions:
                preferences = [sub['preference'] for sub in self.subscriptions.values()]
                try:
                    self.ws_client.subscribe(preferences)
                    self.logger.info(f"Resubscribed to {len(preferences)} preferences")
                except Exception as e:
                    self.logger.error(f"Error resubscribing: {e}")

    def _on_error(self, wsapp, error) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"Paytm WebSocket error: {error}")

    def _on_close(self, wsapp) -> None:
        """Callback when connection is closed"""
        self.logger.info("Paytm WebSocket connection closed")
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
            self.logger.debug(f"RAW PAYTM DATA: {message}")

            # Check if we have a security_id to map back to symbol
            security_id = str(message.get('security_id', ''))

            if not security_id:
                self.logger.warning("Received data without security_id")
                return

            # Find the subscription that matches this security_id
            subscription_info = self.token_map.get(security_id)
            if not subscription_info:
                self.logger.warning(f"Received data for untracked security_id: {security_id}. Token map keys: {list(self.token_map.keys())}")
                return

            symbol, exchange, mode = subscription_info

            # Map subscription mode from message
            subscription_mode = message.get('subscription_mode', mode)
            mode_str = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}.get(subscription_mode, 'QUOTE')

            # Create topic for ZeroMQ
            topic = f"{exchange}_{symbol}_{mode_str}"

            # Normalize the data
            market_data = self._normalize_market_data(message, subscription_mode)

            # Add metadata
            market_data.update({
                'symbol': symbol,
                'exchange': exchange,
                'mode': subscription_mode,
                'timestamp': int(time.time() * 1000)  # Current timestamp in ms
            })

            # Log the market data we're sending
            self.logger.debug(f"Publishing market data: {market_data}")

            # Publish to ZeroMQ
            self.publish_market_data(topic, market_data)

        except Exception as e:
            self.logger.error(f"Error processing market data: {e}", exc_info=True)

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
                'ltp': round(message.get('last_price', 0), 2),
                'ltt': message.get('last_traded_time', 0) or message.get('last_update_time', 0),
                'change_absolute': round(message.get('change_absolute', 0), 2),
                'change_percent': round(message.get('change_percent', 0), 2)
            }
        elif mode == 2:  # Quote mode
            result = {
                'ltp': round(message.get('last_price', 0), 2),
                'ltt': message.get('last_traded_time', 0),
                'volume': message.get('volume_traded', 0),
                'open': round(message.get('open', 0), 2),
                'high': round(message.get('high', 0), 2),
                'low': round(message.get('low', 0), 2),
                'close': round(message.get('close', 0), 2),
                'last_trade_quantity': message.get('last_traded_quantity', 0),
                'average_price': round(message.get('average_traded_price', 0), 2),
                'total_buy_quantity': message.get('total_buy_quantity', 0),
                'total_sell_quantity': message.get('total_sell_quantity', 0),
                'change_absolute': round(message.get('change_absolute', 0), 2),
                'change_percent': round(message.get('change_percent', 0), 2),
                '52_week_high': round(message.get('52_week_high', 0), 2),
                '52_week_low': round(message.get('52_week_low', 0), 2)
            }
            return result
        elif mode == 3:  # Full mode (includes depth data)
            result = {
                'ltp': round(message.get('last_price', 0), 2),
                'ltt': message.get('last_traded_time', 0),
                'volume': message.get('volume_traded', 0),
                'open': round(message.get('open', 0), 2),
                'high': round(message.get('high', 0), 2),
                'low': round(message.get('low', 0), 2),
                'close': round(message.get('close', 0), 2),
                'last_quantity': message.get('last_traded_quantity', 0),
                'average_price': round(message.get('average_traded_price', 0), 2),
                'total_buy_quantity': message.get('total_buy_quantity', 0),
                'total_sell_quantity': message.get('total_sell_quantity', 0),
                'change_absolute': round(message.get('change_absolute', 0), 2),
                'change_percent': round(message.get('change_percent', 0), 2),
                '52_week_high': round(message.get('52_week_high', 0), 2),
                '52_week_low': round(message.get('52_week_low', 0), 2)
            }

            # Add OI for derivatives
            if 'oi' in message:
                result['oi'] = message.get('oi', 0)
                result['oi_change'] = message.get('oi_change', 0)

            # Add depth data if available - format prices to 2 decimals
            if 'depth' in message:
                depth = message['depth']
                result['depth'] = {
                    'buy': [
                        {
                            'price': round(level['price'], 2),
                            'quantity': level['quantity'],
                            'orders': level['orders']
                        }
                        for level in depth.get('buy', [])
                    ],
                    'sell': [
                        {
                            'price': round(level['price'], 2),
                            'quantity': level['quantity'],
                            'orders': level['orders']
                        }
                        for level in depth.get('sell', [])
                    ]
                }

            return result
        else:
            return {}
