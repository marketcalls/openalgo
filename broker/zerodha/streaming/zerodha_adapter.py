from utils.logging import get_logger

logger = get_logger(__name__)

"""
Fixed Zerodha WebSocket adapter that properly handles NIFTY index data.
The key fixes are in the _handle_ticks method for proper topic generation.
"""
import asyncio
import json
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
        self.logger = get_logger("zerodha_websocket")
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
        
        # Batch subscription management
        self.subscription_queue = []
        self.batch_timer = None
        self.batch_delay = 0.5  # 500ms delay to collect more subscriptions in a batch
    
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
    
    def _start_batch_timer(self):
        """Start a timer to process batch subscriptions"""
        if self.batch_timer:
            self.batch_timer.cancel()
        
        self.batch_timer = threading.Timer(self.batch_delay, self._process_batch_subscriptions)
        self.batch_timer.start()
    
    def _process_batch_subscriptions(self):
        """Process queued subscriptions in batches"""
        with self.lock:
            if not self.subscription_queue:
                return
            
            # Group by mode for efficient batch subscription
            mode_groups = {}
            token_exchange_map = {}
            
            for sub in self.subscription_queue:
                mode = sub['mode']
                token = sub['token']
                exchange = sub['exchange']
                
                if mode not in mode_groups:
                    mode_groups[mode] = []
                mode_groups[mode].append(token)
                
                # Build token to exchange mapping
                token_exchange_map[token] = exchange
            
            # Clear the queue
            self.subscription_queue.clear()
        
        # Update token exchange mapping in WebSocket client
        if token_exchange_map and self.ws_client:
            self.ws_client.set_token_exchange_mapping(token_exchange_map)
        
        # Subscribe in batches by mode
        for mode, tokens in mode_groups.items():
            try:
                self.logger.info(f"📦 Batch subscribing {len(tokens)} tokens in {mode} mode")
                self.ws_client.subscribe_tokens(tokens, mode)
            except Exception as e:
                self.logger.error(f"❌ Batch subscription failed for {mode} mode: {e}")
    
    def disconnect(self) -> Dict[str, Any]:
        """
        Disconnect from WebSocket and clean up resources.
        Ensures proper cleanup of ZMQ ports and WebSocket connections.
        """
        try:
            # Cancel any pending batch timer
            if self.batch_timer:
                self.batch_timer.cancel()
                self.batch_timer = None
            
            with self.lock:
                if self.ws_client:
                    # Stop the WebSocket client
                    self.ws_client.stop()
                    self.ws_client = None  # Clear the reference
                    
                    # Update state flags
                    self.running = False
                    self.connected = False
                    self.reconnect_attempts = 0  # Reset reconnect attempts
                    
                    self.logger.info("✅ WebSocket disconnected")
                    
                    # Reset subscriptions tracking
                    self.subscribed_symbols.clear()
                    self.token_to_symbol.clear()
                
                # Always clean up ZMQ resources to ensure proper cleanup
                self.cleanup_zmq()
                    
            return {'status': 'success', 'message': 'Disconnected successfully and resources cleaned up'}
            
        except Exception as e:
            self.logger.error(f"Error disconnecting: {e}")
            # Still try to clean up ZMQ
            try:
                self.cleanup_zmq()
            except Exception as zmq_err:
                self.logger.error(f"Error cleaning up ZMQ resources during disconnect error: {zmq_err}")
            return {'status': 'error', 'message': str(e)}
    
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data for a symbol
        
        Args:
            symbol: Trading symbol (e.g., 'RELIANCE', 'NIFTY')
            exchange: Exchange code (e.g., 'NSE', 'NSE_INDEX', 'MCX')
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
            
            # Track subscription with mapped exchange for consistency
            subscription_exchange = 'NSE' if exchange == 'NSE_INDEX' else exchange
            
            # Add to queue for batch processing
            with self.lock:
                self.subscription_queue.append({
                    'token': token,
                    'mode': zerodha_mode,
                    'symbol': symbol,
                    'exchange': exchange,
                    'subscription_exchange': subscription_exchange,
                    'mode_int': mode
                })
                
                # If this is the first subscription in queue, start the batch timer
                if len(self.subscription_queue) == 1:
                    self._start_batch_timer()
            
            # Immediately track subscription (even before actual WebSocket subscription)
            with self.lock:
                self.subscribed_symbols[f"{exchange}:{symbol}"] = {
                    'exchange': exchange,  # Original exchange for unsubscribe
                    'symbol': symbol,
                    'token': token,
                    'mode': mode,
                    'mapped_exchange': subscription_exchange  # Mapped exchange for data matching
                }
                self.token_to_symbol[token] = (symbol, exchange)
            
            self.logger.info(f"✅ Subscribed to {exchange}:{symbol} (token: [REDACTED], mode: {zerodha_mode})")
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
    
    def _generate_topic(self, symbol: str, subscription_exchange: str, mode_str: str) -> str:
        """
        Generate topic for market data publishing.
        Uses original exchange format for maximum client compatibility.
        """
        # ✅ FIXED: Keep original exchange format for client compatibility
        return f"{subscription_exchange}_{symbol}_{mode_str}"

    def _map_data_exchange(self, subscription_exchange: str) -> str:
        """
        Map subscription exchange to data exchange for client compatibility.
        
        Args:
            subscription_exchange: Original subscription exchange
            
        Returns:
            Mapped exchange for data field
        """
        # Map index exchanges to their base exchanges for data consistency
        if subscription_exchange == 'NSE_INDEX':
            return 'NSE_INDEX'  # ✅ Keep NSE_INDEX in data for client filtering
        elif subscription_exchange == 'BSE_INDEX':
            return 'BSE_INDEX'  # ✅ Keep BSE_INDEX in data for client filtering
        else:
            return subscription_exchange  # Keep as-is for regular exchanges

    def _handle_ticks(self, ticks: List[Dict]):
        """Handle incoming ticks from WebSocket"""
        if not ticks:
            return
        
        try:
            for tick in ticks:
                transformed_tick = self._transform_tick(tick)
                if transformed_tick:
                    symbol = transformed_tick['symbol']
                    token = tick.get('instrument_token')
                    original_tick_mode = transformed_tick.get('mode', 'ltp')  # Original mode from the tick
                    subscription_exchange = None
                    subscribed_modes = set()  # Track which modes this symbol is subscribed to
                    
                    # Get subscription info to determine exchange and subscribed modes
                    with self.lock:
                        for key, sub_info in self.subscribed_symbols.items():
                            if sub_info['token'] == token:
                                # Found a subscription for this token
                                subscription_exchange = sub_info['exchange']
                                mode_num = sub_info['mode']
                                subscribed_modes.add(mode_num)
                    
                    if not subscription_exchange:
                        self.logger.warning(f"No subscription info found for token: {token}")
                        continue
                    
                    # Set the data exchange field
                    data_exchange = self._map_data_exchange(subscription_exchange)
                    transformed_tick['exchange'] = data_exchange
                    
                    # If we have a 'full' mode tick, create and publish separate messages for each subscribed mode
                    if original_tick_mode == 'full':
                        # Always publish the full depth data first
                        depth_tick = transformed_tick.copy()
                        depth_tick['mode'] = 'full'
                        depth_topic = self._generate_topic(symbol, subscription_exchange, 'DEPTH')
                        self.logger.debug(f"📊 Publishing DEPTH data to topic: {depth_topic}")
                        self.publish_market_data(depth_topic, depth_tick)
                        
                        # If subscribed to Quote (mode 2), publish quote data
                        if 2 in subscribed_modes:
                            quote_tick = transformed_tick.copy()
                            # Remove depth data for quote message
                            if 'depth' in quote_tick:
                                del quote_tick['depth']
                            quote_tick['mode'] = 'quote'
                            quote_topic = self._generate_topic(symbol, subscription_exchange, 'QUOTE')
                            self.logger.debug(f"📊 Publishing QUOTE data to topic: {quote_topic}")
                            self.publish_market_data(quote_topic, quote_tick)
                        
                        # If subscribed to LTP (mode 1), publish LTP data
                        if 1 in subscribed_modes:
                            ltp_tick = {
                                'symbol': symbol,
                                'exchange': data_exchange,
                                'mode': 'ltp',
                                'ltp': transformed_tick.get('ltp', 0),
                                'timestamp': transformed_tick.get('timestamp', int(time.time() * 1000))
                            }
                            ltp_topic = self._generate_topic(symbol, subscription_exchange, 'LTP')
                            self.logger.debug(f"📊 Publishing LTP data to topic: {ltp_topic}")
                            self.publish_market_data(ltp_topic, ltp_tick)
                            self.logger.debug(f"📊 LTP Data should be available for polling: {subscription_exchange}:{symbol}")
                    else:
                        # For non-full modes, just publish as-is
                        mode_str = {
                            'ltp': 'LTP',
                            'quote': 'QUOTE',
                            'full': 'DEPTH'
                        }.get(original_tick_mode, 'LTP')
                        
                        topic = self._generate_topic(symbol, subscription_exchange, mode_str)
                        self.logger.debug(f"📊 Publishing to topic: {topic}")
                        self.logger.debug(f"📊 Data structure: {transformed_tick}")
                        
                        # Publish to ZeroMQ
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
            
            # Check if this is an index based on exchange
            is_index = exchange in ['NSE_INDEX', 'BSE_INDEX']
            
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
        # ✅ Keep original exchange in data - don't remap here since _handle_ticks will handle it
        # Make sure we're using NSE_INDEX explicitly
        
        if mode == 'ltp':
            # Index LTP mode - match Angel adapter structure exactly
            transformed = {
                'symbol': symbol,
                'exchange': 'NSE_INDEX',  # ✅ Use NSE_INDEX explicitly
                'mode': mode,
                'ltp': tick.get('last_traded_price', tick.get('last_price', 0)),
                'ltt': tick.get('exchange_timestamp', tick.get('timestamp', int(time.time() * 1000))),
                'timestamp': tick.get('timestamp', int(time.time() * 1000))
            }
        
        elif mode in ['quote', 'full']:
            # Index Quote/Full mode - comprehensive data like Angel adapter
            transformed = {
                'symbol': symbol,
                'exchange': exchange,  # ✅ Keep original exchange
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
                'exchange': exchange,  # ✅ Keep original exchange
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
            
            # Check if this is an index based on exchange
            is_index = exchange in ['NSE_INDEX', 'BSE_INDEX']
            
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
        # Keep original exchange in data - don't remap here since _handle_ticks will handle it
        # Make sure we're using NSE_INDEX explicitly
        
        if mode == 'ltp':
            # Index LTP mode - match Angel adapter structure exactly
            transformed = {
            'symbol': symbol,
            'exchange': 'NSE_INDEX',  # Use NSE_INDEX explicitly
            'mode': mode,
            'ltp': tick.get('last_traded_price', tick.get('last_price', 0)),
            'ltt': tick.get('exchange_timestamp', tick.get('timestamp', int(time.time() * 1000))),
            'timestamp': tick.get('timestamp', int(time.time() * 1000))
        }
    
        elif mode in ['quote', 'full']:
            # Index Quote/Full mode - comprehensive data like Angel adapter
            transformed = {
                'symbol': symbol,
                'exchange': exchange,  # Keep original exchange
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
                'exchange': exchange,  # Keep original exchange
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
    
    def disconnect(self) -> Dict[str, Any]:
        """Disconnect from the WebSocket and clean up resources"""
        try:
            with self.lock:
                if self.ws_client:
                    self.logger.info("Stopping WebSocket client during disconnect...")
                    self.ws_client.stop()
                    self.ws_client = None
                    self.running = False
                    self.connected = False
                    self.reconnect_attempts = 0
                    self.subscribed_symbols.clear()
                    self.token_to_symbol.clear()
                    self.logger.info("WebSocket client stopped and references cleared")
                
            # Clean up ZeroMQ resources
            self.cleanup_zmq()
            
            return {'status': 'success', 'message': 'Disconnected successfully and resources cleaned up'}
        except Exception as e:
            self.logger.error(f"Error disconnecting: {e}")
            try:
                # Last attempt to clean up ZMQ resources
                self.cleanup_zmq()
            except Exception as zmq_err:
                self.logger.error(f"Error during ZMQ cleanup after disconnect error: {zmq_err}")
            
            return {'status': 'error', 'message': f"Error disconnecting: {e}"}
        
    def cleanup(self):
        """Clean up all resources including WebSocket connection and ZMQ resources"""
        try:
            # First disconnect the WebSocket if connected
            with self.lock:
                if self.ws_client:
                    try:
                        self.ws_client.stop()
                        self.ws_client = None
                    except Exception as ws_err:
                        self.logger.error(f"Error stopping WebSocket client during cleanup: {ws_err}")
                
                # Reset adapter state
                self.running = False
                self.connected = False
                self.reconnect_attempts = 0
                
                # Clear subscription records
                self.subscribed_symbols.clear()
                self.token_to_symbol.clear()
            
            # Clean up ZMQ resources using base class method
            self.cleanup_zmq()
            
            self.logger.info("✅ Zerodha adapter cleaned up completely")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            # Try one last time to clean up ZMQ resources
            try:
                self.cleanup_zmq()
            except Exception as zmq_err:
                self.logger.error(f"Error cleaning up ZMQ during final cleanup attempt: {zmq_err}")
    
    def __del__(self):
        """Destructor - ensures resources are released even when adapter is garbage collected"""
        try:
            # During garbage collection, we may not have logger available
            try:
                self.cleanup()
            except Exception:
                pass
                
            # Last resort cleanup
            try:
                self.cleanup_zmq()
            except Exception:
                pass
        except Exception:
            # Can't use logger in __del__ reliably
            pass
