"""
Complete Dhan WebSocket client wrapper for OpenAlgo.
Based on Dhan V2 API documentation with proper binary packet parsing.
"""
import os
import asyncio
import json
import logging
import struct
from datetime import datetime
import websockets
import os
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Union

import websockets

# Set up logging
logger = logging.getLogger("dhan_websocket")

class DhanWebSocket:
    """
    Complete Wrapper for Dhan's MarketFeed WebSocket client.
    Bridges the async implementation with OpenAlgo's threading model.
    """
    # Message type constants (based on Dhan binary packet first byte)
    TYPE_DISCONNECT = 0   # Disconnect notification
    TYPE_TICKER = 15     # LTP data (matches REQUEST_CODE_TICKER)
    TYPE_QUOTE = 17      # Quote data (matches REQUEST_CODE_QUOTE)
    TYPE_DEPTH = 21      # Full market depth (matches REQUEST_CODE_FULL)
    TYPE_OI = 9          # Open Interest data
    TYPE_PREV_CLOSE = 10  # Previous day close price
    TYPE_MARKET_UPDATE = 4  # Market data update packet
    
    # WebSocket URL constants
    MARKET_FEED_WSS = "wss://api-feed.dhan.co"
    
    # Mode constants for V2 API
    MODE_LTP = "ltp"             # LTP only
    MODE_QUOTE = "marketdata"    # Quote mode (includes price, volume, OHLC)
    MODE_FULL = "depth"          # Full/Depth mode (includes market depth)
    
    # Request code constants for Dhan API (from marketfeed_dhan.txt)
    REQUEST_CODE_TICKER = TYPE_TICKER  # 15 - LTP
    REQUEST_CODE_QUOTE = TYPE_QUOTE    # 17 - Quote/marketdata
    REQUEST_CODE_FULL = TYPE_DEPTH     # 21 - Full market data
    
    # Heartbeat interval in seconds
    HEARTBEAT_INTERVAL = 15
    
    # Exchange code mapping for binary packets
    EXCHANGE_MAP = {
        0: "IDX_I",
        1: "NSE_EQ", 
        2: "NSE_FNO",
        3: "NSE_CURRENCY",
        4: "BSE_EQ",
        5: "MCX_COMM",
        7: "BSE_CURRENCY", 
        8: "BSE_FNO"
    }

    def __init__(self, 
                 client_id: str,
                 access_token: str, 
                 on_ticks: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
                 on_disconnect: Optional[Callable[[], None]] = None,
                 on_error: Optional[Callable[[Exception], None]] = None,
                 on_connect: Optional[Callable[[], None]] = None,
                 version: str = 'v2'):
        """Initialize the Dhan WebSocket client wrapper"""
        self.client_id = client_id
        self.access_token = access_token
        self.version = version
        
        # Callback handlers
        self.on_ticks = on_ticks or (lambda ticks: None)
        self.on_disconnect = on_disconnect or (lambda: None)
        self.on_error = on_error or (lambda e: None)
        self.on_connect = on_connect or (lambda: None)
        
        # Connection state
        self.running = False
        self.connected = False
        self.ws = None
        self.loop = None
        self.thread = None
        self.instruments = {}  # Dictionary to store subscribed instruments
        self.lock = threading.Lock()
        
        # Message counters for debugging
        self.message_count = 0
        self.binary_message_count = 0
        self.json_message_count = 0
    
    def wait_for_connection(self, timeout: float = 5.0) -> bool:
        """Wait for WebSocket connection to be established"""
        start_time = time.time()
        while not self.connected and time.time() - start_time < timeout:
            time.sleep(0.1)
        return self.connected
    
    def is_connected(self):
        """Check if WebSocket is connected"""
        return self.connected and self.ws and not self.ws.closed
    
    def start(self) -> bool:
        """Start the WebSocket client in a separate thread."""
        if self.running:
            logger.warning("WebSocket client already running")
            return True

        try:
            self.loop = asyncio.new_event_loop()
            self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
            self.thread.start()
            self.running = True
            logger.info("WebSocket client thread started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start WebSocket client: {e}")
            self.on_error(e)
            return False
    
    def _run_event_loop(self):
        """Run the event loop in a separate thread"""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._run_client())
        except Exception as e:
            logger.error(f"Error in WebSocket event loop: {e}")
        finally:
            loop = self.loop
            self.loop = None
            
            if loop and loop.is_running():
                loop.stop()
            if loop and not loop.is_closed():
                loop.close()
                
            logger.info("WebSocket client thread stopped")
    
    async def _run_client(self):
        """Main WebSocket client loop"""
        retries = 0
        max_retries = 5
        retry_delay = 2
        
        while retries < max_retries and self.running:
            try:
                logger.info(f"Attempting to connect (attempt {retries + 1}/{max_retries})...")
                await self._connect()
                
                retries = 0
                self.connected = True
                
                if hasattr(self, 'instruments') and self.instruments and len(self.instruments) > 0:
                    logger.info(f"Resubscribing to {len(self.instruments)} instruments after reconnection")
                    await self._resubscribe()
                
                await self._process_messages()
                
                logger.info("WebSocket connection closed normally")
                break
                
            except (websockets.exceptions.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK) as e:
                self.connected = False
                logger.warning(f"WebSocket connection closed: {e}")
                retries += 1
                if retries < max_retries and self.running:
                    wait_time = retry_delay * retries
                    logger.info(f"Attempting to reconnect in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
            except Exception as e:
                self.connected = False
                logger.error(f"Unexpected error: {e}", exc_info=True)
                self.on_error(e)
                retries += 1
                if retries < max_retries and self.running:
                    wait_time = retry_delay * retries
                    await asyncio.sleep(wait_time)
                
        if retries >= max_retries:
            logger.error(f"Failed to connect after {max_retries} retries")
            self.on_error(Exception(f"Failed to connect after {max_retries} retries"))
            
        if self.connected:
            self.connected = False
            self.on_disconnect()
    
    async def _connect(self):
        """Establishes the WebSocket connection to the Dhan servers"""
        try:
            await self._close_connection()
            
            # Build connection URL (Dhan V2 format)
            ws_url = f"{self.MARKET_FEED_WSS}?version=2&token={self.access_token}&clientId={self.client_id}&authType=2"
            logger.info(f"Connecting to WebSocket URL: {ws_url[:50]}...")
            
            self.ws = await websockets.connect(
                ws_url,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=10,
                max_size=None
            )
            
            self.connected = True
            logger.info("WebSocket connection established successfully")
            
            if self.on_connect:
                self.on_connect()
            
            if self.instruments:
                await self._resubscribe()
                
            return True
        except Exception as e:
            logger.error(f"Connection error: {e}")
            self.connected = False
            if self.on_error:
                self.on_error(f"Connection error: {str(e)}")
            raise
            
    async def _close_connection(self):
        """Close the WebSocket connection gracefully"""
        logger.info("Closing WebSocket connection")
        try:
            if self.ws:
                await self.ws.close()
                logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error closing WebSocket connection: {e}")
        finally:
            self.connected = False
            if self.on_disconnect:
                self.on_disconnect()
                
    async def _reconnect(self):
        """Reconnect to WebSocket server after disconnection"""
        try:
            # Only attempt reconnect if we're still supposed to be running
            if not self.running:
                logger.info("Not reconnecting because client is stopping")
                return
                
            logger.info("Reconnecting to Dhan WebSocket server...")
            
            # Close existing connection if any
            await self._close_connection()
            
            # Wait a bit before reconnecting to avoid hammering the server
            await asyncio.sleep(2)
            
            # Try to reconnect
            await self._connect()
            
            # Resubscribe to all instruments if reconnection successful
            if self.connected:
                logger.info("Reconnected successfully, resubscribing...")
                await self._resubscribe()
            else:
                logger.warning("Reconnection failed, will retry")
                # Schedule another reconnect attempt
                await asyncio.sleep(5)  # Wait longer before trying again
                asyncio.create_task(self._reconnect())
                
        except Exception as e:
            logger.error(f"Error during reconnect: {e}")
            # Schedule another reconnect attempt
            await asyncio.sleep(5)  # Wait longer before trying again
            asyncio.create_task(self._reconnect())
    
    async def _process_messages(self):
        """Process incoming WebSocket messages in a loop"""
        if not self.ws:
            logger.error("No WebSocket connection to process messages")
            return
            
        try:
            heartbeat_task = asyncio.create_task(self._heartbeat_task())
            
            while self.running and self.connected:
                try:
                    message = await asyncio.wait_for(self.ws.recv(), timeout=1.0)
                    await self._on_message(message)
                    
                except asyncio.TimeoutError:
                    continue
                except (websockets.exceptions.ConnectionClosedOK, websockets.exceptions.ConnectionClosedError) as e:
                    logger.warning(f"WebSocket connection closed while processing messages: {e}")
                    self.connected = False
                    break
                    
            if not heartbeat_task.done():
                heartbeat_task.cancel()
                
        except Exception as e:
            logger.error(f"Error processing messages: {e}")
            self.connected = False
            if self.on_error:
                self.on_error(e)
    
    async def _heartbeat_task(self):
        """
        Periodically send heartbeat to keep the connection alive
        """
        while True:
            if self.ws and hasattr(self.ws, 'open') and self.ws.open:
                try:
                    await self.ws.send(json.dumps({"a": "h"}))
                    logger.debug("Heartbeat sent")
                except Exception as e:
                    logger.error(f"Error sending heartbeat: {e}")
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
    
    async def _on_message(self, message):
        """Process a received WebSocket message"""
        try:
            self.message_count += 1
            
            if isinstance(message, bytes):
                self.binary_message_count += 1
                # More detailed binary message logging
                if len(message) > 0:
                    msg_type = message[0]
                    logger.debug(f"Received binary message #{self.binary_message_count} (type={msg_type}, size={len(message)} bytes, hex={message[:16].hex()})")
                else:
                    logger.debug(f"Received empty binary message #{self.binary_message_count}")
                await self._process_binary_packet(message)
                return
                
            # Handle JSON messages
            self.json_message_count += 1
            try:
                data = json.loads(message)
                logger.info(f"Received JSON message: {data}")
                
                if 'type' in data:
                    if data['type'] == 'error':
                        logger.error(f"Server error: {data}")
                        if self.on_error:
                            self.on_error(Exception(f"Server error: {data.get('message', 'Unknown error')}"))
                    elif data['type'] == 'welcome':
                        logger.info(f"Welcome message: {data.get('message', 'Connected to server')}")
                    elif data['type'] == 'disconnect':
                        logger.warning(f"Server requested disconnect: {data.get('message', 'Unknown reason')}")
                        self.connected = False
            except json.JSONDecodeError:
                logger.warning(f"Received non-JSON text message: {message}")
                
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            if self.on_error:
                self.on_error(e)
    
    async def _process_binary_packet(self, packet_data):
        """
        Process binary data packet from WebSocket with proper Dhan V2 format
        
        Binary packet structure according to Dhan documentation:
        - Byte 1: Feed Response Code (message type)
        - Bytes 2-3: Message Length (2 bytes) - total length of this message
        - Byte 4: Exchange Segment
        - Bytes 5-8: Security ID (token)
        
        Note: A single WebSocket frame may contain multiple concatenated messages.
        Each must be processed separately according to the message length in the header.
        """
        try:
            # Check if packet has valid data
            if len(packet_data) < 8:  # Need at least 8 bytes for header
                logger.warning(f"Received invalid packet (too short): {len(packet_data)} bytes")
                return
                
            # Process all messages in the buffer (there may be multiple concatenated messages)
            offset = 0
            processed_messages = 0
            
            while offset + 8 <= len(packet_data):  # Need at least header (8 bytes)
                # Extract header information
                msg_type, msg_length, exchange_code, token = struct.unpack('<BHBI', packet_data[offset:offset+8])
                
                # Debug header fields
                logger.debug(f"Binary packet header: type={msg_type}, length={msg_length}, exchange={exchange_code}, token={token} (0x{token:04x})")
                
                # Validate message length
                if msg_type == 8:  # Full data packet
                    expected_length = 162  # Full data packet size
                    if msg_length != expected_length:
                        logger.warning(f"Invalid message length for type 8: got {msg_length}, expected {expected_length}")
                        msg_length = expected_length  # Force correct length
                
                # Validate message length
                if msg_length < 8:  # Header must be at least 8 bytes
                    logger.warning(f"Invalid message length in header: {msg_length} bytes at offset {offset}")
                    break  # Can't process further as boundaries are unknown
                    
                if offset + msg_length > len(packet_data):
                    logger.warning(f"Message truncated: need {msg_length} bytes but only {len(packet_data) - offset} available")
                    break  # Message is incomplete
                
                # Extract the complete message for this segment
                message = packet_data[offset:offset+msg_length]
                
                # Process the message based on type
                logger.debug(f"Processing message type {msg_type} for token {token}")
                
                if msg_type == self.TYPE_TICKER:  # 15 - LTP data
                    ticks = self._parse_ticker_data(message)
                    if ticks and self.on_ticks:
                        logger.info(f"Parsed LTP data for token {token}")
                        self.on_ticks(ticks)
                        
                elif msg_type == self.TYPE_QUOTE:  # 17 - Quote/marketdata
                    tick = self._parse_quote_data(message)
                    if tick and self.on_ticks:
                        logger.info(f"Parsed quote data for token {token}")
                        self.on_ticks([tick])
                        
                elif msg_type == self.TYPE_DEPTH:  # 21 - Full market depth
                    tick = self._parse_market_depth(message)
                    if tick and self.on_ticks:
                        logger.info(f"Parsed market depth for token {token}")
                        self.on_ticks([tick])
                        
                elif msg_type == self.TYPE_OI:  # 9 - Open Interest
                    tick = self._parse_oi_data(message)
                    if tick and self.on_ticks:
                        logger.info(f"Parsed OI data for token {token}")
                        self.on_ticks([tick])
                        
                elif msg_type == self.TYPE_PREV_CLOSE:  # 10 - Previous close
                    tick = self._parse_prev_close(message)
                    if tick and self.on_ticks:
                        logger.info(f"Parsed prev close for token {token}")
                        self.on_ticks([tick])
                        
                elif msg_type == self.TYPE_MARKET_UPDATE:  # 4 - Market data update
                    tick = self._parse_market_update(message)
                    if tick and self.on_ticks:
                        logger.info(f"Parsed market update for token {token}")
                        self.on_ticks([tick])
                        
                elif msg_type == 8:  # Full data (ticker + depth)
                    tick = self._parse_full_data(message)
                    if tick and self.on_ticks:
                        logger.info(f"Parsed full data for token {token}")
                        self.on_ticks([tick])
                        
                elif msg_type == self.TYPE_DISCONNECT:  # 0 - Disconnect
                    logger.warning(f"Received disconnect message for token {token}")
                    self._parse_disconnect(message)
                    
                else:
                    logger.warning(f"Unknown message type {msg_type} for token {token}")
                    # Try general parser as fallback
                    tick = self._parse_dhan_binary_packet(message)
                    if tick:
                        ticks = [tick] if not isinstance(tick, list) else tick
                        if self.on_ticks and ticks:
                            self.on_ticks(ticks)
                
                # Move to the next message
                offset += msg_length
                processed_messages += 1
            
            if processed_messages > 0:
                logger.debug(f"Processed {processed_messages} messages from binary packet of {len(packet_data)} bytes")
            else:
                logger.warning(f"Couldn't process any complete messages from binary packet of {len(packet_data)} bytes")
                
        except Exception as e:
            logger.error(f"Error processing binary packet: {e}")
            logger.error(f"Packet data (first 50 bytes): {packet_data[:50].hex()}")

    

    def _parse_ticker_data(self, packet_data):
        """Parse ticker/LTP data (message type TYPE_TICKER = 15) - Based on official Dhan implementation"""
        try:
            # Check if we have enough data for the ticker format
            if len(packet_data) < 16:  # Minimum length per official client
                logger.warning(f"LTP data packet too small: {len(packet_data)} bytes")
                return []
                
            # Unpack according to official Dhan client format: <BHBIfI>
            # B: message type (1 byte)
            # H: sequence number (2 bytes)
            # B: exchange segment (1 byte)
            # I: security ID/token (4 bytes)
            # f: LTP price (4 bytes)
            # I: timestamp (4 bytes)
            unpack_data = struct.unpack('<BHBIfI', packet_data[0:16])
            
            # Extract fields
            exchange_id = unpack_data[2]  # Third field is exchange segment
            token = unpack_data[3]        # Fourth field is security ID/token
            ltp = unpack_data[4]          # Fifth field is LTP
            timestamp = unpack_data[5]    # Sixth field is timestamp
            
            # Map exchange code to string name for compatibility
            if exchange_id == 1:
                exchange = "NSE"
            elif exchange_id == 2:
                exchange = "BSE"
            elif exchange_id == 3:
                exchange = "NFO"
            elif exchange_id == 4:
                exchange = "CDS"
            elif exchange_id == 5:
                exchange = "MCX"
            elif exchange_id == 0:
                exchange = "IDX"  # Index
            else:
                exchange = f"UNK_{exchange_id}"
            
            # Set default values for fields not in this packet
            last_quantity = 0
            volume = 0
            avg_price = 0.0
            open_price = 0.0
            high_price = 0.0
            low_price = 0.0
            close_price = 0.0
            
            # Convert timestamp to datetime
            dt = datetime.fromtimestamp(timestamp) if timestamp > 0 else datetime.now()
            formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # Create tick dictionary in OpenAlgo format
            tick = {
                'token': token,
                'instrument_token': token,
                'exchange': exchange,
                'last_price': ltp,
                'last_quantity': last_quantity,
                'volume': volume,
                'average_price': avg_price,
                'timestamp': formatted_time,
                'exchange_timestamp': formatted_time,
                'ohlc': {
                    'open': open_price,
                    'high': high_price,
                    'low': low_price,
                    'close': close_price
                },
                'mode': 'ltp',
                'packet_type': 'ticker'
            }
            
            logger.info(f"Parsed ticker data for token {token}, exchange_id {exchange_id}, LTP={ltp}")
            return [tick]  # Return as list for consistency
        except Exception as e:
            logger.error(f"Error parsing ticker data: {e}, packet data: {packet_data.hex()}")
            return []
    
    def _parse_dhan_binary_packet(self, packet_data):
        """
        Parse Dhan binary packet based on the first byte which indicates message type
        """
        if len(packet_data) < 1:
            logger.warning("Empty packet received")
            return None
            
        msg_type = struct.unpack('>B', packet_data[0:1])[0]
        
        # Log the binary packet for debugging
        logger.debug(f"Binary packet received: type={msg_type}, size={len(packet_data)}, hex={packet_data.hex()}")
        
        try:
            if msg_type == 2:  # Ticker data
                return self._parse_ticker_data(packet_data)
            elif msg_type == 6:  # Previous close data
                return self._parse_prev_close(packet_data)
            elif msg_type == self.TYPE_TICKER:  # 15 - LTP
                return self._parse_ticker_data(packet_data)
            elif msg_type == self.TYPE_QUOTE:  # 17 - Quote
                return self._parse_quote_data(packet_data)
            elif msg_type == self.TYPE_DEPTH:  # 21 - Full market depth
                return self._parse_market_depth(packet_data)
            elif msg_type == self.TYPE_OI:  # 9 - Open Interest
                return self._parse_oi_data(packet_data)
            elif msg_type == self.TYPE_PREV_CLOSE:  # 10 - Previous close
                return self._parse_prev_close(packet_data)
            elif msg_type == 8:  # Full data (ticker + depth)
                return self._parse_full_data(packet_data)
            elif msg_type == 50:  # Disconnect
                return self._parse_disconnect(packet_data)
            else:
                logger.warning(f"Unknown message type {msg_type} in packet: {packet_data.hex()}")
                return None
        except Exception as e:
            logger.error(f"Error parsing binary packet: {e}, packet data: {packet_data.hex()}")
            return None
    def _parse_ticker_payload(self, payload):
        """Legacy parsing method - redirects to _parse_ticker_data"""
        try:
            # Convert the payload to a proper packet by adding message type byte
            packet = bytes([2]) + payload
            return self._parse_ticker_data(packet)
        except Exception as e:
            logger.error(f"Error in legacy ticker payload parsing: {e}")
            return None
    
    def _parse_market_update(self, packet_data):
        """Parse market data update packet (message type TYPE_MARKET_UPDATE = 4)
        
        Binary format:
        - Byte 0: Message type (4)
        - Bytes 1-2: Message length
        - Byte 3: Exchange segment
        - Bytes 4-7: Token
        - Bytes 8-11: LTP (float)
        - Bytes 12-15: Volume (int)
        - Bytes 16-19: Total buy quantity (int)
        - Bytes 20-23: VWAP (float)
        - Bytes 24-27: Open price (float)
        - Bytes 28-31: Close price (float)
        - Bytes 32-35: High price (float)
        - Bytes 36-39: Low price (float)
        """
        try:
            if len(packet_data) < 40:  # Need at least 40 bytes for all fields
                logger.warning(f"Market update data too short: {len(packet_data)} bytes")
                return None
                
            # Unpack header and basic fields
            msg_type, msg_len, exchange_code, token = struct.unpack('<BHBI', packet_data[0:8])
            
            # Unpack market update fields - using little-endian float and int
            # Format: <fIIfffff (float, int, int, float, float, float, float, float)
            ltp, volume, total_buy_qty, vwap, open_price, close_price, high_price, low_price = struct.unpack(
                '<fIIfffff', packet_data[8:40])
            
            # Map exchange code to string name
            exch_name = self.EXCHANGE_MAP.get(exchange_code, f'UNK_{exchange_code}')
            
            # Log raw values for debugging
            logger.debug(f"Market Update - Token: {token}, LTP: {ltp}, Volume: {volume}, "
                       f"Open: {open_price}, High: {high_price}, Low: {low_price}, Close: {close_price}")
            
            # Create tick dictionary with OHLC data
            tick = {
                'token': token,
                'instrument_token': token,
                'exchange_segment': exchange_code,
                'exchange': exch_name,
                'last_price': ltp,
                'volume': volume,
                'total_buy_quantity': total_buy_qty,
                'average_price': vwap,
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'ohlc': {
                    'open': open_price,
                    'high': high_price,
                    'low': low_price,
                    'close': close_price
                },
                'mode': 'quote',
                'packet_type': 'market_update'
            }
            
            logger.debug(f"Parsed market update: Token={tick['token']} LTP={tick['last_price']}")
            return tick
            
        except Exception as e:
            logger.error(f"Error parsing market update data: {e}")
            return None
            
    def _parse_market_depth(self, packet_data):
        """Parse market depth data (message type 3)"""
        try:
            # Based on official Dhan client, first byte is message type, the rest is structured data
            if len(packet_data) < 162:  # Expected length for market depth
                logger.warning(f"Market depth data too short: {len(packet_data)} bytes, need at least 162")
                return None
                
            # Skip the first byte (message type)
            data = packet_data[1:]
            
            # Unpack fields according to official client format
            token = struct.unpack('<I', data[0:4])[0]
            exchange_id = data[4]
            if exchange_id == 1:
                exchange = "NSE"
            elif exchange_id == 2:
                exchange = "BSE"
            elif exchange_id == 3:
                exchange = "NFO"
            elif exchange_id == 4:
                exchange = "CDS"
            elif exchange_id == 5:
                exchange = "MCX"
            else:
                exchange = f"UNK_{exchange_id}"
            
            # Parse buy and sell depth levels (5 levels each)
            buy_depth = []
            sell_depth = []
            
            # Parse buy depth (5 levels)
            offset = 7  # Starting after token and exchange
            for i in range(5):
                price = struct.unpack('<f', data[offset:offset+4])[0]
                offset += 4
                quantity = struct.unpack('<I', data[offset:offset+4])[0]
                offset += 4
                orders = struct.unpack('<H', data[offset:offset+2])[0]
                offset += 2
                buy_depth.append({
                    'price': price,
                    'quantity': quantity,
                    'orders': orders
                })
            
            # Parse sell depth (5 levels)
            for i in range(5):
                price = struct.unpack('<f', data[offset:offset+4])[0]
                offset += 4
                quantity = struct.unpack('<I', data[offset:offset+4])[0]
                offset += 4
                orders = struct.unpack('<H', data[offset:offset+2])[0]
                offset += 2
                sell_depth.append({
                    'price': price,
                    'quantity': quantity,
                    'orders': orders
                })
            
            # Create the tick data
            tick = {
                'token': token,
                'instrument_token': token,
                'exchange': exchange,
                'depth': {
                    'buy': buy_depth,
                    'sell': sell_depth
                },
                'mode': 'depth',
                'packet_type': 'market_depth'
            }
            
            logger.debug(f"Parsed market depth data for token {token}")
            return tick
        except Exception as e:
            logger.error(f"Error parsing market depth data: {e}")
            return None
            
    def _parse_quote_data(self, packet_data):
        """Parse quote data (message type TYPE_QUOTE = 17)
        
        Binary format (from Dhan API docs):
        <BHBIfHIfIIIffff - 50 bytes total
        B: Message type (1 byte)
        H: Exchange segment (2 bytes)
        B: Padding (1 byte)
        I: Security ID (4 bytes)
        f: LTP (4 bytes)
        H: LTQ (2 bytes)
        I: LTT (4 bytes)
        f: Avg Price (4 bytes)
        I: Volume (4 bytes)
        I: Total Sell Qty (4 bytes)
        I: Total Buy Qty (4 bytes)
        f: Open (4 bytes)
        f: Close (4 bytes)
        f: High (4 bytes)
        f: Low (4 bytes)
        """
        try:
            if len(packet_data) < 50:  # Minimum length for quote data
                logger.warning(f"Quote data too short: {len(packet_data)} bytes, need at least 50")
                return None
                
            # Unpack all fields at once
            (msg_type, exchange_code, _, token, ltp, ltq, ltt, 
             avg_price, volume, total_sell_qty, total_buy_qty,
             open_price, close_price, high_price, low_price) = struct.unpack('<BHBIfHIfIIIffff', packet_data[:50])
            
            # Map exchange code to exchange name
            exchange_map = {
                0: "IDX_I",
                1: "NSE",
                2: "NFO",
                3: "CDS",
                4: "BSE",
                5: "MCX",
                7: "BSE_CURRENCY",
                8: "BSE_FNO"
            }
            exchange = exchange_map.get(exchange_code, f"UNK_{exchange_code}")
            
            tick = {
                'token': token,
                'instrument_token': token,
                'exchange': exchange,
                'last_price': ltp,
                'last_quantity': ltq,
                'average_price': avg_price,
                'volume': volume,
                'buy_quantity': total_buy_qty,
                'sell_quantity': total_sell_qty,
                'ohlc': {
                    'open': open_price,
                    'high': high_price,
                    'low': low_price,
                    'close': close_price
                },
                'depth': {
                    'buy': [{'price': 0, 'quantity': 0, 'orders': 0}],
                    'sell': [{'price': 0, 'quantity': 0, 'orders': 0}]
                },
                'mode': 'quote',
                'packet_type': 'quote',
                'timestamp': ltt  # Include the timestamp if needed
            }
            
            logger.debug(f"Parsed quote data for token {token}: OHLC=({open_price}, {high_price}, {low_price}, {close_price}), LTP={ltp}")
            return tick
            
            logger.debug(f"Parsed quote data for token {token}: LTP={ltp}")
            return tick
        except Exception as e:
            logger.error(f"Error parsing quote data: {e}")
            return None
    
    def _parse_quote_payload(self, payload):
        """Legacy parsing method - redirects to _parse_quote_data"""
        try:
            # Convert the payload to a proper packet by adding message type byte
            packet = bytes([self.TYPE_QUOTE]) + payload  # TYPE_QUOTE = 17
            return self._parse_quote_data(packet)
        except Exception as e:
            logger.error(f"Error in legacy quote payload parsing: {e}")
            return None
    def _get_price_scale(self, exchange_code: int) -> float:
        """Get price scaling factor for an exchange"""
        # NSE Equity and F&O use 100 as price scale
        if exchange_code in [1, 2]:  # NSE_EQ, NSE_FNO
            return 100.0
        # MCX uses 100 for most commodities
        elif exchange_code == 5:  # MCX_COMM
            return 100.0
        # NSE Currency uses 10000
        elif exchange_code == 3:  # NSE_CURRENCY
            return 10000.0
        # NSE Indices use 100
        elif exchange_code == 0:  # IDX_I
            return 100.0
        # Default to 100 for unknown exchanges
        return 100.0

    def _is_valid_price(self, price: float, exchange_code: int) -> bool:
        """Check if a price level is valid for an exchange"""
        # For indices, 0 is a valid price (market closed)
        if exchange_code == 0:  # IDX_I
            return True
        # For all other exchanges, price must be > 0
        return price > 0

    def _parse_full_data(self, packet_data):
        """Parse message type 8: Full data (combination of ticker + depth)
        Format: <BHBIfHIfIIIIIIffff100s> from Dhan marketfeed documentation
        """
        # Debug the binary packet
        logger.debug(f"Full data packet: {packet_data.hex()}, size: {len(packet_data)} bytes")
        
        # Full packet must be exactly 162 bytes
        if len(packet_data) != 162:
            logger.warning(f"Full data packet wrong size: {len(packet_data)} bytes, expected 162")
            return None
            
        try:
            # Unpack the entire packet according to Dhan's format
            # Format: <BHBIIHIIIIIIIIIIIIII100s>
            # B: message type (1)
            # H: message length (2)
            # B: exchange code (1)
            # I: token (4)
            # f: last traded price (4)
            # H: last traded quantity (2)
            # I: timestamp (4)
            # f: average trade price (4)
            # I: volume (4)
            # I: total buy quantity (4)
            # I: total sell quantity (4)
            # I: open interest (4)
            # I: OI high (4)
            # I: OI low (4)
            # f: open price (4)
            # f: high price (4)
            # f: low price (4)
            # f: close price (4)
            # 100s: market depth data (100)
            # I: net change (4)
            # Format for 162-byte packet (total size breakdown):
            # Header (8): message type(1) + length(2) + exchange(1) + token(4)
            # Market data (14): ltp(4) + ltq(2) + timestamp(4) + atp(4)
            # Volume/OI (24): volume(4) + buy_qty(4) + sell_qty(4) + oi(4) + oi_high(4) + oi_low(4)
            # OHLC (16): open(4) + high(4) + low(4) + close(4)
            # Depth data (100): 5 levels * 20 bytes per level
            # Total: 162 bytes
            packet_format = '<BHBIfHIfIIIIIIffff100s'
            
            (
                msg_type, msg_len, exchange_code, token, ltp, ltq,
                timestamp, atp, volume, total_buy_qty, total_sell_qty,
                oi_val, oi_high, oi_low, open_price, high_price,
                low_price, close_price, depth_data
            ) = struct.unpack(packet_format, packet_data)
            
            logger.debug(f"Full packet unpacked: msg_type={msg_type}, exchange={exchange_code}, token={token}, ltp={ltp}")
            
            # Get price scaling factor for this exchange
            price_scale = self._get_price_scale(exchange_code) # Dhan prices are scaled
            exch_name = self.EXCHANGE_MAP.get(exchange_code, 'UNKNOWN')
            
            # Scale all price values
            ltp = round(ltp , 2) 
            open_price = round(open_price , 2) 
            high_price = round(high_price , 2) 
            low_price = round(low_price , 2) 
            close_price = round(close_price , 2) 
            atp = round(atp , 2) 
            
            # Debug exchange and packet info
            logger.debug(f"Processing {exch_name} packet with price scale {price_scale}")
            logger.debug(f"Header values: token={token}, ltp={ltp}, oi={oi_val}, ltq={ltq}, timestamp={timestamp}")
            depth = {
                'buy': [],
                'sell': []
            }
            
            # Each depth level is 20 bytes: <IIHHII> per level
            # I: bid quantity (4)
            # I: ask quantity (4)
            # H: bid orders (2)
            # H: ask orders (2)
            # I: bid price (4)
            # I: ask price (4)
            packet_format = '<IIHHff'
            packet_size = struct.calcsize(packet_format)
            
            # Debug raw depth data
            logger.debug(f"Raw depth data ({len(depth_data)} bytes): {depth_data.hex()}")
            
            for i in range(5):  # 5 depth levels
                offset = i * packet_size
                end_offset = offset + packet_size
                
                if end_offset > len(depth_data):
                    logger.error(f"Not enough data for level {i} (need {end_offset} bytes, have {len(depth_data)})")
                    break
                    
                level_data = depth_data[offset:end_offset]
                logger.debug(f"Level {i} raw bytes: {level_data.hex()}")
                
                try:
                    bid_qty, ask_qty, bid_orders, ask_orders, bid_price, ask_price = struct.unpack(
                        packet_format,
                        level_data
                    )
                    logger.debug(f"Level {i} raw: qty={bid_qty}/{ask_qty} orders={bid_orders}/{ask_orders} price={bid_price}/{ask_price}")
                except Exception as e:
                    logger.error(f"Error unpacking depth level {i}: {e}, data: {level_data.hex()}")
                    continue
                
                # Scale prices - all prices are integers that need to be scaled
                
                bid_price = round(bid_price , 2)
                ask_price = round(ask_price , 2)
                
                logger.debug(f"Level {i} scaled: bid={bid_price}, ask={ask_price}")
                
                # Add bid level if valid
                if self._is_valid_price(bid_price * price_scale, exchange_code):
                    depth['buy'].append({
                        'price': bid_price,
                        'quantity': bid_qty,
                        'orders': bid_orders
                    })
                    logger.debug(f"Added buy level {i}: price={bid_price}, qty={bid_qty}, orders={bid_orders}")
                
                # Add ask level if valid
                if self._is_valid_price(ask_price * price_scale, exchange_code):
                    depth['sell'].append({
                        'price': ask_price,
                        'quantity': ask_qty,
                        'orders': ask_orders
                    })
                    logger.debug(f"Added sell level {i}: price={ask_price}, qty={ask_qty}, orders={ask_orders}")
            
            tick = {
                'instrument_token': token,
                'exchange': self.EXCHANGE_MAP.get(exchange_code, 'NSE_EQ'),
                'last_price': ltp,
                'last_quantity': ltq,
                'average_price': atp,
                'volume': total_buy_qty + total_sell_qty,
                'oi': oi_val,
                'ohlc': {
                    'open': open_price,  # Already scaled above
                    'high': high_price,
                    'low': low_price,
                    'close': close_price
                },
                'depth': depth,
                'total_buy_quantity': total_buy_qty,
                'total_sell_quantity': total_sell_qty,
                'timestamp': datetime.fromtimestamp(timestamp).isoformat(),
                'mode': 'depth'
            }
            
            logger.debug(f"Parsed full data for token {tick['instrument_token']}: {len(depth['buy'])} buy levels, {len(depth['sell'])} sell levels")
            # Return full tick data with depth
            return tick if (depth['buy'] or depth['sell']) else None
            
        except Exception as e:
            logger.error(f"Error parsing full data: {e}")
            logger.error(f"Packet data (hex): {packet_data.hex()}")
            return None
    
    def _parse_full_payload(self, payload):
        """Legacy parsing method - redirects to _parse_full_data"""
        try:
            # Convert the payload to a proper packet by adding message type byte
            packet = bytes([8]) + payload
            return self._parse_full_data(packet)
        except Exception as e:
            logger.error(f"Error in legacy full payload parsing: {e}")
            return None
    
    def _create_subscription_packet(self, token, mode=MODE_FULL):
        """Create a subscription packet for Dhan V2 API"""
        try:
            # Get exchange code for this token
            exchange_code = None
            for token_info in self.instruments.values():
                if token_info['token'] == token:
                    exchange_code = token_info['exchange_code']
                    break
                    
            if exchange_code is None:
                logger.warning(f"No exchange code found for token {token}, using default 1 (NSE_EQ)")
                exchange_code = 1  # Default to NSE_EQ
                
            # Map subscription mode to request code
            if mode == self.MODE_LTP:
                request_code = self.TYPE_TICKER      # 15 - LTP data
            elif mode == self.MODE_QUOTE:
                request_code = self.TYPE_QUOTE       # 17 - Quote/marketdata
            elif mode == self.MODE_FULL:
                request_code = self.TYPE_DEPTH       # 21 - Full market depth
            else:
                logger.error(f"Invalid subscription mode: {mode}")
                return None
                
            # Create subscription packet according to Dhan V2 format
            packet = {
                "RequestCode": request_code,
                "InstrumentCount": 1,
                "InstrumentList": [
                    {
                        "ExchangeSegment": self.get_exchange_segment(exchange_code),
                        "SecurityId": str(token)
                    }
                ]
            }
            
            logger.debug(f"Created subscription packet: {packet}")
            return packet
            
        except Exception as e:
            logger.error(f"Error creating subscription packet: {e}")
            return None
        
    def _parse_oi_data(self, packet_data):
        """
        Parse message type 5: Open Interest data
        Format based on Dhan's marketfeed client
        """
        # Debug the binary packet
        logger.debug(f"OI data packet: {packet_data.hex()}, size: {len(packet_data)} bytes")
        
        # Adjust minimum size
        if len(packet_data) < 13:  # At minimum need type(1) + token(4) + oi(4) + timestamp
            logger.warning(f"OI data packet too small: {len(packet_data)} bytes")
            return None
            
        try:
            # Unpack binary data - format: type(1) + instrument_token(4) + oi(4) + timestamp(8)
            msg_type, token, oi = struct.unpack('<BLL', packet_data[:9])
            timestamp, = struct.unpack('<Q', packet_data[9:17])
            
            tick = {
                'token': token,
                'oi': oi,
                'timestamp': datetime.fromtimestamp(timestamp / 1000).isoformat(),
            }
            
            return tick
            
        except Exception as e:
            logger.error(f"Error parsing OI data: {e}")
            return None

    def subscribe_tokens(self, tokens: List[int], mode: str = MODE_FULL, exchange_codes: Optional[Dict[int, int]] = None) -> bool:
        """
        Subscribe to a list of tokens with specified mode and exchange codes.
        
        Args:
            tokens (List[int]): List of tokens to subscribe to
            mode (str): Subscription mode - 'ltp', 'marketdata', or 'depth'
            exchange_codes (Dict[int, int], optional): Map of token to exchange code.
                If not provided, defaults to NSE_EQ (1)
                
        Returns:
            bool: True if subscription was successful, False otherwise
        """
        if not self.connected or not self.ws:
            logger.error("Cannot subscribe - WebSocket not connected")
            return False
            
        try:
            # Validate mode
            if mode not in [self.MODE_LTP, self.MODE_QUOTE, self.MODE_FULL]:
                logger.error(f"Invalid mode {mode}")
                return False
                
            # Map mode to request code
            if mode == self.MODE_LTP:
                request_code = self.REQUEST_CODE_TICKER
            elif mode == self.MODE_QUOTE:
                request_code = self.REQUEST_CODE_QUOTE
            else:  # MODE_FULL/depth
                request_code = self.REQUEST_CODE_FULL
                
            # Create instrument list with exchange codes
            instrument_list = []
            for token in tokens:
                # Get exchange code from map or default to NSE_EQ (1)
                exchange_code = exchange_codes.get(token, 1) if exchange_codes else 1
                exchange_segment = self.get_exchange_segment(exchange_code)
                
                # Log subscription details for each token
                logger.info(f"Subscribing token {token} with exchange_code {exchange_code} ({exchange_segment}) in mode {mode}")
                
                instrument_list.append({
                    "ExchangeSegment": exchange_segment,
                    "SecurityId": str(token)
                })
                
                # Track subscribed instruments
                with self.lock:
                    self.instruments[token] = {
                        "mode": mode,
                        "exchange_code": exchange_code,
                        "exchange_segment": exchange_segment
                    }
            
            # Create subscription packet
            packet = {
                "RequestCode": request_code,
                "InstrumentCount": len(tokens),
                "InstrumentList": instrument_list
            }
            
            # Send subscription request
            if self.ws and self.connected:
                # Log full subscription packet for debugging
                logger.debug(f"Sending subscription packet: {json.dumps(packet, indent=2)}")
                
                asyncio.run_coroutine_threadsafe(
                    self.ws.send(json.dumps(packet)),
                    self.loop
                )
                
                # Log subscription summary
                exchange_summary = {}
                for instr in instrument_list:
                    exch = instr['ExchangeSegment']
                    exchange_summary[exch] = exchange_summary.get(exch, 0) + 1
                logger.info(f"Subscribed to {len(tokens)} tokens in mode {mode}. Exchange distribution: {exchange_summary}")
                return True
            else:
                logger.error("WebSocket not connected for subscription")
                return False
                
        except Exception as e:
            logger.error(f"Error subscribing to tokens: {e}")
            return False
            
    def _parse_quote_data(self, packet_data):
        """Parse quote data (message type TYPE_QUOTE = 17)"""
        try:
            # Based on official Dhan client, first byte is message type (17), the rest is structured data
            if len(packet_data) < 51:  # Expected minimum length for quote data
                logger.warning(f"Quote data too short: {len(packet_data)} bytes, need at least 51")
                return None
                
            # Skip the first byte (message type)
            data = packet_data[1:]
            
            # Unpack 50 bytes of quote data
            # Format: <BHBIfHIfIIIffff
            # Breakdown:
            # B = 1 byte (msg subtype)
            # H = 2 bytes (message length)
            # B = 1 byte (exchange segment)
            # I = 4 bytes (security id / token)
            # f = 4 bytes (LTP)
            # H = 2 bytes (LTQ)
            # I = 4 bytes (LTT)
            # f = 4 bytes (avg price)
            # I = 4 bytes (volume)
            # I = 4 bytes (total sell qty)
            # I = 4 bytes (total buy qty)
            # f = 4 bytes (open)
            # f = 4 bytes (close)
            # f = 4 bytes (high)
            # f = 4 bytes (low)
            
            unpacked = struct.unpack('<BHBIfHIfIIIffff', data[0:50])
            
            # Get exchange name and price scale
            exchange_code = unpacked[2]
            exch_name = self.EXCHANGE_MAP.get(exchange_code, 'UNKNOWN')
            
            # Create standardized tick format
            tick = {
                'token': unpacked[3],
                'instrument_token': unpacked[3],
                'exchange_segment': exchange_code,
                'exchange': exch_name,
                'last_price': round(unpacked[4], 2),
                'last_quantity': unpacked[5],
                'average_price': round(unpacked[7], 2),
                'volume': unpacked[8],
                'buy_quantity': unpacked[10],
                'sell_quantity': unpacked[9],
                'ohlc': {
                    'open': round(unpacked[11], 2),
                    'high': round(unpacked[13], 2),
                    'low': round(unpacked[14], 2),
                    'close': round(unpacked[12], 2),
                },
                'depth': {
                    'buy': [],  # not provided in quote packet
                    'sell': []  # not provided in quote packet
                },
                'mode': 'quote',
                'packet_type': 'quote',
                'last_trade_time': int(unpacked[6])  # Unix timestamp
            }
            
            logger.debug(f"Parsed quote data: Token={tick['token']} LTP={tick['last_price']}")
            return tick
            
        except Exception as e:
            logger.error(f"Error parsing quote data: {e}")
            return None
            
    def _parse_prev_close(self, packet_data):
        """
        Parse message type 6: Previous close
        Format based on Dhan's marketfeed client
        """
        # Debug the binary packet
        logger.debug(f"Previous close packet: {packet_data.hex()}, size: {len(packet_data)} bytes")
        
        # Adjust minimum size check
        if len(packet_data) < 13:  # At minimum we need type + token + prev_close + some timestamp
            logger.warning(f"Previous close packet too small: {len(packet_data)} bytes")
            return None
            
        try:
            # Unpack binary data based on actual packet size
            msg_type, token, prev_close = struct.unpack('<BLL', packet_data[:9])
            
            # Handle different timestamp formats based on packet size
            if len(packet_data) >= 17:  # Full 8-byte timestamp
                timestamp, = struct.unpack('<Q', packet_data[9:17])
            elif len(packet_data) >= 13:  # 4-byte timestamp
                timestamp = int.from_bytes(packet_data[9:13], byteorder='little')
            else:
                timestamp = int(time.time() * 1000)  # Use current time if no timestamp
            
            tick = {
                'token': token,
                'prev_close': prev_close / 100.0,
                'timestamp': datetime.fromtimestamp(timestamp / 1000).isoformat(),
            }
            
            return tick
            
        except Exception as e:
            logger.error(f"Error parsing previous close: {e}")
            return None

    def _parse_status(self, packet_data):
        """
        Parse message type 7: Status message
        Format based on Dhan's marketfeed client
        """
        # Debug the binary packet
        logger.debug(f"Status message packet: {packet_data.hex()}, size: {len(packet_data)} bytes")
        
        # Adjust minimum size
        if len(packet_data) < 13:  # At minimum need type(1) + token(4) + status(4) + some data
            logger.warning(f"Status message packet too small: {len(packet_data)} bytes")
            return None
            
        try:
            # Unpack binary data - format depends on Dhan's specification
            msg_type, token, status_code = struct.unpack('<BLL', packet_data[:9])
            timestamp, = struct.unpack('<Q', packet_data[9:17])
            
            tick = {
                'token': token,
                'status': status_code,
                'timestamp': datetime.fromtimestamp(timestamp / 1000).isoformat(),
            }
            
            return tick
            
        except Exception as e:
            logger.error(f"Error parsing status message: {e}")
            return None

    def _parse_disconnect(self, packet_data):
        """
        Parse message type 50: Disconnect message from server
        Format based on Dhan's marketfeed client
        """
        try:
            # Log the disconnect message
            logger.warning(f"Server sent disconnect message: {packet_data.hex()}")
            
            # Trigger reconnection
            asyncio.create_task(self._reconnect())
            
            # No tick data to return for this message type
            return None
            
        except Exception as e:
            logger.error(f"Error handling disconnect message: {e}")
            return None

    def get_exchange_segment(self, exchange_code):
        """Get exchange segment string from code"""
        return self.EXCHANGE_MAP.get(exchange_code, 'NSE_EQ')
        
    def unsubscribe(self, token, exchange_code=1):
        """Unsubscribe from a token"""
        try:
            if not self.connected or not self.ws:
                logger.error("Cannot unsubscribe - WebSocket not connected")
                return False
                
            # Create unsubscribe packet
            packet = {
                "RequestCode": 0,  # 0 = Unsubscribe
                "InstrumentCount": 1,
                "InstrumentList": [
                    {
                        "ExchangeSegment": self.get_exchange_segment(exchange_code),
                        "SecurityId": str(token)
                    }
                ]
            }
            
            # Send unsubscribe request
            asyncio.run_coroutine_threadsafe(
                self.ws.send(json.dumps(packet)),
                self.loop
            )
            
            # Remove from instruments dict
            with self.lock:
                if token in self.instruments:
                    del self.instruments[token]
                    
            return True
            
        except Exception as e:
            logger.error(f"Error unsubscribing from token {token}: {e}")
            return False
            
    def stop(self):
        """Stop the WebSocket client"""
        try:
            self.running = False
            if self.ws:
                asyncio.run_coroutine_threadsafe(
                    self.ws.close(),
                    self.loop
                )
            if self.thread:
                self.thread.join()
        except Exception as e:
            logger.error(f"Error stopping WebSocket client: {e}")