import threading
import json
import logging
import time
import websocket
import hashlib
import ssl
import os
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

from .aliceblue_client import Aliceblue, Instrument
from database.auth_db import get_auth_token, get_feed_token
from database.token_db import get_token

import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .aliceblue_mapping import AliceBlueExchangeMapper, AliceBlueCapabilityRegistry, AliceBlueMessageMapper, AliceBlueFeedType

class AliceblueWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """AliceBlue-specific implementation of the WebSocket adapter"""
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("aliceblue_websocket")
        self.ws_client = None
        self.aliceblue_client = None
        self.user_id = None
        self.client_id = None  # Store the API key (client_id) separately
        self.broker_name = "aliceblue"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()
        self.ws_session = None
        self.subscriptions = {}
        self.symbol_state = {}  # Store last known state for each symbol
        self.market_snapshots = {}  # Store complete market snapshots with value retention
        
        # Initialize mappers and registry
        self.exchange_mapper = AliceBlueExchangeMapper()
        self.capability_registry = AliceBlueCapabilityRegistry()
        self.message_mapper = AliceBlueMessageMapper()
    
    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with AliceBlue WebSocket API
        
        Args:
            broker_name: Name of the broker (always 'aliceblue' in this case)
            user_id: Client ID/user ID
            auth_data: If provided, use these credentials instead of fetching from DB
        
        Raises:
            ValueError: If required authentication tokens are not found
        """
        self.user_id = user_id
        self.broker_name = broker_name
        
        # Debug logging
        self.logger.info(f"Initializing AliceBlue adapter with auth_data: {auth_data}")
        
        try:
            if auth_data:
                api_key = auth_data.get('api_key')
                session_id = auth_data.get('session_id')
                self.logger.info(f"Using auth_data: api_key={api_key}, session_id={session_id}")
                # For WebSocket auth, client_id should be the BROKER_API_KEY (user_id from credentials)
                self.client_id = api_key  # This should be the BROKER_API_KEY value like '1412368'
                # Store session_id (JWT) for WebSocket authentication
                self.session_id = session_id
                self.logger.info(f"Using api_key as client_id: {self.client_id}")
                self.logger.info(f"Session ID (JWT) available for auth: {bool(session_id)}")
            else:
                # Fetch authentication tokens from database
                auth_token = get_auth_token(user_id)
                feed_token = get_feed_token(user_id)
                self.logger.info(f"From database: auth_token=[REDACTED], feed_token={feed_token}")
                self.logger.info(f"feed_token type: {type(feed_token)}, value: {repr(feed_token)}")
                
                if not auth_token:
                    self.logger.error(f"No authentication tokens found for user {user_id}")
                    raise ValueError(f"No authentication tokens found for user {user_id}")
                
                # Read BROKER_API_KEY from environment for client_id
                load_dotenv()
                broker_api_key = os.getenv('BROKER_API_KEY')
                if not broker_api_key:
                    self.logger.error("BROKER_API_KEY not found in environment variables")
                    raise ValueError("BROKER_API_KEY not found in environment variables")
                    
                api_key = broker_api_key  # Use BROKER_API_KEY for api_key
                # For AliceBlue, session_id is the auth_token (JWT)
                session_id = auth_token
                # For WebSocket auth, client_id should be the BROKER_API_KEY value
                self.client_id = broker_api_key
                # Store session_id (JWT) for WebSocket authentication
                self.session_id = session_id
                self.logger.info(f"Using BROKER_API_KEY as client_id: {self.client_id}")
                self.logger.info(f"Using auth_token as session_id for auth")
            
            self.logger.info(f"Final values: client_id={self.client_id}, session_id={self.session_id}")
            
            # Initialize AliceBlue client - use client_id as user_id for the AliceBlue client
            self.aliceblue_client = Aliceblue(
                user_id=self.client_id,  # Use client_id (BROKER_API_KEY) as user_id
                api_key=api_key,
                session_id=session_id
            )
            
            self.logger.info(f"AliceBlue WebSocket adapter initialized for user {user_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize AliceBlue adapter: {e}")
            raise
    
    def connect(self):
        """
        Establish WebSocket connection
        
        Returns:
            None: If successful, or dict with error info if failed
        """
        try:
            with self.lock:
                if self.running:
                    self.logger.warning("WebSocket already running")
                    return None
                
                self.running = True
                self.reconnect_attempts = 0
            
            # AliceBlue WebSocket session flow:
            # Note: The WebSocket session creation is not required for authentication
            # The official client invalidates and creates session but doesn't use it for auth
            # We'll skip this step as it's not necessary for WebSocket authentication
            self.logger.info("Skipping WebSocket session creation - not required for authentication")
            
            # Start WebSocket connection
            success = self._start_websocket()
            
            if success:
                self.logger.info("AliceBlue WebSocket connected successfully")
                self.connected = True
                return None  # Success
            else:
                self.logger.error("Failed to connect to AliceBlue WebSocket")
                with self.lock:
                    self.running = False
                return {'success': False, 'error': 'Failed to connect to AliceBlue WebSocket'}
                
        except Exception as e:
            self.logger.error(f"Error connecting to AliceBlue WebSocket: {e}")
            with self.lock:
                self.running = False
            return {'success': False, 'error': f'Error connecting to AliceBlue WebSocket: {e}'}
    
    def _start_websocket(self) -> bool:
        """Start the WebSocket connection"""
        try:
            def on_message(ws, message):
                self._handle_message(message)
            
            def on_error(ws, error):
                self._handle_error(error)
            
            def on_close(ws, close_status_code, close_msg):
                self._handle_disconnect()
            
            def on_open(ws):
                self._authenticate_websocket(ws)
            
            # Create WebSocket connection - use wss instead of https
            websocket.enableTrace(False)  # Disable trace for production
            self.ws_client = websocket.WebSocketApp(
                "wss://ws1.aliceblueonline.com/NorenWS/",
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            
            # Start WebSocket in background thread
            self.ws_thread = threading.Thread(
                target=self.ws_client.run_forever,
                kwargs={'sslopt': {"cert_reqs": ssl.CERT_NONE}}
            )
            self.ws_thread.daemon = True
            self.ws_thread.start()
            
            # Wait a bit for connection to establish
            time.sleep(2)
            
            return self.ws_client.sock and self.ws_client.sock.connected
            
        except Exception as e:
            self.logger.error(f"Error starting WebSocket: {e}")
            return False
    
    def _authenticate_websocket(self, ws):
        """Authenticate WebSocket connection"""
        try:
            # Check if session_id (JWT) is available
            if not self.session_id:
                self.logger.warning("No session_id (JWT) available, skipping authentication")
                return
                
            # Create authentication message - use JWT session_id for susertoken generation
            # This matches the official AliceBlue client implementation
            # First SHA256 hash of session_id
            sha256_encryption1 = hashlib.sha256(self.session_id.encode('utf-8')).hexdigest()
            # Second SHA256 hash of the first hash
            susertoken = hashlib.sha256(sha256_encryption1.encode('utf-8')).hexdigest()
            
            self.logger.info(f"Generating susertoken from session_id (JWT)")
            self.logger.info(f"Session ID length: {len(self.session_id)}")
            self.logger.info(f"First SHA256: {sha256_encryption1}")
            self.logger.info(f"Final susertoken: {susertoken}")
            
            auth_msg = {
                "susertoken": susertoken,
                "t": "c",
                "actid": f"{self.client_id}_API",
                "uid": f"{self.client_id}_API",
                "source": "API"
            }
            
            self.logger.info(f"Sending authentication message: {auth_msg}")
            ws.send(json.dumps(auth_msg))
            self.logger.info("Authentication message sent to AliceBlue WebSocket")
            
        except Exception as e:
            self.logger.error(f"Error authenticating WebSocket: {e}")
    
    def disconnect(self) -> None:
        """Close WebSocket connection"""
        try:
            with self.lock:
                if not self.running:
                    return
                
                self.running = False
            
            if self.ws_client:
                self.ws_client.close()
            
            # Clean up ZeroMQ resources
            self.cleanup_zmq()
            
            self.logger.info("AliceBlue WebSocket disconnected")
            
        except Exception as e:
            self.logger.error(f"Error disconnecting from AliceBlue WebSocket: {e}")
    
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to live data for a symbol
        
        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Depth
            depth_level: Market depth level (5, 20, 30)
        
        Returns:
            Dict[str, Any]: Response with status and message
        """
        try:
            # Auto-reconnect if disconnected (similar to Fyers)
            if not self.ws_client or not self.ws_client.sock or not self.ws_client.sock.connected:
                self.logger.info("AliceBlue WebSocket not connected - attempting to reconnect...")
                reconnect_result = self.connect()
                if reconnect_result and reconnect_result.get('success') == False:
                    self.logger.error("Failed to reconnect to AliceBlue WebSocket")
                    return self._create_error_response("RECONNECT_FAILED", "Failed to reconnect to WebSocket")
                # Wait a bit for connection to stabilize
                import time
                time.sleep(1)
            # Convert exchange to AliceBlue format
            ab_exchange = self.exchange_mapper.to_broker_exchange(exchange)
            
            # Get token for the symbol
            self.logger.info(f"Subscribe: Looking up token for symbol: {symbol}, ab_exchange: {ab_exchange}")
            token = get_token(symbol, ab_exchange)
            self.logger.info(f"Subscribe: Token lookup result: {token}")
            if not token:
                self.logger.error(f"Token not found for {symbol} on {exchange}")
                return self._create_error_response("TOKEN_NOT_FOUND", f"Token not found for {symbol} on {exchange}")
            
            # Determine feed type based on mode
            feed_type = AliceBlueFeedType.DEPTH if mode == 3 else AliceBlueFeedType.MARKET_DATA
            
            # Create subscription message
            sub_msg = self.message_mapper.create_subscription_message(ab_exchange, token, feed_type)
            
            if self.ws_client and self.ws_client.sock and self.ws_client.sock.connected:
                self.ws_client.send(json.dumps(sub_msg))
                
                # Track subscription - use simple key for now
                sub_key = f"{ab_exchange}|{str(token)}"
                
                with self.lock:
                    # If already subscribed with a lower mode, update to higher mode
                    # AliceBlue sends all data for highest subscribed mode
                    existing_mode = self.subscriptions.get(sub_key, {}).get('mode', 0)
                    if mode > existing_mode:
                        self.subscriptions[sub_key] = {
                            'symbol': symbol,
                            'exchange': exchange,
                            'ab_exchange': ab_exchange,
                            'token': token,
                            'mode': mode,  # Store the highest mode subscribed
                            'depth_level': depth_level,
                            'original_symbol': symbol,  # Store original OpenAlgo symbol for lookup
                            'original_exchange': exchange,  # Store original OpenAlgo exchange
                            'all_modes': self.subscriptions.get(sub_key, {}).get('all_modes', set()) | {mode}  # Track all subscribed modes
                        }
                    elif sub_key not in self.subscriptions:
                        self.subscriptions[sub_key] = {
                            'symbol': symbol,
                            'exchange': exchange,
                            'ab_exchange': ab_exchange,
                            'token': token,
                            'mode': mode,
                            'depth_level': depth_level,
                            'original_symbol': symbol,
                            'original_exchange': exchange,
                            'all_modes': {mode}
                        }
                    else:
                        # Add this mode to the set of subscribed modes
                        self.subscriptions[sub_key]['all_modes'] = self.subscriptions[sub_key].get('all_modes', set()) | {mode}
                
                self.logger.info(f"Subscribed to {symbol} ({ab_exchange}|{token}) for mode {mode}")
                self.logger.info(f"Stored subscription with key: {sub_key}")
                self.logger.info(f"Stored symbol: {symbol}, exchange: {exchange}")
                self.logger.info(f"Token type: {type(token)}, value: {repr(token)}")
                return self._create_success_response(f"Subscribed to {symbol} on {exchange} for mode {mode}")
            else:
                self.logger.error("WebSocket not connected")
                return self._create_error_response("NOT_CONNECTED", "WebSocket not connected")
                
        except Exception as e:
            self.logger.error(f"Error subscribing to {symbol}: {e}")
            return self._create_error_response("SUBSCRIPTION_ERROR", str(e))
    
    def _update_market_snapshot(self, symbol_key: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update market snapshot for value retention.
        Only updates non-zero values to retain previous valid data.
        AliceBlue sends 0 for unchanged values, so we need to preserve the last known valid values.
        """
        # Get existing snapshot or create empty one
        snapshot = self.market_snapshots.get(symbol_key, {})
        
        # Fields to check and merge
        price_fields = ['ltp', 'open', 'high', 'low', 'close', 'average_price']
        volume_fields = ['volume', 'total_buy_quantity', 'total_sell_quantity']
        other_fields = ['total_oi', 'change_percent', 'timestamp', 'symbol', 'exchange', 'token']
        
        # Update price fields - only if non-zero
        for field in price_fields:
            if field in data:
                value = data[field]
                # Only update if value is not 0 (AliceBlue sends 0 for unchanged)
                if isinstance(value, (int, float)) and value != 0:
                    snapshot[field] = value
                # If it's 0 and we don't have a previous value, set it to 0
                elif field not in snapshot:
                    snapshot[field] = 0
        
        # Update volume fields - can be 0 at market open
        for field in volume_fields:
            if field in data:
                value = data[field]
                # Volume can legitimately be 0 at market open, but not negative
                if isinstance(value, (int, float)) and value >= 0:
                    snapshot[field] = value
                elif field not in snapshot:
                    snapshot[field] = 0
        
        # Update other fields - always update if present
        for field in other_fields:
            if field in data and data[field] is not None:
                snapshot[field] = data[field]
        
        # Handle depth data specially
        if 'bids' in data or 'asks' in data:
            # Update bids if present and non-empty
            if 'bids' in data and isinstance(data['bids'], list):
                # Filter out entries with 0 price (invalid)
                valid_bids = [bid for bid in data['bids'] 
                             if bid.get('price', 0) != 0]
                if valid_bids:
                    snapshot['bids'] = valid_bids
                elif 'bids' not in snapshot:
                    snapshot['bids'] = []
            
            # Update asks if present and non-empty  
            if 'asks' in data and isinstance(data['asks'], list):
                # Filter out entries with 0 price (invalid)
                valid_asks = [ask for ask in data['asks'] 
                             if ask.get('price', 0) != 0]
                if valid_asks:
                    snapshot['asks'] = valid_asks
                elif 'asks' not in snapshot:
                    snapshot['asks'] = []
        
        # Store updated snapshot
        self.market_snapshots[symbol_key] = snapshot
        
        self.logger.debug(f"Updated snapshot for {symbol_key}: {snapshot}")
        
        return snapshot
    
    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> Dict[str, Any]:
        """
        Unsubscribe from live data for a symbol
        
        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Subscription mode
        
        Returns:
            Dict[str, Any]: Response with status and message
        """
        try:
            # Convert exchange to AliceBlue format
            ab_exchange = self.exchange_mapper.to_broker_exchange(exchange)
            
            # Get token for the symbol
            token = get_token(symbol, ab_exchange)
            if not token:
                self.logger.error(f"Token not found for {symbol} on {exchange}")
                return self._create_error_response("TOKEN_NOT_FOUND", f"Token not found for {symbol} on {exchange}")
            
            # Create unsubscription message
            unsub_msg = self.message_mapper.create_unsubsciption_message(ab_exchange, token)
            
            if self.ws_client and self.ws_client.sock and self.ws_client.sock.connected:
                self.ws_client.send(json.dumps(unsub_msg))
                
                # Remove from tracked subscriptions
                sub_key = f"{ab_exchange}|{token}"
                
                with self.lock:
                    if sub_key in self.subscriptions:
                        # Remove this mode from the set of subscribed modes
                        all_modes = self.subscriptions[sub_key].get('all_modes', set())
                        if mode in all_modes:
                            all_modes.discard(mode)
                        
                        if not all_modes:
                            # No modes left, remove the subscription entirely
                            del self.subscriptions[sub_key]
                            # Also remove symbol state and market snapshot
                            if sub_key in self.symbol_state:
                                del self.symbol_state[sub_key]
                            if sub_key in self.market_snapshots:
                                del self.market_snapshots[sub_key]
                        else:
                            # Update to the highest remaining mode
                            self.subscriptions[sub_key]['all_modes'] = all_modes
                            self.subscriptions[sub_key]['mode'] = max(all_modes)
                    
                    # Check if no more subscriptions remain
                    remaining_subscriptions = len(self.subscriptions)
                
                self.logger.info(f"Unsubscribed from {symbol} ({ab_exchange}|{token})")
                
                # If no more subscriptions, disconnect to stop all background data (like Fyers)
                if remaining_subscriptions == 0:
                    self.logger.info("No active subscriptions remaining - disconnecting from AliceBlue to stop all background data")
                    try:
                        # Close WebSocket connection but keep the adapter ready for reconnection
                        if self.ws_client:
                            self.ws_client.close()
                            # Don't set ws_client to None - keep it for potential reconnection
                        self.connected = False
                        self.running = False
                        
                        # Clear all market data snapshots and states
                        self.symbol_state.clear()
                        self.market_snapshots.clear()
                        
                        self.logger.info("Disconnected from AliceBlue WebSocket - all background data stopped")
                        
                        return {
                            'status': 'success',
                            'message': f'Unsubscribed from {symbol} on {exchange} and disconnected (no active subscriptions)',
                            'disconnected': True,
                            'active_subscriptions': 0
                        }
                    except Exception as e:
                        self.logger.error(f"Error disconnecting from AliceBlue: {e}")
                        return self._create_success_response(f"Unsubscribed from {symbol} on {exchange}")
                
                return self._create_success_response(f"Unsubscribed from {symbol} on {exchange}")
            else:
                self.logger.error("WebSocket not connected")
                return self._create_error_response("NOT_CONNECTED", "WebSocket not connected")
                
        except Exception as e:
            self.logger.error(f"Error unsubscribing from {symbol}: {e}")
            return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))
    
    def _handle_message(self, message: str) -> None:
        """
        Handle incoming WebSocket message
        
        Args:
            message: Raw message from WebSocket
        """
        try:
            # Log all incoming messages for debugging (use debug level to avoid flooding)
            self.logger.debug(f"Received WebSocket message: {message}")
            
            # Parse JSON message
            data = json.loads(message)
            
            # Handle different message types
            msg_type = data.get('t')
            
            if msg_type == 'ck':
                # Connection confirmation
                status = data.get('s', '')
                if status == 'OK':
                    self.logger.info("WebSocket authentication successful")
                    self.connected = True
                    # Resubscribe to any existing subscriptions after successful connection
                    self._resubscribe_after_auth()
                else:
                    self.logger.error(f"WebSocket authentication failed: {data}")
                    self.connected = False
                return
            
            elif msg_type == 'cf':
                # Connection confirmation (documented format)
                if data.get('k') == 'OK':
                    self.logger.info("WebSocket authentication successful")
                    self.connected = True
                else:
                    self.logger.error(f"WebSocket authentication failed: {data}")
                    self.connected = False
                return
            
            elif msg_type == 'tk':
                # Acknowledgment message - contains initial market data
                self.logger.info(f"Received acknowledgment with data: {data}")
                parsed_data = self.message_mapper.parse_tick_data(data)
                self.logger.info(f"Parsed acknowledgment data: {parsed_data}")
                if parsed_data.get('type') != 'error':
                    self._on_data_received(parsed_data)
                else:
                    self.logger.error(f"Error parsing acknowledgment data: {parsed_data['message']}")
                # Don't return here - continue processing other message types
            
            elif msg_type == 'tf':
                # Tick data - continuous updates
                parsed_data = self.message_mapper.parse_tick_data(data)
                if parsed_data.get('type') != 'error':
                    # Always process tick feeds for continuous updates
                    self._on_data_received(parsed_data)
                    self.logger.debug(f"Processing tick feed for token: {data.get('e', 'unknown')}|{data.get('tk', 'unknown')}")
                else:
                    self.logger.error(f"Error parsing tick data: {parsed_data['message']}")
            
            elif msg_type == 'df':
                # Depth data update - continuous updates
                parsed_data = self.message_mapper.parse_depth_data(data)
                if parsed_data.get('type') != 'error':
                    # Add message type
                    parsed_data['message_type'] = 'df'
                    # Always process depth feeds for continuous updates
                    self._on_data_received(parsed_data)
                    self.logger.debug(f"Processing depth feed for token: {data.get('e', 'unknown')}|{data.get('tk', 'unknown')}")
                else:
                    self.logger.error(f"Error parsing depth data: {parsed_data['message']}")
            
            elif msg_type == 'dk':
                # Depth data acknowledgment (full depth data)
                parsed_data = self.message_mapper.parse_depth_data(data)
                if parsed_data.get('type') != 'error':
                    # Add message type
                    parsed_data['message_type'] = 'dk'
                    # Store symbol info from dk message
                    token = data.get('tk', '')
                    exchange = data.get('e', '')
                    symbol_key = f"{exchange}|{token}"
                    if 'ts' in data:
                        # Extract and clean symbol name
                        raw_symbol = data['ts']
                        clean_symbol = raw_symbol.split('-')[0] if raw_symbol else ""
                        parsed_data['symbol'] = clean_symbol
                    self._on_data_received(parsed_data)
                else:
                    self.logger.error(f"Error parsing depth acknowledgment: {parsed_data['message']}")
            
            else:
                self.logger.info(f"Unknown message type: {msg_type}, data: {data}")
                # Try to handle as generic market data if it looks like tick data
                if msg_type and len(data) > 2:  # Non-empty message with some data
                    self._handle_generic_market_data(data)
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing JSON message: {e}")
        except Exception as e:
            self.logger.error(f"Error handling message: {e}")
    
    def _handle_error(self, error: Any) -> None:
        """Handle WebSocket error"""
        self.logger.error(f"AliceBlue WebSocket error: {error}")
        
        # Trigger reconnection logic
        if self.running:
            self._schedule_reconnect()
    
    def _handle_disconnect(self) -> None:
        """Handle WebSocket disconnection"""
        self.logger.warning("AliceBlue WebSocket disconnected")
        
        with self.lock:
            was_running = self.running
            self.running = False
        
        if was_running:
            self._schedule_reconnect()
    
    def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error("Maximum reconnection attempts reached")
            return
        
        delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts), self.max_reconnect_delay)
        self.reconnect_attempts += 1
        
        self.logger.info(f"Scheduling reconnection attempt {self.reconnect_attempts} in {delay} seconds")
        
        def reconnect():
            time.sleep(delay)
            if not self.running:  # Only reconnect if not already running
                self.logger.info("Attempting to reconnect...")
                success = self.connect()
                if success:
                    # Resubscribe to all previous subscriptions
                    self._resubscribe_all()
        
        reconnect_thread = threading.Thread(target=reconnect)
        reconnect_thread.daemon = True
        reconnect_thread.start()
    
    def _resubscribe_all(self) -> None:
        """Resubscribe to all previously subscribed symbols"""
        with self.lock:
            subscriptions_to_restore = self.subscriptions.copy()
        
        for sub_key, sub_info in subscriptions_to_restore.items():
            try:
                self.logger.info(f"Resubscribing to {sub_info['symbol']} on {sub_info['exchange']}")
                self.subscribe(
                    sub_info['symbol'],
                    sub_info['exchange'], 
                    sub_info['mode'],
                    sub_info['depth_level']
                )
            except Exception as e:
                self.logger.error(f"Error resubscribing to {sub_key}: {e}")
    
    def _resubscribe_after_auth(self) -> None:
        """Resubscribe after successful authentication"""
        # This is called after WebSocket authentication succeeds
        # Check if we have any pending subscriptions
        with self.lock:
            if self.subscriptions:
                self.logger.info(f"Resubscribing to {len(self.subscriptions)} symbols after authentication")
                for sub_key, sub_info in self.subscriptions.items():
                    try:
                        # Send subscription message
                        feed_type = AliceBlueFeedType.DEPTH if sub_info['mode'] == 3 else AliceBlueFeedType.MARKET_DATA
                        sub_msg = self.message_mapper.create_subscription_message(
                            sub_info['ab_exchange'], 
                            sub_info['token'], 
                            feed_type
                        )
                        self.ws_client.send(json.dumps(sub_msg))
                        self.logger.info(f"Resubscribed to {sub_info['symbol']}")
                    except Exception as e:
                        self.logger.error(f"Error resubscribing to {sub_key}: {e}")
    
    def is_connected(self) -> bool:
        """Check if WebSocket is connected"""
        return (self.running and 
                self.ws_client and 
                self.ws_client.sock and 
                self.ws_client.sock.connected)
    
    def get_subscriptions(self) -> List[str]:
        """Get list of current subscriptions"""
        with self.lock:
            return list(self.subscriptions.keys())
    
    def _on_data_received(self, parsed_data):
        """Handle received and parsed market data"""
        try:
            self.logger.debug(f"_on_data_received called with parsed_data: {parsed_data}")
            # Extract key identifiers
            token = parsed_data.get('token', '')
            broker_exchange = parsed_data.get('exchange', 'UNKNOWN')
            # Convert broker exchange back to standard exchange format (default mapping)
            exchange = self.exchange_mapper.from_broker_exchange(broker_exchange)
            msg_type = parsed_data.get('message_type', '')
            
            # Create a unique key for this symbol
            symbol_key = f"{broker_exchange}|{str(token)}"
            self.logger.debug(f"Processing data - broker_exchange: {broker_exchange}, token: {token}")
            self.logger.debug(f"Token type in data: {type(token)}, value: {repr(token)}")
            self.logger.debug(f"Current subscriptions keys: {list(self.subscriptions.keys())}")
            
            # Update market snapshot with value retention
            # This ensures we retain previous values when AliceBlue sends 0 for unchanged fields
            snapshot_data = self._update_market_snapshot(symbol_key, parsed_data)
            
            # Handle different message types
            if msg_type == 'tk':
                # Token acknowledgment - contains full data, store it
                self.symbol_state[symbol_key] = snapshot_data.copy()
                symbol = snapshot_data.get('symbol', 'UNKNOWN')
            elif msg_type == 'dk':
                # Depth acknowledgment - contains full data including symbol, store it
                self.symbol_state[symbol_key] = snapshot_data.copy()
                symbol = snapshot_data.get('symbol', 'UNKNOWN')
            elif msg_type == 'tf':
                # Tick feed - use snapshot data which has merged values
                self.symbol_state[symbol_key] = snapshot_data.copy()
                parsed_data = snapshot_data  # Use the snapshot with retained values
                # For tick feed, get symbol from our stored subscription info if not in message
                if 'symbol' not in snapshot_data or snapshot_data.get('symbol') == 'UNKNOWN':
                    # Look up symbol from subscription data
                    if symbol_key in self.subscriptions:
                        sub_data = self.subscriptions[symbol_key]
                        symbol = sub_data.get('original_symbol', f"TOKEN_{token}")
                        parsed_data['symbol'] = symbol
                    else:
                        symbol = f"TOKEN_{token}"
                        parsed_data['symbol'] = symbol
                else:
                    symbol = snapshot_data.get('symbol', 'UNKNOWN')
            elif msg_type == 'df':
                # Depth feed - use snapshot data which has merged values
                self.symbol_state[symbol_key] = snapshot_data.copy()
                parsed_data = snapshot_data  # Use the snapshot with retained values
                # For depth feed, get symbol from our stored subscription info if not in message
                if 'symbol' not in snapshot_data or snapshot_data.get('symbol') == 'UNKNOWN' or snapshot_data.get('symbol', '').startswith('TOKEN_'):
                    # Look up symbol from subscription data
                    if symbol_key in self.subscriptions:
                        sub_data = self.subscriptions[symbol_key]
                        symbol = sub_data.get('original_symbol', sub_data.get('symbol', f"TOKEN_{token}"))
                        parsed_data['symbol'] = symbol
                    else:
                        symbol = f"TOKEN_{token}"
                        parsed_data['symbol'] = symbol
                else:
                    symbol = snapshot_data.get('symbol', f"TOKEN_{token}")
            else:
                # Other message types - use snapshot data
                parsed_data = snapshot_data
                symbol = snapshot_data.get('symbol', 'UNKNOWN')
            
            # Find the original subscription to get the correct exchange and symbol
            # This is important because the client subscribes with NSE_INDEX for NIFTY
            # but the data comes with NSE exchange
            # Also, for NFO/BFO symbols, AliceBlue returns broker symbols but we need OpenAlgo symbols
            sub_key = symbol_key  # Use the same key as created above
            self.logger.debug(f"Looking for subscription with key: {sub_key}")
            original_exchange = exchange  # Default to mapped exchange
            original_symbol = symbol  # Default to parsed symbol
            
            with self.lock:
                self.logger.debug(f"Subscription lookup - checking if '{sub_key}' in subscriptions")
                if sub_key in self.subscriptions:
                    # Use the exchange and symbol from the original subscription
                    original_exchange = self.subscriptions[sub_key].get('original_exchange', self.subscriptions[sub_key].get('exchange', exchange))
                    original_symbol = self.subscriptions[sub_key].get('original_symbol', self.subscriptions[sub_key].get('symbol', symbol))
                    self.logger.debug(f"FOUND subscription: exchange={original_exchange}, symbol={original_symbol}")
                else:
                    self.logger.debug(f"Subscription not found for key: {sub_key}, using parsed values")
            
            # Special handling for NIFTY index based on token (26000 is NIFTY token)
            if token == '26000' and broker_exchange == 'NSE':
                original_symbol = 'NIFTY'
                # Update the parsed_data with correct symbol
                parsed_data['symbol'] = original_symbol
                
            # Use the original subscription exchange and symbol for topic generation
            exchange = original_exchange
            symbol = original_symbol
            self.logger.debug(f"Final values for topic: exchange={exchange}, symbol={symbol}")
            
            # Get all subscribed modes for this symbol
            all_modes = set()
            with self.lock:
                if sub_key in self.subscriptions:
                    all_modes = self.subscriptions[sub_key].get('all_modes', {1})  # Default to LTP if not found
            
            # Determine what data we have
            has_depth = 'bids' in parsed_data or 'asks' in parsed_data or 'depth' in parsed_data
            has_quote = any(k in parsed_data for k in ['open', 'high', 'low', 'close', 'volume'])
            has_ltp = 'ltp' in parsed_data
            
            # Publish to appropriate topics based on subscribed modes and available data
            topics_to_publish = []
            
            # For depth messages (df, dk), publish to DEPTH topic if subscribed
            if msg_type in ['df', 'dk'] and 3 in all_modes:
                topics_to_publish.append(('DEPTH', 3))
            else:
                # For other messages, publish to all applicable subscribed modes
                if has_ltp and 1 in all_modes:
                    topics_to_publish.append(('LTP', 1))
                if has_quote and 2 in all_modes:
                    topics_to_publish.append(('QUOTE', 2))
                if has_depth and 3 in all_modes:
                    topics_to_publish.append(('DEPTH', 3))
            
            # If no specific modes matched but we have data, publish to highest subscribed mode
            if not topics_to_publish and all_modes:
                max_mode = max(all_modes)
                mode_map = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}
                topics_to_publish.append((mode_map[max_mode], max_mode))
            
            # Publish to all applicable topics
            for mode_name, mode_num in topics_to_publish:
                topic = f"{exchange}_{symbol}_{mode_name}"
                self.logger.debug(f"Publishing {msg_type} to {topic}")
            
            # Add timestamp if not present
            if 'timestamp' not in parsed_data:
                parsed_data['timestamp'] = int(time.time() * 1000)
            
            # Publish to all applicable topics
            for mode_name, mode_num in topics_to_publish:
                topic = f"{exchange}_{symbol}_{mode_name}"
                
                # Prepare data based on mode
                if mode_num == 1:  # LTP mode
                    # For LTP mode, only send minimal data
                    publish_data = {
                        'ltp': parsed_data.get('ltp', 0.0),
                        'ltt': parsed_data.get('timestamp', '')  # Last traded time
                    }
                elif mode_num == 2:  # QUOTE mode
                    # For QUOTE mode, send price and volume data
                    publish_data = {
                        'ltp': parsed_data.get('ltp', 0.0),
                        'ltt': parsed_data.get('timestamp', ''),
                        'volume': parsed_data.get('volume', 0),
                        'open': parsed_data.get('open', 0.0),
                        'high': parsed_data.get('high', 0.0),
                        'low': parsed_data.get('low', 0.0),
                        'close': parsed_data.get('close', 0.0),
                        'change_percent': parsed_data.get('change_percent', 0.0),
                        'average_price': parsed_data.get('average_price', 0.0),
                        'total_oi': parsed_data.get('total_oi', 0)
                    }
                else:  # DEPTH mode
                    # For DEPTH mode, format data to match expected client format
                    if parsed_data.get('type') == 'market_depth' or 'bids' in parsed_data or 'asks' in parsed_data:
                        # Convert bids/asks arrays to buy/sell format expected by client
                        depth_data = {
                            'buy': [],
                            'sell': []
                        }
                        
                        # Convert bids to buy array
                        for bid in parsed_data.get('bids', []):
                            depth_data['buy'].append({
                                'price': bid.get('price', 0),
                                'quantity': bid.get('quantity', 0),
                                'orders': 0  # AliceBlue doesn't provide order count
                            })
                        
                        # Convert asks to sell array
                        for ask in parsed_data.get('asks', []):
                            depth_data['sell'].append({
                                'price': ask.get('price', 0),
                                'quantity': ask.get('quantity', 0),
                                'orders': 0  # AliceBlue doesn't provide order count
                            })
                        
                        publish_data = {
                            'ltp': parsed_data.get('ltp', 0),
                            'timestamp': parsed_data.get('timestamp', ''),
                            'depth': depth_data
                        }
                    else:
                        # Fallback for other data types
                        publish_data = {k: v for k, v in parsed_data.items() 
                                      if k not in ['message_type', 'type']}
                
                # Debug logging for data publishing
                self.logger.debug(f"Publishing {msg_type} to topic {topic}")
                
                # Publish to ZMQ - this sends data to frontend
                self.publish_market_data(topic, publish_data)
            
        except Exception as e:
            self.logger.error(f"Error processing received data: {e}")
    
    def _handle_generic_market_data(self, data: Dict) -> None:
        """Handle unknown message format as potential market data"""
        try:
            # Log the raw data so we can understand the format
            self.logger.info(f"Trying to parse as generic market data: {data}")
            
            # Try to create a basic market data object
            market_data = {
                'symbol': 'UNKNOWN',
                'exchange': 'UNKNOWN', 
                'mode': 'UNKNOWN',
                'raw_data': data,
                'timestamp': int(time.time() * 1000)
            }
            
            # Extract any numeric values that might be LTP
            for key, value in data.items():
                if isinstance(value, (int, float)) and value > 0:
                    if key in ['lp', 'ltp', 'price']:
                        market_data['ltp'] = float(value)
                    elif key in ['tk', 'token']:
                        market_data['token'] = str(value)
                    elif key in ['e', 'exchange']:
                        market_data['exchange'] = str(value)
            
            # Publish raw data for debugging
            topic = f"DEBUG_MARKET_DATA"
            self.publish_market_data(topic, market_data)
            
        except Exception as e:
            self.logger.error(f"Error handling generic market data: {e}")
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get adapter capabilities"""
        return {
            "supported_data_types": list(self.capability_registry.get_supported_data_types()),
            "supported_exchanges": list(self.capability_registry.get_supported_exchanges()),
            "supported_instruments": list(self.capability_registry.get_supported_instrument_types()),
            "rate_limits": {
                "subscriptions_per_second": self.capability_registry.get_rate_limit("subscriptions_per_second"),
                "max_concurrent_subscriptions": self.capability_registry.get_rate_limit("max_concurrent_subscriptions")
            }
        }
