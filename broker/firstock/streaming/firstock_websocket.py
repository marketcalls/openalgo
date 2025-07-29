import json
import time
import ssl
import websocket
import os
import logging
import threading
from urllib.parse import urlencode
from utils.logging import get_logger

class FirstockWebSocket:
    """
    Firstock WebSocket Client for real-time market data
    """
    
    ROOT_URI = "wss://socket.firstock.in/ws"
    HEART_BEAT_INTERVAL = 30  # Send ping every 30 seconds
    HEART_BEAT_MESSAGE = "ping"
    
    # Available Actions
    SUBSCRIBE_ACTION = "subscribe"
    UNSUBSCRIBE_ACTION = "unsubscribe"
    
    # Connection states
    CONNECTING = 0
    CONNECTED = 1
    DISCONNECTED = 2
    ERROR = 3
    
    def __init__(self, user_id, auth_token, max_retry_attempt=5, retry_delay=5):
        """
        Initialize the Firstock WebSocket client
        
        Parameters
        ----------
        user_id : str
            User ID for Firstock account
        auth_token : str
            Authentication token (susertoken) from login API
        max_retry_attempt : int
            Maximum number of retry attempts on connection failure
        retry_delay : int
            Delay between retry attempts in seconds
        """
        self.user_id = user_id
        self.auth_token = auth_token
        self.max_retry_attempt = max_retry_attempt
        self.retry_delay = retry_delay
        
        # Connection management
        self.wsapp = None
        self.connection_state = self.DISCONNECTED
        self.current_retry_attempt = 0
        self.is_running = False
        self.ping_thread = None
        self.last_pong_time = time.time()
        self.authenticated = False  # Track authentication status
        
        # Callbacks
        self.on_open = None
        self.on_data = None
        self.on_error = None
        self.on_close = None
        self.on_message = None
        
        # Subscriptions tracking
        self.subscriptions = set()
        self.pending_subscriptions = []  # Queue subscriptions until authenticated
        
        # Logger
        self.logger = get_logger("firstock_websocket")
        
        if not self._sanity_check():
            self.logger.error("Invalid initialization parameters")
            raise ValueError("Provide valid values for user_id and auth_token")
    
    def _sanity_check(self):
        """Validate initialization parameters"""
        return bool(self.user_id and self.auth_token)
    
    def connect(self):
        """Establish WebSocket connection to Firstock"""
        if self.connection_state == self.CONNECTED:
            self.logger.warning("Already connected to Firstock WebSocket")
            return
        
        try:
            self.connection_state = self.CONNECTING
            self.is_running = True
            
            # Build connection URL with query parameters
            params = {
                'userId': self.user_id,
                'jKey': self.auth_token,
                'source': 'developer-api'
            }
            
            connection_url = f"{self.ROOT_URI}?{urlencode(params)}"
            self.logger.info(f"Connecting to Firstock WebSocket: {self.ROOT_URI}")
            self.logger.info(f"Using userId: {self.user_id}")
            self.logger.debug(f"Connection URL: {connection_url}")
            self.logger.debug(f"Using auth token (jKey): {self.auth_token[:10]}...{self.auth_token[-5:] if len(self.auth_token) > 15 else self.auth_token}")
            
            # Important note about authentication
            self.logger.info("Note: The jKey must be the 'susertoken' obtained from Firstock's login API")
            
            # Create WebSocket connection
            self.wsapp = websocket.WebSocketApp(
                connection_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_pong=self._on_pong
            )
            
            # Start WebSocket in a separate thread
            self.ws_thread = threading.Thread(
                target=self._run_websocket,
                daemon=True
            )
            self.ws_thread.start()
            
        except Exception as e:
            self.logger.error(f"Error connecting to Firstock WebSocket: {e}")
            self.connection_state = self.ERROR
            raise
    
    def _run_websocket(self):
        """Run WebSocket with retry logic"""
        try:
            self.logger.info("Starting WebSocket connection thread")
            self.wsapp.run_forever(
                ping_interval=self.HEART_BEAT_INTERVAL,
                ping_timeout=10,
                sslopt={"cert_reqs": ssl.CERT_NONE}  # Add SSL options to avoid SSL errors
            )
            self.logger.info("WebSocket run_forever completed")
        except Exception as e:
            self.logger.error(f"WebSocket connection failed: {e}")
            self.connection_state = self.ERROR
    
    def close_connection(self):
        """Close WebSocket connection"""
        self.is_running = False
        
        # Stop ping thread
        if self.ping_thread and self.ping_thread.is_alive():
            self.ping_thread = None
        
        # Close WebSocket
        if self.wsapp:
            self.wsapp.close()
        
        self.connection_state = self.DISCONNECTED
        self.logger.info("Firstock WebSocket connection closed")
    
    def subscribe(self, correlation_id, mode, token_list):
        """
        Subscribe to market data feed
        
        Parameters
        ----------
        correlation_id : str
            Unique identifier for this subscription
        mode : int
            Subscription mode (1=LTP, 2=Quote, 3=Depth)
        token_list : list
            List of tokens to subscribe to in format [{"exchangeType": "NSE", "tokens": ["26000"]}]
        """
        if self.connection_state != self.CONNECTED:
            self.logger.error("Cannot subscribe: WebSocket not connected")
            self.logger.error(f"Current connection state: {self.get_connection_state()}")
            return
        
        # If not authenticated yet, queue the subscription
        if not self.authenticated:
            self.logger.info(f"Queuing subscription for {correlation_id} until authentication completes")
            self.logger.info("WebSocket is connected but waiting for authentication response from Firstock")
            self.pending_subscriptions.append((correlation_id, mode, token_list))
            return
        
        try:
            # Convert token_list to Firstock format
            tokens = []
            for token_info in token_list:
                exchange = token_info.get("exchangeType", "")
                for token in token_info.get("tokens", []):
                    tokens.append(f"{exchange}:{token}")
            
            # Create subscription message
            subscribe_msg = {
                "action": self.SUBSCRIBE_ACTION,
                "tokens": "|".join(tokens)  # Firstock uses pipe-separated tokens
            }
            
            # Send subscription
            self.wsapp.send(json.dumps(subscribe_msg))
            
            # Track subscription
            self.subscriptions.add(correlation_id)
            
            self.logger.info(f"Subscribed to {correlation_id} with tokens: {tokens}")
            
        except Exception as e:
            self.logger.error(f"Error subscribing to {correlation_id}: {e}")
            raise
    
    def unsubscribe(self, correlation_id, mode, token_list):
        """
        Unsubscribe from market data feed
        
        Parameters
        ----------
        correlation_id : str
            Unique identifier for this subscription
        mode : int
            Subscription mode
        token_list : list
            List of tokens to unsubscribe from
        """
        if self.connection_state != self.CONNECTED:
            self.logger.error("Cannot unsubscribe: WebSocket not connected")
            return
        
        try:
            # Convert token_list to Firstock format
            tokens = []
            for token_info in token_list:
                exchange = token_info.get("exchangeType", "")
                for token in token_info.get("tokens", []):
                    tokens.append(f"{exchange}:{token}")
            
            # Create unsubscription message
            unsubscribe_msg = {
                "action": self.UNSUBSCRIBE_ACTION,
                "tokens": "|".join(tokens)
            }
            
            # Send unsubscription
            self.wsapp.send(json.dumps(unsubscribe_msg))
            
            # Remove from tracking
            self.subscriptions.discard(correlation_id)
            
            self.logger.info(f"Unsubscribed from {correlation_id}")
            
        except Exception as e:
            self.logger.error(f"Error unsubscribing from {correlation_id}: {e}")
            raise
    
    def _on_open(self, wsapp):
        """Handle WebSocket connection open"""
        self.connection_state = self.CONNECTED
        self.current_retry_attempt = 0
        self.last_pong_time = time.time()
        
        self.logger.info("Firstock WebSocket connection established - waiting for authentication response")
        
        # Start ping monitoring
        self.ping_thread = threading.Thread(target=self._monitor_connection, daemon=True)
        self.ping_thread.start()
        
        # Call user callback
        if self.on_open:
            try:
                self.on_open(wsapp)
            except Exception as e:
                self.logger.error(f"Error in on_open callback: {e}")
    
    def _on_message(self, wsapp, message):
        """Handle WebSocket messages"""
        try:
            self.logger.debug(f"Received message: {message}")
            
            # Handle text messages
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                    self.logger.debug(f"Parsed JSON message: {data}")
                    
                    # Handle authentication response
                    if 'status' in data:
                        if data.get('status') == 'success':
                            self.logger.info(f"Authentication successful: {data.get('message', 'No message')}")
                            self.authenticated = True
                            # Process any pending subscriptions
                            self._process_pending_subscriptions()
                        elif data.get('status') == 'failed' or data.get('message') == 'unauthenticated':
                            # Log more details about the auth failure
                            self.logger.error(f"Authentication failed: {data.get('message', 'Unknown error')}")
                            self.logger.error(f"Full response: {data}")
                            self.logger.error(f"Using userId: {self.user_id}")
                            self.logger.error(f"Using jKey (first 10 chars): {self.auth_token[:10] if self.auth_token else 'None'}...")
                            self.logger.error("IMPORTANT: The jKey must be the 'susertoken' from Firstock's login API response")
                            self.logger.error("Make sure you have:")
                            self.logger.error("1. Logged in via Firstock's login API")
                            self.logger.error("2. Stored the 'susertoken' from the login response as the auth_token")
                            self.logger.error("3. The token is not expired (tokens may have limited validity)")
                            self.authenticated = False
                            # Close connection on auth failure to prevent spam
                            self.is_running = False
                            if self.wsapp:
                                self.wsapp.close()
                        return
                    
                    # Handle market data
                    if 'c_symbol' in data:
                        # This is market data - call the data callback
                        self.logger.info(f"Received market data for symbol: {data.get('c_symbol')} on exchange: {data.get('c_exch_seg')}")
                        if self.on_data:
                            self.on_data(wsapp, data)
                        return
                    
                    # Log any other message types we receive
                    self.logger.info(f"Received other message type: {list(data.keys())}")
                    
                    # Handle other message types
                    if self.on_message:
                        self.on_message(wsapp, message)
                        
                except json.JSONDecodeError:
                    # Handle non-JSON text messages
                    self.logger.debug(f"Received non-JSON text message: {message}")
                    if self.on_message:
                        self.on_message(wsapp, message)
            else:
                # Handle binary messages (if any)
                self.logger.info(f"Received binary message of length: {len(message) if hasattr(message, '__len__') else 'unknown'}")
                if self.on_data:
                    self.on_data(wsapp, message)
                    
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
    
    def _on_error(self, wsapp, error):
        """Handle WebSocket errors"""
        self.logger.error(f"Firstock WebSocket error: {error}")
        self.connection_state = self.ERROR
        
        if self.on_error:
            try:
                self.on_error(wsapp, error)
            except Exception as e:
                self.logger.error(f"Error in on_error callback: {e}")
    
    def _on_close(self, wsapp, close_status_code=None, close_msg=None):
        """Handle WebSocket connection close"""
        self.connection_state = self.DISCONNECTED
        self.authenticated = False  # Reset authentication status
        
        # Stop ping monitoring
        if self.ping_thread:
            self.ping_thread = None
        
        self.logger.info(f"Firstock WebSocket connection closed: {close_status_code} - {close_msg}")
        
        if self.on_close:
            try:
                self.on_close(wsapp)
            except Exception as e:
                self.logger.error(f"Error in on_close callback: {e}")
        
        # Only attempt reconnection if we're still supposed to be running
        # and we haven't been explicitly told to stop
        if self.is_running and self.current_retry_attempt < self.max_retry_attempt:
            self.current_retry_attempt += 1
            if self.current_retry_attempt < self.max_retry_attempt:
                self.logger.info(f"Attempting to reconnect (attempt {self.current_retry_attempt + 1})...")
                time.sleep(self.retry_delay)  # Wait before reconnecting
                threading.Thread(target=self._run_websocket, daemon=True).start()
            else:
                self.logger.error("Max retry attempts reached. Stopping reconnection attempts.")
                self.is_running = False
    
    def _on_pong(self, wsapp, message):
        """Handle pong messages"""
        self.last_pong_time = time.time()
        self.logger.debug("Received pong from Firstock server")
    
    def _monitor_connection(self):
        """Monitor connection health with ping-pong"""
        while self.is_running and self.connection_state == self.CONNECTED:
            try:
                # Check if we've received a pong recently
                time_since_pong = time.time() - self.last_pong_time
                if time_since_pong > 40:  # No pong for 40 seconds
                    self.logger.warning("No pong received for 40 seconds, connection may be dead")
                    if self.wsapp:
                        self.wsapp.close()
                    break
                
                time.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                self.logger.error(f"Error in connection monitor: {e}")
                break
    
    def is_connected(self):
        """Check if WebSocket is connected"""
        return self.connection_state == self.CONNECTED
    
    def get_connection_state(self):
        """Get current connection state"""
        states = {
            self.CONNECTING: "CONNECTING",
            self.CONNECTED: "CONNECTED", 
            self.DISCONNECTED: "DISCONNECTED",
            self.ERROR: "ERROR"
        }
        return states.get(self.connection_state, "UNKNOWN")
    
    def get_subscriptions(self):
        """Get list of active subscriptions"""
        return list(self.subscriptions)
    
    def _process_pending_subscriptions(self):
        """Process any subscriptions that were queued while waiting for authentication"""
        if not self.pending_subscriptions:
            return
            
        self.logger.info(f"Processing {len(self.pending_subscriptions)} pending subscriptions")
        
        # Process all pending subscriptions
        for correlation_id, mode, token_list in self.pending_subscriptions:
            try:
                self.subscribe(correlation_id, mode, token_list)
            except Exception as e:
                self.logger.error(f"Error processing pending subscription {correlation_id}: {e}")
        
        # Clear the pending list
        self.pending_subscriptions.clear()