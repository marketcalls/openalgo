"""
Final fixed Zerodha WebSocket adapter that matches OpenAlgo's expected format.
Based on the analysis of the logs and OpenAlgo library examples.
"""
import asyncio
import json
import logging
import os
import threading
import time
from typing import Dict, List, Optional, Set, Any, Callable

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from database.token_db import get_token
from database.auth_db import get_auth_token

# Import the WebSocket client
from .zerodha_websocket import ZerodhaWebSocket

class ZerodhaWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    Fixed Zerodha-specific implementation of the WebSocket adapter.
    Properly implements OpenAlgo WebSocket proxy interface with correct topic formatting.
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
        self.subscribed_symbols = {}  # {symbol: {exchange, token, mode}}
        self.token_to_symbol = {}  # {token: (symbol, exchange)}
        
        # Authentication
        self.api_key = None
        self.access_token = None
        
        # Connection management
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5
        
        # Mode mapping
        self.mode_map = {
            1: ZerodhaWebSocket.MODE_LTP,    # LTP
            2: ZerodhaWebSocket.MODE_QUOTE,  # Quote
            3: ZerodhaWebSocket.MODE_FULL    # Full/Depth
        }
    
    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Initialize the adapter with broker credentials"""
        try:
            if broker_name != self.broker_name:
                return {'status': 'error', 'message': f'Invalid broker name: {broker_name}'}
            
            self.user_id = user_id
            
            # Get API key from environment
            self.api_key = os.getenv('BROKER_API_KEY')
            if not self.api_key:
                return {'status': 'error', 'message': 'API key not found in environment variables'}
            
            # Get auth token from database
            auth_token = get_auth_token(user_id)
            if not auth_token:
                return {'status': 'error', 'message': 'Authentication token not found'}
            
            # Handle auth token format (api_key:access_token)
            if ':' in auth_token:
                parts = auth_token.split(':')
                if len(parts) >= 2:
                    self.access_token = parts[1]  # Use the access token part
                else:
                    self.access_token = auth_token
            else:
                self.access_token = auth_token
            
            if not self.access_token:
                return {'status': 'error', 'message': 'Invalid access token'}
            
            # Initialize WebSocket client
            self.ws_client = ZerodhaWebSocket(
                api_key=self.api_key,
                access_token=self.access_token,
                on_ticks=self._handle_ticks
            )
            
            # Set up WebSocket callbacks
            self.ws_client.on_connect = self._on_connect
            self.ws_client.on_disconnect = self._on_disconnect
            self.ws_client.on_error = self._on_error
            
            self.logger.info(f"✅ Zerodha adapter initialized for user {user_id}")
            return {'status': 'success', 'message': 'Adapter initialized successfully'}
            
        except Exception as e:
            self.logger.error(f"Error initializing adapter: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def connect(self) -> Dict[str, Any]:
        """Connect to Zerodha WebSocket"""
        if not self.ws_client:
            return {'status': 'error', 'message': 'WebSocket client not initialized'}
        
        try:
            with self.lock:
                if self.running and self.connected:
                    return {'status': 'success', 'message': 'Already connected'}
                
                # Start WebSocket client
                if self.ws_client.start():
                    self.running = True
                    
                    # Wait for connection to establish with the client's built-in method
                    self.logger.info("⏳ Waiting for WebSocket connection...")
                    if self.ws_client.wait_for_connection(timeout=15.0):
                        self.connected = True
                        self.logger.info("✅ WebSocket connected successfully")
                        return {'status': 'success', 'message': 'Connected successfully'}
                    else:
                        # Check if at least the client started
                        if self.ws_client.running:
                            self.logger.warning("⚠️ Client started but connection timeout")
                            return {'status': 'success', 'message': 'Client started, connection in progress'}
                        else:
                            return {'status': 'error', 'message': 'Connection timeout'}
                else:
                    return {'status': 'error', 'message': 'Failed to start WebSocket client'}
                    
        except Exception as e:
            self.logger.error(f"Error connecting: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def disconnect(self) -> Dict[str, Any]:
        """Disconnect from WebSocket"""
        try:
            with self.lock:
                if self.ws_client:
                    self.ws_client.stop()
                    self.running = False
                    self.connected = False
                    self.logger.info("✅ WebSocket disconnected")
                    
            return {'status': 'success', 'message': 'Disconnected successfully'}
            
        except Exception as e:
            self.logger.error(f"Error disconnecting: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data for a symbol
        
        Args:
            symbol: Trading symbol (e.g., 'RELIANCE', 'CRUDEOIL18JUN25FUT')
            exchange: Exchange code (e.g., 'NSE', 'MCX')
            mode: Subscription mode (1=LTP, 2=Quote, 3=Full)
            depth_level: Market depth level (for compatibility, not used in Zerodha)
        """
        if not self.ws_client:
            return {'status': 'error', 'message': 'WebSocket client not initialized'}
        
        if not self.running:
            return {'status': 'error', 'message': 'WebSocket not connected. Call connect() first.'}
        
        try:
            # Get instrument token
            token_data = get_token(symbol, exchange)
            if not token_data:
                return {'status': 'error', 'message': f'Token not found for {symbol} on {exchange}'}
            
            # Extract token (handle different formats)
            if isinstance(token_data, dict):
                token = token_data.get('token')
            elif isinstance(token_data, str):
                # Handle formats like "738561::::2885" or "738561:2885"
                if '::::' in token_data:
                    token = token_data.split('::::')[0]
                elif ':' in token_data:
                    token = token_data.split(':')[0]
                else:
                    token = token_data
            else:
                token = str(token_data)
            
            # Convert to integer
            try:
                token = int(token)
            except ValueError:
                return {'status': 'error', 'message': f'Invalid token format: {token}'}
            
            # Map mode to Zerodha format
            zerodha_mode = self.mode_map.get(mode, ZerodhaWebSocket.MODE_QUOTE)
            
            # Check if WebSocket is actually connected
            if not self.ws_client.is_connected():
                self.logger.warning("⚠️ WebSocket not connected, waiting for connection...")
                # Try to wait for connection
                if not self.ws_client.wait_for_connection(timeout=10.0):
                    return {'status': 'error', 'message': 'WebSocket connection timeout'}
            
            # Subscribe using WebSocket client
            self.ws_client.subscribe_tokens([token], zerodha_mode)
            
            # Track subscription
            with self.lock:
                self.subscribed_symbols[f"{exchange}:{symbol}"] = {
                    'exchange': exchange,
                    'symbol': symbol,
                    'token': token,
                    'mode': mode
                }
                self.token_to_symbol[token] = (symbol, exchange)
            
            self.logger.info(f"✅ Subscribed to {exchange}:{symbol} (token: {token}, mode: {zerodha_mode})")
            return {'status': 'success', 'message': f'Subscribed to {symbol}'}
            
        except Exception as e:
            self.logger.error(f"Error subscribing to {exchange}:{symbol}: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def unsubscribe(self, symbol: str, exchange: str, mode: Optional[int] = None, depth_level: Optional[int] = None) -> Dict[str, Any]:
        """Unsubscribe from market data for a symbol
        
        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Optional mode parameter (for compatibility)
            depth_level: Optional depth level parameter (for compatibility)
        """
        try:
            key = f"{exchange}:{symbol}"
            
            with self.lock:
                if key not in self.subscribed_symbols:
                    return {'status': 'error', 'message': f'Not subscribed to {symbol}'}
                
                subscription = self.subscribed_symbols[key]
                token = subscription['token']
                
                # Unsubscribe using WebSocket client
                if self.ws_client:
                    asyncio.run_coroutine_threadsafe(
                        self.ws_client.unsubscribe([token]),
                        self.ws_client.loop
                    )
                
                # Remove from tracking
                del self.subscribed_symbols[key]
                self.token_to_symbol.pop(token, None)
            
            self.logger.info(f"✅ Unsubscribed from {exchange}:{symbol}")
            return {'status': 'success', 'message': f'Unsubscribed from {symbol}'}
            
        except Exception as e:
            self.logger.error(f"Error unsubscribing from {exchange}:{symbol}: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def get_subscriptions(self) -> Dict[str, Any]:
        """Get current subscriptions"""
        with self.lock:
            return {
                'status': 'success',
                'subscriptions': list(self.subscribed_symbols.keys()),
                'count': len(self.subscribed_symbols)
            }
    
    def is_connected(self) -> bool:
        """Check if WebSocket is connected"""
        return self.connected and self.running
    
    def _handle_ticks(self, ticks: List[Dict]):
        """Handle incoming ticks from WebSocket"""
        if not ticks:
            return
        
        try:
            for tick in ticks:
                transformed_tick = self._transform_tick(tick)
                if transformed_tick:
                    symbol = transformed_tick['symbol']
                    exchange = transformed_tick['exchange']
                    
                    # CRITICAL FIX: For LTP subscriptions, always use LTP mode
                    # The issue is that packet size determines mode, but we want
                    # to use the SUBSCRIPTION mode, not the packet mode
                    
                    # Get the subscription info to determine the actual intended mode
                    token = tick.get('instrument_token')
                    subscription_mode = 'ltp'  # Default
                    
                    # Check what mode this token was subscribed with
                    with self.lock:
                        for key, sub_info in self.subscribed_symbols.items():
                            if sub_info['token'] == token:
                                # Map OpenAlgo mode to string
                                mode_num = sub_info['mode']
                                if mode_num == 1:
                                    subscription_mode = 'ltp'
                                elif mode_num == 2:
                                    subscription_mode = 'quote'
                                elif mode_num == 3:
                                    subscription_mode = 'full'
                                break
                    
                    # Override the tick mode with subscription mode
                    transformed_tick['mode'] = subscription_mode
                    
                    # Map mode to string format exactly like Angel adapter
                    mode_str = {
                        'ltp': 'LTP',
                        'quote': 'QUOTE', 
                        'full': 'DEPTH'
                    }.get(subscription_mode, 'LTP')
                    
                    # Clean exchange name (remove _INDEX suffix if present)
                    clean_exchange = exchange.replace('_INDEX', '') if '_INDEX' in exchange else exchange
                    
                    # Create topic exactly like Angel adapter
                    topic = f"{clean_exchange}_{symbol}_{mode_str}"
                    
                    # Debug log to verify correct topic and data structure
                    self.logger.info(f"📊 Publishing to topic: {topic}")
                    self.logger.info(f"📊 Data structure: {transformed_tick}")
                    
                    # Publish to ZeroMQ exactly like Angel adapter
                    self.publish_market_data(topic, transformed_tick)
                    
        except Exception as e:
            self.logger.error(f"Error handling ticks: {e}")
    
    def _transform_tick(self, tick: Dict) -> Optional[Dict]:
        """Transform Zerodha tick to OpenAlgo format with index support"""
        try:
            token = tick.get('instrument_token')
            if not token:
                return None
            
            # Get symbol info
            symbol_info = self.token_to_symbol.get(token)
            if not symbol_info:
                self.logger.warning(f"No symbol mapping for token: {token}")
                return None
            
            symbol, exchange = symbol_info
            mode = tick.get('mode', 'ltp')
            is_index = tick.get('is_index', False)
            
            # Transform based on whether it's an index or regular instrument
            if is_index:
                transformed = self._transform_index_tick(tick, symbol, exchange, mode)
            else:
                transformed = self._transform_regular_tick(tick, symbol, exchange, mode)
            
            return transformed
            
        except Exception as e:
            self.logger.error(f"Error transforming tick: {e}")
            return None
    
    def _transform_index_tick(self, tick: Dict, symbol: str, exchange: str, mode: str) -> Dict:
        """Transform index tick data to match Angel adapter format exactly"""
        if mode == 'ltp':
            # Index LTP mode - match Angel adapter structure exactly
            # Angel returns: {'ltp': price, 'ltt': timestamp}
            transformed = {
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'ltp': tick.get('last_traded_price', tick.get('last_price', 0)),
                'ltt': tick.get('exchange_timestamp', tick.get('timestamp', int(time.time() * 1000))),
                'timestamp': tick.get('timestamp', int(time.time() * 1000))
            }
        
        elif mode in ['quote', 'full']:
            # Index Quote/Full mode - comprehensive data like Angel adapter
            transformed = {
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'ltp': tick.get('last_traded_price', tick.get('last_price', 0)),
                'ltt': tick.get('exchange_timestamp', tick.get('timestamp', int(time.time() * 1000))),
                'timestamp': tick.get('timestamp', int(time.time() * 1000)),
                'volume': tick.get('volume_traded', tick.get('volume', 0)),  # Even if 0 for index
                'price_change': tick.get('price_change', 0),
                'price_change_percent': tick.get('price_change_percent', 0)
            }
            
            # Add OHLC for index
            ohlc = tick.get('ohlc')
            if ohlc:
                transformed.update({
                    'open': ohlc.get('open', 0),
                    'high': ohlc.get('high', 0),
                    'low': ohlc.get('low', 0),
                    'close': ohlc.get('close', 0)
                })
            else:
                # Add individual OHLC fields if available
                if 'open_price' in tick:
                    transformed['open'] = tick['open_price']
                if 'high_price' in tick:
                    transformed['high'] = tick['high_price']
                if 'low_price' in tick:
                    transformed['low'] = tick['low_price']
                if 'close_price' in tick:
                    transformed['close'] = tick['close_price']
            
            # Add exchange timestamp if available
            if 'exchange_timestamp' in tick:
                transformed['exchange_timestamp'] = tick['exchange_timestamp']
        
        else:
            # Fallback for index - minimal like Angel
            transformed = {
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'ltp': tick.get('last_traded_price', tick.get('last_price', 0)),
                'ltt': tick.get('timestamp', int(time.time() * 1000))
            }
        
        return transformed
    
    def _transform_regular_tick(self, tick: Dict, symbol: str, exchange: str, mode: str) -> Dict:
        """Transform regular instrument tick data to match Angel adapter format exactly"""
        if mode == 'ltp':
            # LTP mode - match Angel adapter structure exactly
            # Angel returns: {'ltp': price, 'ltt': timestamp}
            transformed = {
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'ltp': tick.get('last_traded_price', tick.get('last_price', 0)),
                'ltt': tick.get('exchange_timestamp', tick.get('timestamp', int(time.time() * 1000))),
                'timestamp': tick.get('timestamp', int(time.time() * 1000))
            }
        
        elif mode in ['quote', 'full']:
            # Quote/Full mode - comprehensive data like Angel adapter
            transformed = {
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'ltp': tick.get('last_traded_price', tick.get('last_price', 0)),
                'ltt': tick.get('exchange_timestamp', tick.get('timestamp', int(time.time() * 1000))),
                'timestamp': tick.get('timestamp', int(time.time() * 1000)),
                'volume': tick.get('volume_traded', tick.get('volume', 0)),
                'last_quantity': tick.get('last_traded_quantity', 0),
                'average_price': tick.get('average_traded_price', tick.get('average_price', 0)),
                'total_buy_quantity': tick.get('total_buy_quantity', 0),
                'total_sell_quantity': tick.get('total_sell_quantity', 0)
            }
            
            # Add OHLC if available
            ohlc = tick.get('ohlc')
            if ohlc:
                transformed.update({
                    'open': ohlc.get('open', 0),
                    'high': ohlc.get('high', 0),
                    'low': ohlc.get('low', 0),
                    'close': ohlc.get('close', 0)
                })
            else:
                # Add individual OHLC fields if available
                if 'open_price' in tick:
                    transformed['open'] = tick['open_price']
                if 'high_price' in tick:
                    transformed['high'] = tick['high_price']
                if 'low_price' in tick:
                    transformed['low'] = tick['low_price']
                if 'close_price' in tick:
                    transformed['close'] = tick['close_price']
            
            # Add Open Interest for derivatives
            if 'open_interest' in tick:
                transformed['oi'] = tick['open_interest']
                transformed['open_interest'] = tick['open_interest']
            
            # Add depth data for full mode
            if mode == 'full' and 'depth' in tick:
                depth = tick['depth']
                if 'buy' in depth and 'sell' in depth:
                    transformed['depth'] = {
                        'buy': [
                            {
                                'price': level.get('price', 0),
                                'quantity': level.get('quantity', 0),
                                'orders': level.get('orders', 0)
                            }
                            for level in depth['buy'][:5]
                        ],
                        'sell': [
                            {
                                'price': level.get('price', 0),
                                'quantity': level.get('quantity', 0),
                                'orders': level.get('orders', 0)
                            }
                            for level in depth['sell'][:5]
                        ]
                    }
        else:
            # Fallback - basic structure like Angel
            transformed = {
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'ltp': tick.get('last_traded_price', tick.get('last_price', 0)),
                'ltt': tick.get('timestamp', int(time.time() * 1000))
            }
        
        return transformed
    
    def _on_connect(self):
        """Handle WebSocket connection"""
        self.connected = True
        self.reconnect_attempts = 0
        self.logger.info("✅ WebSocket connected")
    
    def _on_disconnect(self):
        """Handle WebSocket disconnection"""
        self.connected = False
        self.logger.warning("❌ WebSocket disconnected")
    
    def _on_error(self, error):
        """Handle WebSocket errors"""
        self.logger.error(f"WebSocket error: {error}")
    
    def cleanup(self):
        """Clean up resources"""
        try:
            self.disconnect()
            if hasattr(super(), 'cleanup'):
                super().cleanup()
            self.logger.info("✅ Zerodha adapter cleaned up")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
    
    def __del__(self):
        """Destructor"""
        try:
            self.cleanup()
        except Exception:
            pass