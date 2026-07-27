from utils.logging import get_logger

logger = get_logger(__name__)

"""
Enhanced Zerodha WebSocket client with improved stability for handling 1800+ symbols.

Uses sync websocket-client (same as Flattrade/Angel/Dhan) to avoid asyncio event loop
conflicts with eventlet in gunicorn+eventlet deployments.

Implements:
- Better connection management with keepalive handling
- Batch subscription to reduce message overhead
- Automatic reconnection with state recovery
- Connection health monitoring
- Optimized for high-volume symbol subscriptions
"""
import json
import ssl
import struct
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Any

import websocket


class ZerodhaWebSocket:
    """
    Enhanced WebSocket client for Zerodha's market data streaming API.
    Optimized for handling large numbers of symbol subscriptions (1800+).

    Uses sync websocket-client instead of async websockets to avoid
    asyncio event loop conflicts with eventlet in gunicorn+eventlet.
    """

    # Subscription modes
    MODE_LTP = "ltp"
    MODE_QUOTE = "quote"
    MODE_FULL = "full"

    # Connection settings
    KEEPALIVE_INTERVAL = 30
    PING_INTERVAL = 30
    PING_TIMEOUT = 10

    # Subscription batching (Zerodha supports up to 3000 instruments per connection)
    MAX_TOKENS_PER_SUBSCRIBE = 200
    SUBSCRIPTION_DELAY = 2.0
    MAX_INSTRUMENTS_PER_CONNECTION = 3000

    # Reconnection settings
    RECONNECT_MAX_DELAY = 60
    RECONNECT_MAX_TRIES = 50

    # Health check
    DATA_TIMEOUT = 90

    def __init__(
        self, api_key: str, access_token: str, on_ticks: Callable[[list[dict]], None] = None
    ):
        """Initialize the Zerodha WebSocket client"""
        self.api_key = api_key
        self.access_token = access_token
        self.on_ticks = on_ticks
        self.ws: websocket.WebSocketApp | None = None
        self.connected = False
        self.running = False
        self._ws_thread: threading.Thread | None = None
        self.logger = get_logger(__name__)
        self.lock = threading.Lock()

        # Subscription management
        self.subscribed_tokens: set[int] = set()
        self.mode_map: dict[int, str] = {}
        self.pending_subscriptions: deque = deque()
        self._subscription_thread: threading.Thread | None = None

        # Exchange mapping for tokens
        self.token_exchange_map: dict[int, str] = {}

        # Connection management
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = self.RECONNECT_MAX_TRIES
        self.reconnect_delay = 2
        self.max_reconnect_delay = self.RECONNECT_MAX_DELAY

        # Health monitoring
        self.last_message_time: float | None = None
        self.last_heartbeat_time: float | None = None
        self._health_check_thread: threading.Thread | None = None

        # Event tracking
        self.event_log: deque = deque(maxlen=100)

        # Callback handlers
        self.on_connect: Callable | None = None
        self.on_disconnect: Callable | None = None
        self.on_error: Callable | None = None

        # WebSocket URL
        self.ws_url = f"wss://ws.kite.trade?api_key={self.api_key}&access_token={self.access_token}"

        # Statistics
        self.message_count = 0
        self.tick_count = 0
        self.error_count = 0

        # Connection state
        self._connection_ready = threading.Event()
        self._stop_event = threading.Event()

        self.logger.info("Enhanced Zerodha WebSocket client initialized (sync)")

    def set_token_exchange_mapping(self, token_exchange_map: dict[int, str]):
        """Set the token to exchange mapping."""
        with self.lock:
            self.token_exchange_map.update(token_exchange_map)
        self.logger.debug(f"Updated token exchange mapping for {len(token_exchange_map)} tokens")

    def start(self) -> bool:
        """Start the WebSocket client in a separate thread"""
        if self.running:
            self.logger.debug("WebSocket client already running")
            return True

        try:
            self.running = True
            self._stop_event.clear()
            self._connection_ready.clear()

            self._ws_thread = threading.Thread(
                target=self._run_websocket, daemon=True, name="ZerodhaWS"
            )
            self._ws_thread.start()

            self.logger.info("Zerodha WebSocket client started")
            return True

        except Exception as e:
            self.logger.error(f"Error starting WebSocket client: {e}")
            self.running = False
            return False

    def _run_websocket(self):
        """Run the WebSocket connection with reconnection logic"""
        while self.running and not self._stop_event.is_set():
            try:
                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self._on_ws_open,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_ws_close,
                )

                self.ws.run_forever(
                    sslopt={"cert_reqs": ssl.CERT_NONE},
                    ping_interval=self.PING_INTERVAL,
                    ping_timeout=self.PING_TIMEOUT,
                )

            except Exception as e:
                self.logger.error(f"WebSocket run_forever error: {e}")

            self.connected = False

            if not self.running or self._stop_event.is_set():
                break

            self.reconnect_attempts += 1
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                self.logger.error("Max reconnect attempts reached")
                break

            delay = min(self.reconnect_delay * (1.5 ** self.reconnect_attempts), self.max_reconnect_delay)
            self.logger.info(f"Reconnecting in {delay:.0f}s (attempt {self.reconnect_attempts})...")
            time.sleep(delay)

        self.logger.info("WebSocket thread exited")

    def stop(self):
        """Stop the WebSocket client"""
        try:
            self.logger.debug("Stopping WebSocket client...")
            self.running = False
            self._stop_event.set()

            if self.ws:
                try:
                    self.ws.close()
                except Exception as e:
                    self.logger.debug(f"Error closing WebSocket: {e}")

            # Don't join threads - daemon threads stop on their own
            # join() causes eventlet.timeout.Timeout in gunicorn+eventlet
            self._ws_thread = None
            self._health_check_thread = None
            self._subscription_thread = None

            self.connected = False
            self.logger.debug("WebSocket client stopped")

        except Exception as e:
            self.logger.error(f"Error stopping WebSocket client: {e}")

    def subscribe_tokens(self, tokens: list[int], mode: str = MODE_QUOTE):
        """Subscribe to tokens with batching support"""
        if not self.running:
            self.logger.error("WebSocket client not running. Call start() first.")
            return

        if not tokens:
            return

        try:
            tokens = [int(token) for token in tokens]
        except (ValueError, TypeError) as e:
            self.logger.error(f"Invalid token format: {e}")
            return

        total_after = len(self.subscribed_tokens) + len(tokens)
        if total_after > self.MAX_INSTRUMENTS_PER_CONNECTION:
            self.logger.error(
                f"Cannot subscribe to {len(tokens)} tokens. Would exceed limit of {self.MAX_INSTRUMENTS_PER_CONNECTION}."
            )
            return

        with self.lock:
            for token in tokens:
                self.pending_subscriptions.append((token, mode))

        # Process subscriptions in a separate thread
        if not self._subscription_thread or not self._subscription_thread.is_alive():
            self._subscription_thread = threading.Thread(
                target=self._process_pending_subscriptions, daemon=True
            )
            self._subscription_thread.start()

    def _process_pending_subscriptions(self):
        """Process pending subscriptions in batches"""
        consecutive_failures = 0

        while self.pending_subscriptions and self.running:
            if not self.connected:
                consecutive_failures += 1
                if consecutive_failures > 3:
                    self.logger.error("Multiple connection failures, clearing pending subscriptions")
                    with self.lock:
                        self.pending_subscriptions.clear()
                    break
                time.sleep(min(2 * consecutive_failures, 10))
                continue

            consecutive_failures = 0

            # Get a batch of tokens with the same mode
            batch_tokens = []
            batch_mode = None

            with self.lock:
                while self.pending_subscriptions and len(batch_tokens) < self.MAX_TOKENS_PER_SUBSCRIBE:
                    token, mode = self.pending_subscriptions[0]
                    if batch_mode is None:
                        batch_mode = mode
                    elif batch_mode != mode:
                        break
                    self.pending_subscriptions.popleft()
                    batch_tokens.append(token)

            if batch_tokens:
                success = self._subscribe_batch(batch_tokens, batch_mode)
                if not success:
                    with self.lock:
                        for token in batch_tokens:
                            self.pending_subscriptions.append((token, batch_mode))
                    time.sleep(5)
                else:
                    time.sleep(self.SUBSCRIPTION_DELAY)

    def _subscribe_batch(self, tokens: list[int], mode: str) -> bool:
        """Subscribe to a batch of tokens"""
        try:
            if not self.connected or not self.ws:
                return False

            # Subscribe
            sub_msg = json.dumps({"a": "subscribe", "v": tokens})
            self.ws.send(sub_msg)
            self.logger.debug(f"Subscribed to batch of {len(tokens)} tokens")

            time.sleep(1.0)

            # Set mode
            mode_msg = json.dumps({"a": "mode", "v": [mode, tokens]})
            self.ws.send(mode_msg)

            with self.lock:
                for token in tokens:
                    self.mode_map[token] = mode
                    self.subscribed_tokens.add(token)

            self.logger.debug(f"Set mode {mode} for {len(tokens)} tokens")
            time.sleep(1.0)
            return True

        except Exception as e:
            self.logger.error(f"Batch subscription failed: {e}")
            return False

    def unsubscribe(self, tokens: list[int]) -> bool:
        """Unsubscribe from tokens"""
        try:
            if not self.connected or not self.ws:
                return False

            unsub_msg = json.dumps({"a": "unsubscribe", "v": tokens})
            self.ws.send(unsub_msg)

            with self.lock:
                for token in tokens:
                    self.subscribed_tokens.discard(token)
                    self.mode_map.pop(token, None)
                    self.token_exchange_map.pop(token, None)

            self.logger.debug(f"Unsubscribed from {len(tokens)} tokens")
            return True

        except Exception as e:
            self.logger.error(f"Error unsubscribing: {e}")
            return False

    def wait_for_connection(self, timeout: float = 15.0) -> bool:
        """Wait for WebSocket connection to be established"""
        return self._connection_ready.wait(timeout=timeout)

    def is_connected(self) -> bool:
        """Check if WebSocket is connected"""
        return self.connected and self.running

    # WebSocket callbacks
    def _on_ws_open(self, ws):
        """Called when WebSocket connection is opened"""
        self.connected = True
        self.reconnect_attempts = 0
        self.reconnect_delay = 2
        self.last_message_time = time.time()
        self._connection_ready.set()

        self.logger.info("Zerodha WebSocket connected")

        # Start health check
        self._start_health_check()

        # Trigger callback
        if self.on_connect:
            try:
                self.on_connect()
            except Exception as e:
                self.logger.error(f"Error in on_connect callback: {e}")

        # Re-subscribe to previously subscribed tokens
        self._resubscribe_all()

    def _on_ws_message(self, ws, message):
        """Called for both binary and text messages"""
        self.last_message_time = time.time()
        self.message_count += 1

        try:
            if isinstance(message, bytes):
                # Handle binary market data
                if len(message) == 1:
                    # Zerodha heartbeat - 1 byte
                    self.last_heartbeat_time = time.time()
                    return

                ticks = self._parse_binary_message(message)
                if ticks:
                    self.tick_count += len(ticks)
                    if self.on_ticks:
                        try:
                            self.on_ticks(ticks)
                        except Exception as e:
                            self.logger.error(f"Error in on_ticks callback: {e}")

            elif isinstance(message, str):
                try:
                    data = json.loads(message)
                    msg_type = data.get("type", "unknown")
                    if msg_type == "error":
                        self.logger.error(f"WebSocket error: {data.get('data', '')}")
                    else:
                        self.logger.debug(f"JSON message: {data}")
                except json.JSONDecodeError:
                    self.logger.debug(f"Non-JSON text: {message[:100]}")

        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
            self.error_count += 1

    def _on_ws_error(self, ws, error):
        """Called on WebSocket error"""
        self.logger.error(f"WebSocket error: {error}")
        self.connected = False
        self.error_count += 1
        if self.on_error:
            try:
                self.on_error(error)
            except Exception:
                pass

    def _on_ws_close(self, ws, close_status_code, close_msg):
        """Called when WebSocket is closed"""
        self.logger.info(f"WebSocket closed (code={close_status_code}, msg={close_msg})")
        self.connected = False
        if self.on_disconnect:
            try:
                self.on_disconnect()
            except Exception as e:
                self.logger.error(f"Error in on_disconnect callback: {e}")

    # Health check
    def _start_health_check(self):
        if self._health_check_thread and self._health_check_thread.is_alive():
            return
        self._health_check_thread = threading.Thread(
            target=self._health_check_loop, daemon=True
        )
        self._health_check_thread.start()

    def _health_check_loop(self):
        while self.running and self.connected:
            time.sleep(self.KEEPALIVE_INTERVAL)
            if not self.running or not self.connected:
                break
            if self.last_message_time:
                elapsed = time.time() - self.last_message_time
                if elapsed > self.DATA_TIMEOUT:
                    self.logger.error(
                        f"Data stall detected - no data for {elapsed:.1f}s. Forcing reconnect..."
                    )
                    if self.ws:
                        try:
                            self.ws.close()
                        except Exception:
                            pass
                    break

    def _resubscribe_all(self):
        """Re-subscribe to all previously subscribed tokens"""
        with self.lock:
            if not self.subscribed_tokens:
                return
            tokens_by_mode: dict[str, list[int]] = {}
            for token in self.subscribed_tokens:
                mode = self.mode_map.get(token, self.MODE_QUOTE)
                if mode not in tokens_by_mode:
                    tokens_by_mode[mode] = []
                tokens_by_mode[mode].append(token)

        for mode, tokens in tokens_by_mode.items():
            for i in range(0, len(tokens), self.MAX_TOKENS_PER_SUBSCRIBE):
                batch = tokens[i:i + self.MAX_TOKENS_PER_SUBSCRIBE]
                try:
                    sub_msg = json.dumps({"a": "subscribe", "v": batch})
                    self.ws.send(sub_msg)
                    time.sleep(0.5)
                    mode_msg = json.dumps({"a": "mode", "v": [mode, batch]})
                    self.ws.send(mode_msg)
                    time.sleep(self.SUBSCRIPTION_DELAY)
                    self.logger.info(f"Re-subscribed batch of {len(batch)} tokens in {mode} mode")
                except Exception as e:
                    self.logger.error(f"Error re-subscribing batch: {e}")

    # Binary message parsing (unchanged from original)
    def _parse_binary_message(self, data: bytes) -> list[dict]:
        """Parse binary message according to Zerodha specification"""
        try:
            if len(data) < 4:
                return []

            num_packets = struct.unpack(">H", data[0:2])[0]
            packets = []
            offset = 2

            for _ in range(num_packets):
                if offset + 2 > len(data):
                    break
                packet_length = struct.unpack(">H", data[offset:offset + 2])[0]
                offset += 2
                if offset + packet_length > len(data):
                    break
                packet_data = data[offset:offset + packet_length]
                tick = self._parse_packet(packet_data)
                if tick:
                    packets.append(tick)
                offset += packet_length

            return packets

        except Exception as e:
            self.logger.error(f"Error parsing binary message: {e}")
            return []

    def _parse_packet(self, packet: bytes) -> dict | None:
        """Parse individual packet with exchange info."""
        try:
            if len(packet) < 8:
                return None

            instrument_token = struct.unpack(">I", packet[0:4])[0]
            last_price_paise = struct.unpack(">i", packet[4:8])[0]
            last_price = last_price_paise / 100.0

            if len(packet) == 8:
                mode = self.MODE_LTP
            elif len(packet) == 44:
                mode = self.MODE_QUOTE
            elif len(packet) >= 184:
                mode = self.MODE_FULL
            else:
                mode = self.mode_map.get(instrument_token, self.MODE_QUOTE)

            exchange = None
            with self.lock:
                exchange = self.token_exchange_map.get(instrument_token)

            tick = {
                "instrument_token": instrument_token,
                "last_traded_price": last_price,
                "last_price": last_price,
                "mode": mode,
                "timestamp": int(time.time() * 1000),
            }

            if exchange:
                tick["source_exchange"] = exchange

            if len(packet) >= 44:
                try:
                    fields = struct.unpack(">11i", packet[0:44])
                    tick.update({
                        "instrument_token": fields[0],
                        "last_traded_price": fields[1] / 100.0,
                        "last_price": fields[1] / 100.0,
                        "last_traded_quantity": fields[2],
                        "average_traded_price": fields[3] / 100.0,
                        "average_price": fields[3] / 100.0,
                        "volume_traded": fields[4],
                        "volume": fields[4],
                        "total_buy_quantity": fields[5],
                        "total_sell_quantity": fields[6],
                        "open_price": fields[7] / 100.0,
                        "high_price": fields[8] / 100.0,
                        "low_price": fields[9] / 100.0,
                        "close_price": fields[10] / 100.0,
                    })

                    tick["ohlc"] = {
                        "open": fields[7] / 100.0,
                        "high": fields[8] / 100.0,
                        "low": fields[9] / 100.0,
                        "close": fields[10] / 100.0,
                    }
                except struct.error as e:
                    self.logger.debug(f"Could not parse extended quote: {e}")

            if len(packet) >= 184:
                try:
                    tick["price_change"] = struct.unpack(">i", packet[44:48])[0] / 100.0

                    depth_offset = 64
                    buy_depth = []
                    sell_depth = []

                    for i in range(5):
                        base = depth_offset + (i * 12)
                        if base + 12 <= len(packet):
                            qty = struct.unpack(">I", packet[base:base + 4])[0]
                            price = struct.unpack(">I", packet[base + 4:base + 8])[0] / 100.0
                            orders = struct.unpack(">H", packet[base + 8:base + 10])[0]
                            buy_depth.append({"quantity": qty, "price": price, "orders": orders})

                    for i in range(5):
                        base = depth_offset + 60 + (i * 12)
                        if base + 12 <= len(packet):
                            qty = struct.unpack(">I", packet[base:base + 4])[0]
                            price = struct.unpack(">I", packet[base + 4:base + 8])[0] / 100.0
                            orders = struct.unpack(">H", packet[base + 8:base + 10])[0]
                            sell_depth.append({"quantity": qty, "price": price, "orders": orders})

                    tick["depth"] = {"buy": buy_depth, "sell": sell_depth}

                    if len(packet) >= 184:
                        try:
                            tick["exchange_timestamp"] = struct.unpack(">I", packet[60:64])[0]
                            oi_offset = 184 - 4
                            if oi_offset + 4 <= len(packet):
                                tick["open_interest"] = struct.unpack(">I", packet[oi_offset:oi_offset + 4])[0]
                        except struct.error:
                            pass

                except struct.error as e:
                    self.logger.debug(f"Could not parse full mode data: {e}")

            return tick

        except Exception as e:
            self.logger.error(f"Error parsing packet: {e}")
            return None
