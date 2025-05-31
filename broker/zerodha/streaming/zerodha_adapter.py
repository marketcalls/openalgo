"""
Zerodha WebSocket adapter for OpenAlgo's WebSocket proxy system.
Implements the BaseBrokerWebSocketAdapter interface for Zerodha's WebSocket API.
"""
import asyncio
import json
import logging
import os
import threading
import time
from typing import Dict, List, Optional, Set, Any, Callable

import zmq
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from database.token_db import get_token
from database.auth_db import get_auth_token

# Import the WebSocket client
from .zerodha_websocket import ZerodhaWebSocket

class ZerodhaWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    Zerodha-specific implementation of the WebSocket adapter.
    Handles connection to Zerodha's WebSocket API and data transformation.
    """
    
    def __init__(self):
        """Initialize the Zerodha WebSocket adapter"""
        super().__init__()
        self.logger = logging.getLogger("zerodha_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "zerodha"
        self.running = False
        self.connected = False
        self.lock = threading.Lock()
        self.subscribed_tokens = set()  # Track subscribed tokens
        self.token_to_symbol = {}  # Map token to (symbol, exchange) tuple
        self.callbacks = {
            'on_ticks': None,
            'on_connect': None,
            'on_disconnect': None,
            'on_error': None
        }
        self.api_key = None
        self.access_token = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5  # seconds
    
    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with Zerodha WebSocket API
        
        Args:
            broker_name: Name of the broker (always 'zerodha' in this case)
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
            self.access_token = get_auth_token(user_id)
            
            # Get API key from environment variables
            self.api_key = os.getenv('BROKER_API_KEY')
            
            if not self.api_key or not self.access_token:
                error_msg = f"Missing authentication data. API Key: {'Found' if self.api_key else 'Missing'}, Access Token: {'Found' if self.access_token else 'Missing'}"
                self.logger.error(error_msg)
                raise ValueError(error_msg)
        else:
            # Use provided tokens
            self.api_key = auth_data.get('api_key')
            self.access_token = auth_data.get('access_token')
            
            if not self.api_key or not self.access_token:
                error_msg = f"Missing required authentication data. API Key: {'Provided' if 'api_key' in auth_data else 'Missing'}, Access Token: {'Provided' if 'access_token' in auth_data else 'Missing'}"
                self.logger.error(error_msg)
                raise ValueError(error_msg)
        
        self._create_websocket_client()
        self.logger.info("Zerodha WebSocket adapter initialized")
    
    def _create_websocket_client(self) -> None:
        """Create and initialize the WebSocket client"""
        try:
            if self.ws_client:
                self.ws_client.stop()
                
            self.ws_client = ZerodhaWebSocket(
                api_key=self.api_key,
                access_token=self.access_token,
                on_ticks=self._on_ticks
            )
            
            # Set up callbacks
            self.ws_client.on_connect = self._on_connect
            self.ws_client.on_disconnect = self._on_disconnect
            self.ws_client.on_error = self._on_error
            
        except Exception as e:
            self.logger.error(f"Error creating WebSocket client: {e}")
            raise
    
    def connect(self) -> bool:
        """
        Establish connection to Zerodha WebSocket
        
        Returns:
            bool: True if connection was successful, False otherwise
        """
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return False
            
        try:
            with self.lock:
                if not self.running:
                    self.logger.info("Starting Zerodha WebSocket client...")
                    if not self.ws_client.start():
                        self.logger.error("Failed to start WebSocket client")
                        return False
                        
                    # Wait for connection to be established
                    max_wait = 10  # seconds
                    start_time = time.time()
                    while not self.connected and (time.time() - start_time) < max_wait:
                        time.sleep(0.1)
                    
                    if not self.connected:
                        self.logger.error("Timed out waiting for WebSocket connection")
                        return False
                        
                    try:
                        # Resubscribe to any existing subscriptions
                        if self.subscribed_tokens:
                            tokens = list(self.subscribed_tokens)
                            self.logger.info(f"Resubscribing to {len(tokens)} tokens")
                            
                            # Use the client's event loop to schedule the subscription
                            if hasattr(self.ws_client, 'loop') and self.ws_client.loop is not None:
                                future = asyncio.run_coroutine_threadsafe(
                                    self.ws_client.subscribe(tokens, 'full'),
                                    self.ws_client.loop
                                )
                                # Wait for the subscription to complete or timeout
                                future.result(timeout=5)  # 5 second timeout for subscription
                            else:
                                self.logger.warning("WebSocket client loop not available for resubscription")
                    except Exception as e:
                        self.logger.error(f"Error during resubscription: {e}", exc_info=True)
                        
                    self.logger.info("Zerodha WebSocket client started and ready")
                    return True
                return True
                
        except Exception as e:
            self.logger.error(f"Error starting Zerodha WebSocket client: {e}", exc_info=True)
            return False
    
    def disconnect(self) -> None:
        """Disconnect from Zerodha WebSocket"""
        try:
            with self.lock:
                if self.ws_client:
                    self.logger.info("Disconnecting from Zerodha WebSocket...")
                    self.ws_client.stop()
                    self.connected = False
                    self.running = False
                    self.logger.info("Disconnected from Zerodha WebSocket")
        except Exception as e:
            self.logger.error(f"Error disconnecting from Zerodha WebSocket: {e}", exc_info=True)
    
    def _on_connect(self) -> None:
        """Handle successful WebSocket connection"""
        self.connected = True
        self.reconnect_attempts = 0
        self.logger.info("Successfully connected to Zerodha WebSocket")
        
        if self.callbacks.get('on_connect'):
            try:
                self.callbacks['on_connect']()
            except Exception as e:
                self.logger.error(f"Error in on_connect callback: {e}")
    
    def _on_disconnect(self) -> None:
        """Handle WebSocket disconnection"""
        self.connected = False
        self.logger.warning("Disconnected from Zerodha WebSocket")
        
        if self.callbacks.get('on_disconnect'):
            try:
                self.callbacks['on_disconnect']()
            except Exception as e:
                self.logger.error(f"Error in on_disconnect callback: {e}")
        
        # Attempt to reconnect if we were running
        if self.running:
            self._attempt_reconnect()
    
    def _on_error(self, error: Exception) -> None:
        """Handle WebSocket errors"""
        self.logger.error(f"WebSocket error: {error}", exc_info=True)
        
        if self.callbacks.get('on_error'):
            try:
                self.callbacks['on_error'](error)
            except Exception as e:
                self.logger.error(f"Error in on_error callback: {e}")
    
    def _attempt_reconnect(self) -> None:
        """Attempt to reconnect to WebSocket with exponential backoff"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error("Max reconnection attempts reached. Giving up.")
            return
            
        delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts), 300)  # Cap at 5 minutes
        self.reconnect_attempts += 1
        
        self.logger.info(f"Attempting to reconnect in {delay} seconds (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")
        
        def _reconnect():
            time.sleep(delay)
            try:
                with self.lock:
                    if self.running:  # Only reconnect if we're supposed to be running
                        self._create_websocket_client()
                        self.connect()
            except Exception as e:
                self.logger.error(f"Reconnection attempt {self.reconnect_attempts} failed: {e}")
                if self.running:  # Only schedule next attempt if we're still running
                    self._attempt_reconnect()
        
        # Start reconnection in a separate thread
        threading.Thread(target=_reconnect, daemon=True).start()
    
    def _on_ticks(self, ticks: List[Dict]) -> None:
        """
        Callback for processing incoming ticks from Zerodha WebSocket
        
        Args:
            ticks: List of tick data dictionaries
        """
        if not ticks:
            return
            
        try:
            # Transform ticks to OpenAlgo format and publish
            for tick in ticks:
                transformed = self._transform_tick(tick)
                if transformed:
                    self.publish_market_data(transformed['symbol'], transformed)
        except Exception as e:
            self.logger.error(f"Error processing ticks: {e}")
    
    def _transform_tick(self, tick: Dict) -> Optional[Dict]:
        """
        Transform Zerodha tick data to OpenAlgo format
        
        Args:
            tick: Raw tick data from Zerodha WebSocket
            
        Returns:
            Transformed tick data in OpenAlgo format or None if transformation fails
        """
        try:
            if 'instrument_token' not in tick:
                return None
                
            # Get symbol and exchange from our mapping
            token = tick['instrument_token']
            symbol_info = self.token_to_symbol.get(token)
            
            if not symbol_info:
                self.logger.warning(f"No symbol mapping found for token: {token}")
                return None
                
            symbol, exchange = symbol_info
            
            # Base tick data
            transformed = {
                'symbol': symbol,
                'exchange': exchange,
                'token': str(token),
                'last_price': tick.get('last_price', 0),
                'volume': tick.get('volume', 0),
                'total_buy_quantity': tick.get('total_buy_quantity', 0),
                'total_sell_quantity': tick.get('total_sell_quantity', 0),
                'average_price': tick.get('average_price', 0),
                'ohlc': tick.get('ohlc', {}),
                'mode': tick.get('mode', 'quote'),
                'timestamp': tick.get('timestamp', int(time.time() * 1000))
            }
            
            # Add depth data if available
            if 'depth' in tick:
                depth = {'buy': [], 'sell': []}
                
                # Process buy side
                for i, level in enumerate(tick['depth'].get('buy', [])):
                    depth['buy'].append({
                        'price': level.get('price', 0),
                        'quantity': level.get('quantity', 0),
                        'orders': level.get('orders', 0),
                        'position': i + 1
                    })
                
                # Process sell side
                for i, level in enumerate(tick['depth'].get('sell', [])):
                    depth['sell'].append({
                        'price': level.get('price', 0),
                        'quantity': level.get('quantity', 0),
                        'orders': level.get('orders', 0),
                        'position': i + 1
                    })
                
                transformed['depth'] = depth
            
            return transformed
            
        except Exception as e:
            self.logger.error(f"Error transforming tick: {e}", exc_info=True)
            return None
                
    def _on_ticks(self, ticks: List[Dict]) -> None:
        """
        Callback for processing incoming ticks from Zerodha WebSocket
        
        Args:
            ticks: List of tick data dictionaries
        """
        if not ticks:
            return
            
        try:
            # Transform ticks to OpenAlgo format and publish
            for tick in ticks:
                transformed = self._transform_tick(tick)
                if transformed:
                    self.publish_market_data(transformed['symbol'], transformed)
        except Exception as e:
            self.logger.error(f"Error processing ticks: {e}")
    
    def _transform_tick(self, tick: Dict) -> Optional[Dict]:
        """
        Transform Zerodha tick data to OpenAlgo format
        
        Args:
            tick: Raw tick data from Zerodha WebSocket
            
        Returns:
            Transformed tick data in OpenAlgo format or None if transformation fails
        """
        try:
            if 'instrument_token' not in tick:
                return None
                
            # Get symbol and exchange from our mapping
            token = tick['instrument_token']
            symbol_info = self.token_to_symbol.get(token)
            
            if not symbol_info:
                self.logger.warning(f"No symbol mapping found for token: {token}")
                return None
                
            symbol, exchange = symbol_info
            
            # Base tick data
            transformed = {
                'symbol': symbol,
                'exchange': exchange,
                'token': str(token),
                'last_price': tick.get('last_price', 0),
                'volume': tick.get('volume', 0),
                'total_buy_quantity': tick.get('total_buy_quantity', 0),
                'total_sell_quantity': tick.get('total_sell_quantity', 0),
                'average_price': tick.get('average_price', 0),
                'ohlc': tick.get('ohlc', {}),
                'mode': tick.get('mode', 'quote'),
                'timestamp': tick.get('timestamp', int(time.time() * 1000))
            }
            
            # Add depth data if available
            if 'depth' in tick:
                depth = {'buy': [], 'sell': []}
                
                # Process buy side
                for i, level in enumerate(tick['depth'].get('buy', [])):
                    depth['buy'].append({
                        'price': level.get('price', 0),
                        'quantity': level.get('quantity', 0),
                        'orders': level.get('orders', 0),
                        'position': i + 1
                    })
                
                # Process sell side
                for i, level in enumerate(tick['depth'].get('sell', [])):
                    depth['sell'].append({
                        'price': level.get('price', 0),
                        'quantity': level.get('quantity', 0),
                        'orders': level.get('orders', 0),
                        'position': i + 1
                    })
                
                transformed['depth'] = depth
            
            return transformed
            
        except Exception as e:
            self.logger.error(f"Error transforming tick data: {e}", exc_info=True)
            return None

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> bool:
        """
        Subscribe to market data for a symbol
        
        Args:
            symbol: Symbol to subscribe to (e.g., 'RELIANCE', 'NIFTY25MAY23FUT')
            exchange: Exchange where the symbol is listed (e.g., 'NSE', 'NFO')
            mode: Subscription mode (1=LTP, 2=Quote, 3=Full)
            depth_level: Number of market depth levels to receive (for full mode)
            
        Returns:
            bool: True if subscription was successful, False otherwise
        """
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized")
            return False
            
        try:
            # Get instrument token for the symbol
            token = get_token(symbol, exchange)
            if not token:
                self.logger.error(f"Could not find token for {symbol} on {exchange}")
                return False
                
            # Map mode
            mode_str = {
                1: 'ltp',
                2: 'quote',
                3: 'full'
            }.get(mode, 'quote')
            
            # Ensure we're connected
            if not self.connected:
                self.logger.warning("Not connected to WebSocket. Attempting to connect...")
                if not self.connect():
                    self.logger.error("Failed to connect to WebSocket")
                    return False
            
            # Subscribe to the token
            future = asyncio.run_coroutine_threadsafe(
                self.ws_client.subscribe([token], mode_str),
                self.ws_client.loop
            )
            
            # Wait for subscription to complete (with timeout)
            try:
                result = future.result(timeout=5)  # 5 second timeout
                if not result:
                    self.logger.error(f"Failed to subscribe to {symbol}")
                    return False
            except asyncio.TimeoutError:
                self.logger.error(f"Timeout subscribing to {symbol}")
                return False
            
            # Update our tracking
            with self.lock:
                self.subscribed_tokens.add(token)
                self.token_to_symbol[token] = (symbol, exchange)
            
            self.logger.info(f"Subscribed to {symbol} ({exchange}) in {mode_str} mode")
            return True
            
        except Exception as e:
            self.logger.error(f"Error subscribing to {symbol}: {e}", exc_info=True)
            return False
    
    def unsubscribe(self, symbol: str, exchange: str) -> bool:
        """
        Unsubscribe from market data for a symbol
        
        Args:
            symbol: Trading symbol
            exchange: Exchange code
            
        Returns:
            bool: True if unsubscription was successful, False otherwise
        """
        try:
            # Get token for the symbol and exchange
            token = self._get_token(symbol, exchange)
            if not token or token not in self.subscribed_tokens:
                return False
            
            # Unsubscribe from the token
            if self.ws_client:
                asyncio.run_coroutine_threadsafe(
                    self.ws_client.unsubscribe([token]),
                    self.ws_client.loop
                )
                
                with self.lock:
                    self.subscribed_tokens.discard(token)
                    
                    # Remove from token to symbol mapping if no longer subscribed
                    if token in self.token_to_symbol and token not in self.subscribed_tokens:
                        del self.token_to_symbol[token]
                
                self.logger.info(f"Unsubscribed from {exchange}:{symbol} (token: {token})")
                return True
                
            return False
            
        except Exception as e:
            self.logger.error(f"Error unsubscribing from {exchange}:{symbol}: {e}")
            return False
    
    def _get_token(self, symbol: str, exchange: str) -> Optional[int]:
        """
        Get instrument token for the given symbol and exchange
        
        Args:
            symbol: Trading symbol
            exchange: Exchange code
            
        Returns:
            Instrument token as integer or None if not found
        """
        try:
            # Try to get token from database
            token = get_token(symbol, exchange, self.broker_name)
            if token:
                return int(token)
                
            # Fallback to reverse lookup in our mapping
            for t, (s, e) in self.token_to_symbol.items():
                if s == symbol and e == exchange:
                    return t
                    
            self.logger.warning(f"Token not found for {exchange}:{symbol}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting token for {exchange}:{symbol}: {e}")
            return None
    
    @staticmethod
    def _map_mode(mode: int) -> Optional[str]:
        """
        Map OpenAlgo subscription mode to Zerodha mode
        
        Args:
            mode: OpenAlgo subscription mode (1=LTP, 2=Quote, 4=Depth)
            
        Returns:
            Zerodha subscription mode ('ltp', 'quote', or 'full') or None if invalid
        """
        if mode == 1:  # LTP
            return 'ltp'
        elif mode == 2:  # Quote
            return 'quote'
        elif mode == 4:  # Depth
            return 'full'
        return None
    
    def set_callback(self, callback_type: str, callback: Callable) -> None:
        """
        Set a callback function for WebSocket events
        
        Args:
            callback_type: Type of callback ('on_ticks', 'on_connect', 'on_disconnect', 'on_error')
            callback: Callback function
        """
        if callback_type in self.callbacks:
            self.callbacks[callback_type] = callback
    
    def _execute_callback(self, callback_type: str, *args, **kwargs) -> None:
        """
        Execute a callback function if it's set
        
        Args:
            callback_type: Type of callback to execute
            *args: Positional arguments to pass to the callback
            **kwargs: Keyword arguments to pass to the callback
        """
        callback = self.callbacks.get(callback_type)
        if callback and callable(callback):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                self.logger.error(f"Error in {callback_type} callback: {e}")
    
    def cleanup(self) -> None:
        """Clean up resources"""
        try:
            self.disconnect()
            self.cleanup_zmq()
            self.logger.info("Zerodha WebSocket adapter cleaned up")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
    
    def __del__(self):
        """Destructor to ensure proper cleanup"""
        self.cleanup()
        super().__del__()
