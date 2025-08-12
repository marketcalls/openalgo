import threading
import json
import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime

from database.auth_db import get_auth_token, get_feed_token
from database.token_db import get_token

import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .fyers_mapping import FyersExchangeMapper, FyersCapabilityRegistry
from .fyers_websocket import FyersWebSocketClient

class FyersWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Fyers-specific implementation of the WebSocket adapter"""
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("fyers_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "fyers"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()
        self.access_token = None
        
    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with Fyers WebSocket API
        
        Args:
            broker_name: Name of the broker (always 'fyers' in this case)
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
            
            if not auth_token:
                self.logger.error(f"No authentication token found for user {user_id}")
                raise ValueError(f"No authentication token found for user {user_id}")
            
            # For Fyers, the auth_token should be in format "appid:accesstoken"
            self.access_token = auth_token
            
        else:
            # Use provided tokens
            auth_token = auth_data.get('auth_token')
            app_id = auth_data.get('app_id', '')
            
            if not auth_token:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data")
            
            # Format access token for Fyers
            if app_id and ':' not in auth_token:
                self.access_token = f"{app_id}:{auth_token}"
            else:
                self.access_token = auth_token
        
        # Create FyersWebSocketClient instance (custom implementation)
        self.ws_client = FyersWebSocketClient(access_token=self.access_token)
        
        # Set callbacks
        self.ws_client.set_callbacks(
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        
        self.running = True
        
    def connect(self) -> None:
        """Establish connection to Fyers WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return
            
        try:
            self.logger.info("Connecting to Fyers WebSocket...")
            self.ws_client.connect()
            # Give it a moment to establish connection
            time.sleep(2)
        except Exception as e:
            self.logger.error(f"Failed to connect: {e}")
    
    def disconnect(self) -> None:
        """Disconnect from Fyers WebSocket"""
        self.running = False
        if hasattr(self, 'ws_client') and self.ws_client:
            self.ws_client.disconnect()
            
        # Clean up ZeroMQ resources
        self.cleanup_zmq()
    
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data with Fyers-specific implementation
        
        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Depth
            depth_level: Market depth level (5, 20)
            
        Returns:
            Dict: Response with status and error message if applicable
        """
        # Validate the mode
        if mode not in [1, 2, 3]:
            return self._create_error_response("INVALID_MODE", 
                                              f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)")
                                              
        # If depth mode, check if supported depth level
        if mode == 3 and depth_level not in [5, 20]:
            # Fyers supports 5 and 20 level depth
            actual_depth = FyersCapabilityRegistry.get_fallback_depth_level(exchange, depth_level)
            self.logger.info(f"Using depth level {actual_depth} instead of requested {depth_level}")
            depth_level = actual_depth
        
        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND", 
                                              f"Symbol {symbol} not found for exchange {exchange}")
            
        token = token_info['token']
        brexchange = token_info['brexchange']
        
        # Get Fyers-specific broker symbol (brsymbol) directly from database
        brsymbol = self._get_fyers_broker_symbol(symbol, exchange)
        
        # Log the token info for debugging - show all fields
        self.logger.info(f"Token info for {symbol}.{exchange}: {token_info}")
        self.logger.info(f"Fyers brsymbol: {brsymbol}")
        
        # For Fyers, check if we have a fytoken or use symbol format
        # Different exchanges might need different formats
        fyers_symbol = None
        
        # Check if we got the broker symbol from database
        if brsymbol:
            # For NSE CASH equities only, brsymbol works fine
            if exchange == 'NSE' and '-EQ' in brsymbol:
                fyers_symbol = brsymbol
                self.logger.info(f"Using NSE equity brsymbol: {fyers_symbol}")
            # For F&O (NFO), BSE, MCX, Indices - use token instead of brsymbol
            elif exchange in ['BSE', 'MCX', 'NFO'] or 'INDEX' in brsymbol.upper() or 'FUT' in brsymbol.upper():
                # Try using the token as subscription identifier
                fyers_symbol = token
                self.logger.warning(f"Using TOKEN for {exchange}: {fyers_symbol} (instead of brsymbol: {brsymbol})")
            else:
                # Default to brsymbol for other cases
                fyers_symbol = brsymbol
                self.logger.info(f"Using brsymbol: {fyers_symbol}")
        elif 'fytoken' in token_info:
            fyers_symbol = token_info['fytoken']
            self.logger.info(f"Using fytoken: {fyers_symbol}")
        elif 'symbol' in token_info and token_info['symbol']:
            # Use the symbol from the token info if available
            fyers_symbol = token_info['symbol']
            self.logger.info(f"Using database symbol: {fyers_symbol}")
        else:
            # Fallback: Create Fyers symbol format
            # Based on your input: Fyers expects "TCS-EQ", not "NSE:TCS-EQ"
            
            # Determine segment suffix based on exchange type
            segment_suffix = ""
            if exchange in ['NSE', 'BSE']:
                segment_suffix = "-EQ"  # Equity segment
            elif exchange == 'NFO':
                # For F&O, need to check if it's index/stock future/option
                segment_suffix = ""  
            elif exchange == 'MCX':
                segment_suffix = ""  # No suffix for commodities
            elif exchange == 'CDS':
                segment_suffix = ""  # No suffix for currency
                
            # Create Fyers symbol - just symbol with suffix, no exchange prefix
            fyers_symbol = f"{symbol}{segment_suffix}"
            
        self.logger.info(f"Final Fyers symbol: {symbol}.{exchange} -> {fyers_symbol}")
        
        # Determine data type based on mode
        data_type = "SymbolUpdate" if mode in [1, 2] else "DepthUpdate"
        
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
                'fyers_symbol': fyers_symbol,
                'brsymbol': brsymbol,  # Store brsymbol for matching
                'data_type': data_type
            }
        
        # Subscribe if connected
        if self.ws_client and self.ws_client.is_connected():
            try:
                success = self.ws_client.subscribe([fyers_symbol], data_type)
                if not success:
                    return self._create_error_response("SUBSCRIPTION_ERROR", 
                                                      "Failed to subscribe to symbol")
            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))
        else:
            self.logger.info(f"Queuing subscription for {symbol}.{exchange}")
        
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
        
        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"
        
        # Get subscription info
        subscription = None
        with self.lock:
            if correlation_id in self.subscriptions:
                subscription = self.subscriptions[correlation_id]
                del self.subscriptions[correlation_id]
        
        # Unsubscribe if connected and subscription exists
        if self.ws_client and self.ws_client.is_connected() and subscription:
            try:
                fyers_symbol = subscription['fyers_symbol']
                data_type = subscription['data_type']
                self.ws_client.unsubscribe([fyers_symbol], data_type)
            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))
        
        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode
        )
    
    def _on_open(self) -> None:
        """Callback when connection is established"""
        self.logger.info("Connected to Fyers WebSocket")
        self.connected = True
        
        # Resubscribe to existing subscriptions if reconnecting
        with self.lock:
            if self.subscriptions:
                symbol_update_list = []
                depth_update_list = []
                
                for sub in self.subscriptions.values():
                    if sub['data_type'] == 'DepthUpdate':
                        depth_update_list.append(sub['fyers_symbol'])
                    else:
                        symbol_update_list.append(sub['fyers_symbol'])
                
                # Resubscribe in batches
                if symbol_update_list:
                    try:
                        self.ws_client.subscribe(symbol_update_list, "SymbolUpdate")
                        self.logger.info(f"Resubscribed to {len(symbol_update_list)} symbols for quotes")
                    except Exception as e:
                        self.logger.error(f"Error resubscribing to symbols: {e}")
                        
                if depth_update_list:
                    try:
                        self.ws_client.subscribe(depth_update_list, "DepthUpdate")
                        self.logger.info(f"Resubscribed to {len(depth_update_list)} symbols for depth")
                    except Exception as e:
                        self.logger.error(f"Error resubscribing to depth: {e}")
    
    def _on_error(self, error) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"Fyers WebSocket error: {error}")
    
    def _on_close(self, close_msg) -> None:
        """Callback when connection is closed"""
        self.logger.info(f"Fyers WebSocket connection closed: {close_msg}")
        self.connected = False
    
    def _on_message(self, message) -> None:
        """Callback for messages from the WebSocket"""
        try:
            # Log raw message for debugging
            if isinstance(message, (bytes, bytearray)):
                self.logger.debug(f"Raw Fyers binary message: {len(message)} bytes")
            else:
                self.logger.debug(f"Raw Fyers message: {message}")
            
            # Parse the message based on type
            if isinstance(message, str):
                data = json.loads(message)
            elif isinstance(message, dict):
                data = message
            else:
                self.logger.warning(f"Unexpected message type: {type(message)}")
                return
            
            # Check message type
            msg_type = data.get('T')
            
            # Handle different message types
            if msg_type == 'L2':  # Level 2 market data
                self._process_market_data(data)
            elif msg_type == 'SUB_ACK':  # Subscription acknowledgment
                self.logger.info(f"Subscription acknowledged: {data}")
            elif msg_type == 'UNSUB_ACK':  # Unsubscription acknowledgment
                self.logger.info(f"Unsubscription acknowledged: {data}")
            elif msg_type == 'ERROR':  # Error message
                self.logger.error(f"Fyers error: {data}")
            elif msg_type == 'sf':  # Symbol Feed (Fyers specific)
                self.logger.info(f"Symbol feed data: {data}")
                self._process_symbol_update(data)
            elif msg_type == 'dp':  # Depth data (Fyers specific)
                self.logger.info(f"Depth data: {data}")
                self._process_market_data(data)
            elif msg_type == 'ack':  # General acknowledgment
                self.logger.info(f"Acknowledgment received: {data}")
            else:
                # Regular market data (SymbolUpdate format)
                # Only log if we have actual data
                if data.get('symbol') or data.get('probable_ltp'):
                    self.logger.info(f"Processing market data: symbol={data.get('symbol')}, ltp={data.get('probable_ltp')}")
                self._process_symbol_update(data)
                
        except Exception as e:
            self.logger.error(f"Error processing market data: {e}", exc_info=True)
    
    def _process_symbol_update(self, data):
        """
        Process symbol update message
        
        Args:
            data: Symbol update data from Fyers
        """
        # Extract symbol from the message
        fyers_symbol = data.get('symbol', data.get('s'))
        
        # If no symbol in data, try to match by token or other means
        if not fyers_symbol:
            # Try to find subscription by token
            token = data.get('token')
            if token:
                self.logger.info(f"No symbol in message, trying to match by token: {token}")
                
                # Look through subscriptions to find matching token
                with self.lock:
                    for sub in self.subscriptions.values():
                        if sub['token'] == token:
                            fyers_symbol = sub['fyers_symbol']
                            self.logger.info(f"Matched token {token} to subscription: {fyers_symbol}")
                            break
        
        if not fyers_symbol:
            self.logger.warning(f"No symbol in message and no token match. Data keys: {list(data.keys())}")
            return
        
        # Find the subscription that matches this symbol
        subscription = None
        with self.lock:
            self.logger.info(f"Looking for subscription matching symbol: {fyers_symbol}")
            for correlation_id, sub in self.subscriptions.items():
                self.logger.info(f"Checking subscription {correlation_id}: fyers_symbol={sub['fyers_symbol']}, brsymbol={sub.get('brsymbol')}")
                # Direct match by fyers_symbol
                if sub['fyers_symbol'] == fyers_symbol:
                    subscription = sub
                    self.logger.info(f"Direct match found: {correlation_id}")
                    break
                # If we used token subscription, also try matching by brsymbol
                elif sub['fyers_symbol'].isdigit() and sub.get('brsymbol') == fyers_symbol:
                    subscription = sub
                    self.logger.info(f"Matched token subscription {sub['fyers_symbol']} to incoming symbol {fyers_symbol}")
                    break
        
        if not subscription:
            # Log more details about unmatched symbols
            self.logger.warning(f"Received data for unsubscribed symbol: {fyers_symbol}")
            with self.lock:
                active_subs = []
                for s in self.subscriptions.values():
                    if s['fyers_symbol'].isdigit():
                        # Token subscription - show both token and brsymbol
                        active_subs.append(f"{s['fyers_symbol']} (token for {s.get('brsymbol', 'unknown')})")
                    else:
                        active_subs.append(s['fyers_symbol'])
                self.logger.debug(f"Active subscriptions: {active_subs}")
            return
        
        # Create topic for ZeroMQ
        symbol = subscription['symbol']
        exchange = subscription['exchange']
        mode = subscription['mode']
        
        mode_str = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}[mode]
        topic = f"{exchange}_{symbol}_{mode_str}"
        
        # Normalize the data
        market_data = self._normalize_market_data(data, mode)
        
        # Add metadata
        market_data.update({
            'symbol': symbol,
            'exchange': exchange,
            'mode': mode,
            'timestamp': int(time.time() * 1000)  # Current timestamp in ms
        })
        
        # Publish to ZeroMQ
        self.publish_market_data(topic, market_data)
    
    def _process_market_data(self, data):
        """
        Process Level 2 market data
        
        Args:
            data: L2 market data from Fyers
        """
        # Extract symbol list
        symbols_data = data.get('L2', [])
        
        for symbol_data in symbols_data:
            fyers_symbol = symbol_data.get('symbol')
            if not fyers_symbol:
                continue
                
            # Find matching subscription
            subscription = None
            with self.lock:
                for sub in self.subscriptions.values():
                    if sub['fyers_symbol'] == fyers_symbol:
                        subscription = sub
                        break
            
            if not subscription:
                continue
                
            # Process and publish the data
            symbol = subscription['symbol']
            exchange = subscription['exchange']
            mode = subscription['mode']
            
            mode_str = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}[mode]
            topic = f"{exchange}_{symbol}_{mode_str}"
            
            # Normalize the data
            market_data = self._normalize_market_data(symbol_data, mode)
            
            # Add metadata
            market_data.update({
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'timestamp': int(time.time() * 1000)
            })
            
            # Publish to ZeroMQ
            self.publish_market_data(topic, market_data)
    
    def _normalize_market_data(self, message, mode) -> Dict[str, Any]:
        """
        Normalize Fyers data format to a common format
        
        Args:
            message: The raw message from Fyers
            mode: Subscription mode
            
        Returns:
            Dict: Normalized market data
        """
        # Handle protobuf parsed data from new FyersProtoParser
        if message.get('data_type') == 'market_data':
            # This is parsed protobuf data using proper schema
            result = {}
            
            # Extract price data
            ltp = message.get('ltp', message.get('probable_ltp', 0))
            if not ltp and 'prices' in message:
                # Use first reasonable price if available
                prices = message['prices']
                if prices:
                    ltp = prices[0]['value']
            
            result['ltp'] = ltp
            result['ltt'] = message.get('ltt', int(time.time()))
            
            # Extract other quote data if available
            result.update({
                'volume': message.get('volume', 0),
                'open': message.get('open', 0),
                'high': message.get('high', 0),
                'low': message.get('low', 0),
                'close': message.get('close', 0),
                'ltq': message.get('ltq', 0),
                'oi': message.get('oi', 0)
            })
            
            if mode == 1:  # LTP mode
                return {
                    'ltp': result['ltp'],
                    'ltt': result['ltt']
                }
            elif mode == 2:  # Quote mode
                return {
                    'ltp': result['ltp'],
                    'ltt': result['ltt'],
                    'volume': result['volume'],
                    'open': result['open'],
                    'high': result['high'],
                    'low': result['low'],
                    'close': result['close'],
                    'last_quantity': result['ltq'],
                    'average_price': 0,  # Not in basic schema yet
                    'total_buy_quantity': message.get('total_buy_quantity', 0),
                    'total_sell_quantity': message.get('total_sell_quantity', 0),
                    'change': 0,  # Calculate if needed
                    'change_percent': 0.0,
                    '_raw_data': {
                        'token': message.get('token'),
                        'symbol': message.get('symbol'),
                        'raw_length': message.get('raw_length', 0)
                    }
                }
            elif mode == 3:  # Depth mode
                depth_data = message.get('depth', {'buy': [], 'sell': []})
                return {
                    'ltp': result['ltp'],
                    'ltt': result['ltt'],
                    'volume': result['volume'],
                    'open': result['open'],
                    'high': result['high'],
                    'low': result['low'],
                    'close': result['close'],
                    'oi': result['oi'],
                    'upper_circuit': 0,  # Not in schema yet
                    'lower_circuit': 0,
                    'depth': {
                        'buy': self._convert_depth_levels(depth_data['buy']),
                        'sell': self._convert_depth_levels(depth_data['sell'])
                    },
                    '_raw_data': {
                        'token': message.get('token'),
                        'symbol': message.get('symbol'),
                        'raw_length': message.get('raw_length', 0)
                    }
                }
            else:
                return result
                
        # Handle standard JSON message format (if Fyers sends JSON)        
        if mode == 1:  # LTP mode
            return {
                'ltp': message.get('ltp', message.get('cmd', {}).get('v', 0)),
                'ltt': message.get('tt', int(time.time()))  # Trade time
            }
        elif mode == 2:  # Quote mode
            # Handle both direct fields and cmd structure
            cmd = message.get('cmd', {})
            return {
                'ltp': message.get('ltp', cmd.get('v', 0)),
                'ltt': message.get('tt', cmd.get('t', int(time.time()))),
                'volume': message.get('v', cmd.get('volume', 0)),
                'open': message.get('open_price', cmd.get('o', 0)),
                'high': message.get('high_price', cmd.get('h', 0)),
                'low': message.get('low_price', cmd.get('l', 0)),
                'close': message.get('prev_close_price', cmd.get('c', 0)),
                'last_quantity': message.get('last_traded_qty', 0),
                'average_price': message.get('avg_trade_price', 0),
                'total_buy_quantity': message.get('bid_size', 0),
                'total_sell_quantity': message.get('ask_size', 0),
                'change': message.get('ch', cmd.get('ch', 0)),
                'change_percent': message.get('chp', cmd.get('chp', 0))
            }
        elif mode == 3:  # Depth mode
            cmd = message.get('cmd', {})
            result = {
                'ltp': message.get('ltp', cmd.get('v', 0)),
                'ltt': message.get('tt', cmd.get('t', int(time.time()))),
                'volume': message.get('v', cmd.get('volume', 0)),
                'open': message.get('open_price', cmd.get('o', 0)),
                'high': message.get('high_price', cmd.get('h', 0)),
                'low': message.get('low_price', cmd.get('l', 0)),
                'close': message.get('prev_close_price', cmd.get('c', 0)),
                'oi': message.get('oi', cmd.get('oi', 0)),
                'upper_circuit': message.get('upper_ckt', 0),
                'lower_circuit': message.get('lower_ckt', 0)
            }
            
            # Add depth data if available
            if 'bids' in message or 'bid' in cmd:
                bids = message.get('bids', cmd.get('bid', []))
                asks = message.get('asks', cmd.get('ask', []))
                
                result['depth'] = {
                    'buy': self._extract_depth_data(bids),
                    'sell': self._extract_depth_data(asks)
                }
            else:
                result['depth'] = {
                    'buy': self._create_empty_depth(),
                    'sell': self._create_empty_depth()
                }
                
            return result
        else:
            return {}
    
    def _extract_depth_data(self, depth_list) -> List[Dict[str, Any]]:
        """
        Extract depth data from Fyers format
        
        Args:
            depth_list: List of depth levels from Fyers
            
        Returns:
            List: List of depth levels with price, quantity, and orders
        """
        depth = []
        
        # Fyers sends depth as list of dicts or list of lists
        for level in depth_list:
            if isinstance(level, dict):
                depth.append({
                    'price': level.get('price', 0),
                    'quantity': level.get('volume', level.get('qty', 0)),
                    'orders': level.get('orders', level.get('ord', 0))
                })
            elif isinstance(level, list) and len(level) >= 3:
                # Format: [price, quantity, orders]
                depth.append({
                    'price': level[0],
                    'quantity': level[1],
                    'orders': level[2] if len(level) > 2 else 0
                })
        
        # If no depth data, return empty levels
        if not depth:
            for i in range(5):  # Default to 5 empty levels
                depth.append({
                    'price': 0.0,
                    'quantity': 0,
                    'orders': 0
                })
                
        return depth
    
    def _create_empty_depth(self) -> List[Dict[str, Any]]:
        """
        Create empty depth levels
        
        Returns:
            List: List of empty depth levels
        """
        return [
            {'price': 0.0, 'quantity': 0, 'orders': 0}
            for _ in range(5)
        ]
    
    def _convert_depth_levels(self, depth_levels) -> List[Dict[str, Any]]:
        """
        Convert depth levels from protobuf parser format to standard format
        
        Args:
            depth_levels: List of depth levels from protobuf parser
            
        Returns:
            List: Standardized depth levels
        """
        if not depth_levels:
            return self._create_empty_depth()
            
        converted = []
        for level in depth_levels:
            converted.append({
                'price': level.get('price', 0.0),
                'quantity': level.get('quantity', 0),
                'orders': level.get('orders', 0)
            })
            
        # Ensure we have at least 5 levels
        while len(converted) < 5:
            converted.append({'price': 0.0, 'quantity': 0, 'orders': 0})
            
        return converted[:5]  # Return only first 5 levels
    
    def _get_fyers_broker_symbol(self, symbol: str, exchange: str) -> Optional[str]:
        """
        Get Fyers-specific broker symbol (brsymbol) from database
        
        Args:
            symbol: Trading symbol (e.g., 'TCS')
            exchange: Exchange code (e.g., 'NSE')
            
        Returns:
            str: Broker symbol in Fyers format (e.g., 'NSE:TCS-EQ') or None
        """
        try:
            from database.symbol import SymToken
            sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
            
            if sym_token and sym_token.brsymbol:
                return sym_token.brsymbol
            else:
                self.logger.warning(f"No brsymbol found for {symbol}.{exchange}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error getting Fyers broker symbol: {e}")
            return None

