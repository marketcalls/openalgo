"""
Complete Dhan WebSocket client wrapper for OpenAlgo.
Based on Dhan V2 API documentation with proper binary packet parsing.
"""
import os
import asyncio
import json
import logging
import struct
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
    TYPE_TICKER = 2      # Ticker data
    TYPE_QUOTE = 6       # Market quote data
    TYPE_DEPTH = 7       # Market depth data
    TYPE_OI = 9          # Open Interest data
    TYPE_PREV_CLOSE = 10  # Previous day close price
    TYPE_DISCONNECT = 0   # Disconnect notification
    
    # WebSocket URL constants
    MARKET_FEED_WSS = "wss://api-feed.dhan.co"
    
    # Mode constants for V2 API
    MODE_LTP = "ltp"             # LTP only
    MODE_QUOTE = "marketdata"    # Quote mode (includes price, volume, OHLC)
    MODE_FULL = "depth"          # Full/Depth mode (includes market depth)
    
    # Request code constants for Dhan API (from marketfeed_dhan.txt)
    REQUEST_CODE_TICKER = 15  # For LTP
    REQUEST_CODE_QUOTE = 17   # For Quote/marketdata
    REQUEST_CODE_DEPTH = 19   # For Depth
    REQUEST_CODE_FULL = 21    # For Full market data
    
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
                msg_type = packet_data[offset]  # Feed Response Code
                
                # Extract message length from bytes 2-3
                msg_length = struct.unpack('<H', packet_data[offset+1:offset+3])[0]  # Message Length (2 bytes)
                
                # Extract exchange segment and token
                exchange_segment = packet_data[offset+3]  # Exchange Segment
                token = struct.unpack('<I', packet_data[offset+4:offset+8])[0]  # Security ID/token (4 bytes)
                
                # Debug token extraction
                logger.info(f"TICK TOKEN DEBUG: Extracted token={token} (0x{token:x}), exchange_code={exchange_segment}")
                
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
                if msg_type == self.TYPE_TICKER:
                    logger.info(f"TICK TOKEN DEBUG: Raw token={token}, origin=unknown, payload_size={len(message)} bytes")
                    ticks = self._parse_ticker_data(message)
                    if ticks and self.on_ticks:
                        token_info = []
                        for tick in ticks:
                            if 'token' in tick:
                                token_info.append(f"{tick['token']} ({type(tick['token']).__name__})")
                        logger.info(f"Parsed ticker packet: {len(ticks)} ticks with tokens: {token_info}")
                        self.on_ticks(ticks)
                elif msg_type == 7:  # ACK packet - likely culprit for previous TOKEN MAPPING FAILURE warnings
                    logger.debug(f"Received ACK packet for token {token}, exchange {exchange_segment}")
                    # Skip processing these as ticks; they contain acknowledgments, not market data
                else:
                    # Use the general parser for other message types
                    tick = self._parse_dhan_binary_packet(message)
                    if tick:
                        # Convert to list if not already
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
        """Parse ticker data (message type 2) - Based on official Dhan implementation"""
        try:
            # Check if we have enough data for the ticker format
            if len(packet_data) < 16:  # Minimum length per official client
                logger.warning(f"Ticker data packet too small: {len(packet_data)} bytes")
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
            
        packet_type = packet_data[0]
        
        # Log the binary packet for debugging
        logger.debug(f"Binary packet received: type={packet_type}, size={len(packet_data)}, hex={packet_data.hex()}")
        
        try:
            if packet_type == 2:  # Ticker data (LTP)
                return self._parse_ticker_data(packet_data)
                
            elif packet_type == 3:  # Market depth
                return self._parse_market_depth(packet_data)
                
            elif packet_type == 4:  # Quote data (OHLC)
                return self._parse_quote_data(packet_data)
                
            elif packet_type == 5:  # OI data
                return self._parse_oi_data(packet_data)
                
            elif packet_type == 6:  # Previous close
                return self._parse_prev_close(packet_data)
                
            elif packet_type == 7:  # Status message
                return self._parse_status(packet_data)
                
            elif packet_type == 8:  # Full data (ticker + depth)
                return self._parse_full_data(packet_data)
                
            elif packet_type == 50:  # Disconnect message
                return self._parse_disconnect(packet_data)
                
            else:
                logger.warning(f"Unknown packet type: {packet_type} in packet: {packet_data.hex()}")
                return None
                
        except Exception as e:
            logger.warning(f"No ticks parsed from binary packet: {e}")
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
        """Parse quote data (message type 4)"""
        try:
            # Based on official Dhan client, first byte is message type, the rest is structured data
            if len(packet_data) < 112:  # Expected minimum length for quote data
                logger.warning(f"Quote data too short: {len(packet_data)} bytes, need at least 112")
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
            
            ltp = struct.unpack('<f', data[7:11])[0]
            last_quantity = struct.unpack('<I', data[11:15])[0]
            avg_price = struct.unpack('<f', data[23:27])[0]
            volume = struct.unpack('<Q', data[15:23])[0]
            bid_price = struct.unpack('<f', data[67:71])[0]
            bid_quantity = struct.unpack('<I', data[71:75])[0]
            ask_price = struct.unpack('<f', data[75:79])[0]
            ask_quantity = struct.unpack('<I', data[79:83])[0]
            open_price = struct.unpack('<f', data[27:31])[0]
            high_price = struct.unpack('<f', data[31:35])[0]
            low_price = struct.unpack('<f', data[35:39])[0]
            close_price = struct.unpack('<f', data[39:43])[0]
            
            tick = {
                'token': token,
                'instrument_token': token,
                'exchange': exchange,
                'last_price': ltp,
                'last_quantity': last_quantity,
                'average_price': avg_price,
                'volume': volume,
                'buy_quantity': bid_quantity,
                'sell_quantity': ask_quantity,
                'ohlc': {
                    'open': open_price,
                    'high': high_price,
                    'low': low_price,
                    'close': close_price
                },
                'depth': {
                    'buy': [{'price': bid_price, 'quantity': bid_quantity, 'orders': 0}],
                    'sell': [{'price': ask_price, 'quantity': ask_quantity, 'orders': 0}]
                },
                'mode': 'quote',
                'packet_type': 'quote'
            }
            
            logger.debug(f"Parsed quote data for token {token}: LTP={ltp}")
            return tick
        except Exception as e:
            logger.error(f"Error parsing quote data: {e}")
            return None
    
    def _parse_quote_payload(self, payload):
        """Legacy parsing method - redirects to _parse_quote_data"""
        try:
            # Convert the payload to a proper packet by adding message type byte
            packet = bytes([4]) + payload
            return self._parse_quote_data(packet)
        except Exception as e:
            logger.error(f"Error in legacy quote payload parsing: {e}")
            return None
    
    def _parse_full_data(self, packet_data):
        """Parse full data (message type 8)"""
        try:
            # Based on official Dhan client, this combines ticker, depth, and additional data
            if len(packet_data) < 162:  # Combined expected length
                logger.warning(f"Full data too short: {len(packet_data)} bytes, need at least 162")
                return None
                
            # First parse the market depth (it contains most fields anyway)
            depth_tick = self._parse_market_depth(bytes([3]) + packet_data[1:])  # Change first byte to 3 for depth
            if not depth_tick:
                return None
                
            # Then parse additional fields from the ticker format
            ticker_tick = self._parse_ticker_data(bytes([2]) + packet_data[1:])  # Change first byte to 2 for ticker
            
            # Combine both ticks into one comprehensive tick
            if ticker_tick:
                depth_tick.update({
                    'last_price': ticker_tick.get('last_price'),
                    'last_quantity': ticker_tick.get('last_quantity'),
                    'average_price': ticker_tick.get('average_price'),
                    'volume': ticker_tick.get('volume'),
                    'ohlc': ticker_tick.get('ohlc'),
                    'mode': 'full',
                    'packet_type': 'full'
                })
            
            logger.debug(f"Parsed full data for token {depth_tick['instrument_token']}")
            return depth_tick
        except Exception as e:
            logger.error(f"Error parsing full data: {e}")
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
    
    def _parse_oi_data(self, packet_data):
        """Parse open interest data (message type 5)"""
        try:
            # Based on official Dhan client format
            if len(packet_data) < 16:  # Basic length for OI data
                logger.warning(f"OI data too short: {len(packet_data)} bytes, need at least 16")
                return None
                
            # Skip the first byte (message type)
            data = packet_data[1:]
            
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
                
            oi = struct.unpack('<I', data[7:11])[0]
            
            tick = {
                'token': token,
                'instrument_token': token,
                'exchange': exchange,
                'oi': oi,
                'mode': 'oi',
                'packet_type': 'open_interest'
            }
            
            logger.debug(f"Parsed OI data for token {token}: OI={oi}")
            return tick
        except Exception as e:
            logger.error(f"Error parsing OI data: {e}")
            return None
    
    def _parse_prev_close(self, packet_data):
        """Parse previous close data (message type 6)"""
        try:
            # Based on official Dhan client format
            if len(packet_data) < 16:  # Basic length for prev close data
                logger.warning(f"Previous close data too short: {len(packet_data)} bytes")
                return None
                
            # Skip the first byte (message type)
            data = packet_data[1:]
            
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
                
            prev_close = struct.unpack('<f', data[7:11])[0]
            
            tick = {
                'token': token,
                'instrument_token': token,
                'exchange': exchange,
                'ohlc': {
                    'close': prev_close
                },
                'mode': 'prev_close',
                'packet_type': 'prev_close'
            }
            
            logger.debug(f"Parsed previous close data for token {token}: prev_close={prev_close}")
            return tick
        except Exception as e:
            logger.error(f"Error parsing previous close data: {e}")
            return None
    
    def _parse_status(self, packet_data):
        """Parse status data (message type 7)"""
        try:
            # This message type indicates status information
            if len(packet_data) < 8:  # Minimum expected length
                logger.warning(f"Status data too short: {len(packet_data)} bytes")
                return None
                
            # Skip the first byte (message type)
            data = packet_data[1:]
            
            token = struct.unpack('<I', data[0:4])[0]
            status = data[4]
            
            tick = {
                'token': token,
                'instrument_token': token,
                'status': status,
                'mode': 'status',
                'packet_type': 'status'
            }
            
            logger.debug(f"Parsed status data for token {token}: status={status}")
            return tick
        except Exception as e:
            logger.error(f"Error parsing status data: {e}")
            return None
    
    def _parse_disconnect(self, packet_data):
        """Parse disconnect message (message type 50)"""
        try:
            # This message type indicates a disconnect request from server
            logger.warning("Received disconnect signal from Dhan server")
            
            # Return a special tick to indicate disconnect
            tick = {
                'mode': 'disconnect',
                'packet_type': 'disconnect',
                'message': 'Server requested disconnect'
            }
            
            # Trigger reconnection process
            asyncio.create_task(self._reconnect())
            
            return tick
        except Exception as e:
            logger.error(f"Error parsing disconnect message: {e}")
            return None
            
    def _parse_generic_payload(self, payload):
        """Parse generic payload when format is unknown"""
        try:
            if len(payload) < 8:
                return None
            
            # Try to extract basic fields
            token = struct.unpack_from('<I', payload, 0)[0]
            
            # Try to find a price value
            price = 0.0
            if len(payload) >= 8:
                try:
                    price = struct.unpack_from('<f', payload, 4)[0]
                except:
                    price = 0.0
            
            tick = {
                'token': token,
                'instrument_token': token,
                'last_price': price,
                'timestamp': int(time.time()),
                'packet_type': 'generic',
                'raw_length': len(payload)
            }
            
            logger.debug(f"Parsed generic: token={token}, price={price}")
            return tick
            
        except Exception as e:
            logger.error(f"Error parsing generic payload: {e}")
            return None
    
    async def _resubscribe(self):
        """Resubscribe to all instruments after reconnection"""
        try:
            for key, details in self.instruments.items():
                logger.debug(f"Resubscribing to {key}")
                packet = self._create_subscription_packet(
                    details["token"], 
                    mode=details.get("mode", self.MODE_FULL)
                )
                await self._send_packet(packet)
        except Exception as e:
            logger.error(f"Error resubscribing: {e}")
            return False
        return True
        
    async def _send_packet(self, packet):
        """Send a packet to the WebSocket server"""
        if not self.ws or not self.connected:
            logger.error("Cannot send packet: WebSocket not connected")
            return False
            
        try:
            await self.ws.send(packet)
            logger.debug(f"Sent packet: {packet}")
            return True
        except Exception as e:
            logger.error(f"Error sending packet: {e}")
            return False
            
    def subscribe(self, instrument_token, exchange, symbol, mode=MODE_FULL):
        """Subscribe to a symbol"""
        with self.lock:
            key = f"{exchange}:{symbol}"
            if key in self.instruments:
                logger.debug(f"Already subscribed to {key}")
                return True
                
            self.instruments[key] = {
                "token": instrument_token,
                "mode": mode,  # Store the actual mode provided
                "exchange": exchange,
                "symbol": symbol
            }
            
            if not self.connected:
                logger.warning(f"Not connected to dhan WebSocket, {key} added to subscription queue")
                return False
                
            try:
                # Ensure we use the mode parameter passed to this method
                packet = self._create_subscription_packet(instrument_token, mode=mode)
                logger.info(f"Sending subscription request for {key} with token {instrument_token} in mode {mode}")
                asyncio.run_coroutine_threadsafe(self._send_packet(packet), self.loop)
                return True
            except Exception as e:
                logger.error(f"Error subscribing to {key}: {e}")
                return False
    
    def subscribe_tokens(self, tokens, mode=MODE_FULL, exchange_codes=None):
        """Subscribe to a list of token IDs
        
        Args:
            tokens (list or int): Token ID(s) to subscribe to
            mode (str): Subscription mode - one of the MODE_* constants (MODE_LTP, MODE_QUOTE, MODE_FULL)
            exchange_codes (dict, optional): Dictionary mapping token -> exchange_code
                                            e.g., {2885: 1, 26000: 2, 26009: 0}
        """
        success = True
        if not isinstance(tokens, list):
            tokens = [tokens]
            
        if exchange_codes is None:
            exchange_codes = {}
            
        # Log which mode is being used for subscription
        if mode == self.MODE_LTP:
            logger.info(f"Subscribing to {len(tokens)} token(s) in LTP mode")
        elif mode == self.MODE_QUOTE:
            logger.info(f"Subscribing to {len(tokens)} token(s) in QUOTE mode")
        elif mode == self.MODE_FULL:
            logger.info(f"Subscribing to {len(tokens)} token(s) in FULL/DEPTH mode")
        else:
            logger.warning(f"Unknown mode {mode}, defaulting to FULL mode")
            
        for token in tokens:
            try:
                # Get exchange code if available, default to NSE_EQ (code 1)
                exchange_code = exchange_codes.get(token, 1)
                
                # Store exchange code information with the token
                key = str(token)
                if key not in self.instruments:
                    self.instruments[key] = {}
                self.instruments[key]['exchange_code'] = exchange_code
                self.instruments[key]['mode'] = mode  # Store the mode for this token
                
                # Display in logs
                exchange_segment = self.get_exchange_segment(exchange_code)
                logger.info(f"Token {token} assigned exchange code {exchange_code} ({exchange_segment}) with mode '{mode}'")
                
                exchange = "UNKNOWN"  # Still kept for backward compatibility
                symbol = f"TOKEN_{token}"
                # Pass the mode parameter to the subscribe method
                result = self.subscribe(token, exchange, symbol, mode=mode)
                if not result:
                    success = False
            except Exception as e:
                logger.error(f"Error subscribing to token {token}: {e}")
                success = False
                
        return success
    
    def unsubscribe(self, instrument_token, exchange=None, symbol=None):
        """Unsubscribe from a symbol"""
        with self.lock:
            if exchange and symbol:
                key = f"{exchange}:{symbol}"
                if key not in self.instruments:
                    logger.debug(f"Not subscribed to {key}")
                    return True
                    
                try:
                    packet = self._create_unsubscription_packet(instrument_token)
                    logger.debug(f"Sending unsubscription request for {key}")
                    asyncio.run_coroutine_threadsafe(self._send_packet(packet), self.loop)
                    del self.instruments[key]
                    return True
                except Exception as e:
                    logger.error(f"Error unsubscribing from {key}: {e}")
                    return False
            else:
                try:
                    packet = self._create_unsubscription_packet(instrument_token)
                    logger.debug(f"Sending unsubscription request for token {instrument_token}")
                    asyncio.run_coroutine_threadsafe(self._send_packet(packet), self.loop)
                    
                    keys_to_remove = []
                    for key, details in self.instruments.items():
                        if details.get("token") == instrument_token:
                            keys_to_remove.append(key)
                    
                    for key in keys_to_remove:
                        del self.instruments[key]
                        
                    return True
                except Exception as e:
                    logger.error(f"Error unsubscribing from token {instrument_token}: {e}")
                    return False
    
    def get_exchange_segment(self, exchange_code):
        """Convert numeric exchange code to string representation as per Dhan's marketfeed client"""
        exchange_map = {
            0: "IDX_I",
            1: "NSE_EQ", 
            2: "NSE_FNO",
            3: "NSE_CURRENCY",
            4: "BSE_EQ",
            5: "MCX_COMM",
            7: "BSE_CURRENCY", 
            8: "BSE_FNO"
        }
        return exchange_map.get(exchange_code, str(exchange_code))
        
    def _create_subscription_packet(self, token, mode=MODE_FULL):
        """Create a subscription packet for Dhan V2 API"""
        # Get exchange segment from token mapping if available
        exchange_segment = "NSE_EQ"  # Default
        
        # Check if this token is in the instruments dictionary
        if str(token) in self.instruments:
            exchange_code = self.instruments[str(token)].get('exchange_code', 1)  # Default to NSE_EQ (code 1)
            exchange_segment = self.get_exchange_segment(exchange_code)
            logger.info(f"Using exchange segment {exchange_segment} for token {token}")
        else:
            logger.warning(f"No exchange info for token {token}, defaulting to NSE_EQ")
        
        # Map mode to request code based on Dhan's API documentation
        request_code = self.REQUEST_CODE_TICKER  # Default to ticker (LTP)
        
        if mode == self.MODE_LTP:
            # For LTP mode, use Ticker request code (15)
            request_code = self.REQUEST_CODE_TICKER
            logger.info(f"Using LTP/Ticker mode (code {request_code}) for token {token}")
        elif mode == self.MODE_QUOTE:
            # For Quote mode, use Quote request code (17)
            request_code = self.REQUEST_CODE_QUOTE
            logger.info(f"Using QUOTE mode (code {request_code}) for token {token}")
        elif mode == self.MODE_FULL:
            # For Full/Depth mode, use Depth request code (19)
            # Note: Using DEPTH, not FULL (21) as that might be for a different purpose
            request_code = self.REQUEST_CODE_DEPTH
            logger.info(f"Using DEPTH mode (code {request_code}) for token {token}")
        else:
            logger.warning(f"Unknown mode {mode}, defaulting to LTP/Ticker subscription (code {request_code})")
            
        # Dhan V2 subscription format with correct request code
        packet = {
            "RequestCode": request_code,  # Use the request code based on mode
            "InstrumentCount": 1,
            "InstrumentList": [
                {
                    "ExchangeSegment": exchange_segment,
                    "SecurityId": str(token)
                }
            ]
        }
        return json.dumps(packet)
        
    def _create_unsubscription_packet(self, token):
        """Create an unsubscription packet for Dhan V2 API"""
        # Get exchange segment from token mapping if available
        exchange_segment = "NSE_EQ"  # Default
        
        # Check if this token is in the instruments dictionary
        if str(token) in self.instruments:
            exchange_code = self.instruments[str(token)].get('exchange_code', 1)  # Default to NSE_EQ (code 1)
            exchange_segment = self.get_exchange_segment(exchange_code)
            logger.info(f"Using exchange segment {exchange_segment} for unsubscribe token {token}")
        else:
            logger.warning(f"No exchange info for unsubscribe token {token}, defaulting to NSE_EQ")
            
        packet = {
            "RequestCode": 16,
            "InstrumentCount": 1,
            "InstrumentList": [
                {
                    "ExchangeSegment": exchange_segment,
                    "SecurityId": str(token)
                }
            ]
        }
        return json.dumps(packet)
    
    def stop(self):
        """Stop the WebSocket client"""
        logger.info("Stopping WebSocket client")
        self.running = False
        
        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._close_connection(), self.loop)
            except Exception as e:
                logger.error(f"Error signaling loop to stop: {e}")
            
        if self.thread and self.thread.is_alive():
            try:
                self.thread.join(timeout=5.0)
                if self.thread.is_alive():
                    logger.warning("WebSocket thread still alive after timeout")
            except Exception as e:
                logger.error(f"Error stopping WebSocket client: {e}")
        
        self.connected = False
        logger.info("WebSocket client stopped")
        
    def _parse_ticker_data(self, packet_data):
        """
        Parse message type 2: Ticker data (LTP)
        Format based on Dhan's marketfeed client
        """
        # Debug the binary packet in hex format for analysis
        logger.debug(f"Ticker data packet: {packet_data.hex()}, size: {len(packet_data)} bytes")
        
        # Adjust minimum size check - we're getting 16-byte packets
        if len(packet_data) < 16:
            logger.warning(f"Ticker data packet too small: {len(packet_data)} bytes")
            return None
            
        try:
            # Extract each byte individually for detailed debug
            msg_type = packet_data[0]  # Message type is first byte
            byte_msg = f"Bytes breakdown: msg_type={msg_type} (0x{msg_type:02x})"
            
            # The correct interpretation based on Dhan V2 API format:
            # After msg_type (1 byte), there's a reserved byte, then 2-byte exchange code,
            # followed by 4-byte instrument token (not 8 bytes as we were processing)
            
            # Correct byte extraction based on Dhan's format
            reserved = packet_data[1]  # Reserved byte
            exchange_bytes = packet_data[2:4]  # 2 bytes for exchange
            token_bytes = packet_data[4:8]  # 4 bytes for token
            
            byte_msg += f", reserved=0x{reserved:02x}, exchange={exchange_bytes.hex()}"
            byte_msg += f", token_bytes={token_bytes.hex()}"
            logger.debug(byte_msg)
            
            # Extract token correctly (bytes 4-8)
            token = int.from_bytes(token_bytes, byteorder='little')
            
            # Extract exchange bytes for detailed logging
            exchange_code = int.from_bytes(exchange_bytes, byteorder='little')
            logger.info(f"TICK TOKEN DEBUG: Extracted token={token} (0x{token:x}), exchange_code={exchange_code}")
            
            # Extract LTP (bytes 8-12)
            ltp_bytes = packet_data[8:12]
            ltp = int.from_bytes(ltp_bytes, byteorder='little')
            
            # Try multiple decoding strategies for price
            ltp_float = struct.unpack('<f', ltp_bytes)[0]  # Try as float
            logger.debug(f"LTP byte values: hex={ltp_bytes.hex()}, as int={ltp}, as float={ltp_float}")
            
            # Extract timestamp if available (typically bytes 12-16)
            timestamp_bytes = packet_data[12:16] if len(packet_data) >= 16 else None
            timestamp = int.from_bytes(timestamp_bytes, byteorder='little') if timestamp_bytes else int(time.time() * 1000)
            
            # Volume is usually not available in LTP mode
            volume = 0
            
            # Try using the float value directly instead of the int value with divisor
            # Create tick dictionary with parsed values
            tick = {
                'token': token,  # Correctly extracted 4-byte token
                'last_price': ltp_float,  # Use the direct float value from struct.unpack
                'volume': volume,
                'timestamp': datetime.fromtimestamp(time.time()).isoformat(),  # Use current time for now
                'exchange_code': int.from_bytes(exchange_bytes, byteorder='little'),
                'mode': self.MODE_LTP  # This is LTP mode
            }
            
            # Debug full tick data including all price representations
            logger.debug(f"Price comparisons: int_bytes={ltp}, float_value={ltp_float}, scaled={ltp/100000.0}")
            
            # Add token origin debug info to catch potential mapping issues
            token_origin = "unknown"
            if token == 2885:
                token_origin = "RELIANCE"
            elif token == 1594:
                token_origin = "INFY"
            elif token == 26000:
                token_origin = "NIFTY"
            elif token == 1: 
                token_origin = "SENSEX"
            
            logger.info(f"TICK TOKEN DEBUG: Raw token={token}, origin={token_origin}, payload_size={len(packet_data)} bytes")
            
            logger.debug(f"Parsed ticker data: {tick}")
            # Return a list containing the single tick to match what _process_binary_packet expects
            return [tick]
            
        except Exception as e:
            logger.error(f"Error parsing ticker data: {e}")
            return None

    def _parse_market_depth(self, packet_data):
        """
        Parse message type 3: Market depth data (top 5 levels)
        Format based on Dhan's marketfeed client
        """
        # Debug the binary packet
        logger.debug(f"Market depth packet: {packet_data.hex()}, size: {len(packet_data)} bytes")
        
        # Adjust minimum size depending on what data we need
        if len(packet_data) < 13:  # At minimum we need type(1) + token(4) + at least some depth data
            logger.warning(f"Market depth packet too small: {len(packet_data)} bytes")
            return None
            
        try:
            # First parse the header with instrument token
            msg_type, token = struct.unpack('<BL', packet_data[:5])
            
            # Create depth data structure
            depth = {
                'buy': [],
                'sell': []
            }
            
            # Parse buy side (5 levels)
            offset = 5
            for i in range(5):
                price, quantity, orders = struct.unpack('<LLL', packet_data[offset:offset+12])
                depth['buy'].append({
                    'price': price / 100.0,
                    'quantity': quantity,
                    'orders': orders
                })
                offset += 12
                
            # Parse sell side (5 levels)
            for i in range(5):
                price, quantity, orders = struct.unpack('<LLL', packet_data[offset:offset+12])
                depth['sell'].append({
                    'price': price / 100.0,
                    'quantity': quantity,
                    'orders': orders
                })
                offset += 12
                
            # Parse timestamp
            timestamp, = struct.unpack('<Q', packet_data[offset:offset+8])
            
            tick = {
                'token': token,
                'depth': depth,
                'timestamp': datetime.fromtimestamp(timestamp / 1000).isoformat(),
                'mode': self.MODE_DEPTH
            }
            
            # Return a list containing the single tick to match what _process_binary_packet expects
            return [tick]
            
        except Exception as e:
            logger.error(f"Error parsing market depth: {e}")
            return None

    def _parse_quote_data(self, packet_data):
        """
        Parse message type 4: Quote data (OHLC, volume, etc.)
        Format based on Dhan's marketfeed client
        """
        # Debug the binary packet
        logger.debug(f"Quote data packet: {packet_data.hex()}, size: {len(packet_data)} bytes")
        
        # Adjust minimum size
        if len(packet_data) < 13:  # At minimum we need type(1) + token(4) + some price data
            logger.warning(f"Quote data packet too small: {len(packet_data)} bytes")
            return None
            
        try:
            # Unpack binary data - format will depend on Dhan's specification
            # Format: type(1) + instrument_token(4) + ltp(4) + open(4) + high(4) + low(4) + close(4) + ...
            msg_type, token, ltp, open_price, high, low, close, volume = struct.unpack('<BLLLLLLQ', packet_data[:33])
            
            # Parse timestamp at the end
            timestamp_offset = 33
            timestamp, = struct.unpack('<Q', packet_data[timestamp_offset:timestamp_offset+8])
            
            tick = {
                'token': token,
                'last_price': ltp / 100.0,
                'ohlc': {
                    'open': open_price / 100.0,
                    'high': high / 100.0,
                    'low': low / 100.0,
                    'close': close / 100.0
                },
                'volume': volume,
                'timestamp': datetime.fromtimestamp(timestamp / 1000).isoformat(),
                'mode': self.MODE_QUOTE
            }
            
            # Return a list containing the single tick to match what _process_binary_packet expects
            return [tick]
            
        except Exception as e:
            logger.error(f"Error parsing quote data: {e}")
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

    def _parse_full_data(self, packet_data):
        """
        Parse message type 8: Full data (combination of ticker + depth)
        Format based on Dhan's marketfeed client
        """
        if len(packet_data) < 200:  # Full data packets are quite large
            logger.warning(f"Full data packet too small: {len(packet_data)} bytes")
            return None
            
        try:
            # First parse the main data fields
            tick_data = self._parse_ticker_data(packet_data)
            depth_data = self._parse_market_depth(packet_data)
            
            if tick_data and depth_data:
                # Merge the two data structures
                combined = {**tick_data, **depth_data}
                combined['mode'] = self.MODE_FULL
                return combined
            elif tick_data:
                tick_data['mode'] = self.MODE_FULL
                return tick_data
            elif depth_data:
                depth_data['mode'] = self.MODE_FULL
                return depth_data
            else:
                return None
                
        except Exception as e:
            logger.error(f"Error parsing full data: {e}")
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