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
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple, Union
from database.token_db import get_token, get_br_symbol, get_oa_symbol, get_symbol
from utils.httpx_client import get_httpx_client

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

    def _parse_binary_message(self, message):
        """Parse binary message from TradeJini WebSocket"""
        try:
            if len(message) < 6:  # Need at least 6 bytes for header
                logger.warning(f"Binary message too short: {len(message)} bytes")
                return None
                
            # Total received length is first 4 bytes
            total_received_len = struct.unpack("i", message[:4])[0]
            # Version is the 5th byte
            version = struct.unpack("b", message[4:5])[0]
            # Compression algorithm is the 6th byte
            compression_algo = struct.unpack("b", message[5:6])[0]
            
            logger.debug(f"Binary message: length={total_received_len}, version={version}, compression={compression_algo}")
            
            # Decompress if needed
            dc_data = message[6:]
            if compression_algo == 100:
                try:
                    dc_data = zlib.decompress(message[6:])
                    logger.debug(f"Decompressed data length: {len(dc_data)}")
                except Exception as e:
                    logger.error(f"Decompression error: {e}")
                    return None
            
            # Process all packets in the message
            total_received_len = len(dc_data)
            buffer_index = 0
            while buffer_index < total_received_len:
                # Each packet starts with a 2-byte length
                pkt_len = struct.unpack("h", dc_data[buffer_index:(buffer_index + 2)])[0]
                if pkt_len <= 0:
                    logger.warning(f"Invalid packet length: {pkt_len}")
                    break
                
                # Process single packet
                self._process_single_packet(dc_data[buffer_index:(buffer_index + pkt_len)], pkt_len)
                buffer_index += pkt_len
            
        except Exception as e:
            logger.error(f"Error parsing binary message: {str(e)}", exc_info=True)
            return None
            
    def _handle_subscription_response(self, data):
        """Handle subscription confirmation/response"""
        try:
            if not isinstance(data, dict):
                return False
                
            status = data.get('status', '').lower()
            request_id = data.get('request_id')
            
            if request_id and request_id in self.pending_requests:
                if status == 'success':
                    logger.info(f"Subscription successful for request_id: {request_id}")
                    self.pending_requests[request_id]['data'] = data
                    self.pending_requests[request_id]['event'].set()
                    return True
                else:
                    error_msg = data.get('message', 'Unknown error')
                    logger.error(f"Subscription failed for request_id {request_id}: {error_msg}")
                    self.pending_requests[request_id]['error'] = error_msg
                    self.pending_requests[request_id]['event'].set()
                    return False
            return False
            
        except Exception as e:
            logger.error(f"Error handling subscription response: {str(e)}", exc_info=True)
            return False
            
    def _process_quote(self, data):
        """Process incoming quote data"""
        try:
            if not isinstance(data, dict):
                logger.warning(f"Expected dict for quote data, got {type(data)}")
                return
                
            # Check if this is a subscription response
            if data.get('type') in ['sub_ack', 'unsub_ack']:
                self._handle_subscription_response(data)
                return
                
            # Handle different quote types
            quote_type = data.get('type', '').lower()
            
            # Store the last quote for get_quotes
            with self.lock:
                self.last_quote = data
                
            # Log the quote data
            logger.debug(f"Quote update: {json.dumps(data, indent=2)}")
            
        except Exception as e:
            logger.error(f"Error processing quote data: {str(e)}", exc_info=True)
    
    def on_message(self, ws, message):
        """Handle incoming WebSocket messages"""
        try:
            self.last_message_time = time.time()
            print(f'received message: {message}')
            if isinstance(message, bytes):
                logger.info(f"Received binary message ({len(message)} bytes)")
                logger.info(f"Binary message first 64 bytes (hex): {message[:64].hex()}")
                try:
                    # Process according to TradeJini format
                    self._parse_binary_message(message)
                except Exception as e:
                    logger.error(f"Error processing binary message: {e}", exc_info=True)
                    logger.debug(f"Full binary message (hex): {message.hex()}")
            else:
                try:
                    data = json.loads(message)
                    logger.info(f"Received JSON message: {json.dumps(data, indent=2)}")
                    
                    msg_type = data.get('type', '').lower()
                    request_id = data.get('request_id')
                    
                    # Handle different message types
                    if msg_type == 'authenticate':
                        logger.info("Authentication response received")
                        self._handle_auth_response(data)
                    elif msg_type in ['l1', 'l5']:
                        logger.info(f"Received {msg_type.upper()} data")
                        if msg_type == 'l1':
                            self._process_quote(data)
                            # Update last_quote for get_quotes
                            with self.lock:
                                self.last_quote = data
                        elif msg_type == 'l5':
                            self._process_depth(data)
                    elif msg_type == 'ping':
                        logger.info("Received ping message, sending pong")
                        # Send pong in response to ping
                        pong_msg = {"type": "PONG"}
                        self.ws.send(json.dumps(pong_msg))
                    else:
                        logger.info(f"Received message with type: {msg_type}")
                        
                except json.JSONDecodeError as e:
                    logger.error(f"Error decoding JSON message: {e}")
                    logger.info(f"Raw non-JSON message: {message}")
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
            # Log the raw packet data for debugging
            logger.info(f"Processing binary packet: length={data_len}, first 32 bytes={data[:32].hex()}")
            
            # Get packet type from the 3rd byte
            pkt_type = struct.unpack("b", data[2:3])[0]
            if pkt_type not in self.PKT_TYPE:
                logger.warning(f"Unknown packet type: {pkt_type}")
                return
                
            packet_type = self.PKT_TYPE[pkt_type]
            logger.info(f"Processing packet of type: {packet_type}")
            
            # Get packet spec for this type
            pkt_spec = self.DEFAULT_PKT_INFO["PKT_SPEC"].get(pkt_type, {})
            if not pkt_spec:
                logger.warning(f"No packet spec found for type {pkt_type} ({packet_type})")
                return
                
            logger.info(f"Using packet spec with {len(pkt_spec)} fields")
            
            # Decode based on packet type
            jData = None
            
            if packet_type == "L1":
                jData = self._decode_l1_packet(pkt_spec, data_len, data)
                logger.info(f"Decoded L1 data: {json.dumps(jData, indent=2) if jData else 'None'}")
            elif packet_type == "L5":
                jData = self._decode_l2_packet(pkt_spec, data_len, data)
                logger.info(f"Decoded L5 depth data: {json.dumps(jData, indent=2) if jData else 'None'}")
            elif packet_type == "OHLC":
                jData = self._decode_ohlc_packet(pkt_spec, data_len, data)
                logger.info(f"Decoded OHLC data: {json.dumps(jData, indent=2) if jData else 'None'}")                
            elif packet_type == "auth":
                jData = self._decode_auth_packet(pkt_spec, data_len, data)
                logger.info(f"Decoded auth data: {json.dumps(jData, indent=2) if jData else 'None'}")                
            elif packet_type == "marketStatus":
                jData = self._decode_market_status(pkt_spec, data_len, data)
            elif packet_type == "EVENTS":
                jData = self._decode_events_message(pkt_spec, data_len, data)
            elif packet_type == "PING":
                jData = self._decode_ping_status(pkt_spec, data_len, data)
            elif packet_type == "greeks":
                jData = self._decode_l1_packet(pkt_spec, data_len, data)  # Same structure as L1
                
            # Process the data if valid
            if jData is not None:
                jData["msgType"] = packet_type
                logger.info(f"Successfully decoded {packet_type} packet for symbol: {jData.get('symbol', 'unknown')}")
                
                # Process the data based on type
                if packet_type == "L1":
                    # Update last_quote for get_quotes
                    with self.lock:
                        self.last_quote = jData
                    logger.info(f"Updated last_quote with L1 data for {jData.get('symbol', 'unknown')}")
                elif packet_type == "L5":
                    self._process_depth(jData)
                    logger.info(f"Processed L5 depth data for {jData.get('symbol', 'unknown')}")
                elif packet_type == "OHLC":
                    self._process_ohlc(jData)
                    logger.info(f"Processed OHLC data for {jData.get('symbol', 'unknown')}")
                elif packet_type == "auth":
                    self._handle_auth_response(jData)
                    logger.info("Processed authentication response")
            else:
                logger.warning(f"Failed to decode {packet_type} packet")
                    
        except Exception as e:
            logger.error(f"Error processing packet: {str(e)}", exc_info=True)
            logger.error(f"Packet data (hex): {data.hex()}")
            return None
            
    def _decode_l2_packet(self, pkt_spec, data_len, data):
        """Decode a level 2 (market depth) packet."""
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
        
        logger.info(f"Decoding L5 market depth packet: length={data_len}")
        
        try:
            while idx < data_len:
                pkt_key = struct.unpack("B", data[idx: idx + 1])
                idx += 1
                
                if pkt_key[0] not in pkt_spec:
                    logger.warning(f"Unknown packet key: {pkt_key[0]} in L5 packet")
                    idx += 1  # Skip to next byte
                    continue
                    
                spec = pkt_spec[pkt_key[0]]
                framed = self._frame_from_spec(spec, data, idx)
                
                logger.debug(f"L5 field: key={spec['key']}, value={framed}")
                
                if spec["key"] == "nDepth":
                    no_level = framed
                    current_list = bids
                    logger.info(f"L5 depth levels: {no_level}")
                elif spec["key"] == "exchSeg":
                    if framed in self.SEG_INFO:
                        exchange_info = self.SEG_INFO[framed]
                        precision = exchange_info["precision"]
                        divisor = exchange_info["divisor"]
                        jData[spec["key"]] = exchange_info["exchSeg"]
                        logger.info(f"L5 exchange: {exchange_info['exchSeg']}, precision={precision}")
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
                        logger.debug(f"Added {len(current_list)}th level to {'bids' if current_list == bids else 'asks'}: {level_obj}")
                        level_obj = {}
                    
                    if len(current_list) == no_level:
                        logger.debug(f"Switching from bids ({len(bids)} levels) to asks")
                        current_list = asks
                
                idx += spec["len"]
            
            if exchange_info is not None:
                self._format_values(divisor, raw_data, jData)
            
            jData["bid"] = bids
            jData["ask"] = asks
            jData["precision"] = precision
            jData["symbol"] = str(jData["token"]) + "_" + jData["exchSeg"]
            
            # Log detailed market depth information
            if bids or asks:
                symbol = jData.get("symbol", "unknown")
                logger.info(f"Decoded L5 market depth for {symbol}: {len(bids)} bid levels, {len(asks)} ask levels")
                
                # Log bid details
                if bids:
                    logger.info(f"Bids for {symbol}:")
                    for i, bid in enumerate(bids):
                        logger.info(f"  Level {i+1}: Price: {bid.get('price', 0)}, Quantity: {bid.get('qty', 0)}, Orders: {bid.get('no', 0)}")
                        
                # Log ask details
                if asks:
                    logger.info(f"Asks for {symbol}:")
                    for i, ask in enumerate(asks):
                        logger.info(f"  Level {i+1}: Price: {ask.get('price', 0)}, Quantity: {ask.get('qty', 0)}, Orders: {ask.get('no', 0)}")
                        
                # Calculate total quantities
                total_buy_qty = sum(bid.get('qty', 0) for bid in bids)
                total_sell_qty = sum(ask.get('qty', 0) for ask in asks)
                logger.info(f"Total Buy Quantity: {total_buy_qty}, Total Sell Quantity: {total_sell_qty}")
            else:
                logger.warning("Decoded L5 packet but no bids or asks found")
            
            return jData
        except Exception as e:
            logger.error(f"Error decoding L5 packet: {str(e)}", exc_info=True)
            logger.error(f"L5 packet data (hex): {data.hex() if isinstance(data, bytes) else 'not binary'}")
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
            logger.debug(f"Processing L5 market depth data: {json.dumps(data, indent=2) if isinstance(data, dict) else data}")
            
            # Extract symbol/token information
            token = data.get('token', '')
            exchange = data.get('exchSeg', '')
            symbol = data.get('symbol', f"{token}_{exchange}")
            
            # Process binary depth data directly from TradeJini
            if 'bid' in data and 'ask' in data:
                logger.info(f"Received binary L5 depth data for {symbol}")
                bids = data.get('bid', [])
                asks = data.get('ask', [])
                
                # Log depth levels
                if bids:
                    logger.info(f"Bids for {symbol}:")
                    for i, bid in enumerate(bids):
                        logger.info(f"  Level {i+1}: Price: {bid.get('price', 0)}, Quantity: {bid.get('qty', 0)}, Orders: {bid.get('no', 0)}")
                        
                if asks:
                    logger.info(f"Asks for {symbol}:")
                    for i, ask in enumerate(asks):
                        logger.info(f"  Level {i+1}: Price: {ask.get('price', 0)}, Quantity: {ask.get('qty', 0)}, Orders: {ask.get('no', 0)}")
            
                # Calculate total buy/sell quantities
                total_buy_qty = sum(bid.get('qty', 0) for bid in bids)
                total_sell_qty = sum(ask.get('qty', 0) for ask in asks)
                
                logger.info(f"Total Buy Quantity: {total_buy_qty}, Total Sell Quantity: {total_sell_qty}")
                
                # Store depth data
                with self.lock:
                    self.last_depth = {
                        'symbol': symbol,
                        'token': token,
                        'exchange': exchange,
                        'bids': bids,
                        'asks': asks,
                        'totalbuyqty': total_buy_qty,
                        'totalsellqty': total_sell_qty,
                        'precision': data.get('precision', 2),
                        'timestamp': datetime.now().isoformat()
                    }
                    
                logger.info(f"Updated market depth for {symbol}")
                
            # Process older JSON format depth data
            elif 'bidPrices' in data and 'askPrices' in data:
                logger.info(f"Received JSON L5 depth data")
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
                
                # Calculate total buy/sell quantities
                total_buy_qty = sum(bid['quantity'] for bid in bids)
                total_sell_qty = sum(ask['quantity'] for ask in asks)
                
                logger.info(f"Total Buy Quantity: {total_buy_qty}, Total Sell Quantity: {total_sell_qty}")
                
                # Store depth data
                with self.lock:
                    self.last_depth = {
                        'bids': bids,
                        'asks': asks,
                        'totalbuyqty': total_buy_qty,
                        'totalsellqty': total_sell_qty,
                        'ltp': float(data.get('ltp', 0)),
                        'volume': int(data.get('vol', 0)),
                        'timestamp': datetime.now().isoformat()
                    }
            else:
                logger.warning(f"Received market depth data in unknown format: {data.keys() if isinstance(data, dict) else type(data)}")
                
        except Exception as e:
            logger.error(f"Error processing depth: {str(e)}", exc_info=True)

    def _format_token(self, token, exchange):
        """Format token according to TradeJini's expected format"""
        try:
            # For NSE, BSE, etc. - use token as is
            if exchange in ['NSE', 'BSE']:
                return f"{token}_{exchange}"
            # For F&O, CDS, etc. - use token as is
            return f"{token}_{exchange}"
        except Exception as e:
            logger.error(f"Error formatting token {token} for {exchange}: {str(e)}")
            return f"{token}_{exchange}"

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
            token_list = []
            for token in tokens:
                if isinstance(token, dict) and 'token' in token and 'exchange' in token:
                    token_str = str(token['token']).strip()
                    token_list.append({"t": token_str})
                    logger.info(f"Subscribing to token: {token_str}")
                elif isinstance(token, str):
                    token_list.append({"t": token.strip()})
                    logger.info(f"Subscribing to token: {token.strip()}")
            
            if not token_list:
                logger.error("No valid tokens provided for subscription")
                return False
                
            # Create subscription message exactly as in TradeJini sample code
            req = {
                "type": "L1",
                "action": "sub",
                "tokens": token_list
            }
            
            logger.debug(f"Sending subscription request: {json.dumps(req, indent=2)}")
            
            # Send subscription message
            if not self._send_json(req):
                logger.error("Failed to send subscription request")
                return False
            
            # No need to wait for explicit confirmation - binary packets will start flowing
            logger.info("Subscription request sent successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in subscribe_quotes: {str(e)}", exc_info=True)
            return False

    def subscribe_ohlc(self, tokens, interval):
        """
        Subscribe to OHLC data for given tokens and interval
        
        Args:
            tokens: List of token strings or token objects
            interval: Chart interval (1m, 5m, 15m, 30m, 60m, 1d)
        """
        if not self.connected:
            logger.error("WebSocket not connected")
            return False
            
        try:
            # Format tokens according to TradeJini's format
            token_list = []
            for token in tokens:
                if isinstance(token, dict) and 'token' in token:
                    token_str = str(token['token']).strip()
                    token_list.append({"t": token_str})
                    logger.info(f"Adding OHLC subscription for token: {token_str}")
                elif isinstance(token, str):
                    token_list.append({"t": token.strip()})
                    logger.info(f"Adding OHLC subscription for token: {token.strip()}")
            
            if not token_list:
                logger.error("No valid tokens provided for OHLC subscription")
                return False
                
            # Create subscription message following TradeJini sample code format
            req = {
                "type": "OHLC",
                "action": "sub",
                "tokens": token_list,
                "chartInterval": interval
            }
            
            logger.info(f"Subscribing to OHLC data with interval {interval}")
            logger.debug(f"Sending OHLC subscription request: {json.dumps(req, indent=2)}")
            
            # Send subscription message
            if not self._send_json(req):
                logger.error("Failed to send OHLC subscription request")
                return False
            
            # No need to wait for explicit confirmation - binary packets will start flowing
            logger.info("OHLC subscription request sent successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in subscribe_ohlc: {str(e)}", exc_info=True)
            return False

    def unsubscribe_ohlc(self, interval):
        """
        Unsubscribe from OHLC data for a specific interval
        
        Args:
            interval: Chart interval to unsubscribe from (1m, 5m, 15m, 30m, 60m, 1d)
        """
        try:
            # Create unsubscription message following TradeJini sample code format
            req = {
                "type": "OHLC",
                "action": "unsub",
                "chartInterval": interval
            }
            
            logger.info(f"Unsubscribing from OHLC data with interval {interval}")
            logger.debug(f"Sending OHLC unsubscription request: {json.dumps(req, indent=2)}")
            
            # Send unsubscribe message
            if not self._send_json(req):
                logger.error("Failed to send OHLC unsubscription request")
                return False
            
            # No need to wait for explicit confirmation
            logger.info("OHLC unsubscription request sent successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in unsubscribe_ohlc: {str(e)}", exc_info=True)
            return False

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
        """Subscribe to market depth using TradeJini's L5 format"""
        try:
            # Create subscription message following TradeJini sample code format
            token_list = [{"t": str(token)}]  # No need for exch parameter
            
            # Create subscription message exactly as in TradeJini sample code
            req = {
                "type": "L5",  # L5 for market depth
                "action": "sub",
                "tokens": token_list
            }
            
            logger.info(f"Subscribing to market depth for {symbol} on {exchange} (token: {token})")
            logger.debug(f"Sending L5 subscription request: {json.dumps(req, indent=2)}")
            
            # Send subscription message
            if not self._send_json(req):
                logger.error("Failed to send L5 subscription request")
                return False
            
            # No need to wait for explicit confirmation - binary packets will start flowing
            logger.info("L5 subscription request sent successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in subscribe_depth: {str(e)}", exc_info=True)
            return False



    def request_historical_data(self, token, exchange, interval, from_date, to_date):
        """
        Request historical OHLC data from TradeJini's interval chart API
        
        Args:
            token: Trading symbol token or symbol name
            exchange: Exchange (NSE, BSE, NFO, etc.)
            interval: Time interval in minutes (e.g., '1' for 1m, '5' for 5m, etc.)
            from_date: Start timestamp in milliseconds
            to_date: End timestamp in milliseconds
            
        Returns:
            tuple: (success: bool, data: pd.DataFrame or error message)
        """
        try:
            import requests
            from datetime import datetime, timezone
            import pytz
            
            # Convert timestamps from milliseconds to seconds for the API
            from_ts = int(from_date) // 1000 if isinstance(from_date, (int, float)) else int(pd.Timestamp(from_date).timestamp())
            to_ts = int(to_date) // 1000 if isinstance(to_date, (int, float)) else int(pd.Timestamp(to_date).timestamp())
            
            # For TradeJini, we need to use the symbol ID format
            # Format: EQT_<SYMBOL>_EQ_<EXCHANGE>
            symbol_id = f"EQT_{token.upper()}_EQ_{exchange.upper()}"
            
            # API endpoint
            url = "https://api.tradejini.com/v2/api/mkt-data/chart/interval-data"
            
            # Headers with authentication
            headers = {
                'Accept': 'application/json',
                'Authorization': f'Bearer {self.auth_token}'
            }
            
            # Query parameters
            params = {
                'from': from_ts,
                'to': to_ts,
                'interval': str(interval).replace('m', '').replace('d', ''),  # Convert '1m' to '1', '1d' to '1'
                'id': symbol_id
            }
            
            logger.debug(f"Making GET request to {url} with params: {params}")
            
            # Make the API request using the shared httpx client
            client = get_httpx_client()
            response = client.get(
                url,
                headers=headers,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('s') != 'ok' or 'd' not in data or 'bars' not in data['d']:
                error_msg = data.get('message', 'Invalid response format from TradeJini')
                logger.error(f"Error in historical data: {error_msg}")
                return False, error_msg
            
            # Process the bars data
            bars = data['d']['bars']
            if not bars or not isinstance(bars, list) or not bars[0]:
                logger.info(f"No data available for {symbol_id} on {exchange} for the given period")
                return True, pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Extract the first (and only) list of bars
            bar_data = bars[0]
            
            # Convert to DataFrame
            df = pd.DataFrame(bar_data)
            
            # Convert timestamp from seconds to datetime in IST
            df['timestamp'] = pd.to_datetime(df['time'], unit='s').dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
            
            # Ensure columns are in the correct order and named properly
            df = df.rename(columns={
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'volume': 'volume',
                'minuteOi': 'open_interest'  # Add open interest if available
            })
            
            # Select and reorder columns
            columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            if 'open_interest' in df.columns:
                columns.append('open_interest')
                
            df = df[columns]
            
            # Ensure numeric columns are float
            for col in ['open', 'high', 'low', 'close', 'volume', 'open_interest']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Sort by timestamp
            df = df.sort_values('timestamp')
            
            # Set timestamp as index
            df = df.set_index('timestamp')
            
            logger.info(f"Successfully retrieved {len(df)} rows of historical data for {symbol_id}")
            return True, df
            
        except Exception as e:
            error_msg = f"Error in request_historical_data: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
            
    def request_historical_data(self, symbol, exchange, interval, from_date, to_date):
        """
        Request historical OHLC data from TradeJini's interval chart API
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (NSE, BSE, NFO, etc.)
            interval: Time interval in minutes (e.g., '1' for 1m, '5' for 5m, etc.)
            from_date: Start timestamp in seconds or date string (YYYY-MM-DD)
            to_date: End timestamp in seconds or date string (YYYY-MM-DD)
            
        Returns:
            tuple: (success, data_or_error) where data is a list of OHLCV records
        """
        try:
            # Get broker symbol using get_br_symbol
            br_symbol = get_br_symbol(symbol, exchange)
            if not br_symbol:
                logger.error(f"Broker symbol not found for {symbol} on {exchange}")
                return False, f"Broker symbol not found for {symbol} on {exchange}"
                
            logger.info(f"Fetching historical data for {exchange}:{symbol} (broker symbol: {br_symbol})")
            import requests
            from datetime import datetime, timedelta
            import pandas as pd
            import time
            
            # Convert date strings to datetime objects if needed
            if isinstance(from_date, str):
                try:
                    from_date = datetime.strptime(from_date, "%Y-%m-%d")
                except ValueError:
                    logger.error(f"Invalid from_date format: {from_date}. Expected YYYY-MM-DD")
                    return False, f"Invalid from_date format: {from_date}"
            else:
                # Convert from milliseconds to seconds if needed
                from_date = datetime.fromtimestamp(from_date / 1000 if from_date > 1e12 else from_date)
            
            if isinstance(to_date, str):
                try:
                    to_date = datetime.strptime(to_date, "%Y-%m-%d")
                except ValueError:
                    logger.error(f"Invalid to_date format: {to_date}. Expected YYYY-MM-DD")
                    return False, f"Invalid to_date format: {to_date}"
            else:
                # Convert from milliseconds to seconds if needed
                to_date = datetime.fromtimestamp(to_date / 1000 if to_date > 1e12 else to_date)
            
            # Initialize list to store all candles
            all_candles = []
            
            # Process data in 30-day chunks to avoid hitting API limits
            current_start = from_date
            chunk_days = 30
            
            while current_start <= to_date:
                # Calculate chunk end date (chunk_days or remaining period)
                current_end = min(current_start + timedelta(days=chunk_days-1), to_date)
                
                # Format dates for API call (in seconds since epoch)
                from_ts = int(current_start.timestamp())
                to_ts = int(current_end.timestamp()) + 86399  # Add 23:59:59 to include full day
                
                logger.info(f"Fetching data for {br_symbol} from {current_start.date()} to {current_end.date()}")
                
                # Make the API request for this chunk
                success, result = self._fetch_historical_chunk(br_symbol, exchange, interval, from_ts, to_ts)
                if not success:
                    return False, result
                    
                # Extend the all_candles list with the new candles
                all_candles.extend(result)
                
                # Move to next chunk
                current_start = current_end + timedelta(days=1)
            
            if not all_candles:
                return True, []
                
            # Convert to DataFrame and sort by timestamp
            df = pd.DataFrame(all_candles)
            df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)
            
            return True, df.to_dict('records')
            
        except requests.exceptions.RequestException as e:
            error_msg = f"API request failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
        except Exception as e:
            error_msg = f"Error in request_historical_data: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    def _fetch_historical_chunk(self, symbol: str, exchange: str, interval: str, from_ts: int, to_ts: int) -> Tuple[bool, Union[List[Dict[str, Any]], str]]:
        """
        Fetch a chunk of historical data from TradeJini API using the shared HTTPX client
        
        Args:
            symbol: Broker symbol
            exchange: Exchange (NSE, BSE, NFO, etc.)
            interval: Time interval in minutes (e.g., '1' for 1m, '5' for 5m, etc.)
            from_ts: Start timestamp in seconds
            to_ts: End timestamp in seconds
            
        Returns:
            tuple: (success, data_or_error) where data is a list of OHLCV records or error message
        """
        try:
            # API endpoint
            url = "https://api.tradejini.com/v2/api/mkt-data/chart/interval-data"
            
            # Get API key from environment
            api_key = os.getenv('BROKER_API_SECRET')
            if not api_key:
                error_msg = "BROKER_API_SECRET environment variable not set"
                logger.error(error_msg)
                return False, error_msg
                
            # Check if auth_token is available
            if not self.auth_token:
                error_msg = "Authentication token is not available. Please authenticate first."
                logger.error(error_msg)
                return False, error_msg
                
            # Format auth header as in funds.py
            auth_header = f"{api_key}:{self.auth_token}"
            headers = {
                'X-Kite-Version': '3',
                'Authorization': f'Bearer {auth_header}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            # Prepare request payload
            payload = {
                'token': symbol,
                'exchange': exchange.upper(),
                'interval': interval,
                'from': from_ts,
                'to': to_ts
            }
            
            logger.debug(f"Making historical data request to {url} with payload: {payload}")
            
            # Get the shared httpx client
            client = get_httpx_client()
            
            # Make the request using the shared client
            response = client.post(
                url,
                json=payload,
                headers=headers,
                timeout=30.0
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('status') != 'success':
                error_msg = f"API Error: {data.get('message', 'Unknown error')}"
                logger.error(error_msg)
                return False, error_msg
                
            # Process the response data
            ohlc_data = []
            for bar in data.get('data', []):
                if not isinstance(bar, list) or len(bar) == 0:
                    continue
                    
                bar_data = bar[0]  # Get the first (and only) item in the bar array
                ohlc_data.append({
                    'timestamp': bar_data.get('time', 0) * 1000,  # Convert to milliseconds
                    'open': bar_data.get('open', 0),
                    'high': bar_data.get('high', 0),
                    'low': bar_data.get('low', 0),
                    'close': bar_data.get('close', 0),
                    'volume': bar_data.get('volume', 0),
                    'oi': bar_data.get('minuteOi', 0)  # Open Interest for derivatives
                })
            
            logger.info(f"Received {len(ohlc_data)} bars of historical data for {symbol}")
            return True, ohlc_data
            
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error in _fetch_historical_chunk: {str(e)} - {e.response.text if hasattr(e, 'response') else ''}"
            logger.error(error_msg)
            return False, error_msg
        except httpx.RequestError as e:
            error_msg = f"Network error in _fetch_historical_chunk: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Unexpected error in _fetch_historical_chunk: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

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
        # Set auth_token in WebSocket instance
        self.ws.auth_token = auth_token
        
        # Initialize pending requests dictionary
        self.pending_requests = {}
        
        # Map common timeframe format to Tradejini resolutions
        self.timeframe_map = {
            '1m': '1m',    # 1 minute
            '5m': '5m',    # 5 minutes
            '15m': '15m',  # 15 minutes
            '30m': '30m',  # 30 minutes
            '1h': '60m',   # 1 hour
            'D': '1d'      # Daily
        }

    def _format_quote(self, quote_data: dict, symbol: str, exchange: str) -> dict:
        """
        Format quote data from Tradejini to standard format
        
        Args:
            quote_data: Raw quote data from Tradejini
            symbol: Trading symbol
            exchange: Exchange
            
        Returns:
            dict: Formatted quote data
        """
        try:
            # Log the raw quote data for debugging
            logger.debug(f"Raw quote data for {symbol}: {json.dumps(quote_data, indent=2, default=str)}")
            
            # Extract values with defaults to handle missing keys
            ltp = float(quote_data.get('ltp', 0))
            open_price = float(quote_data.get('open', 0))
            high = float(quote_data.get('high', 0))
            low = float(quote_data.get('low', 0))
            close = float(quote_data.get('close', 0))
            volume = int(quote_data.get('vol', 0) or 0)
            change = float(quote_data.get('chng', 0))
            change_percent = float(quote_data.get('chngPer', 0))
            last_trade_time = quote_data.get('ltt', '')
            
            # Get best bid/ask from the quote data
            best_bid = float(quote_data.get('bidPrice', 0))
            best_bid_qty = int(quote_data.get('bidQty', 0) or 0)
            best_ask = float(quote_data.get('askPrice', 0))
            best_ask_qty = int(quote_data.get('askQty', 0) or 0)
            
            # If bid/ask not in the main quote, check depth if available
            if (best_bid == 0 or best_ask == 0) and 'depth' in quote_data and quote_data['depth']:
                depth = quote_data['depth']
                if depth.get('bids') and len(depth['bids']) > 0:
                    best_bid = float(depth['bids'][0].get('price', best_bid))
                    best_bid_qty = int(depth['bids'][0].get('quantity', best_bid_qty))
                if depth.get('asks') and len(depth['asks']) > 0:
                    best_ask = float(depth['asks'][0].get('price', best_ask))
                    best_ask_qty = int(depth['asks'][0].get('quantity', best_ask_qty))
            
            # Format the quote with consistent field names
            formatted_quote = {
                'symbol': symbol,
                'exchange': exchange,
                'token': str(quote_data.get('token', '')),  # Include the token for reference
                'last_price': ltp,
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume,
                'change': change,
                'change_percent': change_percent,
                'last_trade_time': last_trade_time,
                'best_bid': best_bid,
                'best_bid_qty': best_bid_qty,
                'best_ask': best_ask,
                'best_ask_qty': best_ask_qty,
                'timestamp': datetime.now().isoformat(),
                'raw_data': quote_data  # Include raw data for debugging
            }
            
            # Log the formatted quote for debugging
            logger.debug(f"Formatted quote for {symbol}: {json.dumps(formatted_quote, indent=2, default=str)}")
            
            return formatted_quote
            
        except Exception as e:
            logger.error(f"Error formatting quote data: {str(e)}\nRaw data: {json.dumps(quote_data, indent=2, default=str)}", exc_info=True)
            # Return minimal valid quote data with error information
            return {
                'symbol': symbol,
                'exchange': exchange,
                'token': str(quote_data.get('token', '')),
                'last_price': 0,
                'open': 0,
                'high': 0,
                'low': 0,
                'close': 0,
                'volume': 0,
                'change': 0,
                'change_percent': 0,
                'last_trade_time': '',
                'best_bid': 0,
                'best_bid_qty': 0,
                'best_ask': 0,
                'best_ask_qty': 0,
                'timestamp': datetime.now().isoformat(),
                'error': str(e),
                'raw_data': quote_data
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
            
            tradejini_exchange = exchange_map.get(exchange.upper())
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

            # Format the token according to TradeJini's requirements
            logger.info(f"Subscribing to {symbol} on {tradejini_exchange} (token: {token})")
            
            # Format subscription request according to TradeJini's format
            subscription = {
                "type": "L1",
                "action": "sub",
                "tokens": [{"t": str(token)}]
            }
            
            # Log the subscription request
            logger.info(f"Sending subscription request: {json.dumps(subscription, indent=2)}")
            
            # Send the subscription request
            if not self.ws._send_json(subscription):
                error_msg = "Failed to send subscription request"
                logger.error(error_msg)
                raise ConnectionError(error_msg)
            
            # No need to wait for explicit confirmation - binary packets will start flowing
            logger.info("Quote subscription request sent successfully")
            
            # Give a moment for any existing quote data to be processed
            time.sleep(0.5)
            
            # Check for existing quote in cache
            with self.ws.lock:
                if self.ws.last_quote is not None:
                    # Verify this is the quote we're looking for
                    quote = self.ws.last_quote
                    quote_token = str(quote.get('token', ''))
                    quote_exchange = str(quote.get('exchSeg', '')).upper()
                    
                    if quote_token == str(token) and quote_exchange == tradejini_exchange.upper():
                        logger.info(f"Found existing quote for {symbol} on {tradejini_exchange}")
                        return self._format_quote(quote, symbol, exchange)
            
            # If not immediately available, wait for a few seconds
            logger.info(f"Waiting up to 5 seconds for quote data for {symbol}...")
            
            # Wait for the first quote with a short timeout
            max_retries = 10  # More retries but shorter wait time
            retry_count = 0
            last_error = None
            
            while retry_count < max_retries:
                try:
                    with self.ws.lock:
                        if self.ws.last_quote is not None:
                            # Verify this is the quote we're looking for
                            quote = self.ws.last_quote
                            quote_token = str(quote.get('token', ''))
                            quote_exchange = str(quote.get('exchSeg', '')).upper()
                            
                            if quote_token == str(token) and quote_exchange == tradejini_exchange.upper():
                                logger.info(f"Received quote for {symbol} on {tradejini_exchange}")
                                return self._format_quote(quote, symbol, exchange)
                    
                    # If we get here, either no quote or wrong symbol
                    logger.debug(f"Waiting for quote data... (retry {retry_count + 1}/{max_retries})")
                    time.sleep(0.5)  # Wait for half a second before next attempt
                    retry_count += 1
                    
                except Exception as e:
                    last_error = str(e)
                    logger.error(f"Error while waiting for quote: {last_error}", exc_info=True)
                    time.sleep(0.5)  # Wait before retry on error
                    retry_count += 1

            # If we get here, retries failed but we'll return a default quote
            error_msg = f"Did not receive quote data for {symbol} on {tradejini_exchange} after {max_retries} attempts"
            if last_error:
                error_msg += f" (Last error: {last_error})"
            logger.warning(error_msg)
            
            # Return a default quote rather than raising an exception
            logger.info(f"Returning default quote for {symbol}")
            return {
                'symbol': symbol,
                'token': token,
                'exchange': exchange,
                'ltp': 0.0,
                'change': 0.0,
                'change_percent': 0.0,
                'open': 0.0,
                'high': 0.0,
                'low': 0.0,
                'close': 0.0,
                'volume': 0,
                'bid_price': 0.0,
                'ask_price': 0.0,
                'last_trade_time': None,
                'timestamp': datetime.now().isoformat()
            }
            
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

    def _get_historical_data(self, symbol: str, exchange: str, interval: str, from_ts: int, to_ts: int) -> Tuple[bool, Union[List[Dict[str, Any]], str]]:
        """
        Fetch historical OHLC data from TradeJini REST API
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (NSE, BSE, NFO, etc.)
            interval: Time interval (e.g., '1', '5', '15', '30', '60', '1D')
            from_ts: Start timestamp in seconds
            to_ts: End timestamp in seconds
            
        Returns:
            tuple: (success, data_or_error) where data is a list of OHLCV records or error message
        """
        try:
            # API endpoint
            base_url = "https://api.tradejini.com/v2"
            endpoint = "/api/mkt-data/chart/interval-data"
            url = f"{base_url}{endpoint}"
            
            # Get API key from environment
            api_key = os.getenv('BROKER_API_SECRET')
            if not api_key:
                error_msg = "BROKER_API_SECRET environment variable not set"
                logger.error(error_msg)
                return False, error_msg
                
            # Check if auth_token is available
            if not self.auth_token:
                error_msg = "Authentication token is not available. Please authenticate first."
                logger.error(error_msg)
                return False, error_msg
            
            # Get broker symbol from database
            symbol_id = get_br_symbol(symbol, exchange)
            if not symbol_id:
                error_msg = f"Broker symbol not found for {symbol} on {exchange}"
                logger.error(error_msg)
                return False, error_msg
            
            # Prepare query parameters
            params = {
                'id': symbol_id,
                'interval': interval,
                'from': from_ts,
                'to': to_ts
            }
            
            # Format auth header as in funds.py
            auth_header = f"{api_key}:{self.auth_token}"
            headers = {
                'Authorization': f'Bearer {auth_header}',
                'Accept': 'application/json'
            }
            
            logger.debug(f"Making historical data request to {url} with params: {params}")
            
            # Get the shared httpx client
            client = get_httpx_client()
            
            # Make the GET request using the shared client
            logger.debug(f"Sending GET request to {url} with params: {params}")
            logger.debug(f"Request headers: {headers}")
            
            response = client.get(
                url,
                params=params,
                headers=headers,
                timeout=30.0
            )
            print(f'response: {response}')    
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response headers: {dict(response.headers)}")
            
            # Log response content for debugging
            response_text = response.text
            logger.debug(f"Raw response: {response_text}")
            
            response.raise_for_status()
            
            try:
                data = response.json()
                logger.debug(f"Parsed JSON response: {json.dumps(data, indent=2)}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {e}")
                logger.error(f"Response content: {response_text}")
                return False, f"Invalid JSON response: {str(e)}"
            
            # Check if the response is successful
            if data.get('s') != 'ok':
                error_msg = f"API Error: Status='{data.get('s')}', Message='{data.get('message', 'No error message')}', Data: {json.dumps(data, indent=2)}"
                logger.error(error_msg)
                return False, error_msg
            
            # Process the response data
            ohlc_data = []
            bars = data.get('d', {}).get('bars', [])
            logger.debug(f"Processing {len(bars)} bars from response")
            
            for bar in bars:
                if not isinstance(bar, list) or len(bar) < 5:  # At least need [timestamp, open, high, low, close]
                    logger.warning(f"Skipping invalid bar format: {bar}")
                    continue
                    
                try:
                    # Parse the bar data
                    # The timestamp is already in milliseconds in the response
                    timestamp = int(bar[0])
                    open_price = float(bar[1])
                    high = float(bar[2])
                    low = float(bar[3])
                    close = float(bar[4])
                    volume = int(bar[5]) if len(bar) > 5 else 0
                    
                    ohlc_data.append({
                        'timestamp': timestamp,  # Already in milliseconds
                        'open': open_price,
                        'high': high,
                        'low': low,
                        'close': close,
                        'volume': volume
                    })
                    
                    logger.debug(f"Processed bar: {pd.Timestamp(timestamp, unit='ms')} - O:{open_price}, H:{high}, L:{low}, C:{close}, V:{volume}")
                except (IndexError, ValueError, TypeError) as e:
                    logger.warning(f"Error parsing bar data: {bar}, error: {str(e)}")
                    continue
            
            logger.info(f"Received {len(ohlc_data)} bars of historical data for {symbol_id}")
            return True, ohlc_data
            
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error in _get_historical_data: {str(e)} - {e.response.text if hasattr(e, 'response') else ''}"
            logger.error(error_msg)
            return False, error_msg
        except httpx.RequestError as e:
            error_msg = f"Network error in _get_historical_data: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Unexpected error in _get_historical_data: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical OHLC data for given symbol using REST API

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
            def parse_timestamp(ts, is_start=True):
                try:
                    if isinstance(ts, str):
                        # Parse string date and localize to IST
                        dt = pd.Timestamp(ts, tz='Asia/Kolkata')
                    else:
                        # Convert Unix timestamp (in ms) to IST
                        dt = pd.Timestamp(ts, unit='ms', tz='Asia/Kolkata')
                    
                    # Set time to 09:15:00 for start date, 23:59:59 for end date
                    if is_start:
                        dt = dt.replace(hour=9, minute=15, second=0, microsecond=0)
                    else:
                        dt = dt.replace(hour=23, minute=59, second=59, microsecond=0)
                    
                    # Convert to Unix timestamp (seconds since epoch)
                    return int(dt.timestamp())
                    
                except Exception as e:
                    logger.error(f"Error parsing timestamp {ts}: {str(e)}", exc_info=True)
                    raise
            
            # Parse timestamps with proper market hours
            start_ts = parse_timestamp(start_date, is_start=True)
            end_ts = parse_timestamp(end_date, is_start=False)
            
            logger.debug(f"Converted timestamps - Start: {pd.Timestamp(start_ts, unit='s')} ({start_ts}), "
                        f"End: {pd.Timestamp(end_ts, unit='s')} ({end_ts})")

            # Get token for the symbol
            token = get_token(symbol, exchange)
            if not token:
                logger.error(f"Token not found for {symbol} on {exchange}")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

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

            # Get symbol in TradeJini format
            token_str = get_symbol(token, exchange)
            
            # Map interval to Tradejini format
            interval_map = {
                '1m': '1',
                '5m': '5',
                '15m': '15',
                '30m': '30',
                '60m': '60',
                '1h': '60',
                '1d': '1D',
                'D': '1D'
            }
            tj_interval = interval_map.get(interval, interval)

            # Fetch historical data using REST API
            success, result = self._get_historical_data(
                symbol=token_str,
                exchange=exchange,
                interval=tj_interval,
                from_ts=start_ts,
                to_ts=end_ts
            )
            
            if not success:
                logger.error(f"Failed to fetch historical data: {result}")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Convert to pandas DataFrame
            if not result:
                logger.warning(f"No data returned for {symbol} on {exchange}")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
            # Convert timestamps to datetime in IST and create DataFrame
            df = pd.DataFrame(result)
            
            # If timestamp is in milliseconds, convert to seconds first
            if 'timestamp' in df.columns and df['timestamp'].max() > 1e12:
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True).dt.tz_convert('Asia/Kolkata')
            else:
                # If no timestamp in response, generate timestamps based on interval
                start_dt = pd.Timestamp(start_ts, unit='s', tz='Asia/Kolkata')
                freq = interval.replace('m', 'T').replace('h', 'H').replace('d', 'D')
                df['datetime'] = pd.date_range(start=start_dt, periods=len(df), freq=freq)
            
            # Set datetime as index and sort
            df.set_index('datetime', inplace=True)
            df.sort_index(inplace=True)
            
            # Convert timestamp to seconds since epoch for backward compatibility
            if 'timestamp' in df.columns:
                df['timestamp'] = df.index.astype('int64') // 10**9
            
            # Ensure all required columns exist
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col not in df.columns:
                    df[col] = 0.0
                    
            # Reset index to include datetime as a column
            df = df.reset_index()
            
            # Convert to OpenAlgo format with timestamp in seconds
            result = []
            for _, row in df.iterrows():
                result.append({
                    'timestamp': int(row['datetime'].timestamp()),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': int(row.get('volume', 0))
                })
            
            return pd.DataFrame(result)
            
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
        Get the latest OHLC data for a symbol using REST API
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Time interval ('1m', '5m', '15m', '30m', '60m', '1d')
            
        Returns:
            dict: Latest OHLC data or empty dict if not available
        """
        try:
            # Get token for the symbol
            token = get_token(symbol, exchange)
            if not token:
                logger.error(f"Token not found for {symbol} on {exchange}")
                return {}
                
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
            
            # Format token for TradeJini API (assuming equity for now, adjust for other types if needed)
            token_str = f"EQT_{token}_EQ_{exchange}"
            
            # Map interval to Tradejini format (remove 'm' or 'h' or 'd' suffix)
            interval_map = {
                '1m': '1',
                '5m': '5',
                '15m': '15',
                '30m': '30',
                '60m': '60',
                '1h': '60',
                '1d': '1D',
                'D': '1D'
            }
            tj_interval = interval_map.get(interval, interval.replace('m', '').replace('h', '').replace('d', ''))
            
            # Get current timestamp and 1 minute before for the latest candle
            to_ts = int(time.time())
            from_ts = to_ts - 60  # 1 minute before
            
            # Get the latest candle using REST API
            success, result = self.ws.request_historical_data(
                token=token_str,
                exchange=exchange,
                interval=tj_interval,
                from_date=from_ts,
                to_date=to_ts
            )
            
            if not success or not isinstance(result, list) or not result:
                logger.error(f"Failed to fetch OHLC data for {symbol} ({exchange})")
                return {}
                
            # Get the latest candle (last in the list)
            latest_candle = result[-1]
            
            return {
                'open': latest_candle.get('open', 0),
                'high': latest_candle.get('high', 0),
                'low': latest_candle.get('low', 0),
                'close': latest_candle.get('close', 0),
                'volume': latest_candle.get('volume', 0),
                'timestamp': latest_candle.get('timestamp', 0)
            }
            
        except Exception as e:
            logger.error(f"Error in get_ohlc: {str(e)}", exc_info=True)
            return {}
