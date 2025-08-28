"""
DefinedGe Securities WebSocket client for real-time market data streaming.
Based on the pyintegrate library and DefinedGe WebSocket API documentation.
"""

import json
import threading
import time
import websocket
import ssl
from utils.logging import get_logger

logger = get_logger(__name__)

class DefinedGeWebSocket:
    """DefinedGe Securities WebSocket client for real-time data streaming"""

    def __init__(self, auth_token):
        self.auth_token = auth_token
        self.api_session_key, self.susertoken, self.api_token = auth_token.split(":::")

        # WebSocket connection
        self.ws = None
        self.ws_url = "wss://integrate.definedgesecurities.com/dart/v1/ws"

        # Connection state
        self.connected = False
        self.authenticated = False

        # Callbacks
        self.on_connect = None
        self.on_disconnect = None
        self.on_error = None
        self.on_tick = None
        self.on_order_update = None
        self.on_depth = None

        # Subscription tracking
        self.subscriptions = {}
        self.subscription_lock = threading.Lock()

        # Connection management
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5

    def connect(self, ssl_verify=True):
        """Connect to DefinedGe WebSocket"""
        try:
            logger.info("Connecting to DefinedGe WebSocket...")

            # WebSocket connection with authentication
            headers = {
                'Authorization': self.api_session_key,
                'susertoken': self.susertoken
            }

            if ssl_verify:
                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    header=headers,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )
            else:
                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    header=headers,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )

            # Start WebSocket connection in a separate thread
            self.ws_thread = threading.Thread(
                target=self.ws.run_forever,
                kwargs={'sslopt': {"cert_reqs": ssl.CERT_NONE} if not ssl_verify else {}}
            )
            self.ws_thread.daemon = True
            self.ws_thread.start()

            # Wait for connection
            timeout = 10
            start_time = time.time()
            while not self.connected and (time.time() - start_time) < timeout:
                time.sleep(0.1)

            if not self.connected:
                raise Exception("WebSocket connection timeout")

            logger.info("DefinedGe WebSocket connected successfully")
            return True

        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from WebSocket"""
        try:
            if self.ws:
                self.ws.close()
            self.connected = False
            self.authenticated = False
            logger.info("DefinedGe WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error disconnecting WebSocket: {e}")

    def _on_open(self, ws):
        """WebSocket connection opened"""
        logger.info("DefinedGe WebSocket connection opened")
        self.connected = True
        self.reconnect_attempts = 0

        # Authenticate after connection
        self._authenticate()

        if self.on_connect:
            try:
                self.on_connect(self)
            except Exception as e:
                logger.error(f"Error in on_connect callback: {e}")

    def _on_close(self, ws, close_status_code, close_msg):
        """WebSocket connection closed"""
        logger.info(f"DefinedGe WebSocket connection closed: {close_status_code} - {close_msg}")
        self.connected = False
        self.authenticated = False

        if self.on_disconnect:
            try:
                self.on_disconnect(self, close_status_code, close_msg)
            except Exception as e:
                logger.error(f"Error in on_disconnect callback: {e}")

        # Auto-reconnect logic
        if self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            logger.info(f"Attempting to reconnect... (attempt {self.reconnect_attempts})")
            time.sleep(self.reconnect_delay)
            self.connect()

    def _on_error(self, ws, error):
        """WebSocket error occurred"""
        logger.error(f"DefinedGe WebSocket error: {error}")

        if self.on_error:
            try:
                self.on_error(self, error)
            except Exception as e:
                logger.error(f"Error in on_error callback: {e}")

    def _on_message(self, ws, message):
        """Process incoming WebSocket message"""
        try:
            data = json.loads(message)
            message_type = data.get('type', '')

            if message_type == 'tick':
                self._handle_tick_data(data)
            elif message_type == 'order':
                self._handle_order_update(data)
            elif message_type == 'depth':
                self._handle_depth_data(data)
            elif message_type == 'ack':
                self._handle_acknowledgement(data)
            elif message_type == 'auth':
                self._handle_auth_response(data)
            else:
                logger.debug(f"Unknown message type: {message_type}")

        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")

    def _authenticate(self):
        """Authenticate WebSocket connection"""
        try:
            auth_message = {
                'type': 'auth',
                'api_session_key': self.api_session_key,
                'susertoken': self.susertoken
            }

            self.ws.send(json.dumps(auth_message))
            logger.info("Authentication message sent")

        except Exception as e:
            logger.error(f"Error sending authentication: {e}")

    def _handle_auth_response(self, data):
        """Handle authentication response"""
        if data.get('status') == 'success':
            self.authenticated = True
            logger.info("WebSocket authentication successful")
        else:
            logger.error(f"WebSocket authentication failed: {data.get('message', 'Unknown error')}")

    def _handle_tick_data(self, data):
        """Handle tick data"""
        if self.on_tick:
            try:
                self.on_tick(self, data)
            except Exception as e:
                logger.error(f"Error in on_tick callback: {e}")

    def _handle_order_update(self, data):
        """Handle order update"""
        if self.on_order_update:
            try:
                self.on_order_update(self, data)
            except Exception as e:
                logger.error(f"Error in on_order_update callback: {e}")

    def _handle_depth_data(self, data):
        """Handle market depth data"""
        if self.on_depth:
            try:
                self.on_depth(self, data)
            except Exception as e:
                logger.error(f"Error in on_depth callback: {e}")

    def _handle_acknowledgement(self, data):
        """Handle acknowledgement messages"""
        logger.debug(f"Received acknowledgement: {data}")

    def subscribe(self, subscription_type, tokens):
        """Subscribe to market data"""
        try:
            if not self.authenticated:
                logger.error("WebSocket not authenticated. Cannot subscribe.")
                return False

            with self.subscription_lock:
                subscribe_message = {
                    'type': 'subscribe',
                    'subscription_type': subscription_type,
                    'tokens': tokens
                }

                self.ws.send(json.dumps(subscribe_message))

                # Track subscriptions
                for exchange, token in tokens:
                    key = f"{exchange}:{token}"
                    if key not in self.subscriptions:
                        self.subscriptions[key] = set()
                    self.subscriptions[key].add(subscription_type)

                logger.info(f"Subscribed to {subscription_type} for {len(tokens)} tokens")
                return True

        except Exception as e:
            logger.error(f"Error subscribing: {e}")
            return False

    def unsubscribe(self, subscription_type, tokens):
        """Unsubscribe from market data"""
        try:
            if not self.authenticated:
                logger.error("WebSocket not authenticated. Cannot unsubscribe.")
                return False

            with self.subscription_lock:
                unsubscribe_message = {
                    'type': 'unsubscribe',
                    'subscription_type': subscription_type,
                    'tokens': tokens
                }

                self.ws.send(json.dumps(unsubscribe_message))

                # Update subscription tracking
                for exchange, token in tokens:
                    key = f"{exchange}:{token}"
                    if key in self.subscriptions:
                        self.subscriptions[key].discard(subscription_type)
                        if not self.subscriptions[key]:
                            del self.subscriptions[key]

                logger.info(f"Unsubscribed from {subscription_type} for {len(tokens)} tokens")
                return True

        except Exception as e:
            logger.error(f"Error unsubscribing: {e}")
            return False

    def get_subscriptions(self):
        """Get current subscriptions"""
        with self.subscription_lock:
            return dict(self.subscriptions)

    def is_connected(self):
        """Check if WebSocket is connected"""
        return self.connected and self.authenticated

    # Subscription type constants (matching pyintegrate)
    SUBSCRIPTION_TYPE_TICK = 'tick'
    SUBSCRIPTION_TYPE_ORDER = 'order'
    SUBSCRIPTION_TYPE_DEPTH = 'depth'

    # Exchange constants
    EXCHANGE_TYPE_NSE = 'NSE'
    EXCHANGE_TYPE_BSE = 'BSE'
    EXCHANGE_TYPE_NFO = 'NFO'
    EXCHANGE_TYPE_CDS = 'CDS'
    EXCHANGE_TYPE_MCX = 'MCX'
