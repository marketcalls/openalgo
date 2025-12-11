"""
Samco WebSocket Client Implementation
Handles connection to Samco's Broadcast API for streaming market data
Based on official Samco Python SDK pattern
"""
import json
import logging
import threading
import time
import websocket
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import unquote

from utils.logging import get_logger

logger = get_logger(__name__)


class SamcoWebSocket:
    """
    Samco WebSocket client for real-time market data streaming

    Uses Samco's Broadcast API at wss://stream.stocknote.com
    """

    # WebSocket URL - Official Samco streaming endpoint
    WS_URL = "wss://stream.stocknote.com"

    # Connection constants
    CONNECTION_TIMEOUT = 15
    THREAD_JOIN_TIMEOUT = 5

    # Heartbeat constants
    HEARTBEAT_INTERVAL = 30
    HEARTBEAT_TIMEOUT = 120
    PING_INTERVAL = 30
    PING_TIMEOUT = 10

    # Subscription modes
    LTP_MODE = 1
    QUOTE_MODE = 2
    DEPTH_MODE = 3

    # Streaming types - Samco uses "quote2" for streaming
    STREAMING_TYPE_QUOTE = "quote2"
    STREAMING_TYPE_MARKETDATA = "marketDepth"

    # Request types
    REQUEST_SUBSCRIBE = "subscribe"
    REQUEST_UNSUBSCRIBE = "unsubscribe"

    def __init__(self, session_token: str, user_id: str,
                 on_message: Optional[Callable] = None,
                 on_error: Optional[Callable] = None,
                 on_close: Optional[Callable] = None,
                 on_open: Optional[Callable] = None,
                 on_data: Optional[Callable] = None):
        """
        Initialize Samco WebSocket client

        Args:
            session_token: Session token from login API
            user_id: User ID for authentication
            on_message: Callback for text messages
            on_error: Callback for connection errors
            on_close: Callback for connection close
            on_open: Callback for connection open
            on_data: Callback for market data
        """
        # Authentication credentials
        # URL-decode the session token if it contains encoded characters
        self.session_token = unquote(session_token) if session_token else session_token
        self.user_id = user_id

        # Connection state
        self.ws = None
        self.ws_thread = None
        self.running = False
        self.connected = False

        # Callbacks
        self._on_message_callback = on_message
        self._on_error_callback = on_error
        self._on_close_callback = on_close
        self._on_open_callback = on_open
        self._on_data_callback = on_data

        # Subscription tracking
        self.subscribed_symbols = {}  # {symbol_key: {symbol, exchange, mode}}
        self.input_request_dict = {}  # For resubscription
        self.RESUBSCRIBE_FLAG = False

        # Heartbeat management
        self._heartbeat_thread = None
        self._last_message_time = None
        self._heartbeat_lock = threading.Lock()

        # Reconnection settings
        self.max_retry_attempts = 5
        self.retry_delay = 5
        self.retry_multiplier = 2
        self.current_retry_attempt = 0
        self.DISCONNECT_FLAG = False

        # Logger
        self.logger = get_logger("samco_websocket")

    # Callback properties for compatibility with adapter
    @property
    def on_open(self):
        return self._on_open_callback

    @on_open.setter
    def on_open(self, callback):
        self._on_open_callback = callback

    @property
    def on_message(self):
        return self._on_message_callback

    @on_message.setter
    def on_message(self, callback):
        self._on_message_callback = callback

    @property
    def on_error(self):
        return self._on_error_callback

    @on_error.setter
    def on_error(self, callback):
        self._on_error_callback = callback

    @property
    def on_close(self):
        return self._on_close_callback

    @on_close.setter
    def on_close(self, callback):
        self._on_close_callback = callback

    @property
    def on_data(self):
        return self._on_data_callback

    @on_data.setter
    def on_data(self, callback):
        self._on_data_callback = callback

    def connect(self) -> bool:
        """
        Establish WebSocket connection with authentication

        Returns:
            bool: True if connection successful, False otherwise
        """
        if self.running:
            self.logger.warning("Already connected or connecting")
            return True

        try:
            self._initialize_connection()
            return self._wait_for_connection()
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            self.close_connection()
            return False

    def _initialize_connection(self) -> None:
        """Initialize WebSocket connection with authentication headers"""
        self.running = True
        self.DISCONNECT_FLAG = False

        # Build headers with session token
        # Log token info for debugging (first/last 4 chars only for security)
        token_preview = f"{self.session_token[:4]}...{self.session_token[-4:]}" if len(self.session_token) > 8 else "***"
        self.logger.info(f"Connecting to {self.WS_URL} with token: {token_preview}")

        # Headers as dict - matching official Samco SDK format
        headers = {
            'x-session-token': self.session_token
        }

        # Enable trace for debugging (matching official SDK)
        websocket.enableTrace(True)

        self.ws = websocket.WebSocketApp(
            self.WS_URL,
            header=headers,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )

        self.ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
        self.ws_thread.start()

    def _wait_for_connection(self) -> bool:
        """Wait for WebSocket connection to be established"""
        start_time = time.time()

        while time.time() - start_time < self.CONNECTION_TIMEOUT:
            if self.connected:
                self.logger.info("Samco WebSocket connected successfully")
                return True
            time.sleep(0.1)

        self.logger.error("Connection timeout")
        self.close_connection()
        return False

    def _run_websocket(self) -> None:
        """Run the WebSocket connection with proper error handling"""
        try:
            self.ws.run_forever(
                ping_interval=self.PING_INTERVAL,
                ping_timeout=self.PING_TIMEOUT
            )
        except Exception as e:
            self.logger.error(f"WebSocket run error: {e}")
        finally:
            self._cleanup_connection_state()

    def _cleanup_connection_state(self) -> None:
        """Clean up connection state"""
        self.connected = False
        self._stop_heartbeat()

    def close_connection(self) -> None:
        """Stop the WebSocket connection and cleanup resources"""
        self.logger.info("Stopping Samco WebSocket connection")

        self.running = False
        self.connected = False
        self.DISCONNECT_FLAG = True
        self.RESUBSCRIBE_FLAG = False

        self._close_websocket()
        self._wait_for_thread_completion()
        self._stop_heartbeat()

    def _close_websocket(self) -> None:
        """Close WebSocket connection"""
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                self.logger.error(f"Error closing WebSocket: {e}")

    def _wait_for_thread_completion(self) -> None:
        """Wait for WebSocket thread to complete"""
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=self.THREAD_JOIN_TIMEOUT)
            if self.ws_thread.is_alive():
                self.logger.warning("WebSocket thread did not terminate within timeout")

    # WebSocket Event Handlers
    def _on_open(self, ws) -> None:
        """Handle WebSocket connection open event"""
        self.connected = True
        self._update_last_message_time()
        self.current_retry_attempt = 0

        self.logger.info("Samco WebSocket connection opened")

        # Start heartbeat
        self._start_heartbeat()

        # Resubscribe if needed
        if self.RESUBSCRIBE_FLAG and self.subscribed_symbols:
            self.logger.info("Resubscribing to previously subscribed symbols")
            self._resubscribe_all()

        # Call external callback
        if self._on_open_callback:
            try:
                self._on_open_callback(ws)
            except Exception as e:
                self.logger.error(f"Error in on_open callback: {e}")

    def _on_message(self, ws, message: str) -> None:
        """Handle incoming WebSocket messages"""
        self._update_last_message_time()

        # Log all incoming messages for debugging
        self.logger.info(f"Received WebSocket message: {message[:500] if len(message) > 500 else message}")

        try:
            # Try to parse as JSON
            data = json.loads(message)

            # Check for response wrapper from Samco
            if 'response' in data:
                response = data['response']
                streaming_type = response.get('streaming_type', '')

                if streaming_type in ['quote', 'marketDepth']:
                    # Market data - normalize and pass to data callback
                    market_data = response.get('data', {})
                    normalized = self._normalize_market_data(market_data, streaming_type)

                    if self._on_data_callback:
                        try:
                            self._on_data_callback(ws, normalized)
                        except Exception as e:
                            self.logger.error(f"Error in on_data callback: {e}")
                    return

            # Other messages - pass to message callback
            if self._on_message_callback:
                try:
                    self._on_message_callback(ws, message)
                except Exception as e:
                    self.logger.error(f"Error in on_message callback: {e}")

        except json.JSONDecodeError:
            # Plain text message
            self.logger.debug(f"Non-JSON message: {message}")
            if self._on_message_callback:
                try:
                    self._on_message_callback(ws, message)
                except Exception as e:
                    self.logger.error(f"Error in on_message callback: {e}")

    def _normalize_market_data(self, data: Dict, streaming_type: str) -> Dict:
        """
        Normalize Samco quote data to common format

        Samco quote response fields:
        - aPr: Ask price
        - aSz: Ask size
        - avgPr: Average price
        - bPr: Bid price
        - bSz: Bid size
        - c: Close
        - ch: Change
        - chPer: Change percentage
        - h: High
        - l: Low
        - lTrdT: Last traded time
        - ltp: Last traded price
        - ltq: Last traded quantity
        - ltt: Last traded time
        - lttUTC: Last traded time UTC
        - o: Open
        - oI: Open interest
        - sym: Symbol
        - vol: Volume
        """
        mode = self.DEPTH_MODE if streaming_type == 'marketDepth' else self.QUOTE_MODE

        return {
            'subscription_mode': mode,
            'subscription_mode_val': 'DEPTH' if mode == self.DEPTH_MODE else 'QUOTE',
            'token': data.get('sym', ''),
            'symbol': data.get('sym', ''),
            'last_traded_price': self._safe_float(data.get('ltp', 0)),
            'open_price_of_the_day': self._safe_float(data.get('o', 0)),
            'high_price_of_the_day': self._safe_float(data.get('h', 0)),
            'low_price_of_the_day': self._safe_float(data.get('l', 0)),
            'closed_price': self._safe_float(data.get('c', 0)),
            'last_traded_quantity': self._safe_int(data.get('ltq', 0)),
            'volume_trade_for_the_day': self._safe_int(data.get('vol', 0)),
            'average_traded_price': self._safe_float(data.get('avgPr', 0)),
            'change': self._safe_float(data.get('ch', 0)),
            'change_percentage': self._safe_float(data.get('chPer', 0)),
            'best_bid_price': self._safe_float(data.get('bPr', 0)),
            'best_bid_quantity': self._safe_int(data.get('bSz', 0)),
            'best_ask_price': self._safe_float(data.get('aPr', 0)),
            'best_ask_quantity': self._safe_int(data.get('aSz', 0)),
            'open_interest': self._safe_int(data.get('oI', 0)),
            'last_traded_time': data.get('lTrdT', '') or data.get('ltt', ''),
            'exchange_timestamp': int(time.time() * 1000)
        }

    def _safe_float(self, value) -> float:
        """Safely convert value to float"""
        if value is None or value == '':
            return 0.0
        try:
            if isinstance(value, str):
                value = value.replace(',', '')
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    def _safe_int(self, value) -> int:
        """Safely convert value to int"""
        if value is None or value == '':
            return 0
        try:
            if isinstance(value, str):
                value = value.replace(',', '')
            return int(float(value))
        except (ValueError, TypeError):
            return 0

    def _on_error(self, ws, error) -> None:
        """Handle WebSocket connection errors with retry logic"""
        self.logger.error(f"Samco WebSocket error: {error}")

        if self._on_error_callback:
            try:
                self._on_error_callback(ws, error)
            except Exception as e:
                self.logger.error(f"Error in on_error callback: {e}")

        # Attempt reconnection if not intentionally disconnected
        if not self.DISCONNECT_FLAG and self.current_retry_attempt < self.max_retry_attempts:
            self.RESUBSCRIBE_FLAG = True
            self.current_retry_attempt += 1
            delay = self.retry_delay * (self.retry_multiplier ** (self.current_retry_attempt - 1))
            self.logger.warning(f"Attempting reconnection (Attempt {self.current_retry_attempt}) after {delay}s delay...")

            time.sleep(delay)

            try:
                self._close_websocket()
                self._initialize_connection()
            except Exception as e:
                self.logger.error(f"Error during reconnection: {e}")

    def _on_close(self, ws, close_status_code: Optional[int] = None, close_msg: Optional[str] = None) -> None:
        """Handle WebSocket connection close event"""
        self.connected = False
        self.logger.info(f"Samco WebSocket closed: {close_status_code} - {close_msg}")

        self._stop_heartbeat()

        if self._on_close_callback:
            try:
                self._on_close_callback(ws)
            except Exception as e:
                self.logger.error(f"Error in on_close callback: {e}")

    # Heartbeat Management
    def _update_last_message_time(self) -> None:
        """Update the timestamp of the last received message"""
        with self._heartbeat_lock:
            self._last_message_time = time.time()

    def _start_heartbeat(self) -> None:
        """Start heartbeat monitoring thread"""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        self._heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
        self._heartbeat_thread.start()
        self.logger.debug("Heartbeat thread started")

    def _stop_heartbeat(self) -> None:
        """Stop heartbeat monitoring thread"""
        pass  # Thread will stop when self.running becomes False

    def _heartbeat_worker(self) -> None:
        """Heartbeat worker thread - monitors connection health"""
        while self.running and self.connected:
            try:
                time.sleep(self.HEARTBEAT_INTERVAL)

                if self.running and self.connected:
                    if not self._check_connection_health():
                        break

            except Exception as e:
                self.logger.error(f"Heartbeat worker error: {e}")
                break

    def _check_connection_health(self) -> bool:
        """Check connection health based on last message timestamp"""
        with self._heartbeat_lock:
            if self._last_message_time:
                time_since_message = time.time() - self._last_message_time
                if time_since_message > self.HEARTBEAT_TIMEOUT:
                    self.logger.error("Connection timeout - no messages received")
                    self._close_websocket()
                    return False
        return True

    # Subscription Management
    def subscribe(self, correlation_id: str, mode: int, token_list: List[Dict]) -> bool:
        """
        Subscribe to market data for given symbols

        Args:
            correlation_id: Unique identifier for tracking
            mode: Subscription mode - 1: LTP, 2: Quote, 3: Depth
            token_list: List of dicts with exchangeType and tokens
                       Format: [{"exchangeType": "NSE", "tokens": ["RELIANCE"]}]

        Returns:
            bool: True if subscription sent successfully
        """
        if not self._validate_connection_state("subscribe"):
            return False

        try:
            # Build symbols list in Samco format
            symbols_list = []

            for token_group in token_list:
                exchange = token_group.get('exchangeType', 'NSE')
                tokens = token_group.get('tokens', [])

                for token in tokens:
                    # Samco uses format like "SYMBOL_EXCHANGE" e.g. "RELIANCE_NSE", "532826_BSE"
                    symbol_key = f"{token}_{exchange}"
                    symbols_list.append({"symbol": symbol_key})

                    # Track subscription
                    self.subscribed_symbols[symbol_key] = {
                        'symbol': token,
                        'exchange': exchange,
                        'mode': mode,
                        'correlation_id': correlation_id
                    }

            # Store for resubscription
            if mode not in self.input_request_dict:
                self.input_request_dict[mode] = {}

            for token_group in token_list:
                exchange = token_group.get('exchangeType', 'NSE')
                tokens = token_group.get('tokens', [])
                if exchange in self.input_request_dict[mode]:
                    self.input_request_dict[mode][exchange].extend(tokens)
                else:
                    self.input_request_dict[mode][exchange] = list(tokens)

            # Determine streaming type based on mode
            streaming_type = self.STREAMING_TYPE_MARKETDATA if mode == self.DEPTH_MODE else self.STREAMING_TYPE_QUOTE

            # Build Samco subscription request
            request_data = {
                "request": {
                    "streaming_type": streaming_type,
                    "data": {
                        "symbols": symbols_list
                    },
                    "request_type": self.REQUEST_SUBSCRIBE,
                    "response_format": "json"
                }
            }

            # Send subscription request - Samco requires newline after message
            request_json = json.dumps(request_data)
            self.logger.info(f"Sending subscription: {request_json}")
            self.ws.send(request_json)
            self.ws.send("\n")
            self.logger.info(f"Subscribed to {len(symbols_list)} symbols with mode {mode}")
            self.RESUBSCRIBE_FLAG = True
            return True

        except Exception as e:
            self.logger.error(f"Error during subscribe: {e}")
            return False

    def unsubscribe(self, correlation_id: str, mode: int, token_list: List[Dict]) -> bool:
        """
        Unsubscribe from market data for given symbols

        Args:
            correlation_id: Unique identifier for tracking
            mode: Subscription mode
            token_list: List of dicts with exchangeType and tokens

        Returns:
            bool: True if unsubscription sent successfully
        """
        if not self._validate_connection_state("unsubscribe"):
            return False

        try:
            symbols_list = []

            for token_group in token_list:
                exchange = token_group.get('exchangeType', 'NSE')
                tokens = token_group.get('tokens', [])

                for token in tokens:
                    symbol_key = f"{token}_{exchange}"
                    symbols_list.append({"symbol": symbol_key})

                    # Remove from tracking
                    if symbol_key in self.subscribed_symbols:
                        del self.subscribed_symbols[symbol_key]

                    # Remove from input_request_dict
                    if mode in self.input_request_dict:
                        if exchange in self.input_request_dict[mode]:
                            if token in self.input_request_dict[mode][exchange]:
                                self.input_request_dict[mode][exchange].remove(token)

            # Determine streaming type
            streaming_type = self.STREAMING_TYPE_MARKETDATA if mode == self.DEPTH_MODE else self.STREAMING_TYPE_QUOTE

            # Build unsubscribe request
            request_data = {
                "request": {
                    "streaming_type": streaming_type,
                    "data": {
                        "symbols": symbols_list
                    },
                    "request_type": self.REQUEST_UNSUBSCRIBE,
                    "response_format": "json"
                }
            }

            # Send unsubscribe request - Samco requires newline after message
            self.ws.send(json.dumps(request_data))
            self.ws.send("\n")
            self.logger.info(f"Unsubscribed from {len(symbols_list)} symbols")
            return True

        except Exception as e:
            self.logger.error(f"Error during unsubscribe: {e}")
            return False

    def _resubscribe_all(self) -> None:
        """Resubscribe to all previously subscribed symbols after reconnection"""
        try:
            for mode, exchanges in self.input_request_dict.items():
                token_list = []
                for exchange, tokens in exchanges.items():
                    if tokens:
                        token_list.append({
                            'exchangeType': exchange,
                            'tokens': tokens
                        })

                if token_list:
                    self.subscribe(f"resub_{mode}", mode, token_list)

        except Exception as e:
            self.logger.error(f"Error during resubscribe: {e}")

    def _validate_connection_state(self, operation_name: str) -> bool:
        """Validate that connection is ready for sending messages"""
        if not self.ws:
            self.logger.warning(f"Cannot {operation_name}: WebSocket not initialized")
            return False

        if not self.connected:
            self.logger.warning(f"Cannot {operation_name}: not connected")
            return False

        return True

    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected"""
        return self.connected and self.running
