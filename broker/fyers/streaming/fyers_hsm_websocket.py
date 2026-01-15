"""
Fyers HSM WebSocket Client
Implements binary protocol for real-time market data streaming
Based on official Fyers library analysis
"""

import base64
import json
import struct
import time
import threading
import websocket
import ssl
import logging
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime

class FyersHSMWebSocket:
    """
    Fyers HSM WebSocket client using binary protocol
    Handles all exchanges: NSE, NFO, BSE, BFO, MCX
    """
    
    HSM_URL = "wss://socket.fyers.in/hsm/v1-5/prod"
    SYMBOLS_TOKEN_API = "https://api-t1.fyers.in/data/symbol-token"
    
    # Data field mappings (from official library map.json)
    DATA_FIELDS = [
        "ltp", "vol_traded_today", "last_traded_time", "exch_feed_time",
        "bid_size", "ask_size", "bid_price", "ask_price", "last_traded_qty",
        "tot_buy_qty", "tot_sell_qty", "avg_trade_price", "OI", "low_price",
        "high_price", "Yhigh", "Ylow", "lower_ckt", "upper_ckt", "open_price",
        "prev_close_price", "type", "symbol"
    ]
    
    INDEX_FIELDS = [
        "ltp", "prev_close_price", "exch_feed_time", "high_price", "low_price",
        "open_price", "type", "symbol"
    ]
    
    DEPTH_FIELDS = [
        "bid_price1", "bid_price2", "bid_price3", "bid_price4", "bid_price5",
        "ask_price1", "ask_price2", "ask_price3", "ask_price4", "ask_price5",
        "bid_size1", "bid_size2", "bid_size3", "bid_size4", "bid_size5",
        "ask_size1", "ask_size2", "ask_size3", "ask_size4", "ask_size5",
        "bid_order1", "bid_order2", "bid_order3", "bid_order4", "bid_order5",
        "ask_order1", "ask_order2", "ask_order3", "ask_order4", "ask_order5",
        "type", "symbol"
    ]
    
    # Exchange segment mapping
    EXCHANGE_SEGMENTS = {
        "1010": "nse_cm",    # NSE Cash
        "1011": "nse_fo",    # NSE F&O
        "1120": "mcx_fo",    # MCX F&O
        "1210": "bse_cm",    # BSE Cash
        "1211": "bse_fo",    # BSE F&O
        "1212": "bcs_fo",    # BSE Currency
        "1012": "cde_fo",    # CDE F&O
        "1020": "nse_com"    # NSE Commodity
    }
    
    def __init__(self, access_token: str, log_path: str = ""):
        """
        Initialize HSM WebSocket client
        
        Args:
            access_token: Fyers access token in format "appid:token"
            log_path: Path for logging (optional)
        """
        self.access_token = access_token
        self.logger = logging.getLogger("fyers_hsm_websocket")
        
        # Extract HSM key from token
        self.hsm_key = self._extract_hsm_key(access_token)
        if not self.hsm_key:
            raise ValueError("Failed to extract HSM key from access token")
            
        self.logger.debug(f"HSM key extracted: {self.hsm_key[:20]}...")
        
        # WebSocket connection
        self.ws = None
        self.ws_thread = None
        self.connected = False
        self.authenticated = False
        self.running = False
        
        # Data structures
        self.subscriptions = {}  # topic_id -> topic_name mapping
        self.symbol_mappings = {}  # hsm_token -> original_symbol
        self.scrips_data = {}  # topic_id -> data for scrips
        self.index_data = {}   # topic_id -> data for indices  
        self.depth_data = {}   # topic_id -> data for depth
        
        # Callbacks
        self.on_message_callback = None
        self.on_error_callback = None
        self.on_open_callback = None
        self.on_close_callback = None
        
        # Threading
        self.lock = threading.Lock()
        
        # Initialize data structures to prevent AttributeError in cleanup
        self.subscriptions = {}
        self.symbol_mappings = {}
        self.scrips_data = {}
        self.index_data = {}
        self.depth_data = {}
        
        # Source identifier
        self.source = "OpenAlgo-HSM"
        self.mode = "P"  # Production mode
        
    def _extract_hsm_key(self, access_token: str) -> Optional[str]:
        """
        Extract HSM key from JWT access token
        
        Args:
            access_token: Fyers access token
            
        Returns:
            HSM key string or None if extraction fails
        """
        try:
            # Remove app_id prefix if present
            if ":" in access_token:
                _, token = access_token.split(":", 1)
            else:
                token = access_token
                
            # Decode JWT token
            header_b64, payload_b64, signature = token.split(".")
            
            # Add padding if needed
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            
            # Decode base64
            decoded_payload = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(decoded_payload.decode())
            
            # Extract HSM key
            hsm_key = payload.get("hsm_key")
            
            # Check token expiration
            exp_time = payload.get("exp", 0)
            current_time = int(time.time())
            
            if exp_time - current_time < 0:
                self.logger.error("Access token has expired")
                return None
                
            return hsm_key
            
        except Exception as e:
            self.logger.error(f"Failed to extract HSM key: {e}")
            return None
    
    def _create_auth_message(self) -> bytearray:
        """
        Create HSM authentication message in binary format
        
        Returns:
            Binary authentication message
        """
        buffer_size = 18 + len(self.hsm_key) + len(self.source)
        
        byte_buffer = bytearray()
        
        # Data length (buffer_size - 2)
        byte_buffer.extend(struct.pack("!H", buffer_size - 2))
        
        # Request type = 1 (authentication)
        byte_buffer.extend(bytes([1]))
        
        # Field count = 4
        byte_buffer.extend(bytes([4]))
        
        # Field-1: AuthToken (HSM key)
        byte_buffer.extend(bytes([1]))  # Field ID
        byte_buffer.extend(struct.pack("!H", len(self.hsm_key)))
        byte_buffer.extend(self.hsm_key.encode())
        
        # Field-2: Mode
        byte_buffer.extend(bytes([2]))  # Field ID
        byte_buffer.extend(struct.pack("!H", 1))
        byte_buffer.extend(self.mode.encode('utf-8'))
        
        # Field-3: Unknown flag
        byte_buffer.extend(bytes([3]))  # Field ID
        byte_buffer.extend(struct.pack("!H", 1))
        byte_buffer.extend(bytes([1]))
        
        # Field-4: Source
        byte_buffer.extend(bytes([4]))  # Field ID
        byte_buffer.extend(struct.pack("!H", len(self.source)))
        byte_buffer.extend(self.source.encode())
        
        return byte_buffer
    
    def _create_subscription_message(self, hsm_symbols: List[str], channel: int = 11) -> bytearray:
        """
        Create subscription message in binary format
        
        Args:
            hsm_symbols: List of HSM tokens (e.g., ["sf|bse_cm|500325"])
            channel: Channel number
            
        Returns:
            Binary subscription message
        """
        #self.logger.info(f"Creating subscription message for {len(hsm_symbols)} symbols")
        
        # Create scrips data
        scrips_data = bytearray()
        scrips_data.append(len(hsm_symbols) >> 8 & 0xFF)
        scrips_data.append(len(hsm_symbols) & 0xFF)
        
        for i, symbol in enumerate(hsm_symbols, 1):
            symbol_bytes = str(symbol).encode("ascii")
            scrips_data.append(len(symbol_bytes))
            scrips_data.extend(symbol_bytes)
            self.logger.debug(f"  Symbol {i}/{len(hsm_symbols)}: {symbol} ({len(symbol_bytes)} bytes)")
        
        # Build complete message
        data_len = 6 + len(scrips_data)
        
        buffer_msg = bytearray()
        buffer_msg.extend(struct.pack(">H", data_len))
        buffer_msg.append(4)  # Request type = 4 (subscription)
        buffer_msg.append(2)  # Field count = 2
        
        # Field-1: Symbols
        buffer_msg.append(1)  # Field ID
        buffer_msg.extend(struct.pack(">H", len(scrips_data)))
        buffer_msg.extend(scrips_data)
        
        # Field-2: Channel
        buffer_msg.append(2)  # Field ID
        buffer_msg.extend(struct.pack(">H", 1))
        buffer_msg.append(channel)
        
        return buffer_msg
    
    def _parse_binary_message(self, data: bytearray):
        """
        Parse incoming binary message from HSM WebSocket
        
        Args:
            data: Binary data received from WebSocket
        """
        try:
            if len(data) < 3:
                return
                
            # Get message type
            msg_type = data[2]
            
            if msg_type == 1:
                # Authentication response
                self.authenticated = True
                self.logger.info("HSM authentication successful")
                if self.on_open_callback:
                    self.on_open_callback()
                    
            elif msg_type == 6:
                # Data feed message
                self.logger.debug(f"Received data feed message (type 6): {len(data)} bytes")
                self._parse_data_feed(data)
                
            elif msg_type == 13:
                # Master data (usually large message on connect)
                self.logger.debug(f"Received master data: {len(data)} bytes")
                
            elif msg_type == 4:
                # Subscription acknowledgment
                self.logger.debug("Subscription acknowledged")
                
            else:
                self.logger.debug(f"Received message type: {msg_type}, length: {len(data)} bytes")
                
        except Exception as e:
            self.logger.error(f"Error parsing binary message: {e}")
            if self.on_error_callback:
                self.on_error_callback(e)
    
    def _parse_data_feed(self, data: bytearray):
        """
        Parse data feed message (message type 6)
        
        Args:
            data: Binary data containing market data
        """
        try:
            if len(data) < 9:
                self.logger.warning(f"Data feed too short: {len(data)} bytes")
                return
                
            # Get scrip count
            scrip_count = struct.unpack("!H", data[7:9])[0]
            self.logger.debug(f"Data feed contains {scrip_count} scrips")
            offset = 9
            
            for i in range(scrip_count):
                if offset >= len(data):
                    self.logger.warning(f"Reached end of data at scrip {i}")
                    break
                    
                # Get data type
                data_type = struct.unpack("B", data[offset:offset + 1])[0]
                offset += 1
                
                self.logger.debug(f"Processing scrip {i+1}/{scrip_count}, data_type: {data_type}")
                
                if data_type == 83:  # Snapshot data feed
                    offset = self._parse_snapshot_data(data, offset)
                elif data_type == 85:  # Update data feed
                    offset = self._parse_update_data(data, offset)
                else:
                    self.logger.warning(f"Unknown data type: {data_type}, skipping")
                    break
                    
        except Exception as e:
            self.logger.error(f"Error parsing data feed: {e}")
    
    def _parse_snapshot_data(self, data: bytearray, offset: int) -> int:
        """
        Parse snapshot data (data_type = 83)
        
        Args:
            data: Binary data
            offset: Current offset in data
            
        Returns:
            New offset after parsing
        """
        try:
            if offset + 3 > len(data):
                return offset
                
            # Get topic ID
            topic_id = struct.unpack("H", data[offset:offset + 2])[0]
            offset += 2
            
            # Get topic name length
            topic_name_len = struct.unpack("B", data[offset:offset + 1])[0]
            offset += 1
            
            if offset + topic_name_len > len(data):
                return offset
                
            # Get topic name (HSM token)
            topic_name = data[offset:offset + topic_name_len].decode("utf-8")
            offset += topic_name_len
            
            # Store mapping
            self.subscriptions[topic_id] = topic_name
            self.logger.debug(f"Mapped topic_id {topic_id} -> {topic_name}")
            
            # Parse based on topic type
            if topic_name.startswith("sf|"):
                offset = self._parse_scrip_snapshot(data, offset, topic_id, topic_name)
            elif topic_name.startswith("if|"):
                offset = self._parse_index_snapshot(data, offset, topic_id, topic_name)
            elif topic_name.startswith("dp|"):
                offset = self._parse_depth_snapshot(data, offset, topic_id, topic_name)
                
        except Exception as e:
            self.logger.error(f"Error parsing snapshot data: {e}")
            
        return offset
    
    def _parse_scrip_snapshot(self, data: bytearray, offset: int, topic_id: int, topic_name: str) -> int:
        """Parse scrip snapshot data"""
        try:
            if offset + 1 > len(data):
                return offset
                
            field_count = struct.unpack("B", data[offset:offset + 1])[0]
            offset += 1
            
            scrip_data = {"type": "sf"}
            
            # Parse field values
            for index in range(field_count):
                if offset + 4 > len(data):
                    break
                    
                value = struct.unpack(">i", data[offset:offset + 4])[0]
                offset += 4
                
                if value != -2147483648 and index < len(self.DATA_FIELDS):
                    scrip_data[self.DATA_FIELDS[index]] = value
            
            # Skip 2 bytes
            offset += 2
            
            if offset + 3 > len(data):
                return offset
                
            # Get multiplier and precision
            multiplier = struct.unpack(">H", data[offset:offset + 2])[0]
            scrip_data["multiplier"] = multiplier
            offset += 2
            
            precision = struct.unpack("B", data[offset:offset + 1])[0]
            scrip_data["precision"] = precision
            offset += 1
            
            # Parse exchange, token, symbol strings
            string_fields = ["exchange", "exchange_token", "symbol"]
            for field in string_fields:
                if offset + 1 > len(data):
                    break
                    
                string_len = struct.unpack("B", data[offset:offset + 1])[0]
                offset += 1
                
                if offset + string_len > len(data):
                    break
                    
                string_data = data[offset:offset + string_len].decode("utf-8", errors='ignore')
                scrip_data[field] = string_data
                offset += string_len
            
            # Add original symbol mapping and HSM token
            if topic_name in self.symbol_mappings:
                scrip_data["original_symbol"] = self.symbol_mappings[topic_name]
                self.logger.debug(f"Symbol mapping: {topic_name} -> {self.symbol_mappings[topic_name]}")
            else:
                self.logger.warning(f"No symbol mapping found for topic_name: {topic_name}")
            
            # Add HSM token for reliable matching in adapter
            scrip_data["hsm_token"] = topic_name
            
            # Store data
            self.scrips_data[topic_id] = scrip_data
            
            # Send to callback
            if self.on_message_callback:
                self.logger.debug(f"Sending scrip data to callback: {scrip_data.get('symbol', 'Unknown')} LTP={scrip_data.get('ltp', 'N/A')}")
                # Debug: Log all available fields in HSM data
                self.logger.debug(f"Complete HSM scrip_data fields: {list(scrip_data.keys())}")
                self.logger.debug(f"OHLC values: open={scrip_data.get('open_price', 'N/A')}, high={scrip_data.get('high_price', 'N/A')}, low={scrip_data.get('low_price', 'N/A')}, close={scrip_data.get('prev_close_price', 'N/A')}")
                self.on_message_callback(scrip_data)
            else:
                self.logger.warning(f"No callback set for scrip data: {scrip_data.get('symbol', 'Unknown')}")
                
        except Exception as e:
            self.logger.error(f"Error parsing scrip snapshot: {e}")
            
        return offset
    
    def _parse_index_snapshot(self, data: bytearray, offset: int, topic_id: int, topic_name: str) -> int:
        """Parse index snapshot data"""
        try:
            if offset + 1 > len(data):
                return offset
                
            field_count = struct.unpack("B", data[offset:offset + 1])[0]
            offset += 1
            
            index_data = {"type": "if"}
            
            # Parse field values
            for index in range(field_count):
                if offset + 4 > len(data):
                    break
                    
                value = struct.unpack(">i", data[offset:offset + 4])[0]
                offset += 4
                
                if value != -2147483648 and index < len(self.INDEX_FIELDS):
                    index_data[self.INDEX_FIELDS[index]] = value
            
            # Add original symbol mapping and HSM token
            if topic_name in self.symbol_mappings:
                index_data["original_symbol"] = self.symbol_mappings[topic_name]
            
            # Add HSM token for reliable matching in adapter
            index_data["hsm_token"] = topic_name
            
            # Store data
            self.index_data[topic_id] = index_data
            
            # Send to callback
            if self.on_message_callback:
                self.on_message_callback(index_data)
                
        except Exception as e:
            self.logger.error(f"Error parsing index snapshot: {e}")
            
        return offset
    
    def _parse_depth_snapshot(self, data: bytearray, offset: int, topic_id: int, topic_name: str) -> int:
        """Parse depth snapshot data"""
        try:
            if offset + 1 > len(data):
                return offset
                
            field_count = struct.unpack("B", data[offset:offset + 1])[0]
            offset += 1
            
            depth_data = {"type": "dp"}
            
            # Parse field values
            for index in range(field_count):
                if offset + 4 > len(data):
                    break
                    
                value = struct.unpack(">i", data[offset:offset + 4])[0]
                offset += 4
                
                if value != -2147483648 and index < len(self.DEPTH_FIELDS):
                    depth_data[self.DEPTH_FIELDS[index]] = value
            
            # Skip 2 bytes (similar to scrip snapshot)
            offset += 2
            
            if offset + 3 > len(data):
                return offset
                
            # Get multiplier and precision (depth data also has these)
            multiplier = struct.unpack(">H", data[offset:offset + 2])[0]
            depth_data["multiplier"] = multiplier
            offset += 2
            
            precision = struct.unpack("B", data[offset:offset + 1])[0]
            depth_data["precision"] = precision
            offset += 1
            
            # Parse exchange, token, symbol strings (same as scrip)
            string_fields = ["exchange", "exchange_token", "symbol"]
            for field in string_fields:
                if offset + 1 > len(data):
                    break
                    
                string_len = struct.unpack("B", data[offset:offset + 1])[0]
                offset += 1
                
                if offset + string_len > len(data):
                    break
                    
                string_data = data[offset:offset + string_len].decode("utf-8", errors='ignore')
                depth_data[field] = string_data
                offset += string_len
            
            # Add original symbol mapping and HSM token
            if topic_name in self.symbol_mappings:
                depth_data["original_symbol"] = self.symbol_mappings[topic_name]
            
            # Add HSM token for reliable matching in adapter
            depth_data["hsm_token"] = topic_name
            
            # Store data
            self.depth_data[topic_id] = depth_data
            
            # Log depth data for debugging
            #self.logger.info(f"Parsed depth data: {depth_data.get('symbol', 'Unknown')}")
            self.logger.debug(f"Depth fields: bid_price1={depth_data.get('bid_price1', 'N/A')}, ask_price1={depth_data.get('ask_price1', 'N/A')}")
            #self.logger.info(f"Multiplier={multiplier}, Precision={precision}")
            
            # Send to callback
            if self.on_message_callback:
                self.on_message_callback(depth_data)
                
        except Exception as e:
            self.logger.error(f"Error parsing depth snapshot: {e}")
            
        return offset
    
    def _parse_update_data(self, data: bytearray, offset: int) -> int:
        """
        Parse update data (data_type = 85)
        
        Args:
            data: Binary data
            offset: Current offset
            
        Returns:
            New offset
        """
        try:
            if offset + 3 > len(data):
                return offset
                
            # Get topic ID
            topic_id = struct.unpack("H", data[offset:offset + 2])[0]
            offset += 2
            
            # Get field count
            field_count = struct.unpack("B", data[offset:offset + 1])[0]
            offset += 1
            
            # Determine data type based on topic ID
            if topic_id in self.subscriptions:
                topic_name = self.subscriptions[topic_id]
                
                if topic_name.startswith("sf|") and topic_id in self.scrips_data:
                    # Update scrip data
                    for index in range(field_count):
                        if offset + 4 > len(data):
                            break
                            
                        value = struct.unpack(">i", data[offset:offset + 4])[0]
                        offset += 4
                        
                        if value != -2147483648 and index < len(self.DATA_FIELDS):
                            old_value = self.scrips_data[topic_id].get(self.DATA_FIELDS[index])
                            if old_value != value:
                                self.scrips_data[topic_id][self.DATA_FIELDS[index]] = value
                                
                                # Send update to callback
                                if self.on_message_callback:
                                    update_data = self.scrips_data[topic_id].copy()
                                    update_data["update_type"] = "live"
                                    self.logger.debug(f"Sending live update: {update_data.get('symbol', 'Unknown')} LTP={update_data.get('ltp', 'N/A')}")
                                    self.on_message_callback(update_data)
                
                elif topic_name.startswith("if|") and topic_id in self.index_data:
                    # Update index data
                    for index in range(field_count):
                        if offset + 4 > len(data):
                            break
                            
                        value = struct.unpack(">i", data[offset:offset + 4])[0]
                        offset += 4
                        
                        if value != -2147483648 and index < len(self.INDEX_FIELDS):
                            old_value = self.index_data[topic_id].get(self.INDEX_FIELDS[index])
                            if old_value != value:
                                self.index_data[topic_id][self.INDEX_FIELDS[index]] = value
                                
                                # Send update to callback
                                if self.on_message_callback:
                                    update_data = self.index_data[topic_id].copy()
                                    update_data["update_type"] = "live"
                                    self.on_message_callback(update_data)
                
                elif topic_name.startswith("dp|") and topic_id in self.depth_data:
                    # Update depth data
                    for index in range(field_count):
                        if offset + 4 > len(data):
                            break
                            
                        value = struct.unpack(">i", data[offset:offset + 4])[0]
                        offset += 4
                        
                        if value != -2147483648 and index < len(self.DEPTH_FIELDS):
                            old_value = self.depth_data[topic_id].get(self.DEPTH_FIELDS[index])
                            if old_value != value:
                                self.depth_data[topic_id][self.DEPTH_FIELDS[index]] = value
                                
                                # Send update to callback
                                if self.on_message_callback:
                                    update_data = self.depth_data[topic_id].copy()
                                    update_data["update_type"] = "live"
                                    self.logger.debug(f"Sending live depth update: {update_data.get('symbol', 'Unknown')}")
                                    self.on_message_callback(update_data)
            else:
                # Skip unknown data
                offset += field_count * 4
                
        except Exception as e:
            self.logger.error(f"Error parsing update data: {e}")
            
        return offset
    
    def set_callbacks(self, on_message=None, on_error=None, on_open=None, on_close=None):
        """Set callback functions"""
        self.on_message_callback = on_message
        self.on_error_callback = on_error
        self.on_open_callback = on_open
        self.on_close_callback = on_close
    
    def _on_ws_open(self, ws):
        """Handle WebSocket open event"""
        self.connected = True
        #self.logger.info("HSM WebSocket connected")
        
        # Send authentication message
        auth_msg = self._create_auth_message()
        ws.send(auth_msg, opcode=websocket.ABNF.OPCODE_BINARY)
        #self.logger.info(f"Sent HSM authentication ({len(auth_msg)} bytes)")
    
    def _on_ws_message(self, ws, message):
        """Handle WebSocket message event"""
        if isinstance(message, bytes):
            self._parse_binary_message(bytearray(message))
        else:
            self.logger.warning(f"Received unexpected text message: {message}")
    
    def _on_ws_error(self, ws, error):
        """Handle WebSocket error event"""
        self.logger.error(f"HSM WebSocket error: {error}")
        if self.on_error_callback:
            self.on_error_callback(error)
    
    def _on_ws_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close event"""
        self.connected = False
        self.authenticated = False
        #self.logger.info(f"HSM WebSocket closed: {close_msg} ({close_status_code})")
        if self.on_close_callback:
            self.on_close_callback()
    
    def connect(self):
        """Connect to HSM WebSocket"""
        if self.connected:
            self.logger.warning("Already connected to HSM WebSocket")
            return
            
        self.running = True
        
        self.ws = websocket.WebSocketApp(
            self.HSM_URL,
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
            header={
                'Authorization': self.access_token,
                'User-Agent': f'{self.source}/1.0'
            }
        )
        
        # Run in separate thread
        self.ws_thread = threading.Thread(
            target=self.ws.run_forever,
            kwargs={'sslopt': {"cert_reqs": ssl.CERT_NONE}}
        )
        self.ws_thread.daemon = True
        self.ws_thread.start()
        
        # Wait for connection
        timeout = 10
        start_time = time.time()
        while not self.connected and time.time() - start_time < timeout:
            time.sleep(0.1)
            
        if not self.connected:
            raise ConnectionError("Failed to connect to HSM WebSocket")
            
        self.logger.info("HSM WebSocket connection established")
    
    def disconnect(self):
        """Disconnect from HSM WebSocket and cleanup all resources"""
        try:
            self.logger.info("Starting HSM WebSocket disconnect and cleanup...")
            
            # Set running flag to false to stop operations
            self.running = False
            self.connected = False
            self.authenticated = False
            
            # Clear all data structures
            with self.lock:
                self.subscriptions.clear()
                self.symbol_mappings.clear()
                self.scrips_data.clear()
                self.index_data.clear()
                self.depth_data.clear()
                self.logger.info("Cleared all data structures and subscriptions")
            
            # Close WebSocket connection
            if self.ws:
                try:
                    self.ws.close()
                    #self.logger.info("WebSocket connection closed")
                except Exception as e:
                    self.logger.error(f"Error closing WebSocket: {e}")
                finally:
                    self.ws = None
            
            # Wait for WebSocket thread to finish
            if self.ws_thread and self.ws_thread.is_alive():
                try:
                    self.ws_thread.join(timeout=5)
                    if self.ws_thread.is_alive():
                        self.logger.warning("WebSocket thread did not terminate within 5 seconds")
                    else:
                        self.logger.debug("WebSocket thread terminated successfully")
                except Exception as e:
                    self.logger.error(f"Error waiting for WebSocket thread: {e}")
                finally:
                    self.ws_thread = None
            
            # Reset connection parameters
            self.hsm_key = None
            
            #self.logger.info("HSM WebSocket disconnect and cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error during HSM WebSocket disconnect: {e}")
        finally:
            # Ensure flags are reset even if cleanup fails
            self.running = False
            self.connected = False
            self.authenticated = False
    
    def subscribe_symbols(self, hsm_symbols: List[str], symbol_mappings: Dict[str, str] = None):
        """
        Subscribe to symbols using HSM format
        
        Args:
            hsm_symbols: List of HSM tokens (e.g., ["sf|bse_cm|500325"])
            symbol_mappings: Dict mapping HSM tokens to original symbols
        """
        if not self.authenticated:
            raise ConnectionError("Not authenticated to HSM WebSocket")
        
        if symbol_mappings:
            self.symbol_mappings.update(symbol_mappings)
            self.logger.debug(f"Updated symbol mappings. Total mappings: {len(self.symbol_mappings)}")
        
        # Create and send subscription message
        sub_msg = self._create_subscription_message(hsm_symbols, channel=11)
        self.ws.send(sub_msg, opcode=websocket.ABNF.OPCODE_BINARY)
        
        #self.logger.info(f"\n✅ Sent subscription request for {len(hsm_symbols)} HSM symbols")
        for i, symbol in enumerate(hsm_symbols, 1):
            mapped_symbol = symbol_mappings.get(symbol, 'Unknown') if symbol_mappings else 'N/A'
            #self.logger.info(f"  {i}. {symbol} => {mapped_symbol}")
        self.logger.debug(f"Total active subscriptions in HSM: {len(hsm_symbols)}")
    
    def is_connected(self) -> bool:
        """Check if connected and authenticated"""
        return self.connected and self.authenticated
    
    def __del__(self):
        """
        Destructor to ensure proper cleanup when HSM WebSocket is destroyed
        """
        try:
            if hasattr(self, 'logger'):
                self.logger.debug("FyersHSMWebSocket destructor called")
            self.disconnect()
        except Exception as e:
            # Fallback logging if self.logger is not available
            import logging
            logger = logging.getLogger("fyers_hsm_websocket")
            logger.error(f"Error in HSM WebSocket destructor: {e}")
    
    def force_cleanup(self):
        """
        Force cleanup all resources (for emergency cleanup)
        """
        try:
            # Force stop all operations
            self.running = False
            self.connected = False
            self.authenticated = False
            
            # Force clear data structures
            if hasattr(self, 'subscriptions'):
                self.subscriptions.clear()
            if hasattr(self, 'symbol_mappings'):
                self.symbol_mappings.clear()
            if hasattr(self, 'scrips_data'):
                self.scrips_data.clear()
            if hasattr(self, 'index_data'):
                self.index_data.clear()
            if hasattr(self, 'depth_data'):
                self.depth_data.clear()
                
            # Force close WebSocket
            if hasattr(self, 'ws') and self.ws:
                try:
                    self.ws.close()
                except:
                    pass
                self.ws = None
                
            # Reset thread
            if hasattr(self, 'ws_thread'):
                self.ws_thread = None
                
            #print("HSM WebSocket force cleanup completed")
            
        except:
            pass  # Suppress all errors in force cleanup