"""
Dhan websocket adapter implementation for OpenAlgo websocket proxy
"""
import os
import json
import time
import struct  # For binary data processing
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple, Union

from broker.dhan.streaming.dhan_websocket import DhanWebSocket
from database.auth_db import get_auth_token
from database.token_db import get_token

import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .dhan_mapping import DhanExchangeMapper, DhanCapabilityRegistry

# Try to import symbol token lookup function
try:
    from ...lookup import get_symbol_from_token
except ImportError:
    # Define a fallback function for get_symbol_from_token if it can't be imported
    def get_symbol_from_token(token: str, exchange: str) -> Optional[str]:
        logging.getLogger(__name__).warning(f"get_symbol_from_token not available, can't lookup token {token} on {exchange}")
        return None

class DhanWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Dhan-specific implementation of the WebSocket adapter"""
    
    def __init__(self):
        """Initialize the Dhan WebSocket adapter"""
        super().__init__()
        self.ws_client = None
        self.broker_name = "dhan"
        self.user_id = None
        self.running = False
        self.lock = threading.RLock()
        
        # Connection and reconnection settings
        self.max_retries = 10  # Maximum number of connection attempts
        self.connect_timeout = 10  # Connection timeout in seconds
        self.reconnect_delay = 1  # Initial reconnect delay in seconds
        self.max_reconnect_delay = 60  # Maximum reconnect delay in seconds
        self.max_reconnect_attempts = 10  # Maximum number of reconnect attempts
        self.reconnect_attempts = 0
        
        # Subscription tracking
        self.mode_subscriptions = {}  # Keep track of subscriptions by mode
    
    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with Dhan WebSocket API
        
        Args:
            broker_name: Name of the broker (always 'dhan' in this case)
            user_id: Client ID/user ID
            auth_data: If provided, use these credentials instead of fetching from DB
        
        Raises:
            ValueError: If required authentication tokens are not found
        """
        self.user_id = user_id
        self.broker_name = broker_name
        
        # Get access token and client ID from environment variables or auth_data
        if not auth_data:
            self.logger.info("Auth data not provided, fetching from environment variables")
            access_token = os.getenv("BROKER_API_SECRET")
            client_id = os.getenv("BROKER_API_KEY")
            
            if not access_token:
                self.logger.error("Missing BROKER_API_SECRET environment variable for Dhan access token")
                raise ValueError("Missing access token for Dhan")
                
            if not client_id:
                self.logger.error("Missing BROKER_API_KEY environment variable for Dhan client ID")
                raise ValueError("Missing client ID for Dhan")
                
            self.logger.debug("Successfully retrieved access token and client ID from environment variables")
        else:
            self.logger.info("Using provided auth data for authentication")
            access_token = auth_data.get("access_token")
            client_id = auth_data.get("client_id")
            
            if not access_token:
                self.logger.error("Missing access_token in auth_data")
                raise ValueError("Missing access token in auth_data")
                
            if not client_id:
                self.logger.error("Missing client_id in auth_data")
                raise ValueError("Missing client ID in auth_data")
                
            self.logger.debug("Successfully retrieved access token and client ID from auth data")
        
        # Create DhanWebSocket instance
        self.logger.info(f"Creating DhanWebSocket client with client ID {client_id}")
        self.ws_client = DhanWebSocket(
            client_id=client_id,
            access_token=access_token,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            reconnect_attempts=self.max_reconnect_attempts,
            reconnect_delay=self.reconnect_delay
        )
        
        self.running = True
        
    def connect(self) -> Dict[str, Any]:
        """Connect to Dhan WebSocket with retry logic"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized, cannot connect")
            return {'success': False, 'error': 'WebSocket client not initialized'}
            
        self.running = True
        retry_count = 0
        delay = 1  # Initial delay in seconds
        max_delay = 60  # Maximum delay in seconds
        
        self.logger.info(f"Attempting to connect to Dhan WebSocket with {self.max_retries} max retries")
        
        while self.running and retry_count < self.max_retries:
            try:
                # Attempt to connect
                self.logger.info(f"Connection attempt {retry_count + 1} of {self.max_retries}")
                self.ws_client.connect()
                
                # Wait for connection to be established
                start_time = time.time()
                self.logger.debug(f"Waiting up to {self.connect_timeout}s for connection to be established")
                while time.time() - start_time < self.connect_timeout and not self.ws_client.connected:
                    time.sleep(0.1)
                
                # If connected, we're done
                if self.ws_client.connected:
                    self.logger.info("Successfully connected to Dhan WebSocket")
                    
                    # Resubscribe to previously subscribed symbols
                    subscription_count = self._resubscribe_all()
                    self.logger.info(f"Resubscribed to {subscription_count} symbols")
                    
                    return {'success': True, 'message': 'Successfully connected to Dhan WebSocket'}
                    
                # If not connected, try again
                retry_count += 1
                self.logger.warning(f"Failed to connect to Dhan WebSocket, attempt {retry_count} of {self.max_retries}")
                
                # Exponential backoff
                if retry_count < self.max_retries:
                    self.logger.info(f"Retrying in {delay} seconds (exponential backoff)")
                    time.sleep(delay)
                    delay = min(delay * 2, max_delay)  # Exponential backoff with cap
            
            except Exception as e:
                retry_count += 1
                self.logger.error(f"Error connecting to WebSocket: {e}")
                
                # Exponential backoff
                if retry_count < self.max_retries:
                    self.logger.info(f"Retrying in {delay} seconds (exponential backoff)")
                    time.sleep(delay)
                    delay = min(delay * 2, max_delay)  # Exponential backoff with cap
        
        # If we've exhausted retries
        self.logger.error("Failed to connect to Dhan WebSocket after maximum retries")
        return {'success': False, 'error': 'Failed to connect after maximum retries'}
        
    def _resubscribe_all(self) -> int:
        """Resubscribe to all previously subscribed symbols"""
        subscription_count = 0
        self.logger.info("Attempting to resubscribe to all previous symbols")
        
        for mode, subscriptions in self.mode_subscriptions.items():
            mode_count = 0
            self.logger.debug(f"Resubscribing to {len(subscriptions)} symbols for mode {mode}")
            
            for key, symbol_data in subscriptions.items():
                try:
                    success = self._subscribe_symbol(
                        symbol_data["symbol"],
                        symbol_data["exchange"],
                        mode,
                        symbol_data["depth_level"],
                        symbol_data["token"]
                    )
                    
                    if success:
                        subscription_count += 1
                        mode_count += 1
                        self.logger.debug(f"Successfully resubscribed to {symbol_data['symbol']} on {symbol_data['exchange']}")
                    else:
                        self.logger.warning(f"Failed to resubscribe to {symbol_data['symbol']} on {symbol_data['exchange']}")
                        
                except Exception as e:
                    self.logger.error(f"Error resubscribing to {symbol_data['symbol']}: {e}")
            
            self.logger.info(f"Resubscribed to {mode_count}/{len(subscriptions)} symbols for mode {mode}")
        
        self.logger.info(f"Completed resubscription with {subscription_count} total successful resubscriptions")
        return subscription_count
        
    def publish_status_update(self, status: str, **kwargs) -> None:
        """Publish status update to ZeroMQ socket
        
        Args:
            status: Status string (connected, disconnected, etc.)
            **kwargs: Additional status data (message, etc.)
        """
        try:
            if not hasattr(self, 'socket') or not self.socket:
                self.logger.warning("ZeroMQ socket not available, cannot publish status update")
                return
            
            status_data = {
                "type": "status",
                "broker": self.broker_name,
                "user_id": self.user_id,
                "status": status
            }
            
            # Add any additional keyword arguments
            for key, value in kwargs.items():
                status_data[key] = value
                
            self.socket.send_string(json.dumps(status_data))
        except Exception as e:
            self.logger.error(f"Error publishing status update: {e}", exc_info=True)
            # Do not re-raise; this is not a critical error
    
    def disconnect(self) -> None:
        """Disconnect from Dhan WebSocket"""
        self.running = False
        if self.ws_client:
            self.ws_client.disconnect()
            self.logger.info("Disconnected from Dhan WebSocket")
            
    def _on_open(self, ws):
        """Callback for when WebSocket connection is established"""
        self.logger.info("Dhan WebSocket connection established")
        try:
            # Call publish_status_update with keyword arguments to avoid TypeError
            self.publish_status_update("connected", message="WebSocket connection established")
        except Exception as e:
            self.logger.error(f"Error in open handler: {e}", exc_info=True)
            
    def _on_message(self, ws, message):
        """Callback for incoming WebSocket messages"""
        try:
            # Check if the message is binary data (market data) or text (control messages)
            if isinstance(message, bytes):
                self.logger.info(f"Received binary market data of length {len(message)}, first few bytes: {message[:16].hex()}")
                # Process binary market data (this contains the actual price updates)
                self._process_binary_message(message)
            else:
                # Process JSON text message (control messages, subscription responses)
                self.logger.info(f"Received text message: {message[:200]}..." if len(message) > 200 else f"Received text message: {message}")
                self._process_message(message)
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in WebSocket message: {e}")
        except Exception as e:
            self.logger.error(f"Error processing WebSocket message: {e}", exc_info=True)
            
    def _process_message(self, message):
        """Process a text message from WebSocket"""
        try:
            # Parse the message as JSON
            data = json.loads(message)
            
            # Check if this is a control message (e.g. successful subscription)
            if 'success' in data or 'status' in data:
                self.logger.info(f"Received control message: {data}")
                
                # Check for subscription response
                if data.get('success') is False and data.get('type') == 'subscription':
                    self.logger.error(f"Subscription failed: {data.get('message', 'No error message')}")
                    # If error details in separate field, log it
                    if 'error' in data:
                        self.logger.error(f"Subscription error details: {data['error']}")
                
                # If it's any other type of control or status message, log it for troubleshooting
                
            else:
                # Process market data in JSON format if present
                processed_data = self._process_market_data(data)
                
                # Publish the processed data to ZeroMQ
                if processed_data:
                    self.publish_market_data(processed_data)
                    
        except Exception as e:
            self.logger.error(f"Error processing text message: {e}")
            
    def _process_binary_message(self, binary_data):
        """Process binary market data from Dhan WebSocket"""
        try:
            # First 8 bytes are the header according to Dhan docs
            if len(binary_data) < 8:
                self.logger.warning(f"Binary message too short: {len(binary_data)} bytes")
                return
                
            # Extract header information
            feed_response_code = binary_data[0]
            message_length = int.from_bytes(binary_data[1:3], byteorder='big')
            exchange_segment = binary_data[3]
            security_id = int.from_bytes(binary_data[4:8], byteorder='big')
            
            # Log raw header for debugging with hexadecimal representation
            self.logger.info(f"Binary header: Code={feed_response_code}, Length={message_length}, Exchange={exchange_segment}, Security ID={security_id}, HexBytes={binary_data[:16].hex()}")
            
            # Convert numeric exchange segment to string code according to Dhan API documentation
            exchange_map = {
                0: 'IDX_I',        # Index - Index Value
                1: 'NSE_EQ',       # NSE - Equity Cash
                2: 'NSE_FNO',      # NSE - Futures & Options
                3: 'NSE_CURRENCY', # NSE - Currency
                4: 'BSE_EQ',       # BSE - Equity Cash
                5: 'MCX_COMM',     # MCX - Commodity
                7: 'BSE_CURRENCY', # BSE - Currency
                8: 'BSE_FNO'       # BSE - Futures & Options
            }
            
            # Get string exchange code
            dhan_exchange = exchange_map.get(exchange_segment, f"UNKNOWN_{exchange_segment}")
            oa_exchange = DhanExchangeMapper.from_dhan_exchange(dhan_exchange)
            
            if not oa_exchange:
                self.logger.warning(f"Could not map Dhan exchange {dhan_exchange} to OpenAlgo exchange")
                return
            
            # First try to find symbol using internal tracking
            symbol_info = None
            security_id_str = str(security_id)
            lookup_key = f"{dhan_exchange}:{security_id_str}"
            
            # Debug what we're looking up
            self.logger.debug(f"Looking up symbol with key: {lookup_key}")
            
            # Check in our mode subscriptions (mode 1 is LTP)
            if 1 in self.mode_subscriptions and lookup_key in self.mode_subscriptions[1]:
                symbol_info = self.mode_subscriptions[1][lookup_key]
                self.logger.info(f"Found symbol in subscriptions: {symbol_info['symbol']} for {lookup_key}")
                
            # For MCX tokens, also try with normalized token
            if not symbol_info and dhan_exchange == 'MCX_FO' and security_id > 100000:
                # Try with normalized token for MCX
                normalized_id = security_id % 1000000
                alt_lookup_key = f"{dhan_exchange}:{normalized_id}"
                self.logger.debug(f"Trying normalized MCX token: {alt_lookup_key}")
                
                if 1 in self.mode_subscriptions and alt_lookup_key in self.mode_subscriptions[1]:
                    symbol_info = self.mode_subscriptions[1][alt_lookup_key]
                    self.logger.info(f"Found symbol with normalized token: {symbol_info['symbol']} for {alt_lookup_key}")
            
            # If not found in our subscriptions, try to get from token database
            if not symbol_info:
                # Try to find symbol using the token database
                try:
                    self.logger.debug(f"Looking up symbol for token {security_id_str} on exchange {dhan_exchange}")
                    symbol = get_symbol_from_token(security_id_str, dhan_exchange)
                    
                    # For MCX tokens, also try with normalized token
                    if not symbol and dhan_exchange == 'MCX_FO' and security_id > 100000:
                        normalized_id = security_id % 1000000
                        self.logger.debug(f"Trying normalized MCX token: {normalized_id}")
                        symbol = get_symbol_from_token(str(normalized_id), dhan_exchange)
                    
                    if symbol:
                        symbol_info = {
                            'symbol': symbol,
                            'exchange': oa_exchange,
                            'token': security_id_str
                        }
                        self.logger.info(f"Found symbol {symbol} for token {security_id_str} on exchange {dhan_exchange}")
                except Exception as e:
                    self.logger.error(f"Error looking up symbol for token {security_id_str}: {e}")
            
            # Identify the binary feed packet type from the Feed Response Code
            feed_type_map = {
                1: "Index Packet",
                2: "Ticker/LTP Packet",
                4: "Quote Packet",
                5: "OI Packet",
                6: "Prev Close Packet",
                7: "Market Status Packet",
                8: "Full Packet",
                50: "Feed Disconnect"
            }
            feed_type = feed_type_map.get(feed_response_code, f"Unknown Feed Type ({feed_response_code})")
            self.logger.info(f"Processing binary {feed_type} from Dhan for exchange {dhan_exchange}, security ID {security_id}")
            
            # Process based on feed response code and if we have a symbol
            if symbol_info:
                # Ticker/LTP packet - Contains LTP and timestamp (minimal data)
                if feed_response_code == 2:  
                    # Must have 16 bytes (8 header + 4 LTP + 4 timestamp)
                    if len(binary_data) >= 16:
                        try:
                            # Parse according to Dhan API docs
                            ltp = struct.unpack('>f', binary_data[8:12])[0]  # float32, big-endian
                            timestamp = int.from_bytes(binary_data[12:16], byteorder='big')  # int32
                            
                            # Log successful data extraction with detailed formatting
                            self.logger.info(f"Received LTP data for {symbol_info['symbol']} on {symbol_info['exchange']}: LTP={ltp:.2f} at timestamp {timestamp}")
                            
                            # Create market data in OpenAlgo format
                            symbol_key = f"{symbol_info['exchange']}:{symbol_info['symbol']}"
                            
                            market_data = {
                                "ltp": {
                                    symbol_key: {
                                        "ltp": ltp,
                                        "ltt": timestamp
                                    }
                                },
                                "broker": self.broker_name,
                                "timestamp": int(time.time() * 1000)
                            }
                            
                            # Log what we're publishing
                            self.logger.info(f"Publishing market data for {symbol_key}: LTP={ltp:.2f}")
                            
                            # Publish to ZeroMQ
                            self.publish_market_data(market_data)
                        except Exception as e:
                            self.logger.error(f"Error processing LTP data: {e}", exc_info=True)
                    else:
                        self.logger.warning(f"LTP packet too short: {len(binary_data)} bytes for {symbol_info['symbol']}")
                            
                elif feed_response_code == 4:  # Quote packet
                    self.logger.debug(f"Quote packet received for {symbol_info['symbol']}, implementation pending")
                    # More complex with market depth data - implementation pending
                    pass
                    
                elif feed_response_code == 8:  # Full packet with market depth
                    self.logger.debug(f"Full market depth packet received for {symbol_info['symbol']}, implementation pending")
                    # Implementation pending
                    pass
                    
                else:
                    self.logger.debug(f"Unhandled feed response code: {feed_response_code} for {symbol_info['symbol']}")
            else:
                self.logger.warning(f"Could not identify symbol for security ID {security_id} on exchange {dhan_exchange}")
                    
        except Exception as e:
            self.logger.error(f"Error processing binary message: {e}", exc_info=True)
            
    def publish_market_data(self, market_data: Dict[str, Any]) -> None:
        """Publish market data to ZeroMQ socket
        
        Args:
            market_data: Market data in OpenAlgo format
        """
        try:
            if not hasattr(self, 'socket') or not self.socket:
                self.logger.warning("ZeroMQ socket not available, cannot publish market data")
                return
                
            # Verify market data has proper format before publishing
            if not market_data:
                self.logger.warning("Empty market data, not publishing")
                return
                
            # Ensure we have LTP data in the expected format
            if 'ltp' not in market_data or not market_data['ltp']:
                self.logger.warning("No LTP data in market_data, not publishing")
                return
                
            # Log what we're publishing (before sending to ZMQ)
            self.logger.info(f"Publishing market data: {json.dumps(market_data)}")
                
            # Send JSON data to ZeroMQ socket
            self.socket.send_string(json.dumps(market_data))
            self.logger.info("Market data sent to ZMQ socket successfully")
        except Exception as e:
            self.logger.error(f"Error publishing market data: {e}", exc_info=True)
    
    def _find_symbol_by_token(self, token: str, exchange_segment: int) -> Optional[Dict[str, str]]:
        """Find subscribed symbol information based on token and exchange segment"""
        # Convert numeric exchange segment to string exchange code
        exchange_map = {
            1: 'NSE_EQ',  # NSE Equity
            2: 'BSE_EQ',  # BSE Equity
            3: 'NSE_FO',  # NSE F&O
            4: 'BSE_FO',  # BSE F&O
            5: 'MCX_FO',  # MCX F&O
            7: 'CDS',     # Currency derivatives
            13: 'NCDEX_FO' # NCDEX F&O
        }
        
        dhan_exchange = exchange_map.get(exchange_segment, str(exchange_segment))
        oa_exchange = DhanExchangeMapper.to_oa_exchange(dhan_exchange)
        
        # Search in all mode subscriptions
        for mode, subscriptions in self.mode_subscriptions.items():
            for key, symbol_data in subscriptions.items():
                if symbol_data.get('token') == token and symbol_data.get('exchange') == oa_exchange:
                    return {
                        'symbol': symbol_data['symbol'],
                        'exchange': oa_exchange
                    }
        
        # If not found, return None
        return None
    
    def _on_error(self, ws, error):
        """Handle WebSocket errors"""
        self.logger.error(f"WebSocket error: {error}")
        # Publish error status update
        try:
            self.publish_status_update("error", f"WebSocket error: {error}")
        except Exception as e:
            self.logger.error(f"Error publishing status update: {e}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Callback when WebSocket connection closes"""
        self.logger.info(f"Dhan WebSocket closed: {close_status_code} - {close_msg}")
        self.publish_status_update("disconnected", f"WebSocket closed: {close_msg}")
        
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """Subscribe to market data with the specified mode and depth level"""
        # Check if the mode is supported
        if not DhanCapabilityRegistry.is_mode_supported(mode):
            return {
                "status": "error",
                "error": f"Unsupported subscription mode: {mode}",
                "symbol": symbol,
                "exchange": exchange
            }
        
        # Get token for the symbol
        token = get_token(symbol, exchange)
        if not token:
            return {
                "status": "error",
                "error": f"Token not found for {symbol} on {exchange}",
                "symbol": symbol,
                "exchange": exchange
            }
            
        # Translate exchange code
        dhan_exchange = DhanExchangeMapper.to_dhan_exchange(exchange)
        
        try:
            # Call internal subscription method
            success = self._subscribe_symbol(symbol, dhan_exchange, mode, depth_level, token)
            
            if success:
                return {
                    "status": "success",
                    "symbol": symbol,
                    "exchange": exchange,
                    "mode": mode,
                    "depth_level": depth_level,
                    "capabilities": DhanCapabilityRegistry.get_mode_fields(mode)
                }
            else:
                return {
                    "status": "error",
                    "error": "Failed to subscribe",
                    "symbol": symbol,
                    "exchange": exchange
                }
        except Exception as e:
            self.logger.error(f"Error subscribing to {symbol} on {exchange}: {e}")
            return {
                "status": "error",
                "error": str(e),
                "symbol": symbol,
                "exchange": exchange
            }
            
    def _subscribe_symbol(self, symbol: str, exchange: str, mode: int, depth_level: int = 5, token: str = None) -> bool:
        """Internal method to subscribe to a symbol
        
        Args:
            symbol: Symbol to subscribe to
            exchange: Exchange code
            mode: Subscription mode (1=LTP, 2=Quote, 3=Full)
            depth_level: Market depth level (usually 5 or 10)
            token: Optional token to use (if not provided, will look up)
            
        Returns:
            bool: True if subscription was successful, False otherwise
        """
        # Initialize subscription tracking if needed
        if mode not in self.mode_subscriptions:
            self.mode_subscriptions[mode] = {}
            
        if not token:
            self.logger.error(f"Token not found for {symbol} on {exchange}")
            return False
                
        # Make sure token is a string
        token = str(token)
        
        self.logger.info(f"Using token {token} for {symbol} on {exchange}")
        
        # Special handling for MCX futures
        if exchange == 'MCX':
            self.logger.info(f"Processing MCX futures symbol: {symbol} with token: {token}")
            
            # For GOLDPETAL specific handling
            if 'GOLDPETAL' in symbol.upper():
                # Special handling for GOLDPETAL
                self.logger.info(f"Special handling for GOLDPETAL symbol: {symbol}")
                # For GOLDPETAL, use a different approach entirely
                # Try using strategic token formats known to work
                if token.isdigit() and int(token) > 100000:
                    # If token is large numeric ID, try using a normalized version
                    token = str(int(token) % 100000)
                    self.logger.info(f"Using normalized token for GOLDPETAL: {token}")
                    
            # MCX futures often need specific formatting
            # Check if this is an MCX symbol known to fail with regular format
            elif any(mcx_symbol in symbol.upper() for mcx_symbol in ['GOLD', 'CRUDEOIL', 'SILVER']):
                # Some brokers require specific token format for MCX futures
                # Try stripping leading zeros if any
                if token.startswith('0'):
                    token = token.lstrip('0')
                    self.logger.info(f"Stripped leading zeros from MCX token: now {token}")
                
                # Ensure token is numeric for MCX
                try:
                    token = str(int(token))
                    self.logger.info(f"Converted MCX token to numeric format: {token}")
                except ValueError:
                    self.logger.warning(f"Could not convert MCX token to numeric format: {token}")
                    
                # Log the exchange code we'll be using
        # Set up subscription tracking
        exchange_code = DhanExchangeMapper.to_dhan_exchange(exchange)
        subscription_key = f"{exchange_code}:{token}"
        
        # Store in mode_subscriptions for later lookup during binary data processing
        symbol_data = {
            'symbol': symbol,
            'exchange': exchange,
            'dhan_exchange': exchange_code,
            'token': token,
            'mode': mode,
            'depth_level': depth_level,
            'subscription_time': int(time.time())
        }
        
        # Save in both directions for easy lookup
        self.mode_subscriptions[mode][subscription_key] = symbol_data
        # Also save by symbol and exchange for reverse lookup
        symbol_key = f"{exchange}:{symbol}"
        self.mode_subscriptions[mode][symbol_key] = symbol_data
        
        # Log what we're tracking
        self.logger.info(f"Added subscription tracking for {symbol_key} with token {token}")
        
        # Log available methods for debugging
        self.logger.info(f"WebSocket client attributes: {dir(self.ws_client)}")
        self.logger.info(f"WebSocket client type: {type(self.ws_client).__name__}")
        
        try:
            # Since we're having module caching issues, send the subscription directly
            if not hasattr(self.ws_client, 'ws') or not self.ws_client.ws:
                self.logger.error("WebSocket connection not available")
                return False
                
            # Map exchange code to Dhan's expected format
            dhan_exchange = DhanExchangeMapper.to_dhan_exchange(exchange)
            self.logger.info(f"Mapped exchange code {exchange} to Dhan exchange code {dhan_exchange}")
            
            # Create subscription request according to Dhan's API docs
            instrument_data = {
                "ExchangeSegment": dhan_exchange,
                "SecurityId": token
            }
            
            # Use the appropriate request code based on mode
            request_code = 15  # Default to full market data
            if mode == 1:      # LTP mode
                request_code = 2  # Ticker/LTP data
            elif mode == 2:    # Quote mode
                request_code = 4  # Quote data per Dhan's API docs
                
            subscription_request = {
                "RequestCode": request_code,
                "InstrumentCount": 1,
                "InstrumentList": [instrument_data]
            }
            
            self.logger.info(f"Sending direct subscription request for {symbol} with code {request_code}")
            
            # Log the full subscription message for debugging
            self.logger.info(f"Subscription request: {json.dumps(subscription_request)}")
                
            # Send the subscription message directly
            try:
                self.ws_client.ws.send(json.dumps(subscription_request))
                self.logger.info("WebSocket message sent successfully")
            except Exception as e:
                self.logger.error(f"Failed to send WebSocket message: {e}")
                return False
            
            # Store subscription for tracking
            key = f"{exchange}:{token}:{symbol}"
            
            # Initialize mode dict if it doesn't exist
            if mode not in self.mode_subscriptions:
                self.mode_subscriptions[mode] = {}
                
            # Store subscription
            self.mode_subscriptions[mode][key] = {
                "symbol": symbol,
                "exchange": exchange,
                "token": token,
                "depth_level": depth_level,
                "timestamp": int(time.time())
            }
            
            self.logger.info(f"Successfully sent subscription request for {symbol} on {exchange} with mode {mode}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error subscribing to {symbol} on {exchange}: {e}")
            return False

            
    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> Dict[str, Any]:
        """Unsubscribe from market data"""
        # Get token for the symbol
        token = get_token(symbol, exchange)
        if not token:
            return {
                "status": "error",
                "error": f"Token not found for {symbol} on {exchange}",
                "symbol": symbol,
                "exchange": exchange
            }
            
        # Translate exchange code
        dhan_exchange = DhanExchangeMapper.to_dhan_exchange(exchange)
        
        try:
            # Send unsubscription request directly via WebSocket
            if not self.ws_client or not hasattr(self.ws_client, 'ws') or not self.ws_client.ws:
                self.logger.error("Cannot unsubscribe: WebSocket connection not available")
                return {
                    "status": "error",
                    "error": "WebSocket connection not available",
                    "symbol": symbol,
                    "exchange": exchange
                }
                
            # Create instrument data for unsubscription
            instrument_data = {
                "ExchangeSegment": dhan_exchange,
                "SecurityId": token
            }
            
            # Create unsubscription request according to Dhan's API docs
            unsubscription_request = {
                "RequestCode": 16,  # Unsubscribe code
                "InstrumentCount": 1,
                "InstrumentList": [instrument_data]
            }
            
            self.logger.info(f"Sending direct unsubscription request for {symbol} on {exchange}")
            
            # Send the unsubscription message directly
            self.ws_client.ws.send(json.dumps(unsubscription_request))
            
            # Remove from subscription tracking
            key = f"{dhan_exchange}:{token}:{symbol}"
            for mode_dict in self.mode_subscriptions.values():
                if key in mode_dict:
                    del mode_dict[key]
                    
            return {
                "status": "success",
                "symbol": symbol,
                "exchange": exchange
            }
            
        except Exception as e:
            self.logger.error(f"Error unsubscribing from {symbol} on {exchange}: {e}")
            return {
                "status": "error",
                "error": str(e),
                "symbol": symbol,
                "exchange": exchange
            }
            
    def _unsubscribe_symbol(self, symbol: str, exchange: str, mode: int, token: str = None) -> bool:
        """Internal method to unsubscribe from a symbol"""
        if not self.ws_client or not self.ws_client.connected:
            self.logger.error("Cannot unsubscribe: Not connected to WebSocket")
            return False
            
        # If token not provided, get it from database
        if not token:
            token = get_token(symbol, exchange)
            if not token:
                self.logger.error(f"Token not found for {symbol} on {exchange}")
                return False
        
        # Prepare unsubscription data
        symbol_data = {
            "exchange": exchange,
            "token": token,
            "symbol": symbol
        }
        
        # Unsubscribe using the Dhan WebSocket client
        success = self.ws_client.unsubscribe([symbol_data])
        
        if success:
            # Remove from subscription tracking
            key = f"{exchange}:{token}:{symbol}"
            
            # Remove from mode subscriptions
            if mode in self.mode_subscriptions and key in self.mode_subscriptions[mode]:
                del self.mode_subscriptions[mode][key]
                
            self.logger.info(f"Successfully unsubscribed from {symbol} on {exchange} with mode {mode}")
            return True
        else:
            self.logger.error(f"Failed to unsubscribe from {symbol} on {exchange}")
            return False
    
    def _process_market_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process market data from Dhan WebSocket and transform to OpenAlgo format"""
        try:
            # Check if data contains error information
            if "error" in data:
                self.logger.error(f"Error in market data: {data['error']}")
                return None
                
            # Skip non-market data messages (e.g. subscription status)
            if "action" in data or not "symbol" in data:
                return None
            
            # Extract the exchange and token
            exchange = data.get("exchange")
            token = data.get("token")
            symbol = data.get("symbol")
            
            if not exchange or not token or not symbol:
                self.logger.warning("Missing exchange, token, or symbol in market data")
                return None
                
            # Convert exchange code back to OpenAlgo format
            oa_exchange = DhanExchangeMapper.to_oa_exchange(exchange)
            
            # Get OpenAlgo symbol if available, otherwise use the provided symbol
            oa_symbol = SymbolMapper.to_oa_symbol(symbol, oa_exchange) or symbol
            
            # Build base structure with common fields
            processed_data = {
                "symbol": oa_symbol,
                "exchange": oa_exchange,
                "token": token,
                "timestamp": int(time.time() * 1000),  # Dhan might not provide timestamp
                "ltp": data.get("lastTradedPrice", 0),
                "ltq": data.get("lastTradedQty", 0),
                "volume": data.get("totalTradedQty", 0),
                "open": data.get("openPrice", 0),
                "high": data.get("highPrice", 0),
                "low": data.get("lowPrice", 0),
                "close": data.get("closePrice", 0),
                "change": data.get("change", 0),
                "change_percent": data.get("changePerc", 0)
            }
            
            # Check if market depth data is available
            if "bids" in data and "asks" in data:
                processed_data["depth"] = {
                    "buy": [],
                    "sell": []
                }
                
                # Process buy orders (bids)
                for bid in data.get("bids", [])[:5]:  # Limit to 5 levels
                    processed_data["depth"]["buy"].append({
                        "price": bid.get("price", 0),
                        "quantity": bid.get("quantity", 0),
                        "orders": bid.get("orders", 1)  # Default to 1 if not provided
                    })
                    
                # Process sell orders (asks)
                for ask in data.get("asks", [])[:5]:  # Limit to 5 levels
                    processed_data["depth"]["sell"].append({
                        "price": ask.get("price", 0),
                        "quantity": ask.get("quantity", 0),
                        "orders": ask.get("orders", 1)  # Default to 1 if not provided
                    })
                
                # If we have depth, add top of the book data
                if processed_data["depth"]["buy"] and processed_data["depth"]["sell"]:
                    processed_data["bid"] = processed_data["depth"]["buy"][0]["price"]
                    processed_data["ask"] = processed_data["depth"]["sell"][0]["price"]
                    processed_data["bid_qty"] = processed_data["depth"]["buy"][0]["quantity"]
                    processed_data["ask_qty"] = processed_data["depth"]["sell"][0]["quantity"]
            
            # Add basic bid/ask if available but no depth
            elif "bestBid" in data and "bestAsk" in data:
                processed_data["bid"] = data.get("bestBid", 0)
                processed_data["ask"] = data.get("bestAsk", 0)
                processed_data["bid_qty"] = data.get("bestBidQty", 0)
                processed_data["ask_qty"] = data.get("bestAskQty", 0)
            
            return processed_data
            
        except Exception as e:
            self.logger.error(f"Error processing market data: {e}")
            return None
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Return adapter capabilities"""
        return DhanCapabilityRegistry.get_capabilities()
        
    def publish_status_update(self, status_data: Dict[str, Any]) -> None:
        """Publish status updates to ZeroMQ socket"""
        try:
            if self.zmq_socket:
                message = {
                    "type": "status",
                    "data": status_data,
                    "broker": self.broker_name,
                    "user_id": self.user_id,
                    "timestamp": int(time.time() * 1000)
                }
                self.zmq_socket.send_json(message)
                self.logger.debug(f"Published status update: {status_data['status']}")
        except Exception as e:
            self.logger.error(f"Error publishing status update: {e}")

