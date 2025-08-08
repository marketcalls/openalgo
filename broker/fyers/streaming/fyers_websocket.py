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
        message = {
            "type": 1,  # Type 1 for subscription
            "data": {
                "subs": 1,  # 1 for subscribe, -1 for unsubscribe
                "symbols": symbols,  # List of symbols like ["NSE:TCS-EQ"]
                "mode": "depth" if data_type == "DepthUpdate" else "quote",  # "depth" or "quote"
                "channel": "1"  # Channel number as string
            }
        }
        
        if self.connected and self.ws:
            try:
                message_str = json.dumps(message)
                self.logger.info(f"Sending subscription message: {message_str}")
                self.ws.send(message_str)
                
                # After subscribing, activate the channel to start receiving data
                # According to Fyers TBT docs, need to resume the channel
                channel_message = {
                    "type": 2,  # Type 2 for channel operations
                    "data": {
                        "resumeChannels": ["1"],  # Resume channel 1
                        "pauseChannels": []       # No channels to pause
                    }
                }
                
                channel_str = json.dumps(channel_message)
                self.logger.info(f"Activating channel: {channel_str}")
                self.ws.send(channel_str)
                
                self.logger.info(f"Subscribed to {len(symbols)} symbols for {data_type} and activated channel")
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
                self.logger.info(f"Received JSON message from Fyers: {message}")
                data = json.loads(message)
                # Check if it's a subscription response
                if 'subscription' in message.lower() or 'error' in message.lower():
                    self.logger.warning(f"Important Fyers response: {data}")
                else:
                    self.logger.debug(f"Parsed JSON data: {data}")
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
            # Fyers uses protobuf for TBT data
            return self._parse_protobuf_data(data)
    
    def _parse_protobuf_data(self, data):
        """
        Parse Fyers protobuf data using manual binary parsing
        
        Args:
            data: Binary protobuf data
            
        Returns:
            Dict: Parsed market data
        """
        try:
            import struct
            
            parsed_data = {}
            parsed_data['data_type'] = 'market_data'
            parsed_data['raw_length'] = len(data)
            
            # Try to decode readable strings from the data
            try:
                data_str = data.decode('utf-8', errors='ignore')
                
                # Extract symbol information using regex
                import re
                # Look for various patterns in the data
                symbol_patterns = [
                    r'NSE:[A-Z0-9]+-EQ',  # NSE equity format
                    r'BSE:[A-Z0-9]+-EQ',  # BSE equity format
                    r'NFO:[A-Z0-9]+',     # F&O format
                    r'MCX:[A-Z0-9]+FUT',  # MCX futures format
                    r'MCX:[A-Z0-9]+',     # MCX general format
                ]
                
                for pattern in symbol_patterns:
                    match = re.search(pattern, data_str)
                    if match:
                        parsed_data['symbol'] = match.group()
                        break
                
                # Extract token (usually 12-15 digits)
                token_match = re.search(r'\b\d{12,15}\b', data_str)
                if token_match:
                    parsed_data['token'] = token_match.group()
                    
            except Exception as decode_error:
                self.logger.debug(f"Could not decode as UTF-8: {decode_error}")
            
            # Parse protobuf varint encoded values for prices
            # Fyers TBT data includes market depth with price levels
            try:
                # Look for price patterns in the data
                # Prices in Indian markets are typically in the range 1-50000
                potential_prices = []
                
                # Scan through the data looking for encoded price values
                # Looking specifically for patterns like \x08\xXX where XX is a varint price
                i = 0
                while i < len(data) - 2:
                    # Look for field tags with varint values (wire type 0)
                    if i < len(data) - 1:
                        tag = data[i]
                        field_num = tag >> 3
                        wire_type = tag & 0x07
                        
                        # Check if this is a varint field (wire type 0)
                        if wire_type == 0 and i + 1 < len(data):
                            # Try to read the varint value
                            value, bytes_read = self._decode_varint(data[i+1:])
                            if value and bytes_read > 0:
                                # Check if this could be a price in paise (Indian currency: 100 paise = 1 rupee)
                                if 10000 <= value <= 10000000:  # 100 to 100000 rupees
                                    price = value / 100.0
                                    potential_prices.append({
                                        'offset': i,
                                        'value': round(price, 2),
                                        'format': 'varint/100',
                                        'field': field_num
                                    })
                            i += 1 + (bytes_read if bytes_read else 0)
                        
                        # Also check for length-delimited fields containing prices
                        elif wire_type == 2 and i + 1 < len(data):
                            # Read length
                            length, bytes_read = self._decode_varint(data[i+1:])
                            if length and bytes_read:
                                start = i + 1 + bytes_read
                                end = start + length
                                if end <= len(data) and length == 4:
                                    # Could be a 4-byte price
                                    try:
                                        price_bytes = data[start:end]
                                        # Try as little-endian integer
                                        int_val = struct.unpack('<I', price_bytes)[0]
                                        if 10000 <= int_val <= 10000000:
                                            price = int_val / 100.0
                                            potential_prices.append({
                                                'offset': start,
                                                'value': round(price, 2),
                                                'format': 'fixed32/100',
                                                'field': field_num
                                            })
                                    except:
                                        pass
                                i = end
                            else:
                                i += 1
                        else:
                            i += 1
                    else:
                        i += 1
                
                # Also scan for common price patterns in the data
                # Look for sequences that match \x08\xXX\xYY\xZZ where the value makes sense as a price
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
                    
                    parsed_data['potential_prices'] = potential_prices[:10]  # Keep top 10 unique prices
                    
                    # Find the most likely LTP
                    # Usually the LTP is one of the first few price fields in the message
                    # For market depth data, prices typically appear in order
                    
                    # Strategy: Look for prices in a reasonable range for the symbol
                    # For NSE stocks, typically between 10 and 50000
                    reasonable_prices = [p for p in potential_prices if 10 <= p['value'] <= 50000]
                    
                    if reasonable_prices:
                        # For TCS and similar large-cap stocks, prices are typically > 1000
                        high_value_prices = [p for p in reasonable_prices if p['value'] >= 1000]
                        
                        if high_value_prices:
                            # The first high-value price is likely the LTP
                            # Check if we have multiple similar prices (within 2% of each other)
                            first_price = high_value_prices[0]['value']
                            similar_prices = [p for p in high_value_prices 
                                            if abs(p['value'] - first_price) / first_price < 0.02]
                            
                            if similar_prices:
                                # Use the most common price or the first one
                                parsed_data['probable_ltp'] = similar_prices[0]['value']
                            else:
                                parsed_data['probable_ltp'] = high_value_prices[0]['value']
                        else:
                            # For lower-priced stocks, use the median price
                            parsed_data['probable_ltp'] = reasonable_prices[len(reasonable_prices)//2]['value']
                    else:
                        # Fallback to first price if no reasonable prices found
                        parsed_data['probable_ltp'] = potential_prices[0]['value'] if potential_prices else 0
                        
            except Exception as binary_parse_error:
                self.logger.debug(f"Binary parsing error: {binary_parse_error}")
            
            # Add some metadata for debugging
            if len(data) > 0:
                parsed_data['first_bytes'] = data[:20].hex()
                parsed_data['last_bytes'] = data[-20:].hex()
            
            self.logger.info(f"Parsed protobuf data: symbol={parsed_data.get('symbol', 'unknown')}, "
                           f"token={parsed_data.get('token', 'unknown')}, "
                           f"probable_ltp={parsed_data.get('probable_ltp', 'unknown')}")
            
            return parsed_data
            
        except Exception as e:
            self.logger.error(f"Error parsing protobuf data: {e}")
            return {"raw_data": data.hex()[:200] if data else "empty", "error": str(e)}
    
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