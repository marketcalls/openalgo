from utils.logging import get_logger

logger = get_logger(__name__)

"""
Enhanced Zerodha WebSocket client with improved stability for handling 1800+ symbols.
Implements:
- Better connection management with keepalive handling
- Batch subscription to reduce message overhead
- Automatic reconnection with state recovery
- Connection health monitoring
- Optimized for high-volume symbol subscriptions
"""
import asyncio
import json
import struct
import threading
import time
from typing import Dict, List, Optional, Callable, Any, Set
import websockets.client
import websockets.exceptions
from datetime import datetime
from collections import deque

class ZerodhaWebSocket:
    """
    Enhanced WebSocket client for Zerodha's market data streaming API.
    Optimized for handling large numbers of symbol subscriptions (1800+).
    """
    
    # Subscription modes
    MODE_LTP = "ltp"
    MODE_QUOTE = "quote" 
    MODE_FULL = "full"
    
    # Connection settings based on official Zerodha WebSocket API documentation
    PING_INTERVAL = None  # Disable automatic pings - Zerodha sends heartbeats
    KEEPALIVE_INTERVAL = 30  # Check connection every 30 seconds 
    PING_TIMEOUT = 10
    CONNECT_TIMEOUT = 10  # Shorter connection timeout
    MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10MB for handling large data
    
    # Subscription batching (Zerodha supports up to 3000 instruments per connection)
    MAX_TOKENS_PER_SUBSCRIBE = 200  # Larger batches as per API specs
    SUBSCRIPTION_DELAY = 2.0  # Longer delay between batches for stability
    MAX_INSTRUMENTS_PER_CONNECTION = 3000  # Official limit
    
    # Reconnection settings (from official library)
    RECONNECT_MAX_DELAY = 60  # Maximum delay between reconnection attempts
    RECONNECT_MAX_TRIES = 50  # Maximum number of reconnection attempts
    
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
        self.logger = get_logger(__name__)
        self.lock = threading.Lock()
        
        # Subscription management
        self.subscribed_tokens = set()
        self.mode_map = {}
        self.pending_subscriptions = deque()  # Queue for pending subscriptions
        
        # Exchange mapping for tokens
        self.token_exchange_map = {}
        
        # Connection management
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = self.RECONNECT_MAX_TRIES
        self.reconnect_delay = 2
        self.max_reconnect_delay = self.RECONNECT_MAX_DELAY
        
        # Health monitoring
        self.last_ping_time = None
        self.last_message_time = None
        self.last_heartbeat_time = None  # Track Zerodha's heartbeat messages
        self.health_check_interval = self.KEEPALIVE_INTERVAL
        self.connection_timeout = 90  # Allow for longer periods without data during subscription
        
        # Event tracking for visibility
        self.event_log = deque(maxlen=100)  # Keep last 100 events
        self.enable_verbose_logging = True  # Toggle for detailed event logging
        
        # Callback handlers
        self.on_connect = None
        self.on_disconnect = None
        self.on_error = None
        
        # WebSocket URL
        self.ws_url = f"wss://ws.kite.trade?api_key={self.api_key}&access_token={self.access_token}"
        
        # Statistics
        self.message_count = 0
        self.tick_count = 0
        self.error_count = 0
        
        # Connection state tracking
        self._connection_ready = threading.Event()
        self._stop_event = threading.Event()
        self._health_check_task = None
        self._consecutive_ping_failures = 0
        self._max_ping_failures = 3  # Allow up to 3 consecutive ping failures
        self._connecting = False  # Flag to prevent concurrent connection attempts
        self._last_connection_attempt = 0
        
        #self._log_event("INIT", "Enhanced Zerodha WebSocket client initialized")
        self.logger.info("✅ Enhanced Zerodha WebSocket client initialized")
    
    def _log_event(self, event_type: str, message: str, data: Any = None):
        """Log an event for visibility"""
        event = {
            'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3],
            'type': event_type,
            'message': message,
            'data': data
        }
        self.event_log.append(event)
        
        if self.enable_verbose_logging:
            # Color coding for different event types
            color_map = {
                'CONNECT': '🔌',
                'DISCONNECT': '🔌',
                'SUBSCRIBE': '📡',
                'UNSUBSCRIBE': '📴',
                'DATA': '📊',
                'PING': '💓',
                'ERROR': '❌',
                'RECONNECT': '🔄',
                'INIT': '🚀',
                'HEALTH': '🏥',
                'BATCH': '📦',
                'MAPPING': '🗺️',
                'CONFIG': '⚙️'
            }
            icon = color_map.get(event_type, '📝')
            self.logger.info(f"{icon} [{event['timestamp']}] {event_type}: {message}")
    
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
        
        #self._log_event("MAPPING", f"Updated token exchange mapping for {len(token_exchange_map)} tokens")
        self.logger.debug(f"✅ Updated token exchange mapping for {len(token_exchange_map)} tokens")
    
    def start(self) -> bool:
        """Start the WebSocket client in a separate thread"""
        if self.running:
            self.logger.debug("✅ WebSocket client already running")
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
                    self.logger.debug("🔄 WebSocket thread cancelled gracefully")
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
                    
                    self.logger.info(" WebSocket thread cleanup completed")
            
            # Start the thread
            self.ws_thread = threading.Thread(target=_run_in_thread, daemon=True, name="ZerodhaWS")
            self.ws_thread.start()
            
            # Wait for thread to start
            time.sleep(0.5)
            
            self.logger.debug("🚀 WebSocket client started")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error starting WebSocket client: {e}")
            self.running = False
            return False
    
    def stop(self):
        """Stop the WebSocket client"""
        try:
            self.logger.debug("🛑 Stopping WebSocket client...")
            
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
            
            self.logger.debug("🛑 WebSocket client stopped")
            
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
        """Subscribe to tokens with batching support"""
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
        
        # Check Zerodha's limit of 3000 instruments per connection
        total_after_subscription = len(self.subscribed_tokens) + len(tokens)
        if total_after_subscription > self.MAX_INSTRUMENTS_PER_CONNECTION:
            self.logger.error(f"❌ Cannot subscribe to {len(tokens)} tokens. Would exceed Zerodha's limit of {self.MAX_INSTRUMENTS_PER_CONNECTION} instruments per connection.")
            self.logger.error(f"Current subscriptions: {len(self.subscribed_tokens)}, Requested: {len(tokens)}, Total would be: {total_after_subscription}")
            return
        
        # Add to pending subscriptions for batch processing
        with self.lock:
            for token in tokens:
                self.pending_subscriptions.append((token, mode))
        
        #self._log_event("SUBSCRIBE", f"Queued {len(tokens)} tokens for subscription in {mode} mode", 
        #               {'count': len(tokens), 'mode': mode})
        
        # Trigger subscription processing
        if self.loop and not self.loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._process_pending_subscriptions(), self.loop)
    
    async def _process_pending_subscriptions(self):
        """Process pending subscriptions in batches"""
        consecutive_failures = 0
        
        while self.pending_subscriptions:
            # Wait for connection
            if not await self._ensure_connected():
                consecutive_failures += 1
                if consecutive_failures > 3:
                    self.logger.error("❌ Multiple connection failures, clearing pending subscriptions")
                    with self.lock:
                        self.pending_subscriptions.clear()
                    break
                await asyncio.sleep(min(2 * consecutive_failures, 10))  # Exponential backoff
                continue
            
            consecutive_failures = 0  # Reset on successful connection
            
            # Process batch
            batch_tokens = []
            batch_mode = None
            
            with self.lock:
                # Get up to MAX_TOKENS_PER_SUBSCRIBE tokens with same mode
                while self.pending_subscriptions and len(batch_tokens) < self.MAX_TOKENS_PER_SUBSCRIBE:
                    token, mode = self.pending_subscriptions[0]
                    if batch_mode is None:
                        batch_mode = mode
                    elif batch_mode != mode:
                        break  # Different mode, process in next batch
                    
                    self.pending_subscriptions.popleft()
                    batch_tokens.append(token)
            
            if batch_tokens:
                success = await self._subscribe_batch(batch_tokens, batch_mode)
                if not success:
                    # Re-queue failed tokens
                    with self.lock:
                        for token in batch_tokens:
                            self.pending_subscriptions.append((token, batch_mode))
                    await asyncio.sleep(5)  # Wait longer on failure
                else:
                    await asyncio.sleep(self.SUBSCRIPTION_DELAY)  # Normal delay between batches
    
    async def _subscribe_batch(self, tokens: List[int], mode: str) -> bool:
        """Subscribe to a batch of tokens"""
        try:
            # Ensure we're connected before subscribing
            if not await self._ensure_connected():
                self.logger.warning("Not connected to WebSocket")
                return False
            
            # Subscribe to tokens
            sub_msg = {
                "a": "subscribe",
                "v": tokens
            }
            
            if not await self._send_json(sub_msg):
                self.logger.error("Failed to send subscription message")
                return False
            
            self.logger.debug(f"✅ Subscribed to batch of {len(tokens)} tokens")
            
            # Wait for subscription to be processed by Zerodha
            await asyncio.sleep(1.0)
            
            # Set mode for the batch
            mode_msg = {
                "a": "mode",
                "v": [mode, tokens]
            }
            
            if await self._send_json(mode_msg):
                with self.lock:
                    for token in tokens:
                        self.mode_map[token] = mode
                        self.subscribed_tokens.add(token)
                self.logger.debug(f"✅ Set mode {mode} for {len(tokens)} tokens")
                
                # Additional delay after mode setting - important for large batches
                await asyncio.sleep(1.0)
                    
                return True
            else:
                self.logger.warning(f"⚠️ Failed to set mode for batch")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Batch subscription failed: {e}")
            return False
    
    async def _ensure_connected(self) -> bool:
        """Ensure WebSocket is connected"""
        if self.connected and self._is_websocket_open():
            return True
        
        return await self._connect()
    
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
            
            self.logger.debug(f"✅ Unsubscribed from {len(tokens)} tokens")
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
        
        # Prevent concurrent connection attempts
        if self._connecting:
            self.logger.debug("Connection already in progress")
            return False
            
        # Rate limit connection attempts (more aggressive)
        current_time = time.time()
        if current_time - self._last_connection_attempt < 5:  # Min 5 seconds between attempts
            self.logger.debug(f"Rate limiting connection attempts (last attempt {current_time - self._last_connection_attempt:.1f}s ago)")
            return False
            
        self._connecting = True
        self._last_connection_attempt = current_time
        
        try:
            self._log_event("CONNECT", f"Attempting connection (attempt {self.reconnect_attempts + 1}/{self.max_reconnect_attempts})")
            
            # Close existing connection if any
            if self.websocket:
                try:
                    await self.websocket.close()
                except Exception:
                    pass
                self.websocket = None
            
            # Create new connection following Zerodha API specifications
            # URL format: wss://ws.kite.trade?api_key=xxx&access_token=xxx
            
            self.websocket = await asyncio.wait_for(
                websockets.client.connect(
                    self.ws_url,
                    ping_interval=self.PING_INTERVAL,  # None - let Zerodha handle heartbeats
                    ping_timeout=self.PING_TIMEOUT,
                    close_timeout=5,
                    max_size=self.MAX_MESSAGE_SIZE,
                    compression=None,  # Disable compression for binary data
                    extra_headers={
                        'User-Agent': 'OpenAlgo-ZerodhaClient/1.0'
                    }
                ),
                timeout=self.CONNECT_TIMEOUT
            )
            
            # Verify connection
            if self.websocket and self._is_websocket_open():
                self.connected = True
                self.reconnect_attempts = 0
                self.reconnect_delay = 2
                self._connection_ready.set()
                self.last_message_time = time.time()
                self.last_ping_time = time.time()
                self._consecutive_ping_failures = 0  # Reset ping failures on new connection
                
                self._log_event("CONNECT", "WebSocket connected successfully")
                
                # Start health check
                if not self._health_check_task or self._health_check_task.done():
                    self._health_check_task = asyncio.create_task(self._health_check_loop())
                
                # Trigger on_connect callback
                if self.on_connect:
                    try:
                        self.on_connect()
                    except Exception as e:
                        self.logger.error(f"❌ Error in on_connect callback: {e}")
                
                # Re-subscribe to previously subscribed tokens
                await self._resubscribe_all()
                
                return True
            else:
                raise Exception("Failed to establish WebSocket connection")
            
        except Exception as e:
            self.connected = False
            self.reconnect_attempts += 1
            self.reconnect_delay = min(self.reconnect_delay * 1.5, self.max_reconnect_delay)
            
            error_msg = str(e) if str(e) else "Unknown connection error"
            self.logger.error(f"❌ Connection failed (attempt {self.reconnect_attempts}): {error_msg}")
            
            if self.on_error:
                try:
                    self.on_error(e)
                except Exception:
                    pass
            
            return False
        finally:
            self._connecting = False
    
    async def _disconnect(self):
        """Disconnect from WebSocket"""
        try:
            self.connected = False
            
            if self._health_check_task:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
            
            if self.websocket:
                try:
                    await self.websocket.close()
                except Exception as e:
                    self.logger.debug(f"Error closing WebSocket: {e}")
                
                self.websocket = None
            
            self.logger.debug("🔌 WebSocket disconnected")
            
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
            self.logger.debug(f"📤 Sent: {message_str[:100]}...")  # Log first 100 chars
            return True
        except Exception as e:
            self.logger.error(f"❌ Error sending message: {e}")
            self.connected = False
            self.error_count += 1
            return False
    
    async def _run_forever(self):
        """Main WebSocket message loop with improved error handling"""
        self.logger.debug("🚀 Starting WebSocket message loop...")
        
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
                            timeout=self.connection_timeout
                        )
                        self.last_message_time = time.time()
                        await self._process_message(message)
                        
                    except asyncio.TimeoutError:
                        self.logger.warning("⚠️ Message receive timeout, connection may be dead")
                        self.connected = False
                    
                    except websockets.exceptions.ConnectionClosed as e:
                        #self.logger.warning(f"🔌 Connection closed: {e}")
                        self.connected = False
                        if self.running:  # Only reconnect if we're still supposed to be running
                            await asyncio.sleep(2)  # Brief delay before reconnection
                    
                    except Exception as e:
                        self.logger.error(f"❌ Error receiving message: {e}")
                        self.connected = False
                        self.error_count += 1
                
                except asyncio.CancelledError:
                    self.logger.debug("🔄 Message loop cancelled")
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
            self.logger.debug("🔄 WebSocket message loop cancelled")
        except Exception as e:
            self.logger.error(f"❌ Unexpected error in message loop: {e}")
        finally:
            # Cleanup on exit
            try:
                await self._disconnect()
            except Exception as e:
                self.logger.debug(f"Error during final disconnect: {e}")
            
            self.logger.debug("🛑 WebSocket message loop stopped")
    
    async def _process_message(self, message):
        """Process incoming WebSocket message"""
        try:
            self.message_count += 1
            
            if isinstance(message, bytes):
                # Handle binary market data
                if len(message) == 1:
                    # Zerodha heartbeat - 1 byte message to keep connection alive
                    self.last_heartbeat_time = time.time()
                    self.logger.debug("💓 Zerodha heartbeat received")
                    return
                
                # Parse binary data
                ticks = self._parse_binary_message(message)
                if ticks:
                    self.tick_count += len(ticks)
                    
                    # Log periodically
                    if self.tick_count % 1000 == 0:
                        self._log_event("DATA", f"Processed {self.tick_count:,} total ticks", 
                                       {'rate': f"{1000 / (time.time() - self.last_message_time):.1f} ticks/sec" if self.last_message_time else 'N/A'})
                    
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
                        self.logger.debug(f"📊 Order update: {data}")
                    else:
                        self.logger.debug(f"📝 JSON message: {data}")
                        
                except json.JSONDecodeError:
                    self.logger.debug(f"📝 Non-JSON text: {message}")
            
        except Exception as e:
            self.logger.error(f"❌ Error processing message: {e}")
            self.error_count += 1
    
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
    
    async def _resubscribe_all(self):
        """Re-subscribe to all previously subscribed tokens after reconnection"""
        if not self.subscribed_tokens:
            return
        
        self.logger.debug(f"🔄 Re-subscribing to {len(self.subscribed_tokens)} tokens...")
        
        # Group tokens by mode
        mode_groups = {}
        with self.lock:
            for token in self.subscribed_tokens:
                mode = self.mode_map.get(token, self.MODE_QUOTE)
                if mode not in mode_groups:
                    mode_groups[mode] = []
                mode_groups[mode].append(token)
        
        # Re-subscribe in batches
        for mode, tokens in mode_groups.items():
            for i in range(0, len(tokens), self.MAX_TOKENS_PER_SUBSCRIBE):
                batch = tokens[i:i + self.MAX_TOKENS_PER_SUBSCRIBE]
                await self._subscribe_batch(batch, mode)
                await asyncio.sleep(self.SUBSCRIPTION_DELAY)
    
    async def _health_check_loop(self):
        """Monitor connection health and trigger reconnection if needed"""
        while self.running and not self._stop_event.is_set():
            try:
                await asyncio.sleep(self.health_check_interval)
                
                if not self.connected or not self._is_websocket_open():
                    continue
                
                # Check connection health using Zerodha's heartbeats
                current_time = time.time()
                
                # Check for Zerodha heartbeats (should come every few seconds)
                if self.last_heartbeat_time:
                    time_since_heartbeat = current_time - self.last_heartbeat_time
                    if time_since_heartbeat > 60:  # No heartbeat for 60 seconds
                        self.logger.warning(f"⚠️ No heartbeat from Zerodha for {time_since_heartbeat:.1f}s")
                        self.connected = False
                        continue
                
                # Check for data messages (only if we have subscriptions)
                if self.last_message_time and len(self.subscribed_tokens) > 0:
                    time_since_last_message = current_time - self.last_message_time
                    # Allow longer timeout during high subscription volume
                    timeout = self.connection_timeout + (len(self.pending_subscriptions) * 2)
                    if time_since_last_message > timeout:
                        self.logger.warning(f"⚠️ No data messages for {time_since_last_message:.1f}s with {len(self.subscribed_tokens)} subscriptions")
                        # Only disconnect if we're not actively subscribing
                        if not self._connecting and len(self.pending_subscriptions) == 0:
                            self.connected = False
                            continue
                
                # Reset consecutive failures since we're still connected
                self._consecutive_ping_failures = 0
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"❌ Error in health check: {e}")
    
    def get_statistics(self) -> Dict:
        """Get connection statistics"""
        return {
            'connected': self.is_connected(),
            'messages_received': self.message_count,
            'ticks_processed': self.tick_count,
            'errors': self.error_count,
            'subscribed_tokens': len(self.subscribed_tokens),
            'pending_subscriptions': len(self.pending_subscriptions),
            'reconnect_attempts': self.reconnect_attempts,
            'last_message_time': self.last_message_time,
            'uptime': time.time() - (self.last_message_time or time.time()) if self.connected else 0,
            'recent_events': list(self.event_log)[-10:]  # Last 10 events
        }
    
    def get_event_log(self) -> List[Dict]:
        """Get the event log for debugging"""
        return list(self.event_log)
    
    def set_verbose_logging(self, enabled: bool):
        """Enable or disable verbose event logging"""
        self.enable_verbose_logging = enabled
        self._log_event("CONFIG", f"Verbose logging {'enabled' if enabled else 'disabled'}")
    
    def wait_for_connection(self, timeout: float = 10.0) -> bool:
        """Wait for connection to be established"""
        return self._connection_ready.wait(timeout)