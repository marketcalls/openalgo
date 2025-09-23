"""
Dhan WebSocket Client Implementation
Handles both 5-level and 20-level market depth connections
"""
import websocket
import json
import struct
import threading
import time
import logging
import asyncio
import platform
from typing import Dict, Any, Optional, List, Callable
from urllib.parse import urlencode


class DhanWebSocket:
    """
    Dhan WebSocket client for real-time market data
    Supports both 5-level depth (regular feed) and 20-level depth connections
    """
    
    # Feed response codes
    FEED_RESPONSE_CODES = {
        2: 'TICKER',
        4: 'QUOTE',
        5: 'OI',
        6: 'PREV_CLOSE',
        8: 'FULL',
        41: 'DEPTH_20_BID',
        51: 'DEPTH_20_ASK',
        50: 'DISCONNECT'
    }
    
    # Request codes
    REQUEST_CODES = {
        'SUBSCRIBE_TICKER': 15,
        'SUBSCRIBE_QUOTE': 17,
        'SUBSCRIBE_FULL': 21,
        'SUBSCRIBE_20_DEPTH': 23,
        'DISCONNECT': 12
    }
    
    def __init__(self, client_id: str, access_token: str, is_20_depth: bool = False):
        """
        Initialize Dhan WebSocket client
        
        Args:
            client_id: Dhan client ID
            access_token: Access token for authentication
            is_20_depth: If True, connects to 20-level depth endpoint
        """
        self.client_id = client_id
        self.access_token = access_token
        self.is_20_depth = is_20_depth
        
        # WebSocket connection
        self.ws = None
        self.ws_thread = None
        self.running = False
        self.connected = False
        
        # Callbacks
        self.on_open = None
        self.on_message = None
        self.on_data = None
        self.on_error = None
        self.on_close = None
        
        # Subscription tracking
        self.subscriptions = {}
        self.lock = threading.Lock()
        
        # Logging
        self.logger = logging.getLogger(f"dhan_websocket_{'20depth' if is_20_depth else '5depth'}")
        
        # Build WebSocket URL
        self._build_url()
    
    def _build_url(self):
        """Build the WebSocket URL based on depth level"""
        if self.is_20_depth:
            base_url = "wss://depth-api-feed.dhan.co/twentydepth"
            params = {
                'token': self.access_token,
                'clientId': self.client_id,
                'authType': '2'
            }
        else:
            base_url = "wss://api-feed.dhan.co"
            params = {
                'version': '2',
                'token': self.access_token,
                'clientId': self.client_id,
                'authType': '2'
            }
        
        self.ws_url = f"{base_url}?{urlencode(params)}"
        self.logger.debug(f"Dhan WebSocket URL constructed: {self.ws_url[:100]}...")  # Log first 100 chars for security
    
    def connect(self):
        """Establish WebSocket connection"""
        if self.running:
            self.logger.warning("Already connected or connecting")
            return
        
        # Handle asyncio event loop conflict on Linux/macOS 
        self._handle_asyncio_compatibility()
        
        self.running = True
        self.ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
        self.ws_thread.start()
    
    def _handle_asyncio_compatibility(self):
        """Handle asyncio event loop conflicts on Linux/macOS systems"""
        try:
            # Check if we're on a platform that might have asyncio conflicts
            if platform.system() in ['Linux', 'Darwin']:  # Darwin is macOS
                try:
                    # Try to get the current event loop
                    loop = asyncio.get_running_loop()
                    if loop and not loop.is_closed():
                        self.logger.info("Detected existing asyncio event loop, using thread isolation for Dhan WebSocket")
                        # We'll run in a completely separate thread context
                        # which is already what we're doing, so no additional action needed
                except RuntimeError:
                    # No running loop, which is fine
                    pass
            else:
                self.logger.debug("Running on Windows, no asyncio compatibility adjustments needed")
        except Exception as e:
            self.logger.warning(f"Error checking asyncio compatibility: {e}")
            # Continue anyway, the thread isolation should handle most cases
    
    def _run_websocket(self):
        """Run the WebSocket connection in a separate thread"""
        while self.running:
            try:
                #self.logger.info(f"Connecting to Dhan WebSocket ({'20-depth' if self.is_20_depth else '5-depth'})...")
                #self.logger.info(f"WebSocket URL: {self.ws_url}")
                
                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_ping=lambda ws, msg: self.logger.debug("Received ping"),
                    on_pong=lambda ws, msg: self.logger.debug("Received pong")
                )
                
                # Run the WebSocket with ping interval
                self.ws.run_forever(ping_interval=10, ping_timeout=5)
                
            except Exception as e:
                self.logger.error(f"WebSocket connection error: {e}", exc_info=True)
                self.connected = False
                
                if self.running:
                    self.logger.info("Reconnecting in 5 seconds...")
                    time.sleep(5)
    
    def disconnect(self):
        """Disconnect from WebSocket"""
        self.running = False
        self.connected = False
        
        # Send disconnect message if connected
        if self.ws and self.connected:
            try:
                disconnect_msg = json.dumps({
                    "RequestCode": self.REQUEST_CODES['DISCONNECT']
                })
                if hasattr(self.ws, 'send') and callable(self.ws.send):
                    self.ws.send(disconnect_msg)
            except Exception as e:
                self.logger.error(f"Error sending disconnect message: {e}")
        
        # Close WebSocket
        if self.ws:
            self.ws.close()
    
    def subscribe(self, instruments: List[Dict[str, str]], mode: str = 'FULL'):
        """
        Subscribe to market data for instruments
        
        Args:
            instruments: List of dicts with 'ExchangeSegment' and 'SecurityId'
            mode: Subscription mode - 'TICKER', 'QUOTE', 'FULL', '20_DEPTH'
        """
        if not self.connected:
            self.logger.error("Not connected to WebSocket")
            return False
        
        # Validate mode
        if self.is_20_depth and mode != '20_DEPTH':
            self.logger.error("20-depth connection only supports 20_DEPTH mode")
            return False
        
        if not self.is_20_depth and mode == '20_DEPTH':
            self.logger.error("Regular connection doesn't support 20_DEPTH mode")
            return False
        
        # Get request code
        request_code_key = f'SUBSCRIBE_{mode}'
        if request_code_key not in self.REQUEST_CODES:
            self.logger.error(f"Invalid subscription mode: {mode}")
            return False
        
        request_code = self.REQUEST_CODES[request_code_key]
        
        # Prepare subscription message
        # Split instruments into batches (max 100 for regular, all for 20-depth)
        max_batch_size = 100 if not self.is_20_depth else 50
        
        for i in range(0, len(instruments), max_batch_size):
            batch = instruments[i:i + max_batch_size]
            
            subscribe_msg = {
                "RequestCode": request_code,
                "InstrumentCount": len(batch),
                "InstrumentList": batch
            }
            
            try:
                if self.ws and hasattr(self.ws, 'send') and callable(self.ws.send):
                    self.ws.send(json.dumps(subscribe_msg))
                    
                    # Track subscriptions
                    with self.lock:
                        for inst in batch:
                            key = f"{inst['ExchangeSegment']}_{inst['SecurityId']}"
                            self.subscriptions[key] = {
                                'mode': mode,
                                'instrument': inst
                            }
                    
                    self.logger.debug(f"Subscribed to {len(batch)} instruments in {mode} mode")
                else:
                    self.logger.error("WebSocket not properly initialized for sending")
                    return False
                
            except Exception as e:
                self.logger.error(f"Error subscribing to instruments: {e}", exc_info=True)
                return False
        
        return True
    
    def unsubscribe(self, instruments: List[Dict[str, str]]):
        """Unsubscribe from market data for instruments"""
        # Dhan doesn't have explicit unsubscribe - just remove from tracking
        with self.lock:
            for inst in instruments:
                key = f"{inst['ExchangeSegment']}_{inst['SecurityId']}"
                if key in self.subscriptions:
                    del self.subscriptions[key]
        
        self.logger.debug(f"Unsubscribed from {len(instruments)} instruments")
        return True
    
    def _on_open(self, ws):
        """Handle WebSocket connection open"""
        self.connected = True
        self.logger.debug("WebSocket connection established")
        
        if self.on_open:
            self.on_open(self)
    
    def _on_error(self, ws, error):
        """Handle WebSocket errors"""
        self.logger.error(f"WebSocket error: {error}")
        
        if self.on_error:
            self.on_error(self, error)
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection close"""
        self.connected = False
        self.logger.debug(f"WebSocket connection closed: {close_status_code} - {close_msg}")
        
        if self.on_close:
            self.on_close(self)
    
    def _on_message(self, ws, message):
        """Handle incoming WebSocket messages"""
        try:
            # All Dhan responses are binary
            if isinstance(message, (bytes, bytearray)):
                self.logger.debug(f"Received binary message of length: {len(message)} bytes")
                self._parse_binary_message(message)
            else:
                self.logger.warning(f"Received non-binary message: {type(message)}: {message}")
                
        except Exception as e:
            self.logger.error(f"Error processing message: {e}", exc_info=True)
    
    def _parse_binary_message(self, data: bytes):
        """Parse binary message from Dhan"""
        if self.is_20_depth:
            self._parse_20_depth_message(data)
        else:
            self._parse_regular_message(data)
    
    def _parse_regular_message(self, data: bytes):
        """Parse regular (5-depth) binary message"""
        offset = 0
        
        while offset < len(data):
            if offset + 8 > len(data):
                break
            
            # Parse header (8 bytes)
            feed_response_code = struct.unpack('<B', data[offset:offset+1])[0]
            message_length = struct.unpack('<H', data[offset+1:offset+3])[0]
            exchange_segment = struct.unpack('<B', data[offset+3:offset+4])[0]
            security_id = struct.unpack('<I', data[offset+4:offset+8])[0]
            
            self.logger.debug(f"Parsed header - Code: {feed_response_code}, Length: {message_length}, Exchange: {exchange_segment}, Security: {security_id}")
            
            # Parse payload based on response code
            payload_start = offset + 8
            payload_end = offset + message_length
            
            if payload_end > len(data):
                self.logger.warning("Incomplete message received")
                break
            
            payload = data[payload_start:payload_end]
            
            # Parse based on feed response code
            parsed_data = None
            
            if feed_response_code == 2:  # Ticker
                self.logger.debug("Parsing TICKER packet")
                parsed_data = self._parse_ticker_packet(payload, exchange_segment, security_id)
            elif feed_response_code == 4:  # Quote
                self.logger.debug("Parsing QUOTE packet")
                parsed_data = self._parse_quote_packet(payload, exchange_segment, security_id)
            elif feed_response_code == 5:  # OI
                self.logger.debug("Parsing OI packet")
                parsed_data = self._parse_oi_packet(payload, exchange_segment, security_id)
            elif feed_response_code == 6:  # Prev Close
                self.logger.debug("Parsing PREV_CLOSE packet")
                parsed_data = self._parse_prev_close_packet(payload, exchange_segment, security_id)
            elif feed_response_code == 8:  # Full
                self.logger.debug("Parsing FULL packet")
                parsed_data = self._parse_full_packet(payload, exchange_segment, security_id)
            elif feed_response_code == 50:  # Disconnect
                self.logger.debug("Parsing DISCONNECT packet")
                self._handle_disconnect_packet(payload)
            else:
                self.logger.warning(f"Unknown feed response code: {feed_response_code}")
            
            if parsed_data and self.on_data:
                self.logger.debug(f"Sending parsed data to callback: {parsed_data.get('type')}")
                self.on_data(self, parsed_data)
            elif parsed_data:
                self.logger.warning("Parsed data available but no callback set")
            
            # Move to next message
            offset = payload_end
    
    def _parse_20_depth_message(self, data: bytes):
        """Parse 20-level depth binary message"""
        offset = 0
        
        #self.logger.info(f"Parsing 20-depth message with {len(data)} bytes")
        
        while offset < len(data):
            if offset + 12 > len(data):
                break
            
            # Parse header (12 bytes for 20-depth)
            message_length = struct.unpack('<H', data[offset:offset+2])[0]
            feed_response_code = struct.unpack('<B', data[offset+2:offset+3])[0]
            exchange_segment = struct.unpack('<B', data[offset+3:offset+4])[0]
            security_id = struct.unpack('<I', data[offset+4:offset+8])[0]
            # Skip message sequence (4 bytes)
            
            # Parse payload
            payload_start = offset + 12
            payload_end = offset + message_length
            
            if payload_end > len(data):
                self.logger.warning("Incomplete 20-depth message received")
                break
            
            payload = data[payload_start:payload_end]
            
            # Parse based on feed response code
            if feed_response_code in [41, 51]:  # 20-depth bid/ask
                side = 'BID' if feed_response_code == 41 else 'ASK'
                #self.logger.info(f"Parsing 20-depth {side} packet for security {security_id}")
                
                parsed_data = self._parse_20_depth_packet(
                    payload, exchange_segment, security_id, 
                    is_bid=(feed_response_code == 41)
                )
                
                if parsed_data and self.on_data:
                    #self.logger.info(f"Sending 20-depth {side} data to callback")
                    self.on_data(self, parsed_data)
                else:
                    self.logger.warning(f"Failed to parse 20-depth {side} data")
            else:
                self.logger.warning(f"Unknown 20-depth response code: {feed_response_code}")
            
            # Move to next message
            offset = payload_end
    
    def _parse_ticker_packet(self, payload: bytes, exchange_segment: int, security_id: int) -> Dict[str, Any]:
        """Parse ticker packet (LTP and LTT)"""
        if len(payload) < 8:
            return None
        
        ltp = struct.unpack('<f', payload[0:4])[0]
        ltt = struct.unpack('<I', payload[4:8])[0]
        
        return {
            'type': 'ticker',
            'exchange_segment': exchange_segment,
            'security_id': str(security_id),
            'ltp': ltp,
            'ltt': ltt
        }
    
    def _parse_quote_packet(self, payload: bytes, exchange_segment: int, security_id: int) -> Dict[str, Any]:
        """Parse quote packet"""
        if len(payload) < 42:
            return None
        
        return {
            'type': 'quote',
            'exchange_segment': exchange_segment,
            'security_id': str(security_id),
            'ltp': struct.unpack('<f', payload[0:4])[0],
            'ltq': struct.unpack('<H', payload[4:6])[0],
            'ltt': struct.unpack('<I', payload[6:10])[0],
            'atp': struct.unpack('<f', payload[10:14])[0],
            'volume': struct.unpack('<I', payload[14:18])[0],
            'total_sell_quantity': struct.unpack('<I', payload[18:22])[0],
            'total_buy_quantity': struct.unpack('<I', payload[22:26])[0],
            'open': struct.unpack('<f', payload[26:30])[0],
            'close': struct.unpack('<f', payload[30:34])[0],
            'high': struct.unpack('<f', payload[34:38])[0],
            'low': struct.unpack('<f', payload[38:42])[0]
        }
    
    def _parse_oi_packet(self, payload: bytes, exchange_segment: int, security_id: int) -> Dict[str, Any]:
        """Parse OI packet"""
        if len(payload) < 4:
            return None
        
        return {
            'type': 'oi',
            'exchange_segment': exchange_segment,
            'security_id': str(security_id),
            'oi': struct.unpack('<I', payload[0:4])[0]
        }
    
    def _parse_prev_close_packet(self, payload: bytes, exchange_segment: int, security_id: int) -> Dict[str, Any]:
        """Parse previous close packet"""
        if len(payload) < 8:
            return None
        
        return {
            'type': 'prev_close',
            'exchange_segment': exchange_segment,
            'security_id': str(security_id),
            'prev_close': struct.unpack('<f', payload[0:4])[0],
            'prev_oi': struct.unpack('<I', payload[4:8])[0]
        }
    
    def _parse_full_packet(self, payload: bytes, exchange_segment: int, security_id: int) -> Dict[str, Any]:
        """Parse full packet (includes 5-level depth)"""
        # Payload should be 154 bytes (162 total - 8 byte header)
        if len(payload) < 154:
            self.logger.warning(f"FULL packet payload too short: {len(payload)} bytes, expected 154")
            return None
        
        self.logger.debug(f"Parsing FULL packet with payload length: {len(payload)}")
        
        result = {
            'type': 'full',
            'exchange_segment': exchange_segment,
            'security_id': str(security_id),
            'ltp': struct.unpack('<f', payload[0:4])[0],
            'ltq': struct.unpack('<H', payload[4:6])[0],
            'ltt': struct.unpack('<I', payload[6:10])[0],
            'atp': struct.unpack('<f', payload[10:14])[0],
            'volume': struct.unpack('<I', payload[14:18])[0],
            'total_sell_quantity': struct.unpack('<I', payload[18:22])[0],
            'total_buy_quantity': struct.unpack('<I', payload[22:26])[0],
            'oi': struct.unpack('<I', payload[26:30])[0],
            'oi_high': struct.unpack('<I', payload[30:34])[0],
            'oi_low': struct.unpack('<I', payload[34:38])[0],
            'open': struct.unpack('<f', payload[38:42])[0],
            'close': struct.unpack('<f', payload[42:46])[0],
            'high': struct.unpack('<f', payload[46:50])[0],
            'low': struct.unpack('<f', payload[50:54])[0],
            'depth': {
                'buy': [],
                'sell': []
            }
        }
        
        # Parse 5-level depth (100 bytes starting at offset 54)
        depth_offset = 54
        for i in range(5):
            packet_offset = depth_offset + (i * 20)
            
            bid_qty = struct.unpack('<I', payload[packet_offset:packet_offset+4])[0]
            ask_qty = struct.unpack('<I', payload[packet_offset+4:packet_offset+8])[0]
            bid_orders = struct.unpack('<H', payload[packet_offset+8:packet_offset+10])[0]
            ask_orders = struct.unpack('<H', payload[packet_offset+10:packet_offset+12])[0]
            bid_price = struct.unpack('<f', payload[packet_offset+12:packet_offset+16])[0]
            ask_price = struct.unpack('<f', payload[packet_offset+16:packet_offset+20])[0]
            
            result['depth']['buy'].append({
                'price': bid_price,
                'quantity': bid_qty,
                'orders': bid_orders
            })
            
            result['depth']['sell'].append({
                'price': ask_price,
                'quantity': ask_qty,
                'orders': ask_orders
            })
        
        self.logger.debug(f"FULL packet parsed successfully: LTP={result.get('ltp')}, Volume={result.get('volume')}")
        return result
    
    def _parse_20_depth_packet(self, payload: bytes, exchange_segment: int, security_id: int, is_bid: bool) -> Dict[str, Any]:
        """Parse 20-level depth packet"""
        if len(payload) < 320:  # 20 levels * 16 bytes
            return None
        
        levels = []
        for i in range(20):
            offset = i * 16
            price = struct.unpack('<d', payload[offset:offset+8])[0]
            quantity = struct.unpack('<I', payload[offset+8:offset+12])[0]
            orders = struct.unpack('<I', payload[offset+12:offset+16])[0]
            
            levels.append({
                'price': price,
                'quantity': quantity,
                'orders': orders
            })
        
        return {
            'type': 'depth_20',
            'exchange_segment': exchange_segment,
            'security_id': str(security_id),
            'side': 'buy' if is_bid else 'sell',
            'levels': levels
        }
    
    def _handle_disconnect_packet(self, payload: bytes):
        """Handle disconnect packet"""
        if len(payload) >= 2:
            disconnect_code = struct.unpack('<H', payload[0:2])[0]
            self.logger.warning(f"Received disconnect packet with code: {disconnect_code}")
            
            # Common disconnect codes
            disconnect_reasons = {
                805: "Maximum websocket connections exceeded"
            }
            
            reason = disconnect_reasons.get(disconnect_code, "Unknown reason")
            self.logger.warning(f"Disconnect reason: {reason}")