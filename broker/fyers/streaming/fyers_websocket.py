"""
Fyers WebSocket Client Implementation (Without Library)
Handles real-time market data streaming using raw WebSocket connection
"""

import json
import logging
import threading
import time
import websocket
import ssl
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
from urllib.parse import urlencode
from .fyers_proto_parser import FyersProtoParser

class FyersWebSocketClient:
    """
    Custom Fyers WebSocket client for real-time market data without using fyers-apiv3 library
    """
    
    # Fyers WebSocket endpoints - Updated based on official documentation
    # TBT endpoint for tick-by-tick data
    DATA_WS_URL = "wss://rtsocket-api.fyers.in/versova"
    # Regular data socket endpoint 
    DATA_WS_URL_ALT = "wss://api-t1.fyers.in/socket/v4/dataSock"
    ORDER_WS_URL = "wss://api-t1.fyers.in/socket/v4/orderSock"
    
    # Data type constants
    DATA_TYPES = {
        "SymbolUpdate": 1,
        "DepthUpdate": 2
    }
    
    def __init__(self, access_token: str):
        """
        Initialize Fyers WebSocket client
        
        Args:
            access_token: Fyers access token in format "appid:accesstoken"
        """
        self.access_token = access_token
        self.logger = logging.getLogger("fyers_websocket")
        
        self.ws = None
        self.ws_thread = None
        self.connected = False
        self.subscriptions = {}  # Track active subscriptions
        self.callbacks = {}
        self.lock = threading.Lock()
        self.running = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5
        
        # Parse symbol data
        self.symbol_data = {}
        
        # Initialize protobuf parser
        self.proto_parser = FyersProtoParser()
        
    def set_callbacks(self, 
                     on_open: Optional[Callable] = None,
                     on_message: Optional[Callable] = None,
                     on_error: Optional[Callable] = None,
                     on_close: Optional[Callable] = None):
        """
        Set callback functions for WebSocket events
        
        Args:
            on_open: Callback when connection opens
            on_message: Callback for incoming messages
            on_error: Callback for errors
            on_close: Callback when connection closes
        """
        self.callbacks['on_open'] = on_open
        self.callbacks['on_message'] = on_message
        self.callbacks['on_error'] = on_error
        self.callbacks['on_close'] = on_close
        
    def connect(self):
        """
        Establish WebSocket connection
        """
        self.running = True
        self.ws_thread = threading.Thread(target=self._connect_ws, daemon=True)
        self.ws_thread.start()
        
    def _connect_ws(self):
        """
        Internal method to connect to WebSocket
        """
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                # Fyers uses Authorization header with api_key:auth_token format
                url = self.DATA_WS_URL
                
                self.logger.info(f"Connecting to Fyers WebSocket (attempt {self.reconnect_attempts + 1})...")
                self.logger.info(f"Connecting to URL: {url}")
                
                # Create WebSocket connection with proper Authorization header
                # Fyers expects Authorization header in format "api_key:auth_token"
                self.ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    header={
                        'Authorization': self.access_token,  # In format "appid:accesstoken"
                        'User-Agent': 'OpenAlgo-Fyers-WebSocket-Client/1.0',
                        'Accept': '*/*'
                    }
                )
                
                # Run WebSocket with SSL options
                self.ws.run_forever(
                    sslopt={"cert_reqs": ssl.CERT_NONE}
                )
                
                # If we reach here, connection was closed
                if self.running:
                    self.reconnect_attempts += 1
                    delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts), 60)
                    self.logger.info(f"Reconnecting in {delay} seconds...")
                    time.sleep(delay)
                    
            except Exception as e:
                self.logger.error(f"Connection error: {e}")
                self.reconnect_attempts += 1
                delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts), 60)
                time.sleep(delay)
                
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error("Max reconnection attempts reached")
            
    def disconnect(self):
        """Disconnect from WebSocket"""
        self.running = False
        self.connected = False
        
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
                
        self.logger.info("Disconnected from Fyers WebSocket")
        
    def subscribe(self, symbols: List[str], data_type: str = "SymbolUpdate"):
        """
        Subscribe to market data for symbols
        
        Args:
            symbols: List of symbols in Fyers format (e.g., ['NSE:SBIN-EQ'])
            data_type: Type of data subscription ('SymbolUpdate' or 'DepthUpdate')
        """
        if not self.connected:
            self.logger.warning("WebSocket not connected. Queuing subscription.")
            
        # Store subscription info
        with self.lock:
            for symbol in symbols:
                self.subscriptions[symbol] = {
                    'data_type': data_type,
                    'subscribed_at': datetime.now()
                }
        
        # Use the OFFICIAL Fyers TBT WebSocket protocol format
        # Based on https://github.com/FyersDev/fyers-api-sample-code/tree/sample_v3/v3/python/websocket
        
        # Log exchange type for debugging
        exchange_types = set()
        for symbol in symbols:
            if ':' in symbol:
                exchange = symbol.split(':')[0]
                exchange_types.add(exchange)
        
        self.logger.info(f"Subscribing to exchanges: {exchange_types}")
        
        # Fyers supports: "quote", "depth", "ohlcv" modes
        mode = "depth" if data_type == "DepthUpdate" else "quote"
        
        # Check if this might be an index symbol (by token pattern or INDEX keyword)
        is_index = any('-INDEX' in str(s).upper() for s in symbols)
        index_tokens = [s for s in symbols if str(s).startswith('10100000002')]  # Index tokens often start with this pattern
        
        if is_index or index_tokens:
            # Try "ohlcv" mode for indices
            mode = "ohlcv" if data_type == "SymbolUpdate" else mode
            self.logger.warning(f"Detected INDEX symbol, using mode '{mode}' instead of 'quote'")
            
            if index_tokens:
                self.logger.warning(f"Index tokens detected: {index_tokens}")
        
        # Log mode being used
        if 'MCX' in exchange_types or 'BSE' in exchange_types:
            self.logger.warning(f"Subscribing to MCX/BSE with mode '{mode}'")
        
        # Try different channels for different asset types
        channel_num = "1"  # Default channel
        
        if is_index or index_tokens:
            # Indices might use a different channel
            channel_num = "3"
            self.logger.warning(f"Using channel {channel_num} for INDEX symbols")
        elif 'MCX' in exchange_types:
            # Try channel 2 for MCX
            channel_num = "2"
            self.logger.warning(f"Using channel {channel_num} for MCX")
        elif 'BSE' in exchange_types:
            # BSE might need different channel too
            channel_num = "4"
            self.logger.warning(f"Using channel {channel_num} for BSE")
        
        message = {
            "type": 1,  # Type 1 for subscription
            "data": {
                "subs": 1,  # 1 for subscribe, -1 for unsubscribe
                "symbols": symbols,  # List of symbols like ["NSE:TCS-EQ"]
                "mode": mode,  # "ltp", "quote", or "depth"
                "channel": channel_num  # Channel number as string
            }
        }
        
        if self.connected and self.ws:
            try:
                message_str = json.dumps(message)
                self.logger.info(f"Sending subscription message: {message_str}")
                
                # Also log what we're actually trying to subscribe to
                for symbol in symbols:
                    exchange = symbol.split(':')[0] if ':' in symbol else 'Unknown'
                    self.logger.warning(f"Subscribing to {exchange} symbol: {symbol}")
                    
                    # Check if we should try token-based subscription instead
                    if exchange in ['BSE', 'MCX'] or '-INDEX' in symbol.upper():
                        self.logger.warning(f"Non-NSE-equity symbol detected: {symbol}")
                        self.logger.warning(f"Consider using fytoken instead of symbol format")
                
                self.ws.send(message_str)
                
                # Wait a moment for subscription to be processed
                import time
                time.sleep(0.1)
                
                # After subscribing, activate the channel to start receiving data
                # According to Fyers TBT docs, need to resume the channel
                channel_message = {
                    "type": 2,  # Type 2 for channel operations
                    "data": {
                        "resumeChannels": [channel_num],  # Resume the channel
                        "pauseChannels": []                # No channels to pause
                    }
                }
                
                channel_str = json.dumps(channel_message)
                self.logger.info(f"Activating channel: {channel_str}")
                self.ws.send(channel_str)
                
                self.logger.info(f"Subscribed to {len(symbols)} symbols for {data_type} and activated channel {channel_num}")
                
                # Send another ping to ensure connection is active
                self.ws.send("ping")
                
                # For debugging token-based subscriptions (anything not NSE cash equity)
                token_based = [s for s in symbols if not (s.startswith('NSE:') and '-EQ' in s)]
                if token_based:
                    self.logger.warning(f"Token-based subscription complete: {token_based}")
                    self.logger.warning(f"These symbols are using TOKEN-based subscription")
                    self.logger.warning(f"If no data received, the token format might be incorrect")
                    
                    # Suggest alternative
                    for symbol in token_based:
                        if symbol.isdigit():
                            self.logger.info(f"Token {symbol} - this should work if token is correct")
                        else:
                            self.logger.warning(f"Symbol {symbol} - might need token format instead")
                
                return True
            except Exception as e:
                self.logger.error(f"Subscription error: {e}")
                return False
        else:
            self.logger.info(f"Queued subscription for {len(symbols)} symbols")
            return True
            
    def unsubscribe(self, symbols: List[str], data_type: str = "SymbolUpdate"):
        """
        Unsubscribe from market data
        
        Args:
            symbols: List of symbols to unsubscribe
            data_type: Type of data subscription
        """
        # Remove from subscriptions
        with self.lock:
            for symbol in symbols:
                if symbol in self.subscriptions:
                    del self.subscriptions[symbol]
        
        # Create unsubscribe message using official Fyers TBT protocol
        message = {
            "type": 1,  # Type 1 for subscription operations
            "data": {
                "subs": -1,  # -1 for unsubscribe
                "symbols": symbols,  # List of symbols to unsubscribe
                "mode": "depth" if data_type == "DepthUpdate" else "quote",
                "channel": "1"  # Channel number as string
            }
        }
        
        if self.connected and self.ws:
            try:
                self.ws.send(json.dumps(message))
                self.logger.info(f"Unsubscribed from {len(symbols)} symbols")
                return True
            except Exception as e:
                self.logger.error(f"Unsubscription error: {e}")
                return False
        
        return True
        
    def _on_open(self, ws):
        """Handle WebSocket connection open"""
        self.connected = True
        self.reconnect_attempts = 0
        self.logger.info("Fyers WebSocket connected successfully")
        
        # Send a ping message first to test connection using official Fyers format
        try:
            # According to Fyers docs: Ping message is just the string "ping"
            ping_message = "ping"
            self.ws.send(ping_message)
            self.logger.info(f"Sent ping message: {ping_message}")
        except Exception as e:
            self.logger.error(f"Failed to send ping: {e}")
        
        # Call user callback
        if self.callbacks.get('on_open'):
            self.callbacks['on_open']()
            
        # Resubscribe to existing subscriptions if reconnecting
        if self.subscriptions:
            # Group by data type for resubscription
            symbol_updates = []
            depth_updates = []
            
            for symbol, info in self.subscriptions.items():
                if info['data_type'] == 'DepthUpdate':
                    depth_updates.append(symbol)
                else:
                    symbol_updates.append(symbol)
            
            # Resubscribe in batches
            if symbol_updates:
                self.subscribe(symbol_updates, "SymbolUpdate")
            if depth_updates:
                self.subscribe(depth_updates, "DepthUpdate")
                
    def _on_message(self, ws, message):
        """
        Handle incoming WebSocket messages
        
        Args:
            ws: WebSocket instance
            message: Raw message from WebSocket
        """
        try:
            # Log differently based on message type
            if isinstance(message, str):
                # JSON messages - log fully
                data = json.loads(message)
                
                # Check for important messages
                if any(keyword in str(message).lower() for keyword in ['error', 'fail', 'reject', 'invalid', 'subscription', 'denied', 'unauthorized']):
                    self.logger.error(f"IMPORTANT Fyers response: {message}")
                    # Also check if this is related to indices/BSE/MCX
                    if any(term in str(message).lower() for term in ['index', 'bse', 'mcx', 'token', 'symbol']):
                        self.logger.error(f"This error might be related to indices/BSE/MCX subscription!")
                elif message.strip() in ['pong', 'ping']:
                    self.logger.debug(f"Ping/Pong: {message}")
                else:
                    self.logger.info(f"Received JSON from Fyers: {message}")
            elif isinstance(message, (bytes, bytearray)):
                # Binary messages - log size and parse
                data = self._parse_binary_data(message)
                
                # Log parsed data with symbol info
                if data.get('symbol'):
                    self.logger.info(f"Received {len(message)} bytes for {data['symbol']}: LTP={data.get('probable_ltp', 'unknown')}")
                    # Extra logging for MCX
                    if 'MCX:' in data.get('symbol', ''):
                        self.logger.warning(f"MCX data received: {data}")
                else:
                    self.logger.debug(f"Received {len(message)} bytes, no symbol found")
            else:
                self.logger.warning(f"Unexpected message type: {type(message)}")
                return
            
            # Pass to callback if registered
            if self.callbacks.get('on_message'):
                self.callbacks['on_message'](data)
                
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
            
    def _parse_binary_data(self, data):
        """
        Parse binary data from Fyers WebSocket (protobuf format)
        
        Args:
            data: Binary data from WebSocket
            
        Returns:
            Dict: Parsed market data
        """
        try:
            # Try to decode as JSON first (some messages are JSON)
            decoded = data.decode('utf-8')
            return json.loads(decoded)
        except:
            # Handle binary market data (protobuf format)
            # Use hybrid approach: new parser for symbol/token, old parser for prices
            parsed_data = self.proto_parser.parse_market_data(data)
            
            # If we got symbol/token from new parser but no LTP, use old price extraction
            if parsed_data.get('symbol') and parsed_data.get('token') and not parsed_data.get('probable_ltp'):
                old_parsed = self._parse_protobuf_data_old(data)
                if old_parsed.get('probable_ltp'):
                    parsed_data['probable_ltp'] = old_parsed['probable_ltp']
                    self.logger.info(f"Using old parser LTP: {parsed_data['probable_ltp']}")
                    
            return parsed_data
    
    def _parse_protobuf_data_old(self, data):
        """
        Old working protobuf parser - used for price extraction only
        """
        try:
            import struct
            
            parsed_data = {}
            parsed_data['data_type'] = 'market_data'
            parsed_data['raw_length'] = len(data)
            
            # Parse protobuf varint encoded values for prices
            try:
                potential_prices = []
                
                # Scan through the data looking for encoded price values
                i = 0
                while i < len(data) - 2:
                    if i < len(data) - 1:
                        tag = data[i]
                        field_num = tag >> 3
                        wire_type = tag & 0x07
                        
                        # Check if this is a varint field (wire type 0)
                        if wire_type == 0 and i + 1 < len(data):
                            # Try to read the varint value
                            value, bytes_read = self._decode_varint(data[i+1:])
                            if value and bytes_read > 0:
                                # Check if this could be a price in paise
                                if 10000 <= value <= 10000000:  # 100 to 100000 rupees
                                    price = value / 100.0
                                    potential_prices.append({
                                        'offset': i,
                                        'value': round(price, 2),
                                        'format': 'varint/100',
                                        'field': field_num
                                    })
                            i += 1 + (bytes_read if bytes_read else 0)
                        else:
                            i += 1
                    else:
                        i += 1
                
                # Also scan for common price patterns in the data
                for offset in range(0, min(len(data) - 4, 500)):
                    if data[offset] == 0x08:  # Field number 1 with wire type 0 (varint)
                        # Try to decode the following bytes as a varint
                        value, _ = self._decode_varint(data[offset+1:])
                        if value and 10000 <= value <= 5000000:
                            price = value / 100.0
                            if price not in [p['value'] for p in potential_prices]:
                                potential_prices.append({
                                    'offset': offset,
                                    'value': round(price, 2),
                                    'format': 'varint_field/100'
                                })
                
                if potential_prices:
                    # Remove duplicates and sort by value
                    unique_prices = {}
                    for p in potential_prices:
                        if p['value'] not in unique_prices:
                            unique_prices[p['value']] = p
                    
                    potential_prices = list(unique_prices.values())
                    potential_prices.sort(key=lambda x: x['value'])
                    
                    parsed_data['potential_prices'] = potential_prices[:10]
                    
                    # Log all potential prices for debugging
                    price_list = [f"{p['value']} (field {p.get('field', '?')}, {p['format']})" for p in potential_prices[:10]]
                    self.logger.info(f"All potential prices: {price_list}")
                    
                    # More intelligent LTP selection based on frequency and field position
                    # Group prices by similarity (within 1% of each other)
                    price_groups = []
                    for price in potential_prices:
                        added_to_group = False
                        for group in price_groups:
                            if any(abs(price['value'] - p['value']) / max(price['value'], p['value']) < 0.01 for p in group):
                                group.append(price)
                                added_to_group = True
                                break
                        if not added_to_group:
                            price_groups.append([price])
                    
                    # Sort groups by size (frequency) and average value
                    price_groups.sort(key=lambda g: (len(g), -min(p['value'] for p in g)), reverse=True)
                    
                    if price_groups:
                        # Use the price from the largest group (most frequent)
                        best_group = price_groups[0]
                        # Within the group, prefer prices from earlier fields (lower field numbers)
                        best_group.sort(key=lambda p: (p.get('field', 999), p['offset']))
                        
                        selected_price = best_group[0]['value']
                        
                        # Sanity check: reject prices that seem too high/low for Indian stocks
                        # SBIN: 800-820, INFY: 1400-1500, TCS: 3000-3500
                        if 50 <= selected_price <= 5000:  # Reasonable range for most Indian stocks
                            parsed_data['probable_ltp'] = selected_price
                            self.logger.info(f"Selected LTP {selected_price} from group of {len(best_group)} similar prices")
                        else:
                            # Try the second group if first seems unreasonable
                            if len(price_groups) > 1:
                                second_group = price_groups[1]
                                second_price = second_group[0]['value']
                                if 50 <= second_price <= 5000:
                                    parsed_data['probable_ltp'] = second_price
                                    self.logger.info(f"Selected backup LTP {second_price} (first choice {selected_price} rejected)")
                                else:
                                    parsed_data['probable_ltp'] = 0
                                    self.logger.warning(f"No reasonable LTP found (tried {selected_price}, {second_price})")
                            else:
                                parsed_data['probable_ltp'] = 0
                                self.logger.warning(f"LTP {selected_price} rejected as unreasonable")
                    else:
                        parsed_data['probable_ltp'] = 0
                        
            except Exception as binary_parse_error:
                self.logger.debug(f"Old binary parsing error: {binary_parse_error}")
            
            return parsed_data
            
        except Exception as e:
            self.logger.error(f"Error in old protobuf parser: {e}")
            return {"probable_ltp": 0}
    
    def _decode_varint(self, data):
        """
        Decode a protobuf varint from bytes
        
        Args:
            data: Byte data starting with the varint
            
        Returns:
            Tuple of (value, bytes_read) or (None, 0) if invalid
        """
        try:
            result = 0
            shift = 0
            bytes_read = 0
            
            for i, byte in enumerate(data):
                if i >= 10:  # Varint too long
                    return None, 0
                    
                result |= (byte & 0x7F) << shift
                bytes_read += 1
                
                if (byte & 0x80) == 0:  # MSB is 0, this is the last byte
                    return result, bytes_read
                    
                shift += 7
            
            return None, 0
        except:
            return None, 0
            
    def _on_error(self, ws, error):
        """
        Handle WebSocket errors
        
        Args:
            ws: WebSocket instance
            error: Error message or exception
        """
        self.logger.error(f"Fyers WebSocket error: {error}")
        
        if self.callbacks.get('on_error'):
            self.callbacks['on_error'](error)
            
    def _on_close(self, ws, close_status_code, close_msg):
        """
        Handle WebSocket connection close
        
        Args:
            ws: WebSocket instance
            close_status_code: Status code
            close_msg: Close message from server
        """
        self.connected = False
        self.logger.info(f"Fyers WebSocket closed: {close_msg} (code: {close_status_code})")
        
        if self.callbacks.get('on_close'):
            self.callbacks['on_close'](close_msg)
            
    def is_connected(self) -> bool:
        """Check if WebSocket is connected"""
        return self.connected
    
    def get_subscriptions(self) -> Dict[str, Any]:
        """Get current active subscriptions"""
        with self.lock:
            return self.subscriptions.copy()
            
    def send_custom_message(self, message: Dict):
        """
        Send a custom message to the WebSocket
        
        Args:
            message: Dictionary to send as JSON
        """
        if self.connected and self.ws:
            try:
                self.ws.send(json.dumps(message))
                return True
            except Exception as e:
                self.logger.error(f"Failed to send message: {e}")
                return False
        return False