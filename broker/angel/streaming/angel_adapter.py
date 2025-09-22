import threading
import json
import logging
import time
from typing import Dict, Any, Optional, List

from broker.angel.streaming.smartWebSocketV2 import SmartWebSocketV2
from database.auth_db import get_auth_token, get_feed_token
from database.token_db import get_token

import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .angel_mapping import AngelExchangeMapper, AngelCapabilityRegistry

class AngelWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Angel-specific implementation of the WebSocket adapter"""
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("angel_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "angel"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()
    
    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with Angel WebSocket API
        
        Args:
            broker_name: Name of the broker (always 'angel' in this case)
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
            auth_token = get_auth_token(user_id)
            feed_token = get_feed_token(user_id)
            
            if not auth_token or not feed_token:
                self.logger.error(f"No authentication tokens found for user {user_id}")
                raise ValueError(f"No authentication tokens found for user {user_id}")
                
            # Use API key from somewhere, or generate it
            api_key = "api_key"  # This should be retrieved from a secure location
        else:
            # Use provided tokens
            auth_token = auth_data.get('auth_token')
            feed_token = auth_data.get('feed_token')
            api_key = auth_data.get('api_key')
            
            if not auth_token or not feed_token or not api_key:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data")
        
        # Create SmartWebSocketV2 instance
        self.ws_client = SmartWebSocketV2(
            auth_token=auth_token, 
            api_key=api_key, 
            client_code=user_id,  # client_code is the user_id
            feed_token=feed_token,
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
        """Establish connection to Angel WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return
            
        threading.Thread(target=self._connect_with_retry, daemon=True).start()
    
    def _connect_with_retry(self) -> None:
        """Connect to Angel WebSocket with retry logic"""
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.logger.info(f"Connecting to Angel WebSocket (attempt {self.reconnect_attempts + 1})")
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
        """Disconnect from Angel WebSocket"""
        self.running = False
        if hasattr(self, 'ws_client') and self.ws_client:
            self.ws_client.close_connection()
            
        # Clean up ZeroMQ resources
        self.cleanup_zmq()
    
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data with Angel-specific implementation
        
        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Snap Quote (Depth)
            depth_level: Market depth level (5, 20, 30)
            
        Returns:
            Dict: Response with status and error message if applicable
        """
        # Implementation for Angel subscription
        # First validate the mode
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
            if not AngelCapabilityRegistry.is_depth_level_supported(exchange, depth_level):
                # If requested depth is not supported, use the highest available
                actual_depth = AngelCapabilityRegistry.get_fallback_depth_level(
                    exchange, depth_level
                )
                is_fallback = True
                
                self.logger.info(
                    f"Depth level {depth_level} not supported for {exchange}, "
                    f"using {actual_depth} instead"
                )
        
        # Create token list for Angel API
        token_list = [{
            "exchangeType": AngelExchangeMapper.get_exchange_type(brexchange),
            "tokens": [token]
        }]
        
        # Generate unique correlation ID that includes mode to prevent overwriting
        # This ensures each symbol can be subscribed in multiple modes simultaneously
        correlation_id = f"{symbol}_{exchange}_{mode}"
        if mode == 4:
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
        
        # Create token list for Angel API
        token_list = [{
            "exchangeType": AngelExchangeMapper.get_exchange_type(brexchange),
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
        self.logger.info("Connected to Angel WebSocket")
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
        self.logger.error(f"Angel WebSocket error: {error}")
    
    def _on_close(self, wsapp) -> None:
        """Callback when connection is closed"""
        self.logger.info("Angel WebSocket connection closed")
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
            # Debug log the raw message data to see what we're actually receiving
            self.logger.debug(f"RAW ANGEL DATA: Type: {type(message)}, Data: {message}")
            
            # Check if we're getting binary data as per Angel's documentation
            if isinstance(message, bytes) or isinstance(message, bytearray):
                self.logger.debug(f"Received binary data of length: {len(message)}")
                # We need to parse the binary data according to Angel's format
                # For now, we'll log what we have and exit early
                return
                
            # The existing code assumes message is a dictionary, but it might not be
            if not isinstance(message, dict):
                self.logger.warning(f"Received message is not a dictionary: {type(message)}")
                return
                
            # Extract symbol and exchange from our subscriptions using token
            token = message.get('token')
            exchange_type = message.get('exchange_type')
            
            self.logger.debug(f"Processing message with token: {token}, exchange_type: {exchange_type}")
            
            # Find the subscription that matches this token
            subscription = None
            with self.lock:
                for sub in self.subscriptions.values():
                    if sub['token'] == token and AngelExchangeMapper.get_exchange_type(sub['brexchange']) == exchange_type:
                        subscription = sub
                        break
            
            if not subscription:
                self.logger.warning(f"Received data for unsubscribed token: {token}")
                return
            
            # Create topic for ZeroMQ
            symbol = subscription['symbol']
            exchange = subscription['exchange']
            mode = subscription['mode']
            
            # Important: Always use the actual mode from the message rather than the subscription
            # This ensures data is published with the correct mode identifier
            actual_msg_mode = message.get('subscription_mode')
            mode_str = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}[actual_msg_mode]  # Mode 3 is Snap Quote (includes depth data)
            topic = f"{exchange}_{symbol}_{mode_str}"
            
            # Normalize the data based on the actual message mode, not subscription mode
            market_data = self._normalize_market_data(message, actual_msg_mode)
            
            # Add metadata
            market_data.update({
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'timestamp': int(time.time() * 1000)  # Current timestamp in ms
            })
            # Log the market data we're sendingAdd commentMore actions
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
        # Based on the logs, the Angel WebSocket sends a message with this format:
        # {'subscription_mode': 1, 'exchange_type': 1, 'token': '2885', 
        #  'sequence_number': 10100759, 'exchange_timestamp': 1746171226000, 
        #  'last_traded_price': 141840, 'subscription_mode_val': 'LTP'}
        #
        # Prices are in paise (1/100 of a rupee) so we need to divide by 100
        
        if mode == 1:  # LTP mode
            return {
                'ltp': message.get('last_traded_price', 0) / 100,  # Divide by 100 for correct price
                'ltt': message.get('exchange_timestamp', 0)
            }
        elif mode == 2:  # Quote mode
            # Extract additional fields based on what's available in the message
            result = {
                'ltp': message.get('last_traded_price', 0) / 100,  # Divide by 100 for correct price
                'ltt': message.get('exchange_timestamp', 0),
                'volume': message.get('volume_trade_for_the_day', 0),
                'open': message.get('open_price_of_the_day', 0) / 100,  # Divide by 100 for correct price
                'high': message.get('high_price_of_the_day', 0) / 100,  # Divide by 100 for correct price
                'low': message.get('low_price_of_the_day', 0) / 100,  # Divide by 100 for correct price
                'close': message.get('closed_price', 0) / 100,  # Divide by 100 for correct price
                'last_quantity': message.get('last_traded_quantity', 0),
                'average_price': message.get('average_traded_price', 0) / 100,  # Divide by 100 for correct price
                'total_buy_quantity': message.get('total_buy_quantity', 0),
                'total_sell_quantity': message.get('total_sell_quantity', 0)
            }
            return result
        elif mode == 3:  # Snap Quote mode (includes depth data)
            # For snap quote mode, extract the depth data if available
            # Note: OI is intentionally excluded for depth mode as per requirement
            # Note: OI is intentionally excluded for depth mode as per requirement
            result = {
                'ltp': message.get('last_traded_price', 0) / 100,  # Divide by 100 for correct price
                'ltt': message.get('exchange_timestamp', 0),
                'volume': message.get('volume_trade_for_the_day', 0),
                'open': message.get('open_price', 0) / 100,
                'high': message.get('high_price', 0) / 100,
                'low': message.get('low_price', 0) / 100,
                'close': message.get('close_price', 0) / 100,
                'oi': message.get('open_interest', 0),
                'upper_circuit': message.get('upper_circuit_limit', 0) / 100,
                'lower_circuit': message.get('lower_circuit_limit', 0) / 100
            }
            
            # Add depth data if available
            if 'best_5_buy_data' in message and 'best_5_sell_data' in message:
                result['depth'] = {
                    'buy': self._extract_depth_data(message, is_buy=True),
                    'sell': self._extract_depth_data(message, is_buy=False)
                }
            elif 'depth_20_buy_data' in message and 'depth_20_sell_data' in message:
                result['depth'] = {
                    'buy': self._extract_depth_data(message, is_buy=True),
                    'sell': self._extract_depth_data(message, is_buy=False)
                }
                
            return result
        else:
            return {}
    
    def _extract_depth_data(self, message, is_buy: bool) -> List[Dict[str, Any]]:
        """
        Extract depth data from Angel's message format
        
        Args:
            message: The raw message containing depth data
            is_buy: Whether to extract buy or sell side
            
        Returns:
            List: List of depth levels with price, quantity, and orders
        """
        depth = []
        side_label = 'Buy' if is_buy else 'Sell'
        
        # Log the raw message structure to help debug
        self.logger.debug(f"Extracting {side_label} depth data from message: {message.keys()}")
        
        # Check for different possible depth data formats that Angel might send
        # Angel can send depth data in different formats depending on the request:
        # - depth_20_buy_data and depth_20_sell_data for 20 level depth
        # - best_5_buy_data and best_5_sell_data for 5 level depth
        # - For MCX, the format might be slightly different
        
        # First check for best_5 data (most common for MCX)
        best_5_key = 'best_5_buy_data' if is_buy else 'best_5_sell_data'
        if best_5_key in message and isinstance(message[best_5_key], list):
            depth_data = message.get(best_5_key, [])
            self.logger.debug(f"Found {side_label} depth data using {best_5_key}: {len(depth_data)} levels")
            
            for level in depth_data:
                if isinstance(level, dict):
                    price = level.get('price', 0)
                    # Ensure price is properly scaled (divide by 100)
                    if price > 0:
                        price = price / 100
                    
                    depth.append({
                        'price': price,
                        'quantity': level.get('quantity', 0),
                        'orders': level.get('no of orders', 0)
                    })
                    
        # Then check for depth_20 data
        elif 'depth_20_buy_data' in message and is_buy:
            depth_data = message.get('depth_20_buy_data', [])
            self.logger.debug(f"Found {side_label} depth data using depth_20_buy_data: {len(depth_data)} levels")
            
            for level in depth_data:
                if isinstance(level, dict):
                    price = level.get('price', 0)
                    # Ensure price is properly scaled (divide by 100)
                    if price > 0:
                        price = price / 100
                        
                    depth.append({
                        'price': price,
                        'quantity': level.get('quantity', 0),
                        'orders': level.get('no of orders', 0)
                    })
                    
        elif 'depth_20_sell_data' in message and not is_buy:
            depth_data = message.get('depth_20_sell_data', [])
            self.logger.debug(f"Found {side_label} depth data using depth_20_sell_data: {len(depth_data)} levels")
            
            for level in depth_data:
                if isinstance(level, dict):
                    price = level.get('price', 0)
                    # Ensure price is properly scaled (divide by 100)
                    if price > 0:
                        price = price / 100
                        
                    depth.append({
                        'price': price,
                        'quantity': level.get('quantity', 0),
                        'orders': level.get('no of orders', 0)
                    })
        
        # For MCX, the data might be in a different format, check for best_five_buy/sell_market_data
        elif 'best_five_buy_market_data' in message and is_buy:
            depth_data = message.get('best_five_buy_market_data', [])
            self.logger.debug(f"Found {side_label} depth data using best_five_buy_market_data: {len(depth_data)} levels")
            
            for level in depth_data:
                if isinstance(level, dict):
                    price = level.get('price', 0)
                    if price > 0:
                        price = price / 100
                        
                    depth.append({
                        'price': price,
                        'quantity': level.get('quantity', 0),
                        'orders': level.get('no of orders', 0)
                    })
                    
        elif 'best_five_sell_market_data' in message and not is_buy:
            depth_data = message.get('best_five_sell_market_data', [])
            self.logger.debug(f"Found {side_label} depth data using best_five_sell_market_data: {len(depth_data)} levels")
            
            for level in depth_data:
                if isinstance(level, dict):
                    price = level.get('price', 0)
                    if price > 0:
                        price = price / 100
                        
                    depth.append({
                        'price': price,
                        'quantity': level.get('quantity', 0),
                        'orders': level.get('no of orders', 0)
                    })
        
        # If no depth data found, return empty levels as fallback
        if not depth:
            self.logger.warning(f"No {side_label} depth data found in message. Available keys: {message.keys()}")
            for i in range(5):  # Default to 5 empty levels
                depth.append({
                    'price': 0.0,
                    'quantity': 0,
                    'orders': 0
                })
        else:
            # Log the depth data being returned for debugging
            self.logger.debug(f"{side_label} depth data found: {len(depth)} levels")
            if depth and depth[0]['price'] > 0:
                self.logger.debug(f"{side_label} depth first level: Price={depth[0]['price']}, Qty={depth[0]['quantity']}")
            
        return depth