"""
Fixed Zerodha WebSocket client with proper websockets library usage.
Addresses the 'ClientConnection' object has no attribute 'closed' error.
Enhanced to properly handle exchange mapping for INDEX instruments.
"""
import asyncio
import json
import logging
import struct
import threading
import time
from typing import Dict, List, Optional, Callable, Any, Set
import websockets.client
import websockets.exceptions
from datetime import datetime

class ZerodhaWebSocket:
    """
    Fixed WebSocket client for Zerodha's market data streaming API.
    Addresses connection issues and improves reliability.
    Enhanced for proper INDEX exchange handling.
    """
    
    # Subscription modes
    MODE_LTP = "ltp"
    MODE_QUOTE = "quote" 
    MODE_FULL = "full"
    
    def __init__(self, api_key: str, access_token: str, on_ticks: Callable[[List[Dict]], None] = None):
        """Initialize the Zerodha WebSocket client"""
        self.api_key = api_key
        self.access_token = access_token
        self.on_ticks = on_ticks
        self.websocket = None
        self.connected = False
        self.running = False
        self.loop = None
        self.ws_thread = None
        self.logger = logging.getLogger(__name__)
        self.lock = threading.Lock()
        
        # Subscription management
        self.subscribed_tokens = set()
        self.mode_map = {}
        
        # ✅ NEW: Exchange mapping for tokens (critical for INDEX handling)
        self.token_exchange_map = {}  # {token: exchange}
        
        # Connection management
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60
        
        # Callback handlers
        self.on_connect = None
        self.on_disconnect = None
        self.on_error = None
        
        # WebSocket URL
        self.ws_url = f"wss://ws.kite.trade?api_key={self.api_key}&access_token={self.access_token}"
        
        # Statistics
        self.message_count = 0
        self.tick_count = 0
        
        # Connection state tracking
        self._connection_ready = threading.Event()
        self._stop_event = threading.Event()
        
        self.logger.info("✅ Zerodha WebSocket client initialized")
    
    def set_token_exchange_mapping(self, token_exchange_map: Dict[int, str]):
        """
        Set the token to exchange mapping.
        This should be called by the adapter when subscribing to tokens.
        
        Args:
            token_exchange_map: Dictionary mapping tokens to exchanges
                                e.g., {256265: 'NSE_INDEX', 738561: 'NSE'}
        """
        with self.lock:
            self.token_exchange_map.update(token_exchange_map)
        
        self.logger.info(f"✅ Updated token exchange mapping for {len(token_exchange_map)} tokens")
    
    def start(self) -> bool:
        """Start the WebSocket client in a separate thread"""
        if self.running:
            self.logger.info("✅ WebSocket client already running")
            return True
        
        try:
            self.running = True
            self._stop_event.clear()
            self._connection_ready.clear()
            
            def _run_in_thread():
                try:
                    # Create new event loop for this thread
                    self.loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(self.loop)
                    
                    # Run the WebSocket loop with proper exception handling
                    self.loop.run_until_complete(self._run_forever())
                    
                except asyncio.CancelledError:
                    self.logger.info("🔄 WebSocket thread cancelled gracefully")
                except RuntimeError as e:
                    if "Event loop stopped before Future completed" in str(e):
                        self.logger.debug("🔄 Event loop stopped during shutdown (normal)")
                    else:
                        self.logger.error(f"❌ Runtime error in WebSocket thread: {e}")
                except Exception as e:
                    self.logger.error(f"❌ Error in WebSocket thread: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    # Clean up the event loop
                    try:
                        if self.loop and not self.loop.is_closed():
                            # Cancel all pending tasks
                            pending = asyncio.all_tasks(self.loop)
                            for task in pending:
                                task.cancel()
                            
                            # Wait for tasks to complete cancellation
                            if pending:
                                self.loop.run_until_complete(
                                    asyncio.gather(*pending, return_exceptions=True)
                                )
                            
                            self.loop.close()
                    except Exception as e:
                        self.logger.debug(f"Error closing event loop: {e}")
                    
                    self.logger.info("🧹 WebSocket thread cleanup completed")
            
            # Start the thread
            self.ws_thread = threading.Thread(target=_run_in_thread, daemon=True, name="ZerodhaWS")
            self.ws_thread.start()
            
            # Wait for thread to start
            time.sleep(0.5)
            
            self.logger.info("🚀 WebSocket client started")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error starting WebSocket client: {e}")
            self.running = False
            return False
    
    def stop(self):
        """Stop the WebSocket client"""
        try:
            self.logger.info("🛑 Stopping WebSocket client...")
            
            # Signal stop
            self.running = False
            self._stop_event.set()
            
            # If we have a running loop, schedule disconnect
            if self.loop and not self.loop.is_closed():
                try:
                    # Schedule disconnect in the event loop
                    future = asyncio.run_coroutine_threadsafe(self._async_stop(), self.loop)
                    future.result(timeout=5)  # Wait up to 5 seconds
                except Exception as e:
                    self.logger.error(f"❌ Error during async stop: {e}")
            
            # Wait for thread to finish
            if self.ws_thread and self.ws_thread.is_alive():
                self.ws_thread.join(timeout=5)
                if self.ws_thread.is_alive():
                    self.logger.warning("⚠️ WebSocket thread did not stop gracefully")
            
            # Reset state
            self.connected = False
            self.websocket = None
            
            self.logger.info("🛑 WebSocket client stopped")
            
        except Exception as e:
            self.logger.error(f"❌ Error stopping WebSocket client: {e}")
    
    async def _async_stop(self):
        """Async stop method to run in the event loop"""
        try:
            await self._disconnect()
            # Stop the event loop
            self.loop.stop()
        except Exception as e:
            self.logger.error(f"❌ Error in async stop: {e}")
    
    def subscribe_tokens(self, tokens: List[int], mode: str = MODE_QUOTE):
        """
        Subscribe to tokens (thread-safe)
        
        Args:
            tokens: List of instrument tokens as integers
            mode: Subscription mode (ltp, quote, full)
        """
        if not self.running:
            self.logger.error("❌ WebSocket client not running. Call start() first.")
            return
        
        if not tokens:
            self.logger.warning("⚠️ No tokens provided to subscribe")
            return
        
        # Convert tokens to integers
        try:
            tokens = [int(token) for token in tokens]
        except (ValueError, TypeError) as e:
            self.logger.error(f"❌ Invalid token format: {e}")
            return
        
        self.logger.info(f"📡 Scheduling subscription for {len(tokens)} tokens in {mode} mode")
        
        # Schedule subscription in the event loop
        if self.loop and not self.loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(
                    self._subscribe_tokens(tokens, mode),
                    self.loop
                )
            except Exception as e:
                self.logger.error(f"❌ Error scheduling subscription: {e}")
        else:
            self.logger.error("❌ Event loop not available for subscription")
    
    async def _subscribe_tokens(self, tokens: List[int], mode: str):
        """Internal method to subscribe to tokens"""
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Ensure we're connected
                if not self.connected or not self._is_websocket_open():
                    self.logger.info("🔌 Not connected, attempting to connect...")
                    if not await self._connect():
                        retry_count += 1
                        await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                        continue
                
                # Subscribe to tokens
                sub_msg = {
                    "a": "subscribe",
                    "v": tokens
                }
                
                if not await self._send_json(sub_msg):
                    raise Exception("Failed to send subscription message")
                
                self.logger.info(f"✅ Subscribed to {len(tokens)} tokens: {tokens}")
                
                # Wait for subscription to process
                await asyncio.sleep(0.5)
                
                # Set mode for each token individually
                for token in tokens:
                    mode_msg = {
                        "a": "mode",
                        "v": [mode, [token]]
                    }
                    
                    if await self._send_json(mode_msg):
                        self.mode_map[token] = mode
                        self.logger.debug(f"✅ Set mode {mode} for token {token}")
                    else:
                        self.logger.warning(f"⚠️ Failed to set mode for token {token}")
                    
                    # Small delay between mode changes
                    await asyncio.sleep(0.1)
                
                # Update tracking
                with self.lock:
                    self.subscribed_tokens.update(tokens)
                
                self.logger.info(f"✅ Successfully configured {len(tokens)} tokens in {mode} mode")
                return  # Success, exit retry loop
                
            except Exception as e:
                retry_count += 1
                self.logger.error(f"❌ Subscription attempt {retry_count} failed: {e}")
                if retry_count < max_retries:
                    await asyncio.sleep(2 ** retry_count)  # Exponential backoff
        
        self.logger.error(f"❌ Failed to subscribe after {max_retries} attempts")
    
    async def unsubscribe(self, tokens: List[int]) -> bool:
        """Unsubscribe from market data for given tokens"""
        try:
            if not self.connected or not self._is_websocket_open():
                self.logger.warning("⚠️ Not connected, cannot unsubscribe")
                return False
            
            unsub_msg = {
                "a": "unsubscribe",
                "v": tokens
            }
            
            if not await self._send_json(unsub_msg):
                return False
            
            # Update tracking
            with self.lock:
                for token in tokens:
                    self.subscribed_tokens.discard(token)
                    self.mode_map.pop(token, None)
                    # ✅ NEW: Clean up exchange mapping
                    self.token_exchange_map.pop(token, None)
            
            self.logger.info(f"✅ Unsubscribed from {len(tokens)} tokens")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error unsubscribing: {e}")
            return False
    
    def _is_websocket_open(self) -> bool:
        """Check if WebSocket connection is open"""
        try:
            if not self.websocket:
                return False
            
            # Check for different websocket library attributes
            if hasattr(self.websocket, 'closed'):
                return not self.websocket.closed
            elif hasattr(self.websocket, 'state'):
                # For websockets library, check state
                from websockets.protocol import State
                return self.websocket.state == State.OPEN
            else:
                # Fallback - assume open if connected flag is True
                return self.connected
                
        except Exception as e:
            self.logger.debug(f"Error checking WebSocket state: {e}")
            return False
    
    async def _connect(self) -> bool:
        """Connect to WebSocket with improved error handling"""
        if self.connected and self._is_websocket_open():
            return True
        
        try:
            self.logger.info(f"🔌 Connecting to WebSocket (attempt {self.reconnect_attempts + 1})...")
            
            # Close existing connection if any
            if self.websocket:
                try:
                    await self.websocket.close()
                except Exception:
                    pass
                self.websocket = None
            
            # Create new connection with proper configuration
            self.websocket = await websockets.client.connect(
                self.ws_url,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=10,
                max_size=2**20,  # 1MB max message size
                compression=None,  # Disable compression for binary data
                extra_headers={
                    'User-Agent': 'ZerodhaWebSocketClient/1.0'
                }
            )
            
            # Verify connection
            if self.websocket and self._is_websocket_open():
                self.connected = True
                self.reconnect_attempts = 0
                self.reconnect_delay = 5
                self._connection_ready.set()
                
                self.logger.info("✅ WebSocket connected successfully")
                
                # Trigger on_connect callback
                if self.on_connect:
                    try:
                        self.on_connect()
                    except Exception as e:
                        self.logger.error(f"❌ Error in on_connect callback: {e}")
                
                return True
            else:
                raise Exception("Failed to establish WebSocket connection")
            
        except Exception as e:
            self.connected = False
            self.reconnect_attempts += 1
            self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
            
            error_msg = f"❌ Connection failed (attempt {self.reconnect_attempts}): {e}"
            self.logger.error(error_msg)
            
            # Trigger on_error callback
            if self.on_error:
                try:
                    self.on_error(e)
                except Exception as e2:
                    self.logger.error(f"❌ Error in on_error callback: {e2}")
            
            return False
    
    async def _disconnect(self):
        """Disconnect from WebSocket"""
        try:
            self.connected = False
            
            if self.websocket:
                try:
                    await self.websocket.close()
                except Exception as e:
                    self.logger.debug(f"Error closing WebSocket: {e}")
                
                self.websocket = None
            
            self.logger.info("🔌 WebSocket disconnected")
            
            # Trigger on_disconnect callback
            if self.on_disconnect:
                try:
                    self.on_disconnect()
                except Exception as e:
                    self.logger.error(f"❌ Error in on_disconnect callback: {e}")
                    
        except Exception as e:
            self.logger.error(f"❌ Error during disconnect: {e}")
    
    async def _send_json(self, message: Dict) -> bool:
        """Send JSON message to WebSocket"""
        if not self.connected or not self._is_websocket_open():
            self.logger.error("❌ WebSocket not connected")
            return False
        
        try:
            message_str = json.dumps(message)
            await self.websocket.send(message_str)
            self.logger.debug(f"📤 Sent: {message_str}")
            return True
        except Exception as e:
            self.logger.error(f"❌ Error sending message: {e}")
            self.connected = False  # Mark as disconnected on send error
            return False
    
    async def _run_forever(self):
        """Main WebSocket message loop with improved error handling"""
        self.logger.info("🚀 Starting WebSocket message loop...")
        
        try:
            while self.running and not self._stop_event.is_set():
                try:
                    # Connect if not connected
                    if not self.connected or not self._is_websocket_open():
                        if not await self._connect():
                            if self.reconnect_attempts >= self.max_reconnect_attempts:
                                self.logger.error("❌ Max reconnection attempts reached")
                                break
                            
                            # Wait before retrying
                            await asyncio.sleep(self.reconnect_delay)
                            continue
                    
                    try:
                        # Process messages with timeout
                        message = await asyncio.wait_for(
                            self.websocket.recv(),
                            timeout=30
                        )
                        await self._process_message(message)
                        
                    except asyncio.TimeoutError:
                        # Send ping to keep connection alive
                        try:
                            if self._is_websocket_open():
                                pong_waiter = await self.websocket.ping()
                                await asyncio.wait_for(pong_waiter, timeout=5)
                                self.logger.debug("💓 Ping/Pong successful")
                            else:
                                self.logger.warning("⚠️ WebSocket not open during ping")
                                self.connected = False
                        except Exception as e:
                            self.logger.warning(f"⚠️ Ping failed: {e}")
                            self.connected = False
                    
                    except websockets.exceptions.ConnectionClosed as e:
                        self.logger.warning(f"🔌 Connection closed: {e}")
                        self.connected = False
                        if self.running:  # Only reconnect if we're still supposed to be running
                            await asyncio.sleep(2)  # Brief delay before reconnection
                    
                    except Exception as e:
                        self.logger.error(f"❌ Error receiving message: {e}")
                        self.connected = False
                
                except asyncio.CancelledError:
                    self.logger.info("🔄 Message loop cancelled")
                    break
                except Exception as e:
                    self.logger.error(f"❌ Error in message loop: {e}")
                    self.connected = False
                    await asyncio.sleep(1)
                
                # Small delay to prevent tight loop on errors
                try:
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    break
            
        except asyncio.CancelledError:
            self.logger.info("🔄 WebSocket message loop cancelled")
        except Exception as e:
            self.logger.error(f"❌ Unexpected error in message loop: {e}")
        finally:
            # Cleanup on exit
            try:
                await self._disconnect()
            except Exception as e:
                self.logger.debug(f"Error during final disconnect: {e}")
            
            self.logger.info("🛑 WebSocket message loop stopped")
    
    async def _process_message(self, message):
        """Process incoming WebSocket message"""
        try:
            self.message_count += 1
            
            if isinstance(message, bytes):
                # Handle binary market data
                if len(message) == 1:
                    self.logger.debug("💓 Heartbeat received")
                    return
                
                # Parse binary data
                ticks = self._parse_binary_message(message)
                if ticks:
                    self.tick_count += len(ticks)
                    
                    # Log first few ticks for debugging
                    if self.tick_count <= 10:
                        self.logger.info(f"📈 Processed {len(ticks)} ticks (Total: {self.tick_count})")
                        for tick in ticks[:2]:  # Log first 2 ticks
                            self.logger.info(f"  Token {tick['instrument_token']}: LTP={tick['last_price']}")
                    elif self.tick_count % 100 == 0:
                        self.logger.info(f"📈 Total ticks processed: {self.tick_count}")
                    
                    # Call tick callback
                    if self.on_ticks:
                        try:
                            self.on_ticks(ticks)
                        except Exception as e:
                            self.logger.error(f"❌ Error in on_ticks callback: {e}")
                else:
                    self.logger.debug("⚠️ No ticks parsed from binary message")
            
            elif isinstance(message, str):
                # Handle JSON messages
                try:
                    data = json.loads(message)
                    msg_type = data.get('type', 'unknown')
                    
                    if msg_type == 'error':
                        self.logger.error(f"❌ WebSocket error: {data.get('data', '')}")
                    elif msg_type == 'order':
                        self.logger.info(f"📊 Order update: {data}")
                    else:
                        self.logger.debug(f"📝 JSON message: {data}")
                        
                except json.JSONDecodeError:
                    self.logger.debug(f"📝 Non-JSON text: {message}")
            
        except Exception as e:
            self.logger.error(f"❌ Error processing message: {e}")
    
    def _parse_binary_message(self, data: bytes) -> List[Dict]:
        """Parse binary message according to Zerodha specification"""
        try:
            if len(data) < 4:
                return []
            
            # Parse header: first 2 bytes = number of packets
            num_packets = struct.unpack('>H', data[0:2])[0]
            
            packets = []
            offset = 2
            
            for packet_idx in range(num_packets):
                if offset + 2 > len(data):
                    break
                
                # Next 2 bytes: packet length
                packet_length = struct.unpack('>H', data[offset:offset+2])[0]
                offset += 2
                
                if offset + packet_length > len(data):
                    break
                
                # Extract and parse packet
                packet_data = data[offset:offset+packet_length]
                tick = self._parse_packet(packet_data)
                if tick:
                    packets.append(tick)
                
                offset += packet_length
            
            return packets
            
        except Exception as e:
            self.logger.error(f"❌ Error parsing binary message: {e}")
            return []
    
    def _parse_packet(self, packet: bytes) -> Optional[Dict]:
        """
        Parse individual packet with improved error handling.
        ✅ ENHANCED: Adds exchange information to tick data.
        """
        try:
            if len(packet) < 8:
                return None
            
            # Extract instrument token and last price
            instrument_token = struct.unpack('>I', packet[0:4])[0]
            last_price_paise = struct.unpack('>i', packet[4:8])[0]
            last_price = last_price_paise / 100.0
            
            # Determine mode based on packet length
            if len(packet) == 8:
                mode = self.MODE_LTP
            elif len(packet) == 44:
                mode = self.MODE_QUOTE
            elif len(packet) >= 184:
                mode = self.MODE_FULL
            else:
                mode = self.mode_map.get(instrument_token, self.MODE_QUOTE)
            
            # ✅ NEW: Get exchange information for this token
            exchange = None
            with self.lock:
                exchange = self.token_exchange_map.get(instrument_token)
            
            # Basic tick structure
            tick = {
                'instrument_token': instrument_token,
                'last_traded_price': last_price,
                'last_price': last_price,
                'mode': mode,
                'timestamp': int(time.time() * 1000)
            }
            
            # ✅ NEW: Add exchange information if available
            if exchange:
                tick['source_exchange'] = exchange  # Add source exchange from mapping
            
            # Parse additional fields for quote mode (44 bytes)
            if len(packet) >= 44:
                try:
                    # Only unpack exactly 44 bytes for quote mode
                    fields = struct.unpack('>11i', packet[0:44])  # 11 integers * 4 bytes = 44 bytes
                    
                    tick.update({
                        'instrument_token': fields[0],
                        'last_traded_price': fields[1] / 100.0,
                        'last_price': fields[1] / 100.0,
                        'last_traded_quantity': fields[2],
                        'average_traded_price': fields[3] / 100.0,
                        'average_price': fields[3] / 100.0,
                        'volume_traded': fields[4],
                        'volume': fields[4],
                        'total_buy_quantity': fields[5],
                        'total_sell_quantity': fields[6],
                        'open_price': fields[7] / 100.0,
                        'high_price': fields[8] / 100.0,
                        'low_price': fields[9] / 100.0,
                        'close_price': fields[10] / 100.0,
                        'ohlc': {
                            'open': fields[7] / 100.0,
                            'high': fields[8] / 100.0,
                            'low': fields[9] / 100.0,
                            'close': fields[10] / 100.0
                        }
                    })
                except struct.error as e:
                    self.logger.debug(f"⚠️ Quote parsing issue (packet length: {len(packet)}): {e}")
                    # Fallback - just use LTP data
                    pass
            
            # Parse full mode fields if available (64+ bytes)
            if len(packet) >= 64:
                try:
                    extended_fields = struct.unpack('>iiiii', packet[44:64])
                    tick.update({
                        'last_traded_timestamp': extended_fields[0],
                        'open_interest': extended_fields[1],
                        'oi': extended_fields[1],
                        'exchange_timestamp': extended_fields[4]
                    })
                except struct.error:
                    pass
            
            # Parse market depth for full mode (184+ bytes)
            if len(packet) >= 184:
                try:
                    depth = self._parse_market_depth(packet[64:184])
                    if depth:
                        tick['depth'] = depth
                except Exception:
                    pass
            
            return tick
            
        except Exception as e:
            self.logger.error(f"❌ Error parsing packet: {e}")
            return None
    
    def _parse_market_depth(self, depth_data: bytes) -> Optional[Dict]:
        """Parse market depth data"""
        try:
            if len(depth_data) < 120:
                return None
            
            depth = {'buy': [], 'sell': []}
            
            # Parse buy side (first 5 entries)
            for i in range(5):
                offset = i * 12
                if offset + 10 <= len(depth_data):
                    quantity, price, orders = struct.unpack('>iih', depth_data[offset:offset+10])
                    if price > 0:  # Only add valid prices
                        depth['buy'].append({
                            'quantity': quantity,
                            'price': price / 100.0,
                            'orders': orders
                        })
            
            # Parse sell side (next 5 entries)
            for i in range(5):
                offset = 60 + (i * 12)
                if offset + 10 <= len(depth_data):
                    quantity, price, orders = struct.unpack('>iih', depth_data[offset:offset+10])
                    if price > 0:  # Only add valid prices
                        depth['sell'].append({
                            'quantity': quantity,
                            'price': price / 100.0,
                            'orders': orders
                        })
            
            return depth if (depth['buy'] or depth['sell']) else None
            
        except Exception as e:
            self.logger.error(f"❌ Error parsing market depth: {e}")
            return None
    
    def is_connected(self) -> bool:
        """Check if WebSocket is connected"""
        return self.connected and self._is_websocket_open()
    
    def get_subscriptions(self) -> Set[int]:
        """Get current subscriptions"""
        with self.lock:
            return self.subscribed_tokens.copy()
    
    def get_token_exchange_map(self) -> Dict[int, str]:
        """Get current token to exchange mapping"""
        with self.lock:
            return dict(self.token_exchange_map)
    
    def wait_for_connection(self, timeout: float = 10.0) -> bool:
        """Wait for connection to be established"""
        return self._connection_ready.wait(timeout)