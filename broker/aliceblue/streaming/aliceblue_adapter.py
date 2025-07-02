import threading
import json
import logging
import time
import websocket
import hashlib
import ssl
from typing import Dict, Any, Optional, List

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
        
        try:
            if auth_data:
                api_key = auth_data.get('api_key')
                session_id = auth_data.get('session_id')
                # For WebSocket auth, we need the simple client_id from env, not JWT token
                self.client_id = os.getenv('BROKER_API_KEY', api_key)
                # Store session_id for WebSocket authentication
                self.session_id = session_id
            else:
                # Fetch authentication tokens from database
                auth_token = get_auth_token(user_id)
                feed_token = get_feed_token(user_id)
                
                if not auth_token:
                    self.logger.error(f"No authentication tokens found for user {user_id}")
                    raise ValueError(f"No authentication tokens found for user {user_id}")
                    
                api_key = auth_token
                session_id = feed_token
                # For WebSocket auth, use BROKER_API_KEY from env, not the JWT token
                self.client_id = os.getenv('BROKER_API_KEY', user_id)
            
            # Store session_id for WebSocket authentication
            self.session_id = session_id
            
            # Initialize AliceBlue client
            self.aliceblue_client = Aliceblue(
                user_id=user_id,
                api_key=api_key,
                session_id=session_id
            )
            
            self.logger.info(f"AliceBlue WebSocket adapter initialized for user {user_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize AliceBlue adapter: {e}")
            raise
    
    def connect(self) -> bool:
        """
        Establish WebSocket connection
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            with self.lock:
                if self.running:
                    self.logger.warning("WebSocket already running")
                    return True
                
                self.running = True
                self.reconnect_attempts = 0
            
            # Create WebSocket session
            session_response = self.aliceblue_client.create_websocket_session()
            
            if session_response.get('stat') != 'Ok':
                self.logger.error(f"Failed to create WebSocket session: {session_response}")
                return False
            
            self.ws_session = session_response['result']['wsSess']
            self.logger.info(f"WebSocket session created: {self.ws_session}")
            
            # Start WebSocket connection
            success = self._start_websocket()
            
            if success:
                self.logger.info("AliceBlue WebSocket connected successfully")
                self._on_connect()
                return True
            else:
                self.logger.error("Failed to connect to AliceBlue WebSocket")
                with self.lock:
                    self.running = False
                return False
                
        except Exception as e:
            self.logger.error(f"Error connecting to AliceBlue WebSocket: {e}")
            with self.lock:
                self.running = False
            return False
    
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
            websocket.enableTrace(True)
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
            # Create authentication message - use session_id not ws_session
            susertoken = hashlib.sha256(
                hashlib.sha256(self.session_id.encode()).hexdigest().encode()
            ).hexdigest()
            
            auth_msg = {
                "susertoken": susertoken,
                "t": "c",
                "actid": f"{self.client_id}_API",
                "uid": f"{self.client_id}_API",
                "source": "API"
            }
            
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
            # Convert exchange to AliceBlue format
            ab_exchange = self.exchange_mapper.to_broker_exchange(exchange)
            
            # Get token for the symbol
            token = get_token(symbol, ab_exchange)
            if not token:
                self.logger.error(f"Token not found for {symbol} on {exchange}")
                return self._create_error_response("TOKEN_NOT_FOUND", f"Token not found for {symbol} on {exchange}")
            
            # Determine feed type based on mode
            feed_type = AliceBlueFeedType.DEPTH if mode == 3 else AliceBlueFeedType.MARKET_DATA
            
            # Create subscription message
            sub_msg = self.message_mapper.create_subscription_message(ab_exchange, token, feed_type)
            
            if self.ws_client and self.ws_client.sock and self.ws_client.sock.connected:
                self.ws_client.send(json.dumps(sub_msg))
                
                # Track subscription with more details for resubscription
                sub_key = f"{ab_exchange}|{token}"
                with self.lock:
                    self.subscriptions[sub_key] = {
                        'symbol': symbol,
                        'exchange': exchange,
                        'ab_exchange': ab_exchange,
                        'token': token,
                        'mode': mode,
                        'depth_level': depth_level
                    }
                
                self.logger.info(f"Subscribed to {symbol} ({ab_exchange}|{token}) for mode {mode}")
                return self._create_success_response(f"Subscribed to {symbol} on {exchange} for mode {mode}")
            else:
                self.logger.error("WebSocket not connected")
                return self._create_error_response("NOT_CONNECTED", "WebSocket not connected")
                
        except Exception as e:
            self.logger.error(f"Error subscribing to {symbol}: {e}")
            return self._create_error_response("SUBSCRIPTION_ERROR", str(e))
    
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
                        del self.subscriptions[sub_key]
                
                self.logger.info(f"Unsubscribed from {symbol} ({ab_exchange}|{token})")
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
            # Parse JSON message
            data = json.loads(message)
            
            # Handle different message types
            msg_type = data.get('t')
            
            if msg_type == 'ck':
                # Connection confirmation (current format)
                if data.get('s') == 'OK':
                    self.logger.info("WebSocket authentication successful")
                    self.connected = True
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
                # Acknowledgment message
                self.logger.debug(f"Received acknowledgment: {data}")
                return
            
            elif msg_type == 'tf':
                # Tick data
                parsed_data = self.message_mapper.parse_tick_data(data)
                if parsed_data.get('type') != 'error':
                    self._on_data_received(parsed_data)
                else:
                    self.logger.error(f"Error parsing tick data: {parsed_data['message']}")
            
            elif msg_type == 'df':
                # Depth data
                parsed_data = self.message_mapper.parse_depth_data(data)
                if parsed_data.get('type') != 'error':
                    self._on_data_received(parsed_data)
                else:
                    self.logger.error(f"Error parsing depth data: {parsed_data['message']}")
            
            else:
                self.logger.debug(f"Unknown message type: {msg_type}, data: {data}")
                
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
            # Extract symbol and exchange info
            symbol = parsed_data.get('symbol', 'UNKNOWN')
            exchange = parsed_data.get('exchange', 'UNKNOWN')
            mode = parsed_data.get('mode', 'LTP')
            
            # Create topic for ZMQ publishing
            topic = f"{exchange}_{symbol}_{mode}"
            
            # Add timestamp if not present
            if 'timestamp' not in parsed_data:
                parsed_data['timestamp'] = int(time.time() * 1000)
            
            # Publish to ZMQ
            self.publish_market_data(topic, parsed_data)
            
        except Exception as e:
            self.logger.error(f"Error processing received data: {e}")
    
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
