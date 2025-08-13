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
        
        # Determine subscription format based on exchange
        # NSE cash equities: Use symbol format (NSE:SBIN-EQ)
        # BSE, MCX, NFO, Indices: Use token format
        fyers_symbol = None
        use_token = False
        
        # Check exchange type to determine subscription format
        if exchange == 'NSE' and brsymbol and '-EQ' in brsymbol:
            # NSE cash equities - use symbol format
            fyers_symbol = brsymbol
            self.logger.info(f"Using NSE equity symbol: {fyers_symbol}")
        elif exchange in ['BSE', 'MCX', 'NFO', 'CDS']:
            # These exchanges require token-based subscription
            fyers_symbol = token
            use_token = True
            self.logger.info(f"Using TOKEN for {exchange}: {fyers_symbol}")
        elif exchange == 'NSE_INDEX' or (brsymbol and 'INDEX' in brsymbol.upper()):
            # Indices also need token-based subscription
            fyers_symbol = token
            use_token = True
            self.logger.info(f"Using TOKEN for INDEX: {fyers_symbol}")
        elif brsymbol:
            # Use broker symbol if available
            fyers_symbol = brsymbol
            self.logger.info(f"Using brsymbol: {fyers_symbol}")
        else:
            # Fallback to token
            fyers_symbol = token
            use_token = True
            self.logger.warning(f"Fallback to TOKEN: {fyers_symbol}")
            
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
        
        # Subscribe if connected (following Angel adapter pattern)
        self.logger.info(f"Subscription check: self.connected={getattr(self, 'connected', False)}, ws_client_exists={self.ws_client is not None}")
        if self.connected and self.ws_client:
            try:
                # Pass the mode to websocket client for proper Fyers mode selection
                self.ws_client.subscribe([fyers_symbol], data_type, mode=mode)
                self.logger.info(f"Subscription sent for {fyers_symbol}")
            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))
        else:
            self.logger.info(f"WebSocket not connected. Queuing subscription for {symbol}.{exchange}")
            # Still return success even if queued (following Angel pattern)
            # The subscription will be processed when connection is established
        
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
        # Extract symbol or token from the message
        # Handle both direct fields and official parser structure
        fyers_symbol = data.get('symbol', data.get('s'))
        token = data.get('token', data.get('fyToken'))
        
        # For official parser output, also check symbol_key
        if not fyers_symbol:
            fyers_symbol = data.get('symbol_key')
        
        # Log the data we're processing for debugging
        ltp_value = data.get('ltp', data.get('probable_ltp', 0))
        self.logger.info(f"Processing market data: symbol={fyers_symbol}, token={token}, ltp={ltp_value}")
        
        # Special handling for numeric-only data (common in LTP mode)
        if not fyers_symbol and not token:
            # Check if we have a simple numeric value that could be a price
            numeric_keys = [k for k, v in data.items() if isinstance(v, (int, float)) and k.isdigit()]
            if numeric_keys and (data.get('probable_ltp') or data.get('ltp')):
                # This might be LTP data with just a price, try to match to active subscriptions
                self.logger.debug(f"Potential LTP data without symbol: {data}")
                # Use the first active subscription as fallback
                with self.lock:
                    if self.subscriptions:
                        first_sub = next(iter(self.subscriptions.values()))
                        fyers_symbol = first_sub['fyers_symbol']
                        token = first_sub['token']
                        self.logger.info(f"Matched LTP data to active subscription: {first_sub['symbol']}.{first_sub['exchange']}")
        
        # If we have a token but no symbol, try to match by token
        if not fyers_symbol and token:
            self.logger.debug(f"Matching by token: {token}")
            
            # Look through subscriptions to find matching token
            with self.lock:
                for sub in self.subscriptions.values():
                    # Check if subscription token matches or fyers_symbol is the token
                    if sub['token'] == str(token) or sub['fyers_symbol'] == str(token):
                        fyers_symbol = sub['fyers_symbol']
                        self.logger.debug(f"Matched token {token} to subscription")
                        break
        
        if not fyers_symbol and not token:
            # Log and skip data without proper symbol/token identification
            if data.get('probable_ltp') or data.get('ltp'):
                self.logger.warning(f"Protobuf parser failed to extract symbol/token from market data: {data}")
            else:
                self.logger.debug(f"No symbol/token and no price data. Keys: {list(data.keys())}")
            return
        
        # If still no fyers_symbol but we have token, use token as fyers_symbol
        if not fyers_symbol and token:
            fyers_symbol = str(token)
            self.logger.debug(f"Using token as fyers_symbol: {fyers_symbol}")
        
        # Special handling for numeric symbols (likely tokens in LTP mode)
        if fyers_symbol and fyers_symbol.isdigit():
            # Try to match by token in subscriptions
            with self.lock:
                for sub in self.subscriptions.values():
                    if sub['token'] == fyers_symbol:
                        # Use the original symbol for topic generation
                        original_symbol = sub['symbol']
                        self.logger.info(f"Matched token {fyers_symbol} to subscription {original_symbol}.{sub['exchange']}")
                        # Continue processing with original symbol for topic
                        symbol = original_symbol
                        exchange = sub['exchange']
                        break
        
        # Find the subscription that matches this symbol
        subscription = None
        with self.lock:
            for correlation_id, sub in self.subscriptions.items():
                # Direct match by fyers_symbol
                if sub['fyers_symbol'] == fyers_symbol:
                    subscription = sub
                    break
                # Match by token
                elif sub['token'] == fyers_symbol:
                    subscription = sub
                    break
                # If incoming symbol is brsymbol and subscription uses token
                elif sub['fyers_symbol'].isdigit() and sub.get('brsymbol') == fyers_symbol:
                    subscription = sub
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
        
        # Important: Like Angel, check if we have actual mode from message
        # This ensures data is published with the correct mode identifier
        actual_msg_mode = mode  # Default to subscription mode
        
        # For Fyers protobuf data, determine actual mode based on what's available
        if data.get('data_type') == 'socket_message':
            # Check what data fields are present to determine actual mode
            has_ohlc = any(key in data for key in ['open', 'high', 'low', 'close', 'volume'])
            has_depth = 'depth' in data or any('bid' in key or 'ask' in key for key in data.keys())
            
            self.logger.info(f"Mode detection: has_ohlc={has_ohlc}, has_depth={has_depth}, subscription_mode={mode}")
            self.logger.info(f"Available data keys: {list(data.keys())}")
            
            if has_depth and mode == 3:
                actual_msg_mode = 3  # Depth mode
            elif has_ohlc:
                actual_msg_mode = 2  # Quote mode (has OHLC)
            else:
                actual_msg_mode = 1  # LTP mode (basic data)
            
            self.logger.info(f"Determined actual_msg_mode: {actual_msg_mode} (subscription was {mode})")
        
        mode_str = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}[actual_msg_mode]
        topic = f"{exchange}_{symbol}_{mode_str}"
        
        # Normalize the data based on actual message mode like Angel does
        market_data = self._normalize_market_data(data, actual_msg_mode)
        
        # Add metadata
        market_data.update({
            'symbol': symbol,
            'exchange': exchange,
            'mode': actual_msg_mode,  # Use actual message mode like Angel
            'timestamp': int(time.time() * 1000)  # Current timestamp in ms
        })
        
        # Log the normalized data for debugging
        self.logger.info(f"Publishing to ZeroMQ - Topic: {topic}, LTP: {market_data.get('ltp', 0)}")
        
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
        # Handle Fyers JSON symbol feed format (sf)
        if message.get('type') == 'sf':
            # This is Fyers JSON symbol feed data
            ltp = message.get('ltp', 0)
            
            if mode == 1:  # LTP mode
                return {
                    'ltp': float(ltp) if ltp else 0.0,
                    'ltt': message.get('last_traded_time', int(time.time()))
                }
            elif mode == 2:  # Quote mode
                return {
                    'ltp': float(ltp) if ltp else 0.0,
                    'ltt': message.get('last_traded_time', int(time.time())),
                    'volume': message.get('vol_traded_today', 0),
                    'open': message.get('open_price', 0),
                    'high': message.get('high_price', 0),
                    'low': message.get('low_price', 0),
                    'close': message.get('prev_close_price', 0),
                    'last_quantity': message.get('last_traded_qty', 0),
                    'average_price': message.get('avg_trade_price', 0),
                    'total_buy_quantity': message.get('tot_buy_qty', 0),
                    'total_sell_quantity': message.get('tot_sell_qty', 0),
                    'change': message.get('ch', 0),
                    'change_percent': message.get('chp', 0),
                    'bid_price': message.get('bid_price', 0),
                    'ask_price': message.get('ask_price', 0),
                    'bid_size': message.get('bid_size', 0),
                    'ask_size': message.get('ask_size', 0)
                }
            elif mode == 3:  # Depth mode - need to handle depth data separately
                base_data = {
                    'ltp': float(ltp) if ltp else 0.0,
                    'ltt': message.get('last_traded_time', int(time.time())),
                    'volume': message.get('vol_traded_today', 0),
                    'open': message.get('open_price', 0),
                    'high': message.get('high_price', 0),
                    'low': message.get('low_price', 0),
                    'close': message.get('prev_close_price', 0),
                    'oi': 0,  # Not in basic sf message
                    'upper_circuit': 0,  # Not in basic sf message
                    'lower_circuit': 0,
                    'depth': {
                        'buy': self._create_empty_depth(),
                        'sell': self._create_empty_depth()
                    }
                }
                return base_data
        
        # Handle protobuf parsed data from official FyersOfficialProtoParser
        if message.get('data_type') == 'socket_message':
            # This is parsed protobuf data using the official .proto schema
            result = {}
            
            # Extract price data - official parser puts LTP in 'ltp' key
            ltp = message.get('ltp', 0)
            if not ltp:
                # Fallback to older parser format
                ltp = message.get('probable_ltp', 0)
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
                    'total_buy_quantity': message.get('total_buy_qty', 0),
                    'total_sell_quantity': message.get('total_sell_qty', 0),
                    'change': 0,  # Calculate if needed
                    'change_percent': 0.0,
                    'bid_price': message.get('bid', 0),
                    'ask_price': message.get('ask', 0),
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
        
        # Handle protobuf parsed data from legacy FyersProtoParser
        if message.get('data_type') == 'market_data':
            # This is parsed protobuf data using legacy parser (fallback)
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
            # Extract LTP from various possible fields
            ltp = message.get('ltp', 0) or message.get('probable_ltp', 0)
            if not ltp and 'cmd' in message:
                ltp = message['cmd'].get('v', 0)
            
            return {
                'ltp': float(ltp) if ltp else 0.0,
                'ltt': message.get('tt', message.get('last_traded_time', int(time.time())))
            }
        elif mode == 2:  # Quote mode
            # Handle both direct fields and cmd structure
            cmd = message.get('cmd', {})
            
            # Extract LTP with fallbacks
            ltp = message.get('ltp', 0) or message.get('probable_ltp', 0) or cmd.get('v', 0)
            
            return {
                'ltp': float(ltp) if ltp else 0.0,
                'ltt': message.get('tt', message.get('last_traded_time', cmd.get('t', int(time.time())))),
                'volume': message.get('vol_traded_today', message.get('v', cmd.get('volume', 0))),
                'open': message.get('open_price', cmd.get('o', 0)),
                'high': message.get('high_price', cmd.get('h', 0)),
                'low': message.get('low_price', cmd.get('l', 0)),
                'close': message.get('prev_close_price', cmd.get('c', 0)),
                'last_quantity': message.get('last_traded_qty', cmd.get('ltq', 0)),
                'average_price': message.get('avg_trade_price', 0),
                'total_buy_quantity': message.get('tot_buy_qty', message.get('bid_size', 0)),
                'total_sell_quantity': message.get('tot_sell_qty', message.get('ask_size', 0)),
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

