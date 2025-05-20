import json
import os
import time
import struct
import zlib
import traceback
import socket
import threading
import logging
import pandas as pd
import websocket
import re
from datetime import datetime, timedelta
from database.token_db import get_token, get_br_symbol, get_oa_symbol

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TradejiniWebSocket:
    def __init__(self):
        """Initialize WebSocket connection"""
        self.ws = None
        self.auth_token = None
        self.symbol_map = {}
        self.lock = threading.Lock()
        self.connected = False
        self.authenticated = False  # Track authentication status
        self.pending_subscriptions = []
        self.pending_requests = {}
        self.response_event = threading.Event()
        self.last_message_time = 0
        self.request_id = int(time.time() * 1000)
        self.ohlc_data = {}
        self.last_quote = None  # Initialize last_quote
        self.last_depth = None  # Initialize last_depth
        self.connection_timeout = 30  # seconds
        self.auth_timeout = 10  # seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        self.ws_url = "wss://api.tradejini.com/v2.1/stream"
        self.connection_state = {
            'connection_attempts': 0,
            'last_connection_time': None,
            'last_error': None,
            'last_ping': None,
            'last_pong': None
        }

    def _handle_auth_response(self, data):
        """Handle authentication response"""
        try:
            status = data.get('status', '').lower()
            if status == 'success':
                self.authenticated = True
                logger.info("Successfully authenticated with Tradejini WebSocket")
                # Process any pending subscriptions now that we're authenticated
                self._process_pending_subscriptions()
            else:
                error_msg = data.get('message', 'No error message')
                logger.error(f"Authentication failed: {error_msg}")
                self.authenticated = False
                
            # Signal that we've received an auth response
            self.response_event.set()
            
        except Exception as e:
            logger.error(f"Error handling auth response: {str(e)}", exc_info=True)

    def _get_websocket_headers(self):
        """
        Generate WebSocket headers with debug info
        
        Returns:
            dict: Dictionary of HTTP headers for WebSocket connection
        """
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept': '*/*',
            'Connection': 'Upgrade',
            'Upgrade': 'websocket',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
            'Origin': 'https://tradejini.com',
            'Sec-WebSocket-Version': '13',
            'Sec-WebSocket-Key': 'x3JJHMbDL1EzLkh9GBhXDw==',  # This is a fixed test key for debugging
            'Sec-WebSocket-Extensions': 'permessage-deflate; client_max_window_bits',
            'Content-Type': 'application/json'  # Added as per funds.py
        }
        
        # Add Authorization header if auth_token is set
        if hasattr(self, 'auth_token') and self.auth_token:
            headers['Authorization'] = f'Bearer {self.auth_token}'
            
        return headers

    def _log_websocket_handshake(self, headers):
        """Log WebSocket handshake details"""
        logger.debug("WebSocket Handshake Headers:")
        for key, value in headers.items():
            if key.lower() == 'authorization':
                logger.debug(f"  {key}: [REDACTED]")
            else:
                logger.debug(f"  {key}: {value}")

    def connect(self, auth_token):
        """
        Connect to Tradejini WebSocket
        
        Args:
            auth_token (str): Authentication token in the format 'api_key:access_token'
                             or just the access token (if TRADEJINI_API_KEY is set in env)
        """
        try:
            # Store auth token
            self.auth_token = auth_token
            
            # Set connection state data
            self.connection_state['connection_attempts'] += 1
            self.connection_state['last_connection_time'] = datetime.now().isoformat()
            self.connection_state['last_error'] = None
            
            # Reset WebSocket connection event
            self.response_event.clear()
            
            # Reset reconnect attempts on new connection
            self.reconnect_attempts = 0
            
            # Get API key from environment if not provided in token
            api_key = os.environ.get('BROKER_API_SECRET', '')
            
            # Format the auth token as per funds.py
            if ':' not in auth_token and api_key:
                # If token doesn't contain ':', use format 'api_key:access_token'
                auth_header = f"{api_key}:{auth_token}"
                logger.info("Using API key from BROKER_API_SECRET environment variable")
            elif ':' in auth_token:
                # If token already contains ':', use as is
                auth_header = auth_token
                logger.info("Using provided API key and access token")
            else:
                error_msg = "Invalid auth token format. Expected 'api_key:access_token' or set BROKER_API_SECRET"
                logger.error(error_msg)
                self.connection_state['last_error'] = error_msg
                raise ValueError(error_msg)
            
            # Log the token format for debugging (mask sensitive parts)
            if ':' in auth_header:
                parts = auth_header.split(':', 1)
                masked_header = f"{parts[0][:4]}...:{parts[1][:4]}..." if len(parts[1]) > 4 else "****"
                logger.debug(f"Using auth header: {masked_header}")
            
            # Set the WebSocket URL (no token in URL, we'll use headers)
            ws_url = "wss://api.tradejini.com/v2.1/stream"
            
            logger.info(f"Initiating WebSocket connection to Tradejini")
            logger.debug(f"WebSocket URL: {ws_url}")
            
            # Get headers with authentication
            headers = self._get_websocket_headers()
            
            # Add Authorization header in Bearer format as per funds.py
            headers['Authorization'] = f'Bearer {auth_header}'
            
            # Log headers (with sensitive info masked)
            self._log_websocket_handshake(headers)
            
            # Initialize basic WebSocket (compatibility with older websocket-client versions)
            self.ws = websocket.WebSocketApp(
                ws_url,
                header=headers,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            
            # Start WebSocket connection in a separate thread (basic mode for compatibility)
            ws_thread = threading.Thread(
                target=self.ws.run_forever
            )
            ws_thread.daemon = True
            ws_thread.start()
            
            # Wait for connection with timeout
            logger.info("Waiting for WebSocket connection...")
            if not self.response_event.wait(self.connection_timeout):
                logger.error(f"Failed to connect to Tradejini WebSocket within {self.connection_timeout} seconds")
                self.close()
                return False
                
            # Wait for authentication with timeout
            logger.info("Waiting for WebSocket authentication...")
            auth_start = time.time()
            while not self.authenticated and (time.time() - auth_start) < self.auth_timeout:
                time.sleep(0.1)
                
            if not self.authenticated:
                logger.error(f"WebSocket authentication failed after {self.auth_timeout} seconds")
                self.close()
                return False
                
            logger.info("WebSocket connection and authentication successful")
            self.reconnect_attempts = 0  # Reset reconnect attempts on successful connection
            return True
            
        except Exception as e:
            error_msg = f"Error connecting to WebSocket: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.close()
            return False

    def _log_connection_state(self, state_change):
        """Log connection state changes with detailed information"""
        state_info = {
            'timestamp': datetime.now().isoformat(),
            'state_change': state_change,
            'connection_state': self.connection_state.copy(),
            'threads': threading.active_count(),
            'ws_state': {
                'connected': self.connected,
                'authenticated': self.authenticated,
                'has_ws': hasattr(self, 'ws') and self.ws is not None,
                'ws_sock': hasattr(self, 'ws') and hasattr(self.ws, 'sock') and self.ws.sock is not None,
                'ws_connected': hasattr(self, 'ws') and hasattr(self.ws, 'sock') and hasattr(self.ws.sock, 'connected') and self.ws.sock.connected
            }
        }
        logger.debug(f"Connection state change - {state_change}:\n{json.dumps(state_info, indent=2)}")
        return state_info

    def on_open(self, ws):
        """Handle WebSocket open event"""
        try:
            # Update connection state
            self.connection_state.update({
                'connection_attempts': self.connection_state.get('connection_attempts', 0) + 1,
                'last_connection_time': datetime.now().isoformat(),
                'last_error': None,
                'connected': True,
                'authenticated': False,
                'ws_state': 'connected',
                'websocket_headers': dict(ws.header) if hasattr(ws, 'header') else {}
            })
            
            # Log the connection state
            self._log_connection_state("WebSocket connection established")
            
            # Log WebSocket details
            if hasattr(ws, 'sock') and ws.sock:
                sock = ws.sock
                self.connection_state.update({
                    'local_address': sock.getsockname() if hasattr(sock, 'getsockname') else None,
                    'remote_address': sock.getpeername() if hasattr(sock, 'getpeername') else None,
                    'socket_fd': sock.fileno() if hasattr(sock, 'fileno') else None
                })
                logger.debug(f"Socket details: {self.connection_state['local_address']} -> {self.connection_state['remote_address']}")
            
            # Set connection flags and notify waiting threads
            self.connected = True
            self.response_event.set()
            
            # Start authentication
            logger.info("Starting authentication...")
            if not self.authenticate():
                logger.error("Initial authentication failed")
                self.connection_state['last_error'] = 'Authentication failed'
                self.close()
                
        except Exception as e:
            error_msg = f"Error in WebSocket on_open: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.connection_state['last_error'] = error_msg
            self.close()
            
    def _get_exchange_token(self, token_str, exchange):
        """
        Get the exchange token for TradeJini WebSocket API
        
        Args:
            token_str: Token string
            exchange: Exchange name (NSE, BSE, NFO, etc.)
            
        Returns:
            Exchange token formatted for TradeJini WebSocket API
        """
        try:
            # First try to get the actual exchange token using the token database
            token_info = get_token(token_str, exchange)
            if token_info and 'token' in token_info:
                exchange_token = token_info['token']
                logger.debug(f"Found token {exchange_token} for symbol {token_str} on {exchange}")
                return exchange_token
            
            # If not found, check if token_str is already a numeric token
            if token_str.isdigit():
                logger.debug(f"Using numeric token {token_str} directly")
                return token_str
            
            # Try to get broker symbol as fallback
            br_symbol = get_br_symbol(token_str, exchange)
            if br_symbol and isinstance(br_symbol, str) and br_symbol.isdigit():
                logger.debug(f"Using broker symbol {br_symbol} for {token_str}")
                return br_symbol
            
            # Last resort: just use the token string
            logger.warning(f"Could not get exchange token for {token_str} on {exchange}, using token string directly")
            return token_str
            
        except Exception as e:
            logger.error(f"Error getting exchange token for {token_str} on {exchange}: {str(e)}")
            return token_str
            
    def authenticate(self):
        """Authenticate with Tradejini WebSocket"""
        if not self.auth_token:
            error_msg = "No auth token available for WebSocket authentication"
            logger.error(error_msg)
            self.connection_state['last_error'] = error_msg
            return False
            
        try:
            # For TradeJini, authentication is handled via the token in the URL
            # The authToken format should be '<APIkey>:<accessToken>'
            # Send initial auth data to signal we're connected
            auth_msg = {
                "type": "PING"  # Send ping to check connection is active
            }
            auth_str = json.dumps(auth_msg)
            logger.debug(f"Sending initial ping message to verify connection")
            self.ws.send(auth_str)
            logger.info("Authentication message sent successfully")
            
            # Mark as authenticated since token is already in the URL
            self.authenticated = True
            return True
        except Exception as e:
            error_msg = f"Error sending authentication message: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.connection_state['last_error'] = error_msg
            return False

    def on_message(self, ws, message):
        """Handle incoming WebSocket messages"""
        try:
            self.last_message_time = time.time()
            # Log the raw message with more detail for debugging
            if isinstance(message, bytes):
                logger.debug(f"Raw binary message received: length={len(message)} bytes")
                # First few bytes can help identify the message type
                logger.debug(f"First 20 bytes: {message[:20].hex()}")
            else:
                logger.debug(f"Raw message received: {message[:200]}..." if len(message) > 200 else f"Raw message received: {message}")
            
            # Try to parse as JSON first
            try:
                data = json.loads(message)
                logger.info(f"Parsed JSON message type: {data.get('type', 'unknown')}")
                logger.debug(f"Full message content: {json.dumps(data, indent=2)}")
                
                # Handle different message types
                if isinstance(data, dict):
                    msg_type = data.get('type')
                    request_id = data.get('request_id')
                    
                    # Handle authentication response
                    if msg_type == 'auth_ack':
                        logger.info(f"Received authentication acknowledgement: {data}")
                        self._handle_auth_response(data)
                    elif msg_type in ['L1', 'L2', 'quote']:
                        self._process_quote(data)
                    elif msg_type == 'error':
                        error_code = data.get('code', 'Unknown')
                        error_msg = data.get('message', 'Unknown error')
                        logger.error(f"Error from TradeJini WebSocket: Code={error_code}, Message={error_msg}")
                        self.connection_state['last_error'] = f"{error_code} - {error_msg}"
                    elif msg_type == 'ping':
                        logger.debug("Received ping message")
                        # Send pong in response to ping
                        pong_msg = {"type": "PONG"}
                        self.ws.send(json.dumps(pong_msg))
                    elif msg_type == 'pong':
                        logger.debug("Received pong message")
                        self.connection_state['last_pong'] = time.time()
                    else:
                        logger.info(f"Received message with type: {msg_type}")
                    
                    # Process pending requests
                    if request_id and request_id in self.pending_requests:
                        logger.debug(f"Processing response for request_id: {request_id}")
                        self.pending_requests[request_id]['data'] = data
                        self.pending_requests[request_id]['event'].set()
                        
            except json.JSONDecodeError:
                # Handle binary or non-JSON messages
                logger.debug(f"Received non-JSON message (length: {len(message)} bytes)")
                self._handle_binary_message(message)
                
        except Exception as e:
            error_msg = f"Error processing WebSocket message: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.connection_state['last_error'] = error_msg

    def _get_connection_error_details(self, error):
        """Extract detailed error information from WebSocket error"""
        error_details = {
            'type': type(error).__name__,
            'message': str(error),
            'time': datetime.now().isoformat(),
            'traceback': traceback.format_exc()
        }
        
        # Add specific error details based on error type
        if isinstance(error, socket.gaierror):
            error_details['error_type'] = 'DNS Resolution Error'
            error_details['suggestion'] = 'Please check your network connection and DNS settings'
        elif isinstance(error, ConnectionRefusedError):
            error_details['error_type'] = 'Connection Refused'
            error_details['suggestion'] = 'The server might be down or the port is blocked by a firewall'
        elif hasattr(error, 'status_code'):
            error_details['status_code'] = error.status_code
            error_details['error_type'] = f'HTTP {error.status_code}'
        elif hasattr(error, 'errno'):
            error_details['error_number'] = error.errno
            error_details['error_message'] = os.strerror(error.errno)
            
        return error_details

    def on_error(self, ws, error):
        """Handle WebSocket errors"""
        # Get detailed error information
        error_details = self._get_connection_error_details(error)
        
        # Log the error with all available details
        logger.error("WebSocket Error:")
        for key, value in error_details.items():
            if key != 'traceback':
                logger.error(f"  {key}: {value}")
        
        # Provide specific guidance based on error type for TradeJini
        if "4001" in str(error) or "Unauthorized Access" in str(error):
            logger.error("Authentication error (4001) detected. This typically means:")
            logger.error("1. Your API key or access token is incorrect or has expired")
            logger.error("2. TradeJini requires token format: '<APIkey>:<accessToken>'")
            logger.error("3. You may need to generate a fresh token from TradeJini developer portal")
            
            # Try to extract API key format from the stored token for debugging
            if self.auth_token:
                if ':' in self.auth_token:
                    parts = self.auth_token.split(':', 1)
                    api_key_masked = parts[0][:3] + "*" * (len(parts[0]) - 3) if len(parts[0]) > 3 else "***"
                    token_masked = parts[1][:3] + "*" * (len(parts[1]) - 3) if len(parts[1]) > 3 else "***"
                    logger.debug(f"Token format: '{api_key_masked}:{token_masked}' - API key length={len(parts[0])}, Access token length={len(parts[1])}")
                else:
                    token_masked = self.auth_token[:4] + "*" * (len(self.auth_token) - 4) if len(self.auth_token) > 4 else "****"
                    logger.debug(f"Token missing ':' separator: '{token_masked}' (length={len(self.auth_token)})")
                    logger.error("Token is missing the required ':' separator between API key and access token")
        
        # Log full traceback at debug level
        logger.debug(f"Full traceback:\n{error_details.get('traceback', 'No traceback available')}")
        
        # Update connection state
        self.connected = False
        self.authenticated = False
        self.connection_state.update({
            'last_error': error_details,
            'last_error_time': datetime.now().isoformat(),
            'connected': False,
            'authenticated': False
        })
        
        # Unblock any waiting threads
        self.response_event.set()
        
        # Log connection state for debugging
        logger.debug(f"Connection state after error: {json.dumps(self.connection_state, indent=2)}")
        
        # Attempt to reconnect if not already reconnecting
        if self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            wait_time = min(5 * self.reconnect_attempts, 30)  # Exponential backoff with max 30s
            logger.warning(f"Attempting to reconnect (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts}) after {wait_time}s...")
            
            # Schedule reconnect
            def delayed_reconnect():
                time.sleep(wait_time)
                logger.info(f"Initiating reconnection attempt {self.reconnect_attempts}...")
                self.connect(self.auth_token)
                
            threading.Thread(target=delayed_reconnect, daemon=True).start()
        else:
            logger.error(f"Max reconnection attempts ({self.max_reconnect_attempts}) reached. Giving up.")
            logger.info("Please check your network connection and API token. If the issue persists, contact support.")
            
        # Log the full error details to a file for further analysis
        try:
            error_log = {
                'timestamp': datetime.now().isoformat(),
                'error': error_details,
                'connection_state': self.connection_state,
                'reconnect_attempts': self.reconnect_attempts
            }
            with open('tradejini_websocket_errors.log', 'a') as f:
                f.write(json.dumps(error_log, indent=2) + '\n')
        except Exception as log_error:
            logger.error(f"Failed to write error log: {str(log_error)}")

    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close"""
        try:
            # Log the close event
            close_info = {
                'status_code': close_status_code,
                'message': close_msg,
                'timestamp': datetime.now().isoformat(),
                'was_connected': self.connected,
                'was_authenticated': self.authenticated,
                'reconnect_attempts': self.reconnect_attempts
            }
            
            logger.info(f"WebSocket connection closed: {close_status_code} - {close_msg}")
            
            # Provide specific guidance for common TradeJini closure codes
            if close_status_code == 4001 or (close_msg and "Unauthorized Access" in close_msg):
                logger.error("TradeJini authentication error (4001). Please check:")
                logger.error("1. Your API key is correct and active in TradeJini developer portal")
                logger.error("2. Your access token is valid and not expired")
                logger.error("3. The token format must be '<APIkey>:<accessToken>'")
                logger.error("4. The API key permissions include data streaming access")
                
                # Check token format in a more structured way
                if self.auth_token:
                    if ':' in self.auth_token:
                        parts = self.auth_token.split(':', 1)
                        api_key_part = parts[0]
                        access_token_part = parts[1]
                        
                        # Typical TradeJini API key is 32 characters
                        if len(api_key_part) != 32:
                            logger.warning(f"API key part has unusual length: {len(api_key_part)} chars (expected 32)")
                        
                        # Typical TradeJini access token has specific length
                        if len(access_token_part) < 20:
                            logger.warning(f"Access token part seems too short: {len(access_token_part)} chars")
                            
                        logger.debug(f"Token parts: API key length={len(api_key_part)}, Access token length={len(access_token_part)}")
                    else:
                        logger.error("Token is missing the ':' separator between API key and access token")
                        logger.debug(f"Current token length: {len(self.auth_token)} chars")
            
            logger.debug(f"Close details: {json.dumps(close_info, indent=2)}")
            
            # Update connection state
            self.connected = False
            self.authenticated = False
            self.connection_state.update({
                'connected': False,
                'authenticated': False,
                'ws_state': 'closed',
                'last_close': close_info,
                'last_activity': datetime.now().isoformat()
            })
            
            # Log the final connection state
            self._log_connection_state("WebSocket connection closed")
            
            # If we were connected and this was unexpected, try to reconnect
            if self.connected and close_status_code != 1000:  # 1000 is normal closure
                logger.warning("Unexpected WebSocket closure, will attempt to reconnect...")
                self.reconnect()
                
        except Exception as e:
            logger.error(f"Error in on_close handler: {str(e)}", exc_info=True)
            
        finally:
            # Ensure we clean up properly
            self.connected = False
            self.authenticated = False
            self.response_event.set()  # Unblock any waiting threads

    def reconnect(self):
        """Attempt to reconnect to the WebSocket"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.warning(f"Max reconnection attempts ({self.max_reconnect_attempts}) already reached")
            return False
            
        self.reconnect_attempts += 1
        wait_time = min(5 * self.reconnect_attempts, 30)  # Exponential backoff with max 30s
        
        logger.info(f"Scheduling reconnection attempt {self.reconnect_attempts}/{self.max_reconnect_attempts} in {wait_time}s...")
        
        def _reconnect():
            try:
                time.sleep(wait_time)
                logger.info(f"Attempting to reconnect (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})...")
                if self.connect(self.auth_token):
                    logger.info("Reconnection successful")
                    return True
                else:
                    logger.warning(f"Reconnection attempt {self.reconnect_attempts} failed")
                    if self.reconnect_attempts < self.max_reconnect_attempts:
                        self.reconnect()  # Schedule next attempt
                    return False
            except Exception as e:
                logger.error(f"Error during reconnection attempt: {str(e)}", exc_info=True)
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    self.reconnect()  # Schedule next attempt
                return False
        
        # Start reconnection in a separate thread
        threading.Thread(target=_reconnect, daemon=True).start()
        return True

    def close(self, code=1000, reason=''):
        """Close WebSocket connection gracefully"""
        if not hasattr(self, 'ws') or not self.ws:
            logger.debug("No active WebSocket connection to close")
            return
            
        try:
            # Log the close attempt
            close_info = {
                'code': code,
                'reason': reason,
                'timestamp': datetime.now().isoformat(),
                'was_connected': self.connected,
                'was_authenticated': self.authenticated
            }
            logger.info(f"Closing WebSocket connection (code: {code}, reason: {reason or 'No reason provided'})")
            
            # Update connection state
            self.connection_state.update({
                'closing': True,
                'last_close_attempt': close_info,
                'ws_state': 'closing'
            })
            
            # Perform the close
            try:
                self.ws.close()
                logger.debug("WebSocket close frame sent")
            except Exception as close_error:
                logger.error(f"Error sending WebSocket close frame: {str(close_error)}")
                # Continue with cleanup even if close frame fails
                
        except Exception as e:
            logger.error(f"Error during WebSocket close: {str(e)}", exc_info=True)
            
        finally:
            # Ensure we clean up our state
            self.connected = False
            self.authenticated = False
            self.ws = None
            self.connection_state.update({
                'connected': False,
                'authenticated': False,
                'ws_state': 'closed',
                'last_activity': datetime.now().isoformat()
            })
            self.response_event.set()  # Unblock any waiting threads
            logger.info("WebSocket connection closed and cleaned up")

    def _send_json(self, data):
        """Send JSON data through WebSocket with request tracking"""
        try:
            if not self.connected:
                logger.error("WebSocket not connected")
                return False
                
            json_data = json.dumps(data)
            logger.debug(f"Sending WebSocket message: {json_data[:500]}...")
            
            try:
                self.ws.send(json_data)
                return True
            except Exception as e:
                logger.error(f"Error sending message: {str(e)}")
                self.connected = False
                return False
                
        except Exception as e:
            logger.error(f"Error in _send_json: {str(e)}", exc_info=True)
            return False

    def _process_historical_data(self, data):
        """Process historical OHLC data"""
        try:
            request_id = data.get('request_id')
            status = data.get('status', '').lower()
            
            if status == 'success':
                candles = data.get('data', [])
                df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                # Convert timestamp from milliseconds to datetime
                if not df.empty and 'timestamp' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                
                with self.lock:
                    if request_id in self.pending_requests:
                        self.pending_requests[request_id]['data'] = df
                        self.pending_requests[request_id]['event'].set()
                        logger.info(f"Received historical data for request {request_id}: {len(df)} candles")
            else:
                error_msg = data.get('message', 'Unknown error')
                logger.error(f"Error in historical data request {request_id}: {error_msg}")
                with self.lock:
                    if request_id in self.pending_requests:
                        self.pending_requests[request_id]['error'] = error_msg
                        self.pending_requests[request_id]['event'].set()
                        
        except Exception as e:
            logger.error(f"Error processing historical data: {str(e)}\nRaw data: {data}", exc_info=True)
            with self.lock:
                if request_id in self.pending_requests:
                    self.pending_requests[request_id]['error'] = str(e)
                    self.pending_requests[request_id]['event'].set()

    # TradeJini binary message format constants
    CURRENT_VERSION = 1
    PKT_TYPE = {
        10: "L1",
        11: "L5",
        12: "OHLC",
        13: "auth",
        14: "marketStatus",
        15: "EVENTS",
        16: "PING",
        17: "greeks"
    }
    
    SEG_INFO = {
        1: {"exchSeg": "NSE", "precision": 2, "divisor": 100.0},
        2: {"exchSeg": "BSE", "precision": 2, "divisor": 100.0},
        3: {"exchSeg": "NFO", "precision": 2, "divisor": 100.0},
        4: {"exchSeg": "BFO", "precision": 2, "divisor": 100.0},
        5: {"exchSeg": "CDS", "precision": 4, "divisor": 10000000.0},
        6: {"exchSeg": "BCD", "precision": 4, "divisor": 10000.0},
        7: {"exchSeg": "MCD", "precision": 4, "divisor": 10000.0},
        8: {"exchSeg": "MCX", "precision": 2, "divisor": 100.0},
        9: {"exchSeg": "NCO", "precision": 2, "divisor": 10000.0},
        10: {"exchSeg": "BCO", "precision": 2, "divisor": 10000.0}
    }
    
    # Default packet specifications for binary parsing
    DEFAULT_PKT_INFO = {
        "PKT_SPEC": {
            10: {
                26: {"struct": "B", "key": "exchSeg", "len": 1},
                27: {"struct": "i", "key": "token", "len": 4},
                28: {"struct": "B", "key": "precision", "len": 1},
                29: {"struct": "i", "key": "ltp", "len": 4, "fmt": lambda v, d: v / d},
                30: {"struct": "i", "key": "open", "len": 4, "fmt": lambda v, d: v / d},
                31: {"struct": "i", "key": "high", "len": 4, "fmt": lambda v, d: v / d},
                32: {"struct": "i", "key": "low", "len": 4, "fmt": lambda v, d: v / d},
                33: {"struct": "i", "key": "close", "len": 4, "fmt": lambda v, d: v / d},
                34: {"struct": "i", "key": "chng", "len": 4, "fmt": lambda v, d: v / d},
                35: {"struct": "i", "key": "chngPer", "len": 4, "fmt": lambda v, d: v / 100.0},
                36: {"struct": "i", "key": "atp", "len": 4, "fmt": lambda v, d: v / d},
                37: {"struct": "i", "key": "yHigh", "len": 4, "fmt": lambda v, d: v / d},
                38: {"struct": "i", "key": "yLow", "len": 4, "fmt": lambda v, d: v / d},
                39: {"struct": "<I", "key": "ltq", "len": 4},
                40: {"struct": "<I", "key": "vol", "len": 4},
                41: {"struct": "d", "key": "ttv", "len": 8},
                42: {"struct": "i", "key": "ucl", "len": 4, "fmt": lambda v, d: v / d},
                43: {"struct": "i", "key": "lcl", "len": 4, "fmt": lambda v, d: v / d},
                44: {"struct": "<I", "key": "OI", "len": 4},
                45: {"struct": "i", "key": "OIChngPer", "len": 4, "fmt": lambda v, d: v / 100.0},
                46: {"struct": "i", "key": "ltt", "len": 4, "fmt": lambda v: datetime.fromtimestamp(v).isoformat()},
                49: {"struct": "i", "key": "bidPrice", "len": 4, "fmt": lambda v, d: v / d},
                50: {"struct": "<I", "key": "qty", "len": 4},
                51: {"struct": "<I", "key": "no", "len": 4},
                52: {"struct": "i", "key": "askPrice", "len": 4, "fmt": lambda v, d: v / d},
                53: {"struct": "<I", "key": "qty", "len": 4},
                54: {"struct": "<I", "key": "no", "len": 4},
                55: {"struct": "B", "key": "nDepth", "len": 1},
                56: {"struct": "H", "key": "nLen", "len": 2},
                58: {"struct": "<I", "key": "prevOI", "len": 4},
                59: {"struct": "<I", "key": "dayHighOI", "len": 4},
                60: {"struct": "<I", "key": "dayLowOI", "len": 4},
                70: {"struct": "i", "key": "spotPrice", "len": 4, "fmt": lambda v, d: v / d},
                71: {"struct": "i", "key": "dayClose", "len": 4, "fmt": lambda v, d: v / d},
                74: {"struct": "i", "key": "vwap", "len": 4, "fmt": lambda v, d: v / d},
            },
            11: {
                26: {"struct": "B", "key": "exchSeg", "len": 1},
                27: {"struct": "i", "key": "token", "len": 4},
                28: {"struct": "B", "key": "precision", "len": 1},
                47: {"struct": "<I", "key": "totBuyQty", "len": 4},
                48: {"struct": "<I", "key": "totSellQty", "len": 4},
                49: {"struct": "i", "key": "price", "len": 4, "fmt": lambda v, d: v / d},
                50: {"struct": "<I", "key": "qty", "len": 4},
                51: {"struct": "<I", "key": "no", "len": 4},
                52: {"struct": "i", "key": "price", "len": 4, "fmt": lambda v, d: v / d},
                53: {"struct": "<I", "key": "qty", "len": 4},
                54: {"struct": "<I", "key": "no", "len": 4},
                55: {"struct": "B", "key": "nDepth", "len": 1},
            },
            12: {
                26: {"struct": "B", "key": "exchSeg", "len": 1},
                27: {"struct": "i", "key": "token", "len": 4},
                28: {"struct": "B", "key": "precision", "len": 1},
                30: {"struct": "i", "key": "open", "len": 4, "fmt": lambda v, d: v / d},
                31: {"struct": "i", "key": "high", "len": 4, "fmt": lambda v, d: v / d},
                32: {"struct": "i", "key": "low", "len": 4, "fmt": lambda v, d: v / d},
                33: {"struct": "i", "key": "close", "len": 4, "fmt": lambda v, d: v / d},
                40: {"struct": "<I", "key": "vol", "len": 4},
                46: {"struct": "i", "key": "time", "len": 4, "fmt": lambda v: datetime.fromtimestamp(v).isoformat()},
                74: {"struct": "i", "key": "vwap", "len": 4, "fmt": lambda v, d: v / d},
                75: {"struct": "string", "key": "type", "len": 4},
                76: {"struct": "<I", "key": "minuteOi", "len": 4},
            },
            13: {
                25: {"struct": "B", "key": "auth_status", "len": 1},
            },
            14: {
                56: {"struct": "H", "key": "nLen", "len": 2},
                26: {"struct": "B", "key": "exchSeg", "len": 1},
                57: {"struct": "B", "key": "marketStatus", "len": 1},
            },
            15: {
                56: {"struct": "H", "key": "nLen", "len": 2},
                61: {"struct": "string", "key": "message", "len": 100},
            },
            16: {
                62: {"struct": "B", "key": "pong", "len": 1},
            },
            17: {
                26: {"struct": "B", "key": "exchSeg", "len": 1},
                27: {"struct": "i", "key": "token", "len": 4},
                63: {"struct": "d", "key": "itm", "len": 8},
                64: {"struct": "d", "key": "iv", "len": 8},
                65: {"struct": "d", "key": "delta", "len": 8},
                66: {"struct": "d", "key": "gamma", "len": 8},
                67: {"struct": "d", "key": "theta", "len": 8},
                68: {"struct": "d", "key": "rho", "len": 8},
                69: {"struct": "d", "key": "vega", "len": 8},
                72: {"struct": "d", "key": "highiv", "len": 8},
                73: {"struct": "d", "key": "lowiv", "len": 8},
            }
        },
        "BID_ASK_OBJ_LEN": 3,
        "MARKET_STATUS_OBJ_LEN": 2
    }

    def _ab2str(self, buf, offset, length):
        """Convert binary data to string."""
        try:
            unpacklen = str(length) + "s"
            v = struct.unpack(unpacklen, buf[offset: offset + length])
            res = v[0].rstrip(b'\x00').decode("utf_8")
            return res
        except Exception as e:
            logger.error(f"Error in _ab2str: {str(e)}")
            return ""

    def _frame_from_spec(self, spec, data, idx):
        """Extract data based on binary specification."""
        binaryKey = spec["struct"]
        binaryLen = spec["len"]

        if binaryKey == "string":
            return self._ab2str(data, idx, binaryLen)
        else:
            try:
                return struct.unpack(binaryKey, data[idx: idx + binaryLen])[0]
            except Exception as e:
                logger.error(f"Error unpacking {binaryKey} at position {idx}: {str(e)}")
                return 0

    def _format_values(self, divisor, raw_data, jData):
        """Format raw values using appropriate formatters."""
        for key, value in raw_data.items():
            try:
                spec = value[0]
                framed = value[1]
                formatted_value = framed
                
                if "fmt" in spec:
                    try:
                        formatted_value = spec["fmt"](framed, divisor)
                    except Exception as format_error:
                        logger.error(f"Error formatting value {key}: {format_error}")
                        formatted_value = framed
                        
                jData[spec["key"]] = formatted_value
            except Exception as e:
                logger.error(f"Error in _format_values for key {key}: {str(e)}")

    def _process_single_packet(self, data, data_len):
        """Process a single binary packet based on its type."""
        try:
            # Get packet type
            pktType = struct.unpack("b", data[2:3])[0]
            pktSpec = self.DEFAULT_PKT_INFO["PKT_SPEC"]
            
            if pktType not in pktSpec:
                logger.error(f"Unknown packet type: {pktType}")
                return
                
            packet_type = self.PKT_TYPE[pktType]
            quote_spec = pktSpec[pktType]
            jData = None
            
            # Process packet based on its type
            if packet_type == "L1":
                jData = self._decode_l1_packet(quote_spec, data_len, data)
            elif packet_type == "L5":
                jData = self._decode_l2_packet(quote_spec, data_len, data)
            elif packet_type == "OHLC":
                jData = self._decode_ohlc_packet(quote_spec, data_len, data)
            elif packet_type == "auth":
                jData = self._decode_auth_packet(quote_spec, data_len, data)
            elif packet_type == "marketStatus":
                jData = self._decode_market_status(quote_spec, data_len, data)
            elif packet_type == "EVENTS":
                jData = self._decode_events_message(quote_spec, data_len, data)
            elif packet_type == "PING":
                jData = self._decode_ping_status(quote_spec, data_len, data)
            elif packet_type == "greeks":
                jData = self._decode_l1_packet(quote_spec, data_len, data)  # Same structure as L1
                
            # Process the data if valid
            if jData is not None:
                jData["msgType"] = packet_type
                
                # Cache L1 data
                if packet_type == "L1":
                    t = jData["symbol"]
                    if t in self.symbol_map:
                        _cache_d = self.symbol_map[t]
                        _cache_d.update(jData)
                        jData = _cache_d
                    self.symbol_map[t] = jData
                    
                # Process the data based on type
                if packet_type == "L1":
                    self._process_quote(jData)
                elif packet_type == "L5":
                    self._process_depth(jData)
                elif packet_type == "OHLC":
                    self._process_ohlc(jData)
                elif packet_type == "auth":
                    self._handle_auth_response(jData)
                    
        except Exception as e:
            logger.error(f"Error processing packet: {str(e)}", exc_info=True)
            
    def _decode_l1_packet(self, pkt_spec, data_len, data):
        """Decode a level 1 quote packet."""
        jData = {}
        raw_data = {}
        exchange_info = None
        divisor = 100.0
        precision = 2
        idx = 3
        
        try:
            while idx < data_len:
                pkt_key = struct.unpack("B", data[idx: idx + 1])
                idx += 1
                
                if pkt_key[0] not in pkt_spec:
                    logger.warning(f"Unknown packet key: {pkt_key[0]} in L1 packet")
                    idx += 1  # Skip to next byte
                    continue
                    
                spec = pkt_spec[pkt_key[0]]
                framed = self._frame_from_spec(spec, data, idx)
                
                if spec["key"] == "exchSeg":
                    if framed in self.SEG_INFO:
                        exchange_info = self.SEG_INFO[framed]
                        precision = exchange_info["precision"]
                        divisor = exchange_info["divisor"]
                        jData[spec["key"]] = exchange_info["exchSeg"]
                    else:
                        logger.warning(f"Unknown exchange segment: {framed}")
                        jData[spec["key"]] = f"UNKNOWN_{framed}"
                elif spec["key"] == "ltt":
                    jData[spec["key"]] = spec["fmt"](framed) if "fmt" in spec else framed
                else:
                    raw_data[spec["key"]] = (spec, framed)
                
                idx += spec["len"]
                
            if exchange_info is not None:
                self._format_values(divisor, raw_data, jData)
            
            jData["symbol"] = f"{jData['token']}_{jData['exchSeg']}"
            jData["precision"] = precision
            
            return jData
        except Exception as e:
            logger.error(f"Error decoding L1 packet: {str(e)}", exc_info=True)
            return None
            
    def _decode_l2_packet(self, pkt_spec, data_len, data):
        """Decode a level 2 market depth packet."""
        exchange_info = None
        raw_data = {}
        divisor = 100.0
        precision = 2
        no_level = 0
        bids = []
        asks = []
        current_list = None
        level_obj = {}
        jData = {}
        idx = 3
        
        try:
            while idx < data_len:
                pkt_key = struct.unpack("B", data[idx: idx + 1])
                idx += 1
                
                if pkt_key[0] not in pkt_spec:
                    logger.warning(f"Unknown packet key: {pkt_key[0]} in L2 packet")
                    idx += 1  # Skip to next byte
                    continue
                    
                spec = pkt_spec[pkt_key[0]]
                framed = self._frame_from_spec(spec, data, idx)
                
                if spec["key"] == "nDepth":
                    no_level = framed
                    current_list = bids
                elif spec["key"] == "exchSeg":
                    if framed in self.SEG_INFO:
                        exchange_info = self.SEG_INFO[framed]
                        precision = exchange_info["precision"]
                        divisor = exchange_info["divisor"]
                        jData[spec["key"]] = exchange_info["exchSeg"]
                    else:
                        logger.warning(f"Unknown exchange segment: {framed}")
                        jData[spec["key"]] = f"UNKNOWN_{framed}"
                else:
                    if current_list is not None:
                        if "fmt" in spec:
                            level_obj[spec["key"]] = spec["fmt"](framed, divisor)
                        else:
                            level_obj[spec["key"]] = framed
                    else:
                        raw_data[spec["key"]] = (spec, framed)
                
                if current_list is not None and level_obj:
                    if len(level_obj) == self.DEFAULT_PKT_INFO["BID_ASK_OBJ_LEN"]:
                        current_list.append(level_obj.copy())
                        level_obj = {}
                    
                    if len(current_list) == no_level:
                        current_list = asks
                
                idx += spec["len"]
            
            if exchange_info is not None:
                self._format_values(divisor, raw_data, jData)
            
            jData["bid"] = bids
            jData["ask"] = asks
            jData["precision"] = precision
            jData["symbol"] = f"{jData['token']}_{jData['exchSeg']}"
            
            return jData
        except Exception as e:
            logger.error(f"Error decoding L2 packet: {str(e)}", exc_info=True)
            return None

    def _decode_ohlc_packet(self, pkt_spec, data_len, data):
        """Decode an OHLC packet."""
        jData = {}
        raw_data = {}
        exchange_info = None
        divisor = 100.0
        precision = 2
        idx = 3
        
        try:
            while idx < data_len:
                pkt_key = struct.unpack("B", data[idx: idx + 1])
                idx += 1
                
                if pkt_key[0] not in pkt_spec:
                    logger.warning(f"Unknown packet key: {pkt_key[0]} in OHLC packet")
                    idx += 1  # Skip to next byte
                    continue
                
                spec = pkt_spec[pkt_key[0]]
                framed = self._frame_from_spec(spec, data, idx)
                
                if spec["key"] == "exchSeg":
                    if framed in self.SEG_INFO:
                        exchange_info = self.SEG_INFO[framed]
                        precision = exchange_info["precision"]
                        divisor = exchange_info["divisor"]
                        jData[spec["key"]] = exchange_info["exchSeg"]
                    else:
                        logger.warning(f"Unknown exchange segment: {framed}")
                        jData[spec["key"]] = f"UNKNOWN_{framed}"
                elif spec["key"] == "time":
                    jData[spec["key"]] = spec["fmt"](framed) if "fmt" in spec else framed
                else:
                    raw_data[spec["key"]] = (spec, framed)
                
                idx += spec["len"]
            
            if exchange_info is not None:
                self._format_values(divisor, raw_data, jData)
            
            jData["symbol"] = f"{jData['token']}_{jData['exchSeg']}"
            jData["precision"] = precision
            
            return jData
        except Exception as e:
            logger.error(f"Error decoding OHLC packet: {str(e)}", exc_info=True)
            return None
            
    def _decode_auth_packet(self, pkt_spec, data_len, data):
        """Decode an authentication packet."""
        try:
            jData = {}
            idx = 3
            
            while idx < data_len:
                pkt_key = struct.unpack("B", data[idx: idx + 1])
                idx += 1
                
                if pkt_key[0] not in pkt_spec:
                    logger.warning(f"Unknown packet key: {pkt_key[0]} in auth packet")
                    idx += 1  # Skip to next byte
                    continue
                    
                spec = pkt_spec[pkt_key[0]]
                framed = self._frame_from_spec(spec, data, idx)
                jData[spec["key"]] = framed
                
                idx += spec["len"]
                
            # Convert auth status to success/error format for consistency
            if "auth_status" in jData:
                if jData["auth_status"] == 1:
                    jData["status"] = "success"
                else:
                    jData["status"] = "error"
                    jData["message"] = "Authentication failed"
                    
            return jData
        except Exception as e:
            logger.error(f"Error decoding auth packet: {str(e)}", exc_info=True)
            return None
            
    def _decode_market_status(self, pkt_spec, data_len, data):
        """Decode a market status packet."""
        try:
            level_obj = {}
            jData = {}
            idx = 3
            no_of_len = 0
            exchange_info = None
            status_list = None
            
            while idx < data_len:
                pkt_key = struct.unpack("B", data[idx: idx + 1])
                idx += 1
                
                if pkt_key[0] not in pkt_spec:
                    logger.warning(f"Unknown packet key: {pkt_key[0]} in market status packet")
                    idx += 1  # Skip to next byte
                    continue
                    
                spec = pkt_spec[pkt_key[0]]
                framed = self._frame_from_spec(spec, data, idx)
                
                if spec["key"] == "nLen":
                    no_of_len = framed
                    status_list = []
                else:
                    level_obj[spec["key"]] = framed
                    if spec["key"] == "exchSeg" and framed in self.SEG_INFO:
                        exchange_info = self.SEG_INFO[framed]
                        level_obj[spec["key"]] = exchange_info["exchSeg"]
                
                if status_list is not None and level_obj:
                    if len(level_obj) == self.DEFAULT_PKT_INFO["MARKET_STATUS_OBJ_LEN"]:
                        status_list.append(level_obj.copy())
                        level_obj = {}
                
                idx += spec["len"]
            
            jData["status"] = status_list if status_list else []
            return jData
        except Exception as e:
            logger.error(f"Error decoding market status packet: {str(e)}", exc_info=True)
            return None
            
    def _decode_events_message(self, pkt_spec, data_len, data):
        """Decode an events message packet."""
        try:
            jData = {}
            idx = 3
            no_of_len = 0
            
            while idx < data_len:
                pkt_key = struct.unpack("B", data[idx: idx + 1])
                idx += 1
                
                if pkt_key[0] not in pkt_spec:
                    logger.warning(f"Unknown packet key: {pkt_key[0]} in events message packet")
                    idx += 1  # Skip to next byte
                    continue
                    
                spec = pkt_spec[pkt_key[0]]
                framed = self._frame_from_spec(spec, data, idx)
                
                if spec["key"] == "nLen":
                    no_of_len = framed
                    # Update message length based on actual value
                    if 61 in pkt_spec:
                        pkt_spec[61]["len"] = no_of_len
                else:
                    jData[spec["key"]] = framed
                
                idx += spec["len"]
                
            return jData
        except Exception as e:
            logger.error(f"Error decoding events message packet: {str(e)}", exc_info=True)
            return None
            
    def _decode_ping_status(self, pkt_spec, data_len, data):
        """Decode a ping status packet."""
        try:
            jData = {}
            idx = 3
            
            while idx < data_len:
                pkt_key = struct.unpack("B", data[idx: idx + 1])
                idx += 1
                
                if pkt_key[0] not in pkt_spec:
                    logger.warning(f"Unknown packet key: {pkt_key[0]} in ping status packet")
                    idx += 1  # Skip to next byte
                    continue
                    
                spec = pkt_spec[pkt_key[0]]
                framed = self._frame_from_spec(spec, data, idx)
                jData[spec["key"]] = spec["fmt"](framed) if "fmt" in spec else framed
                
                idx += spec["len"]
                
            return jData
        except Exception as e:
            logger.error(f"Error decoding ping status packet: {str(e)}", exc_info=True)
            return None

    def _handle_binary_message(self, message):
        """Handle binary WebSocket messages"""
        try:
            # Parse the binary message
            logger.debug(f"Handling binary message (length: {len(message)} bytes)")
            
            # Extract total received length and version
            totalRecivedLen = struct.unpack("i", message[:4])[0]
            version = struct.unpack("b", message[4:5])[0]
            
            if version != self.CURRENT_VERSION:
                logger.error(f"Unsupported protocol version: {version}, expected {self.CURRENT_VERSION}")
                return
            
            # Check compression algorithm
            compressionAlgo = struct.unpack("b", message[5:6])[0]
            dc_data = message[6:]
            
            if compressionAlgo == 100:
                # Decompress ZLib data
                try:
                    dc_data = zlib.decompress(message[6:])
                    logger.debug(f"Decompressed data length: {len(dc_data)} bytes")
                except Exception as e:
                    logger.error(f"Error decompressing data: {str(e)}")
                    return
            
            # Process all packets in the message
            totalRecivedLen = len(dc_data)
            bufferIndex = 0
            
            while bufferIndex < totalRecivedLen:
                try:
                    pktLen = struct.unpack("h", dc_data[bufferIndex: (bufferIndex + 2)])[0]
                    if pktLen <= 0:
                        logger.error(f"Invalid packet length: {pktLen}")
                        break
                        
                    self._process_single_packet(dc_data[bufferIndex: (bufferIndex + pktLen)], pktLen)
                    bufferIndex += pktLen
                    
                except Exception as packet_error:
                    logger.error(f"Error processing packet at index {bufferIndex}: {str(packet_error)}")
                    break
                    
        except Exception as e:
            logger.error(f"Error handling binary message: {str(e)}", exc_info=True)

    def on_ping(self, ws, message):
        """Handle WebSocket ping"""
        logger.debug("Received ping from server")
        self.connection_state['last_ping'] = datetime.now().isoformat()
        try:
            # Send pong response
            self.ws.pong()
        except Exception as e:
            logger.error(f"Error sending pong: {str(e)}")
            
    def on_pong(self, ws, message):
        """Handle WebSocket pong"""
        logger.debug("Received pong from server")
        self.connection_state['last_pong'] = datetime.now().isoformat()
        
    def get_connection_state(self):
        """Get current connection state for debugging"""
        return {
            'connected': self.connected,
            'authenticated': self.authenticated,
            'last_message': datetime.fromtimestamp(self.last_message_time).isoformat() if self.last_message_time else None,
            'reconnect_attempts': self.reconnect_attempts,
            'connection_state': self.connection_state,
            'pending_subscriptions': len(self.pending_subscriptions),
            'pending_requests': len(self.pending_requests)
        }

    def _process_quote(self, data):
        """Process quote data"""
        try:
            token = data.get('token')
            exchange = data.get('exchSeg')
            symbol = f"{token}_{exchange}"
            
            # Extract all possible fields with defaults
            quote_data = {
                'symbol': symbol,
                'token': token,
                'exchange': exchange,
                'bid': float(data.get('bidPrice', 0)),
                'ask': float(data.get('askPrice', 0)),
                'bid_qty': float(data.get('bidQty', 0)),
                'ask_qty': float(data.get('askQty', 0)),
                'open': float(data.get('open', 0)),
                'high': float(data.get('high', 0)),
                'low': float(data.get('low', 0)),
                'ltp': float(data.get('ltp', 0)),
                'close': float(data.get('close', 0)),
                'prev_close': float(data.get('prevClose', data.get('close', 0))),
                'volume': int(data.get('vol', 0)),
                'total_buy_qty': float(data.get('totalBuyQty', 0)),
                'total_sell_qty': float(data.get('totalSellQty', 0)),
                'oi': float(data.get('oi', 0)),
                'timestamp': data.get('ltt', data.get('time', int(time.time() * 1000))),
                'raw_data': data  # Keep original data for reference
            }
            
            logger.debug(f"Processed quote for {symbol}: {quote_data}")
            
            with self.lock:
                self.last_quote = quote_data
                logger.info(f"Updated last_quote for {symbol}")
                
            # If there are pending requests for this symbol, notify them
            if symbol in self.pending_requests:
                self.pending_requests[symbol]['data'] = quote_data
                self.pending_requests[symbol]['event'].set()
                
        except Exception as e:
            logger.error(f"Error processing quote: {str(e)}\nRaw data: {data}", exc_info=True)

    def _process_depth(self, data):
        """Process market depth data"""
        try:
            bids = []
            asks = []
            
            # Process bids (up to 5 levels)
            for i in range(5):
                if i < len(data.get('bidPrices', [])) and i < len(data.get('bidQtys', [])):
                    bids.append({
                        'price': float(data['bidPrices'][i]),
                        'quantity': int(data['bidQtys'][i])
                    })
            
            # Process asks (up to 5 levels)
            for i in range(5):
                if i < len(data.get('askPrices', [])) and i < len(data.get('askQtys', [])):
                    asks.append({
                        'price': float(data['askPrices'][i]),
                        'quantity': int(data['askQtys'][i])
                    })
            
            with self.lock:
                self.last_depth = {
                    'bids': bids,
                    'asks': asks,
                    'totalbuyqty': sum(bid['quantity'] for bid in bids),
                    'totalsellqty': sum(ask['quantity'] for ask in asks),
                    'ltp': float(data.get('ltp', 0)),
                    'volume': int(data.get('vol', 0))
                }
        except Exception as e:
            logger.error(f"Error processing depth: {e}")

    def subscribe_quotes(self, tokens):
        """
        Subscribe to quote updates for given tokens
        
        Args:
            tokens: List of dicts with 'token' and 'exchange' or list of token strings
        """
        if not self.connected:
            logger.error("WebSocket not connected")
            return False
            
        try:
            # Format tokens for subscription according to TradeJini format
            formatted_tokens = []
            for token in tokens:
                if isinstance(token, dict) and 'token' in token and 'exchange' in token:
                    # Format according to TradeJini WebSocket API: append to tokens list with 't' key
                    token_str = str(token['token'])
                    exchange = token['exchange']
                    exchange_token = self._get_exchange_token(token_str, exchange)
                    formatted_tokens.append({"t": exchange_token})
                    logger.info(f"Subscribing to {exchange_token} from {token_str} on {exchange}")
                elif isinstance(token, str):
                    # Assume format "TOKEN_EXCHANGE" or just TOKEN (default to NSE)
                    parts = token.split('_')
                    if len(parts) == 2:
                        token_str = parts[0].strip()
                        exchange = parts[1].strip()
                    else:
                        token_str = token.strip()
                        exchange = "NSE"
                    formatted_tokens.append({"t": token_str, "exch": exchange})
                    logger.info(f"Subscribing to {token_str} on {exchange}")
            
            if not formatted_tokens:
                logger.error("No valid tokens provided for subscription")
                return False
                
            # Create subscription message
            request_id = str(int(time.time() * 1000))
            # Send subscription request in TradeJini format
            req = {
                "type": "L1",
                "action": "sub",
                "tokens": formatted_tokens
            }
            
            # Add to pending requests
            self.pending_requests[request_id] = {
                'event': threading.Event(),
                'data': None,
                'error': None
            }
            
            # Send subscription message
            if not self._send_json(req):
                return False
                
            # Wait for response with timeout
            if not self.pending_requests[request_id]['event'].wait(5):  # Reduced timeout to 5 seconds
                logger.warning("Timeout waiting for subscription confirmation")
                return False
                
            # Check for errors
            if self.pending_requests[request_id].get('error'):
                logger.error(f"Subscription failed: {self.pending_requests[request_id]['error']}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error in subscribe_quotes: {str(e)}", exc_info=True)
            return False
        finally:
            # Clean up pending request
            if 'request_id' in locals() and request_id in self.pending_requests:
                del self.pending_requests[request_id]

    def subscribe_ohlc(self, tokens, interval):
        """
        Subscribe to OHLC data for given tokens and interval
        
        Args:
            tokens: List of dicts with 'token' and 'exchange' or list of token strings
            interval: Chart interval (1m, 5m, 15m, 30m, 60m, 1d)
        """
        if not self.connected:
            logger.error("WebSocket not connected")
            return False
            
        try:
            # Format tokens for subscription
            formatted_tokens = []
            for token in tokens:
                if isinstance(token, dict) and 'token' in token and 'exchange' in token:
                    token_str = str(token['token'])
                    exchange = token['exchange']
                    formatted_tokens.append({"t": token_str, "exch": exchange})
                    logger.info(f"Subscribing to OHLC {token_str} on {exchange} with interval {interval}")
                elif isinstance(token, str):
                    # Assume format "TOKEN:EXCHANGE" or just TOKEN (default to NSE)
                    parts = token.split(':')
                    if len(parts) == 2:
                        token_str = parts[0].strip()
                        exchange = parts[1].strip()
                    else:
                        token_str = token.strip()
                        exchange = "NSE"
                    formatted_tokens.append({"t": token_str, "exch": exchange})
                    logger.info(f"Subscribing to OHLC {token_str} on {exchange} with interval {interval}")
            
            if not formatted_tokens:
                logger.error("No valid tokens provided for OHLC subscription")
                return False
                
            # Create subscription message
            request_id = str(int(time.time() * 1000))
            req = {
                "type": "OHLC",
                "action": "sub",
                "tokens": formatted_tokens,
                "chartInterval": interval,
                "request_id": request_id
            }
            
            # Add to pending requests
            self.pending_requests[request_id] = {
                'event': threading.Event(),
                'data': None,
                'error': None
            }
            
            # Send subscription message
            if not self._send_json(req):
                return False
                
            # Wait for response with timeout
            if not self.pending_requests[request_id]['event'].wait(10):
                logger.warning("Timeout waiting for OHLC subscription confirmation")
                return False
                
            # Check for errors
            if self.pending_requests[request_id].get('error'):
                logger.error(f"OHLC subscription failed: {self.pending_requests[request_id]['error']}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error in subscribe_ohlc: {str(e)}", exc_info=True)
            return False
        finally:
            # Clean up pending request
            if 'request_id' in locals() and request_id in self.pending_requests:
                del self.pending_requests[request_id]

    def unsubscribe_ohlc(self, interval):
        """
        Unsubscribe from OHLC data for a specific interval
        
        Args:
            interval: Chart interval to unsubscribe from (1m, 5m, 15m, 30m, 60m, 1d)
        """
        try:
            request_id = str(int(time.time() * 1000))
            unsub_msg = {
                "type": "OHLC",
                "action": "unsub",
                "chartInterval": interval,
                "request_id": request_id
            }
            
            # Add to pending requests
            self.pending_requests[request_id] = {
                'event': threading.Event(),
                'data': None,
                'error': None
            }
            
            # Send unsubscribe message
            if not self._send_json(unsub_msg):
                return False
                
            # Wait for response with timeout
            if not self.pending_requests[request_id]['event'].wait(10):
                logger.warning("Timeout waiting for OHLC unsubscription confirmation")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error in unsubscribe_ohlc: {str(e)}", exc_info=True)
            return False
        finally:
            # Clean up pending request
            if 'request_id' in locals() and request_id in self.pending_requests:
                del self.pending_requests[request_id]

    def _process_ohlc(self, data):
        """Process OHLC data packet"""
        try:
            ohlc_data = {
                'token': str(data.get('token', '')),
                'exchange': data.get('exchSeg', ''),
                'open': float(data.get('open', 0)),
                'high': float(data.get('high', 0)),
                'low': float(data.get('low', 0)),
                'close': float(data.get('close', 0)),
                'volume': int(data.get('vol', 0)),
                'timestamp': data.get('time', ''),
                'interval': data.get('chartInterval', '')
            }
            
            symbol = f"{ohlc_data['token']}_{ohlc_data['exchange']}"
            
            # Store the latest OHLC data
            with self.lock:
                if not hasattr(self, 'ohlc_data'):
                    self.ohlc_data = {}
                if symbol not in self.ohlc_data:
                    self.ohlc_data[symbol] = {}
                self.ohlc_data[symbol][ohlc_data['interval']] = ohlc_data
                
            logger.debug(f"Processed OHLC data for {symbol} ({ohlc_data['interval']}): {ohlc_data}")
            
            # Trigger callback if set
            if hasattr(self, 'on_ohlc'):
                self.on_ohlc(ohlc_data)
                
        except Exception as e:
            logger.error(f"Error processing OHLC data: {str(e)}\nRaw data: {data}", exc_info=True)

    def _send_message(self, message):
        """Send message to WebSocket with request tracking"""
        try:
            request_id = self._send_json(message)
            if not request_id:
                return False
                
            # If this is a request that expects a response
            if 'request_id' in message and message.get('expect_response', True):
                try:
                    # Wait for response with timeout
                    if not self.pending_requests[request_id]['event'].wait(10):  # 10 second timeout
                        logger.warning(f"Timeout waiting for response to request {request_id}")
                        return False
                        
                    # Check for errors in the response
                    if self.pending_requests[request_id].get('error'):
                        logger.error(f"Request {request_id} failed: {self.pending_requests[request_id]['error']}")
                        return False
                        
                    return True
                finally:
                    # Clean up the pending request
                    if request_id in self.pending_requests:
                        del self.pending_requests[request_id]
            return True
            
        except Exception as e:
            logger.error(f"Error in _send_message: {str(e)}", exc_info=True)
            return False

    def subscribe_quote(self, symbol, exchange, token):
        """Subscribe to real-time quotes for a single symbol"""
        return self.subscribe_quotes([{"token": token, "exchange": exchange}])
        
    def subscribe_depth(self, symbol, exchange, token):
        """Subscribe to market depth"""
        try:
            # Create subscription message
            request_id = str(int(time.time() * 1000))
            sub_msg = {
                "type": "L5",
                "action": "sub",
                "tokens": [{"t": str(token), "exch": exchange}],
                "request_id": request_id
            }
            
            # Add to pending requests
            self.pending_requests[request_id] = {
                'event': threading.Event(),
                'data': None,
                'error': None
            }
            
            # Send subscription message
            if not self._send_json(req):
                return False
                
            # Wait for response with timeout
            if not self.pending_requests[request_id]['event'].wait(10):
                logger.warning("Timeout waiting for depth subscription confirmation")
                return False
                
            # Check for errors
            if self.pending_requests[request_id].get('error'):
                logger.error(f"Depth subscription failed: {self.pending_requests[request_id]['error']}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error in subscribe_depth: {str(e)}", exc_info=True)
            return False
        finally:
            # Clean up pending request
            if 'request_id' in locals() and request_id in self.pending_requests:
                del self.pending_requests[request_id]

    def request_historical_data(self, token, exchange, interval, from_date, to_date):
        """
        Request historical OHLC data
        
        Args:
            token: Trading symbol token
            exchange: Exchange (NSE, BSE, etc.)
            interval: Time interval (1m, 5m, 15m, 30m, 60m, 1d)
            from_date: Start date (YYYY-MM-DD or timestamp in ms)
            to_date: End date (YYYY-MM-DD or timestamp in ms)
            
        Returns:
            tuple: (success, data_or_error)
        """
        try:
            # Generate a unique request ID
            request_id = str(int(time.time() * 1000))
            
            # Create event to wait for response
            self.pending_requests[request_id] = {
                'event': threading.Event(),
                'data': None,
                'error': None
            }
            
            # Prepare historical data request
            hist_msg = {
                'type': 'historical',
                'request_id': request_id,
                'token': str(token),
                'exchange': exchange,
                'interval': interval,
                'from': from_date,
                'to': to_date,
                'expect_response': True
            }
            
            logger.info(f"Requesting historical data: {hist_msg}")
            
            # Send the request
            if not self._send_json(hist_msg):
                return False, "Failed to send historical data request"
            
            # Wait for response with timeout (30 seconds)
            if not self.pending_requests[request_id]['event'].wait(30):
                return False, "Request timed out"
            
            # Get response data
            result = self.pending_requests[request_id]
            
            if 'error' in result and result['error']:
                return False, result['error']
                
            return True, result.get('data', pd.DataFrame())
            
        except Exception as e:
            logger.error(f"Error in request_historical_data: {str(e)}", exc_info=True)
            return False, str(e)
        finally:
            # Clean up
            if 'request_id' in locals() and request_id in self.pending_requests:
                del self.pending_requests[request_id]

    def close(self):
        """Close WebSocket connection"""
        if self.ws:
            self.ws.close()
            self.connected = False
            self.authenticated = False

    def _process_pending_subscriptions(self):
        """Process any pending subscriptions after successful authentication"""
        with self.lock:
            if self.pending_subscriptions:
                logger.info(f"Processing {len(self.pending_subscriptions)} pending subscriptions")
                for sub_msg in self.pending_subscriptions:
                    self._send_json(sub_msg)
                self.pending_subscriptions = []

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Tradejini data handler with authentication token"""
        self.auth_token = auth_token
        self.ws = TradejiniWebSocket()
        
        # Map common timeframe format to Tradejini resolutions
        self.timeframe_map = {
            '1m': '1m',    # 1 minute
            '5m': '5m',    # 5 minutes
            '15m': '15m',  # 15 minutes
            '30m': '30m',  # 30 minutes
            '1h': '60m',   # 1 hour
            'D': '1d'      # Daily
        }

    def _get_auth_header(self):
        """
        Get the authentication header in the format used by funds.py
        
        Returns:
            str: Authentication header in the format 'api_key:auth_token'
        """
        try:
            # Get API key from environment
            api_key = os.getenv('BROKER_API_SECRET')
            if not api_key:
                error_msg = "BROKER_API_SECRET not set in environment variables"
                logger.error(error_msg)
                raise ValueError(error_msg)
                
            if not self.auth_token:
                error_msg = "No authentication token provided"
                logger.error(error_msg)
                raise ValueError(error_msg)
                
            # Format: 'api_key:auth_token' as per funds.py
            auth_header = f"{api_key}:{self.auth_token}"
            
            # Log the format (mask sensitive parts)
            masked_header = f"{api_key[:4]}...:{self.auth_token[:4]}..." if len(api_key) > 4 and len(self.auth_token) > 4 else "****"
            logger.debug(f"Using auth header format: {masked_header}")
            
            return auth_header
            
        except Exception as e:
            logger.error(f"Error generating auth header: {str(e)}", exc_info=True)
            raise

    def connect_websocket(self):
        """
        Initialize WebSocket connection if not already connected
        
        Returns:
            bool: True if connection is successful or already established, False otherwise
        """
        try:
            # Check if WebSocket is already connected
            if hasattr(self, 'ws') and self.ws.connected:
                logger.debug("WebSocket is already connected")
                return True
                
            logger.info("Initializing new WebSocket connection...")
            
            # Get the authentication header in the correct format
            auth_header = self._get_auth_header()
            
            # Initialize new WebSocket instance with the formatted auth header
            self.ws = TradejiniWebSocket()
            
            # Attempt to connect with the formatted auth header
            logger.info("Connecting to TradeJini WebSocket...")
            self.ws.connect(auth_header)
            
            # Wait briefly to allow connection to establish
            time.sleep(1)
            
            # Verify connection status
            if hasattr(self.ws, 'connected') and self.ws.connected:
                logger.info("Successfully connected to TradeJini WebSocket")
                return True
            else:
                error_msg = "Failed to establish WebSocket connection"
                if hasattr(self.ws, 'connection_state') and 'last_error' in self.ws.connection_state:
                    error_msg += f": {self.ws.connection_state['last_error']}"
                logger.error(error_msg)
                return False
                
        except Exception as e:
            error_msg = f"Error in connect_websocket: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol (e.g., 'RELIANCE', 'NIFTY25MAY23FUT')
            exchange: Exchange (e.g., 'NSE', 'BSE', 'NFO', 'MCX')
        Returns:
            dict: Quote data with required fields
        """
        try:
            logger.info(f"Getting quotes for {symbol} on {exchange}")
            
            # Convert symbol to broker format and get token
            token = get_token(symbol, exchange)
            if not token:
                error_msg = f"Token not found for {symbol} on {exchange}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            # Map exchange to Tradejini format
            exchange_map = {
                'NSE': 'NSE',
                'BSE': 'BSE',
                'NFO': 'NFO',
                'BFO': 'BFO',
                'CDS': 'CDS',
                'BCD': 'BCD',
                'MCD': 'MCD',
                'MCX': 'MCX',
                'NCO': 'NCO',
                'BCO': 'BCO',
                'NSE_INDEX': 'NSE',
                'BSE_INDEX': 'BSE'
            }
            
            tradejini_exchange = exchange_map.get(exchange)
            if not tradejini_exchange:
                error_msg = f"Unsupported exchange: {exchange}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            # Connect to WebSocket if not already connected
            if not self.ws.connected:
                logger.info("WebSocket not connected, attempting to connect...")
                try:
                    if not self.connect_websocket():
                        error_msg = "Failed to connect to WebSocket"
                        logger.error(error_msg)
                        
                        # Check if we have connection state details
                        if hasattr(self.ws, 'connection_state') and 'last_error' in self.ws.connection_state:
                            error_msg += f" - {self.ws.connection_state['last_error']}"
                            
                        # Log detailed connection state if available
                        if hasattr(self.ws, 'connection_state'):
                            logger.debug(f"Connection state: {json.dumps(self.ws.connection_state, indent=2, default=str)}")
                            
                        raise ConnectionError(error_msg)
                except Exception as e:
                    error_msg = f"Error connecting to WebSocket: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    raise ConnectionError(error_msg) from e

            # Reset last_quote before subscribing
            with self.ws.lock:
                self.ws.last_quote = None

            # Subscribe to quotes
            logger.info(f"Subscribing to {symbol} on {tradejini_exchange} (token: {token})")
            if not self.ws.subscribe_quote(symbol, tradejini_exchange, token):
                error_msg = f"Failed to subscribe to {symbol} on {tradejini_exchange}"
                logger.error(error_msg)
                raise ConnectionError(error_msg)

            # Wait for data to arrive with retry logic
            max_retries = 3
            retry_delay = 2  # seconds
            last_quote = None
            
            for attempt in range(max_retries):
                logger.info(f"Waiting for quote data (attempt {attempt + 1}/{max_retries})...")
                timeout = time.time() + 5  # 5 seconds per attempt
                
                while time.time() < timeout:
                    with self.ws.lock:
                        if self.ws.last_quote:
                            last_quote = self.ws.last_quote
                            logger.info(f"Received quote data: {last_quote}")
                            return last_quote
                    time.sleep(0.1)
                    
                logger.warning(f"No quote data received in attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
            
            # If we get here, all retries failed
            error_msg = f"Failed to get quote data for {symbol} after {max_retries} attempts"
            logger.error(error_msg)
            raise TimeoutError(error_msg)
            
        except Exception as e:
            logger.error(f"Error in get_quotes: {str(e)}", exc_info=True)
            # Return a default quote structure on error
            return {
                'bid': 0, 'ask': 0, 'open': 0,
                'high': 0, 'low': 0, 'ltp': 0,
                'prev_close': 0, 'volume': 0,
                'error': str(e)
            }

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data with bids, asks and other details
        """
        try:
            # Get token for the symbol
            token = get_token(symbol, exchange)
            if not token:
                raise ValueError(f"Token not found for {symbol} on {exchange}")

            # Map exchange to Tradejini format
            exchange_map = {
                'NSE': 'NSE',
                'BSE': 'BSE',
                'NFO': 'NFO',
                'BFO': 'BFO',
                'CDS': 'CDS',
                'NSE_INDEX': 'NSE',
                'BSE_INDEX': 'BSE'
            }
            tradejini_exchange = exchange_map.get(exchange)
            if not tradejini_exchange:
                raise ValueError(f"Unsupported exchange: {exchange}")

            # Connect to WebSocket if not already connected
            self.connect_websocket()
            
            # Subscribe to market depth
            self.ws.subscribe_depth(symbol, tradejini_exchange, token)
            
            # Wait for data to arrive
            timeout = time.time() + 5  # 5 seconds timeout
            while not self.ws.last_depth and time.time() < timeout:
                time.sleep(0.1)
            
            # Return default structure if no data received
            default_depth = {
                'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'totalbuyqty': 0,
                'totalsellqty': 0,
                'ltp': 0,
                'ltq': 0,
                'volume': 0,
                'open': 0,
                'high': 0,
                'low': 0,
                'prev_close': 0,
                'oi': 0
            }
            
            return self.ws.last_depth or default_depth
            
        except Exception as e:
            logger.error(f"Error in get_depth: {e}")
            return {
                'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'totalbuyqty': 0,
                'totalsellqty': 0,
                'ltp': 0,
                'ltq': 0,
                'volume': 0,
                'open': 0,
                'high': 0,
                'low': 0,
                'prev_close': 0,
                'oi': 0
            }

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical OHLC data for given symbol

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE', 'TATASTEEL')
            exchange: Exchange (e.g., 'NSE', 'BSE')
            interval: Time interval ('1m', '5m', '15m', '30m', '60m', '1d')
            start_date: Start date in 'YYYY-MM-DD' format or timestamp in milliseconds
            end_date: End date in 'YYYY-MM-DD' format or timestamp in milliseconds

        Returns:
            pd.DataFrame: DataFrame with OHLCV data
        """
        try:
            # Convert dates to timestamp in milliseconds if they're strings
            if isinstance(start_date, str):
                start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
            else:
                start_ts = int(start_date)

            if isinstance(end_date, str):
                end_ts = int(pd.Timestamp(end_date).timestamp() * 1000)
            else:
                end_ts = int(end_date)

            # Get token for the symbol
            token = get_token(symbol, exchange)
            if not token:
                logger.error(f"Token not found for {symbol} on {exchange}")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            # Ensure WebSocket is connected
            if not self.ws.connected:
                self.ws.connect(self.auth_token)

            # Map interval to Tradejini format
            interval_map = {
                '1m': '1m',
                '5m': '5m',
                '15m': '15m',
                '30m': '30m',
                '60m': '60m',
                '1h': '60m',
                '1d': '1d',
                'D': '1d'
            }

            tj_interval = interval_map.get(interval, interval)

            # Request historical data
            success, result = self.ws.request_historical_data(
                token=token,
                exchange=exchange.upper(),
                interval=tj_interval,
                from_date=start_ts,
                to_date=end_ts
            )

            if not success:
                logger.error(f"Failed to get historical data: {result}")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            # Ensure we have the required columns
            if not result.empty:
                required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                for col in required_cols:
                    if col not in result.columns:
                        result[col] = 0.0

                # Ensure timestamp is datetime
                if not pd.api.types.is_datetime64_any_dtype(result['timestamp']):
                    result['timestamp'] = pd.to_datetime(result['timestamp'], unit='ms')

                # Sort by timestamp
                result = result.sort_values('timestamp')

                # Set timestamp as index
                result = result.set_index('timestamp')

                # Ensure numeric columns are float
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    result[col] = pd.to_numeric(result[col], errors='coerce')

                logger.info(f"Successfully retrieved {len(result)} rows of historical data for {symbol} ({exchange})")
                return result

            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        except Exception as e:
            logger.error(f"Error in get_history: {str(e)}", exc_info=True)
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

    def get_intervals(self) -> list:
        """
        Get list of supported intervals
        Returns:
            list: List of supported intervals
        """
        return list(self.timeframe_map.keys())

    def subscribe_ohlc(self, symbol: str, exchange: str, interval: str):
        """
        Subscribe to OHLC data for a symbol
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Time interval ('1m', '5m', '15m', '30m', '60m', '1d')
        """
        try:
            token = get_token(symbol, exchange)
            if not token:
                raise ValueError(f"Token not found for {symbol} on {exchange}")
                
            # Map exchange to Tradejini format
            exchange_map = {
                'NSE': 'NSE',
                'BSE': 'BSE',
                'NFO': 'NFO',
                'BFO': 'BFO',
                'CDS': 'CDS',
                'BCD': 'BCD',
                'MCD': 'MCD',
                'MCX': 'MCX',
                'NCO': 'NCO',
                'BCO': 'BCO'
            }
            
            exchange = exchange_map.get(exchange, exchange)
            
            # Connect WebSocket if not connected
            self.connect_websocket()
            
            # Subscribe to OHLC data
            success = self.ws.subscribe_ohlc(
                tokens=[{"token": token, "exchange": exchange}],
                interval=interval
            )
            
            if not success:
                logger.error(f"Failed to subscribe to OHLC data for {symbol} ({exchange})")
                return False
                
            logger.info(f"Successfully subscribed to OHLC data for {symbol} ({exchange}) with interval {interval}")
            return True
            
        except Exception as e:
            logger.error(f"Error in subscribe_ohlc: {str(e)}", exc_info=True)
            return False
    
    def unsubscribe_ohlc(self, interval: str):
        """
        Unsubscribe from OHLC data for a specific interval
        
        Args:
            interval: Time interval to unsubscribe from ('1m', '5m', '15m', '30m', '60m', '1d')
        """
        try:
            if not hasattr(self, 'ws') or not self.ws.connected:
                logger.warning("WebSocket not connected")
                return False
                
            return self.ws.unsubscribe_ohlc(interval)
            
        except Exception as e:
            logger.error(f"Error in unsubscribe_ohlc: {str(e)}", exc_info=True)
            return False
    
    def get_ohlc(self, symbol: str, exchange: str, interval: str) -> dict:
        """
        Get the latest OHLC data for a symbol
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Time interval ('1m', '5m', '15m', '30m', '60m', '1d')
            
        Returns:
            dict: Latest OHLC data or empty dict if not available
        """
        try:
            if not hasattr(self, 'ws') or not self.ws.connected:
                logger.warning("WebSocket not connected")
                return {}
                
            token = get_token(symbol, exchange)
            if not token:
                logger.error(f"Token not found for {symbol} on {exchange}")
                return {}
                
            exchange_map = {
                'NSE': 'NSE',
                'BSE': 'BSE',
                'NFO': 'NFO',
                'BFO': 'BFO',
                'CDS': 'CDS',
                'BCD': 'BCD',
                'MCD': 'MCD',
                'MCX': 'MCX',
                'NCO': 'NCO',
                'BCO': 'BCO'
            }
            exchange = exchange_map.get(exchange, exchange)
            
            symbol_key = f"{token}_{exchange}"
            
            with self.ws.lock:
                if hasattr(self.ws, 'ohlc_data') and symbol_key in self.ws.ohlc_data:
                    return self.ws.ohlc_data[symbol_key].get(interval, {})
                
            return {}
            
        except Exception as e:
            logger.error(f"Error in get_ohlc: {str(e)}", exc_info=True)
            return {}
