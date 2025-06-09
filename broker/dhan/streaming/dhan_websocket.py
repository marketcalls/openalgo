"""
WebSocket client for Dhan broker API with binary message parsing
"""
import json
import threading
import time
import logging
import struct
from typing import Dict, Any, List, Optional, Callable, Union, Tuple
import websocket
import ssl
from urllib.parse import urlencode

class DhanWebSocket:
    """
    WebSocket client for connecting to Dhan's market data stream
    Based on API documentation at https://dhanhq.co/docs/v2/live-market-feed/
    """
    
    # Dhan WebSocket endpoints - primary and fallbacks
    WS_URLS = [
        "wss://api-feed.dhan.co",   # Primary endpoint from docs
        "wss://api.dhan.co/feed",    # Possible fallback 1
        "wss://feed.dhanhq.co",      # Possible fallback 2
        "wss://feed-api.dhan.co"     # Possible fallback 3
    ]
    
    def __init__(
        self, 
        client_id: str, 
        access_token: str, 
        on_message: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_close: Optional[Callable] = None,
        on_open: Optional[Callable] = None,
        reconnect_attempts: int = 5,
        reconnect_delay: int = 5
    ):
        """
        Initialize the Dhan WebSocket client
        
        Args:
            client_id: The client ID (User ID)
            access_token: The access token from authentication
            on_message: Callback function for received messages
            on_error: Callback function for errors
            on_close: Callback function for connection close
            on_open: Callback function for successful connection
            reconnect_attempts: Maximum number of reconnect attempts
            reconnect_delay: Initial delay between reconnect attempts (in seconds)
        """
        self.logger = logging.getLogger("dhan_websocket")
        self.client_id = client_id
        self.access_token = access_token
        self.ws = None
        self.subscriptions = {}
        self.connection_thread = None
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = 60  # Maximum reconnection delay (in seconds)
        self.current_reconnect_attempts = 0
        self.connected = False
        self.lock = threading.Lock()
        self.is_running = False
        
        # Set up callback functions
        self.on_message = on_message if on_message else self._default_on_message
        self.on_error = on_error if on_error else self._default_on_error
        self.on_close = on_close if on_close else self._default_on_close
        self.on_open = on_open if on_open else self._default_on_open
        
    def _default_on_message(self, ws, message):
        """Default message handler"""
        self.logger.debug(f"Received message: {message}")
        
    def _default_on_error(self, ws, error):
        """Default error handler"""
        self.logger.error(f"WebSocket error: {error}")
        
    def _default_on_close(self, ws, close_status_code, close_msg):
        """Default close handler"""
        self.logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
        self.connected = False
        
    def _default_on_open(self, ws):
        """Default open handler"""
        self.logger.info("WebSocket connection established")
        self.connected = True
        self.current_reconnect_attempts = 0
        
    def _ws_message_handler(self, ws, message):
        """Handle incoming messages"""
        try:
            if self.on_message_callback:
                self._on_message(ws, message)
        except Exception as e:
            self.logger.error(f"Error in message handler: {e}")
        
    def _ws_error_handler(self, ws, error):
        """Handler for WebSocket errors with enhanced diagnostics"""
        try:
            # Get detailed error information
            error_type = type(error).__name__
            error_msg = str(error)
            
            # Log detailed error information
            self.logger.error(f"WebSocket error: {error_type} - {error_msg}")
            
            # Check for specific error types to provide better diagnostics
            if "getaddrinfo failed" in error_msg:
                self.logger.error("DNS resolution failed. The WebSocket URL could not be resolved.")
                self.logger.error(f"Attempted to connect to one of these URLs: {', '.join(self.WS_URLS)}")
                
            elif "connection refused" in str(error).lower():
                self.logger.error("Connection refused. The server might be down or not accepting connections.")
                
            elif isinstance(error, (ConnectionRefusedError, ConnectionResetError)):
                self.logger.error("Connection was refused or reset by the server.")
                
            elif "handshake" in str(error).lower():
                self.logger.error("WebSocket handshake failed. Authentication might be incorrect.")
                
            # Call user-provided error callback if available
            if self.on_error:
                self.on_error(ws, error)
                
        except Exception as e:
            self.logger.error(f"Error in error handler: {e}")
        
    def _ws_close_handler(self, ws, close_status_code, close_msg):
        """Handle WebSocket close events"""
        self.connected = False
        try:
            if self.on_close:
                self.on_close(ws, close_status_code, close_msg)
                
            # Attempt to reconnect if needed
            if self.is_running and self.current_reconnect_attempts < self.reconnect_attempts:
                self.logger.info(f"Attempting reconnection ({self.current_reconnect_attempts + 1}/{self.reconnect_attempts})...")
                reconnect_delay = min(
                    self.reconnect_delay * (2 ** self.current_reconnect_attempts),
                    self.max_reconnect_delay
                )
                self.logger.info(f"Reconnecting in {reconnect_delay} seconds...")
                time.sleep(reconnect_delay)
                self.current_reconnect_attempts += 1
                self._connect()
            elif self.current_reconnect_attempts >= self.reconnect_attempts:
                self.logger.error("Maximum reconnection attempts reached. Giving up.")
        except Exception as e:
            self.logger.error(f"Error in close handler: {e}")
        
    def _ws_open_handler(self, ws):
        """Handle WebSocket open events"""
        self.connected = True
        try:
            if self.on_open:
                self.on_open(ws)
        except Exception as e:
            self.logger.error(f"Error in open handler: {e}")
        
    def _connect(self):
        """Establish connection to Dhan WebSocket server using official URL format and query parameters"""
        # Common query parameters for authentication based on documentation
        params = {
            "version": "2",
            "token": self.access_token,
            "clientId": self.client_id,
            "authType": "2"
        }
        
        self.logger.info("Attempting to connect to Dhan WebSocket with query parameters")
        
        # Try each URL in sequence
        for base_url in self.WS_URLS:
            try:
                # Create the full URL with query parameters
                ws_url = f"{base_url}?{urlencode(params)}"
                self.logger.info(f"Trying WebSocket endpoint: {base_url}")
                
                # Initialize WebSocket connection
                self.ws = websocket.WebSocketApp(
                    ws_url,
                    on_message=self._ws_message_handler,
                    on_error=self._ws_error_handler,
                    on_close=self._ws_close_handler,
                    on_open=self._ws_open_handler
                )
                
                # Set the ping interval for WebSocket
                self.ws.keep_running = True
                self.ws.ping_interval = 30
                self.ws.ping_timeout = 10
                
                # Start WebSocket connection in a separate thread
                self.connection_thread = threading.Thread(
                    target=self.ws.run_forever,
                    kwargs={
                        "sslopt": {"cert_reqs": ssl.CERT_NONE},
                        "ping_interval": 30,
                        "ping_timeout": 10
                    },
                    daemon=True
                )
                self.connection_thread.start()
                
                # Wait for WebSocket to connect or timeout
                start_time = time.time()
                timeout = 10  # Wait up to 10 seconds for connection
                
                while not self.connected and time.time() - start_time < timeout:
                    time.sleep(0.1)
                
                # If connected, we're done
                if self.connected:
                    self.logger.info(f"Successfully connected to Dhan WebSocket at {base_url}")
                    return True
                    
                # If not connected, clean up and try next URL
                self.logger.warning(f"Connection timeout with {base_url}, trying next URL if available")
                try:
                    if self.ws:
                        self.ws.keep_running = False
                        self.ws.close()
                except Exception as e:
                    self.logger.debug(f"Error cleaning up WebSocket connection: {e}")
                    
            except Exception as e:
                self.logger.warning(f"Failed to connect to {base_url}: {e}")
        
        # If we've tried all URLs and none worked
        self.logger.error("Failed to connect to any Dhan WebSocket URL after trying all endpoints")
        return False
    def connect(self):
        """
        Connect to the Dhan WebSocket server
        
        Returns:
            bool: True if connection was successful, False otherwise
        """
        with self.lock:
            if self.connected and self.ws:
                self.logger.info("Already connected to WebSocket")
                return True
                
            self.is_running = True
            return self._connect()
        
    def disconnect(self):
        """
        Disconnect from the Dhan WebSocket server
        """
        with self.lock:
            self.is_running = False
            return True

        self.is_running = True
        return self._connect()

def disconnect(self):
    """
    Disconnect from the Dhan WebSocket server
    """
    with self.lock:
        self.is_running = False
        if self.ws:
            self.logger.info("Disconnecting from WebSocket")
            self.ws.close()
            self.connected = False

def send_message(self, message: Dict[str, Any]) -> bool:
    """
    Send a message to the WebSocket server

    Args:
        message: The message to send

    Returns:
        bool: True if the message was sent successfully, False otherwise
    """
    if not self.connected or not self.ws:
        self.logger.error("Cannot send message: Not connected to WebSocket")
        return False

    try:
        self.ws.send(json.dumps(message))
        return True
    except Exception as e:
        self.logger.error(f"Error sending message: {e}")
        return False

    def subscribe(self, symbol_list, request_code=15):
        """Subscribe to market data feeds
        
        Args:
            symbol_list: List of symbols to subscribe
                     [{"exchange": "NSE_EQ", "token": "26000", "symbol": "HDFCBANK-EQ"}]
            request_code: Feed request code (default: 15):
                - 15: Full market data (quote + depth + OI)
                - 10: Quote data
                - 2: Ticker/LTP data
                     
        Returns:
            bool: True if subscription request was sent successfully
        """
        if not self.connected:
            self.logger.error("Cannot subscribe: Not connected to WebSocket")
            return False

        try:
            # Convert broker-specific format to Dhan's expected format
            instrument_list = []
            for symbol_data in symbol_list:
                instrument_list.append({
                    "ExchangeSegment": symbol_data.get("exchange"),
                    "SecurityId": symbol_data.get("token")
                })
                
            # Ensure we don't exceed 100 instruments per request as per docs
            chunks = [instrument_list[i:i+100] for i in range(0, len(instrument_list), 100)]

            for chunk in chunks:
                subscription_request = {
                    "RequestCode": request_code,
                    "InstrumentCount": len(chunk),
                    "InstrumentList": chunk
                }

                self.logger.info(f"Subscribing to {len(chunk)} instruments with request code {request_code}")
                self.logger.debug(f"Subscription request: {subscription_request}")

                # Send subscription request
                self.ws.send(json.dumps(subscription_request))

                # Store subscribed instruments for reconnection
                for i, instrument in enumerate(chunk):
                    # Get original symbol data for reference
                    original_data = symbol_list[i] if i < len(symbol_list) else {}
                    symbol = original_data.get("symbol", f"Unknown-{instrument['SecurityId']}")
                    
                    key = f"{instrument['ExchangeSegment']}:{instrument['SecurityId']}"
                    self.subscriptions[key] = {
                        "exchange": instrument['ExchangeSegment'],
                        "token": instrument['SecurityId'],
                        "symbol": symbol,
                        "request_code": request_code
                    }
            
            return True
        except Exception as e:
            self.logger.error(f"Error subscribing to instruments: {e}")
            return False


    def unsubscribe(self, symbols: List[Dict[str, str]]) -> bool:
        """
        Unsubscribe from market data feeds

        Args:
            symbols: List of symbols to unsubscribe
                     [{"exchange": "NSE_EQ", "token": "26000", "symbol": "HDFCBANK-EQ"}]

        Returns:
            bool: True if unsubscription request was sent successfully
        """
        if not self.connected:
            self.logger.error("Cannot unsubscribe: Not connected to WebSocket")
            return False
            
        try:
            # Convert broker format to Dhan format
            instrument_list = []
            for symbol_data in symbols:
                instrument_list.append({
                    "ExchangeSegment": symbol_data.get("exchange"),
                    "SecurityId": symbol_data.get("token")
                })
                
            # Create unsubscribe request
            unsubscription_request = {
                "RequestCode": 16,  # Unsubscribe code
                "InstrumentCount": len(instrument_list),
                "InstrumentList": instrument_list
            }
            
            self.logger.info(f"Unsubscribing from {len(instrument_list)} instruments")
            self.ws.send(json.dumps(unsubscription_request))
            
            # Remove from subscriptions
            for symbol_data in symbols:
                key = f"{symbol_data.get('exchange')}:{symbol_data.get('token')}"
                if key in self.subscriptions:
                    del self.subscriptions[key]
                    
            return True
        except Exception as e:
            self.logger.error(f"Error unsubscribing from instruments: {e}")
            return False


    def is_subscribed(self, exchange: str, token: str) -> bool:
        """
        Check if a symbol is subscribed

        Args:
            exchange: Exchange code
            token: Symbol token

        Returns:
            bool: True if subscribed, False otherwise
        """
        key = f"{exchange}:{token}"
        return key in self.subscriptions


        
    def is_subscribed(self, exchange: str, token: str) -> bool:
        """
        Check if a symbol is subscribed
        
        Args:
            exchange: Exchange code
            token: Symbol token
            
        Returns:
            bool: True if subscribed, False otherwise
        """
        key = f"{exchange}:{token}"
        return key in self.subscriptions
