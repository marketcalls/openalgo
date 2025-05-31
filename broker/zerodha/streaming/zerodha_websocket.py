"""
Zerodha WebSocket client implementation for market data streaming.
Handles connection, subscription, and data processing for Zerodha's WebSocket API.
"""
import asyncio
import json
import logging
import struct
from typing import Dict, List, Optional, Callable, Any
import websockets
from datetime import datetime
import time

class ZerodhaWebSocket:
    """
    WebSocket client for Zerodha's market data streaming API.
    Handles connection, subscription, and data processing.
    """
    
    # WebSocket endpoint base
    WS_BASE_URL = "wss://ws.kite.trade"
    
    # Subscription modes
    MODE_LTP = "ltp"
    MODE_QUOTE = "quote"
    MODE_FULL = "full"
    
    def __init__(self, api_key: str, access_token: str, on_ticks: Callable[[List[Dict]], None] = None):
        """
        Initialize the Zerodha WebSocket client.
        
        Args:
            api_key: Zerodha API key
            access_token: Zerodha access token
            on_ticks: Callback function to handle incoming ticks
        """
        self.api_key = api_key
        self.access_token = access_token
        self.on_ticks = on_ticks
        self.websocket = None
        self.ws_url = f"{self.WS_BASE_URL}?api_key={self.api_key}&access_token={self.access_token}"
        self.connected = False
        self.subscribed_tokens = set()
        self.mode_map = {}  # Maps token to subscription mode
        self.logger = logging.getLogger(__name__)
        self.reconnect_delay = 5  # Initial reconnect delay in seconds
        self.max_reconnect_delay = 60  # Maximum reconnect delay
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.loop = asyncio.new_event_loop()
        
    async def connect(self):
        """Establish WebSocket connection to Zerodha"""
        if self.connected:
            return True
            
        try:
            self.websocket = await websockets.connect(self.ws_url, ping_interval=30, ping_timeout=10)
            self.connected = True
            self.reconnect_attempts = 0
            self.reconnect_delay = 5
            self.logger.info("Connected to Zerodha WebSocket")
            
            # Resubscribe to any previously subscribed tokens
            if self.subscribed_tokens:
                tokens_by_mode = {}
                for token in self.subscribed_tokens:
                    mode = self.mode_map.get(token, self.MODE_QUOTE)
                    if mode not in tokens_by_mode:
                        tokens_by_mode[mode] = []
                    tokens_by_mode[mode].append(token)
                
                for mode, tokens in tokens_by_mode.items():
                    await self._subscribe(tokens, mode)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error connecting to Zerodha WebSocket: {e}")
            self.connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from WebSocket"""
        self.running = False
        if self.websocket:
            await self.websocket.close()
            self.connected = False
            self.logger.info("Disconnected from Zerodha WebSocket")
    
    async def _subscribe(self, tokens: List[int], mode: str = MODE_QUOTE):
        """
        Internal method to subscribe to tokens with a specific mode
        
        Args:
            tokens: List of instrument tokens to subscribe to
            mode: Subscription mode (ltp, quote, full)
        """
        if not self.connected:
            self.logger.warning("Not connected to WebSocket, cannot subscribe")
            return False
            
        try:
            # Set mode for all tokens first
            if mode != self.MODE_LTP:  # LTP is default, no need to set mode
                mode_msg = {
                    "a": "mode",
                    "v": [mode, [str(token) for token in tokens]]
                }
                await self.websocket.send(json.dumps(mode_msg))
            
            # Subscribe to tokens
            sub_msg = {
                "a": "subscribe",
                "v": [str(token) for token in tokens]
            }
            await self.websocket.send(json.dumps(sub_msg))
            
            # Update our tracking
            for token in tokens:
                self.subscribed_tokens.add(token)
                self.mode_map[token] = mode
                
            self.logger.debug(f"Subscribed to {len(tokens)} tokens in {mode} mode")
            return True
            
        except Exception as e:
            self.logger.error(f"Error subscribing to tokens: {e}")
            return False
    
    async def subscribe(self, tokens: List[int], mode: str = MODE_QUOTE) -> bool:
        """
        Subscribe to market data for the given tokens
        
        Args:
            tokens: List of instrument tokens to subscribe to
            mode: Subscription mode (ltp, quote, full)
            
        Returns:
            bool: True if subscription was successful, False otherwise
        """
        if mode not in [self.MODE_LTP, self.MODE_QUOTE, self.MODE_FULL]:
            self.logger.error(f"Invalid subscription mode: {mode}")
            return False
            
        if not tokens:
            self.logger.warning("No tokens provided to subscribe")
            return False
            
        return await self._subscribe(tokens, mode)
    
    async def unsubscribe(self, tokens: List[int]) -> bool:
        """
        Unsubscribe from market data for the given tokens
        
        Args:
            tokens: List of instrument tokens to unsubscribe from
            
        Returns:
            bool: True if unsubscription was successful, False otherwise
        """
        if not self.connected:
            self.logger.warning("Not connected to WebSocket, cannot unsubscribe")
            return False
            
        try:
            unsub_msg = {
                "a": "unsubscribe",
                "v": [str(token) for token in tokens]
            }
            await self.websocket.send(json.dumps(unsub_msg))
            
            # Update our tracking
            for token in tokens:
                if token in self.subscribed_tokens:
                    self.subscribed_tokens.remove(token)
                if token in self.mode_map:
                    del self.mode_map[token]
                    
            self.logger.debug(f"Unsubscribed from {len(tokens)} tokens")
            return True
            
        except Exception as e:
            self.logger.error(f"Error unsubscribing from tokens: {e}")
            return False
    
    def _parse_binary_data(self, data: bytes) -> List[Dict]:
        """
        Parse binary market data message from Zerodha WebSocket
        
        Args:
            data: Binary data received from WebSocket
            
        Returns:
            List of parsed quote dictionaries
        """
        if len(data) < 4:
            return []
            
        # First 2 bytes: number of packets in the message (short/int16)
        num_packets = struct.unpack('!H', data[0:2])[0]
        
        # Next 2 bytes: length of the first packet (short/int16)
        packet_length = struct.unpack('!H', data[2:4])[0]
        
        packets = []
        offset = 4  # Start after the header
        
        for _ in range(num_packets):
            if offset + packet_length > len(data):
                break
                
            packet_data = data[offset:offset+packet_length]
            quote = self._parse_packet(packet_data)
            if quote:
                packets.append(quote)
                
            offset += packet_length
            
            # If there are more packets, read the next packet length
            if offset + 2 <= len(data):
                packet_length = struct.unpack('!H', data[offset:offset+2])[0]
                offset += 2
        
        return packets
    
    def _parse_packet(self, packet: bytes) -> Optional[Dict]:
        """
        Parse a single binary packet into a quote dictionary
        
        Args:
            packet: Binary packet data
            
        Returns:
            Dictionary with quote data or None if parsing fails
        """
        try:
            if len(packet) < 44:  # Minimum size for LTP packet
                return None
                
            # Extract instrument token (first 4 bytes)
            token = struct.unpack('!I', packet[0:4])[0]
            
            # Last traded price (4 bytes)
            ltp = struct.unpack('!i', packet[4:8])[0] / 100.0
            
            # If this is just LTP mode, return minimal data
            mode = self.mode_map.get(token, self.MODE_QUOTE)
            if mode == self.MODE_LTP or len(packet) < 44:
                return {
                    'instrument_token': token,
                    'mode': 'ltp',
                    'last_price': ltp,
                    'timestamp': int(time.time() * 1000)
                }
                
            # Parse quote data (44 bytes total for quote mode)
            last_quantity = struct.unpack('!i', packet[8:12])[0]
            avg_traded_price = struct.unpack('!i', packet[12:16])[0] / 100.0
            volume_traded = struct.unpack('!i', packet[16:20])[0]
            total_buy_quantity = struct.unpack('!i', packet[20:24])[0]
            total_sell_quantity = struct.unpack('!i', packet[24:28])[0]
            open_price = struct.unpack('!i', packet[28:32])[0] / 100.0
            high_price = struct.unpack('!i', packet[32:36])[0] / 100.0
            low_price = struct.unpack('!i', packet[36:40])[0] / 100.0
            close_price = struct.unpack('!i', packet[40:44])[0] / 100.0
            
            quote = {
                'instrument_token': token,
                'mode': 'quote',
                'last_price': ltp,
                'last_quantity': last_quantity,
                'average_price': avg_traded_price,
                'volume': volume_traded,
                'total_buy_quantity': total_buy_quantity,
                'total_sell_quantity': total_sell_quantity,
                'ohlc': {
                    'open': open_price,
                    'high': high_price,
                    'low': low_price,
                    'close': close_price
                },
                'timestamp': int(time.time() * 1000)
            }
            
            # If this is full mode and we have depth data (184 bytes total for full mode)
            if mode == self.MODE_FULL and len(packet) >= 184:
                depth = {'buy': [], 'sell': []}
                
                # Parse market depth (5 levels each for buy and sell)
                # Each level has: quantity, price, orders (2 bytes padding)
                for i in range(5):  # 5 levels
                    # Buy side (starts at offset 64)
                    bid_offset = 64 + (i * 12)
                    bid_quantity = struct.unpack('!i', packet[bid_offset:bid_offset+4])[0]
                    bid_price = struct.unpack('!i', packet[bid_offset+4:bid_offset+8])[0] / 100.0
                    bid_orders = struct.unpack('!H', packet[bid_offset+8:bid_offset+10])[0]
                    depth['buy'].append({
                        'quantity': bid_quantity,
                        'price': bid_price,
                        'orders': bid_orders
                    })
                    
                    # Sell side (starts at offset 124)
                    ask_offset = 124 + (i * 12)
                    ask_quantity = struct.unpack('!i', packet[ask_offset:ask_offset+4])[0]
                    ask_price = struct.unpack('!i', packet[ask_offset+4:ask_offset+8])[0] / 100.0
                    ask_orders = struct.unpack('!H', packet[ask_offset+8:ask_offset+10])[0]
                    depth['sell'].append({
                        'quantity': ask_quantity,
                        'price': ask_price,
                        'orders': ask_orders
                    })
                
                quote['depth'] = depth
                quote['mode'] = 'full'
                
                # Parse additional fields for full mode
                if len(packet) >= 64:
                    quote['last_trade_time'] = struct.unpack('!i', packet[44:48])[0]
                    quote['oi'] = struct.unpack('!i', packet[48:52])[0]
                    quote['oi_day_high'] = struct.unpack('!i', packet[52:56])[0]
                    quote['oi_day_low'] = struct.unpack('!i', packet[56:60])[0]
                    quote['exchange_timestamp'] = struct.unpack('!i', packet[60:64])[0]
            
            return quote
            
        except Exception as e:
            self.logger.error(f"Error parsing packet: {e}")
            return None
    
    async def _process_message(self, message: str) -> None:
        """
        Process incoming WebSocket message.
        
        Args:
            message: Raw WebSocket message
        """
        try:
            # Check if message is binary (market data) or text (control messages)
            if isinstance(message, bytes):
                await self._process_binary_message(message)
            else:
                data = json.loads(message)
                self.logger.debug(f"Received message: {data}")
                
                # Handle different message types
                msg_type = data.get("type")
                if msg_type == "order":
                    self.logger.info(f"Order update: {data}")
                elif msg_type == "error":
                    self.logger.error(f"Error: {data.get('data')}")
                elif msg_type == "message":
                    self.logger.info(f"Message: {data.get('data')}")
                elif "a" in data:  # Action messages
                    action = data["a"]
                    if action == "authenticated":
                        self.logger.info("Successfully authenticated with WebSocket")
                    elif action == "subscribed":
                        self.logger.info(f"Successfully subscribed to: {data.get('v', [])}")
                    elif action == "mode":
                        self.logger.info(f"Mode set: {data.get('v')}")
                    
        except json.JSONDecodeError:
            self.logger.warning(f"Failed to decode message: {message}")
        except Exception as e:
            self.logger.error(f"Error processing message: {e}", exc_info=True)
    
    async def _process_binary_message(self, message: bytes) -> None:
        """
        Process incoming binary WebSocket message.
        
        Args:
            message: Raw binary WebSocket message
        """
        try:
            ticks = self._parse_binary_data(message)
            if ticks and self.on_ticks:
                self.on_ticks(ticks)
        except Exception as e:
            self.logger.error(f"Error processing binary message: {e}")
    
    async def _run_forever(self):
        """Main WebSocket message loop"""
        self.running = True
        
        while self.running:
            try:
                if not self.connected:
                    await self._reconnect()
                    
                if not self.connected:
                    await asyncio.sleep(min(self.reconnect_delay, self.max_reconnect_delay))
                    self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
                    continue
                
                # Reset reconnect delay on successful connection
                self.reconnect_delay = 5
                self.reconnect_attempts = 0
                
                # Process messages
                try:
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=30)
                    await self._process_message(message)
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    if self.connected:
                        await self.websocket.ping()
                except websockets.exceptions.ConnectionClosed as e:
                    self.logger.warning(f"WebSocket connection closed: {e}")
                    self.connected = False
                
            except Exception as e:
                self.logger.error(f"Error in WebSocket loop: {e}")
                self.connected = False
                await asyncio.sleep(1)
    
    async def _reconnect(self):
        """Handle reconnection logic"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error("Max reconnection attempts reached")
            return False
            
        self.reconnect_attempts += 1
        self.logger.info(f"Attempting to reconnect (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")
        
        try:
            await self.disconnect()
            await asyncio.sleep(self.reconnect_delay)
            return await self.connect()
        except Exception as e:
            self.logger.error(f"Reconnection failed: {e}")
            return False
    
    def start(self):
        """Start the WebSocket client in a background thread"""
        if not self.running:
            try:
                # Check if there's an existing event loop
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # If loop is already running, create a new one for this client
                        self.loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(self.loop)
                except RuntimeError:
                    # No event loop, create one
                    self.loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(self.loop)
                
                # Connect and start the client
                self.loop.run_until_complete(self.connect())
                self.loop.create_task(self._run_forever())
                
                # Start the event loop in a separate thread if not already running
                if not self.loop.is_running():
                    def run_loop():
                        asyncio.set_event_loop(self.loop)
                        self.loop.run_forever()
                        
                    self.thread = threading.Thread(target=run_loop, daemon=True)
                    self.thread.start()
                
                self.running = True
                return True
                
            except Exception as e:
                self.logger.error(f"Error starting WebSocket client: {e}", exc_info=True)
                self.running = False
                return False
    
    def stop(self):
        """Stop the WebSocket client"""
        self.running = False
        if hasattr(self, 'loop') and self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
        if hasattr(self, 'thread') and self.thread:
            self.thread.join(timeout=5)
        asyncio.run_coroutine_threadsafe(self.disconnect(), self.loop)
        
    def subscribe_tokens(self, tokens: List[int], mode: str = MODE_QUOTE):
        """
        Subscribe to tokens (thread-safe)
        
        Args:
            tokens: List of instrument tokens to subscribe to
            mode: Subscription mode (ltp, quote, full)
        """
        if not tokens:
            return
            
        asyncio.run_coroutine_threadsafe(
            self.subscribe(tokens, mode),
            self.loop
        )
    
    def unsubscribe_tokens(self, tokens: List[int]):
        """
        Unsubscribe from tokens (thread-safe)
        
        Args:
            tokens: List of instrument tokens to unsubscribe from
        """
        if not tokens:
            return
            
        asyncio.run_coroutine_threadsafe(
            self.unsubscribe(tokens),
            self.loop
        )
