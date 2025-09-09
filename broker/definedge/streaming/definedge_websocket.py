"""
DefinedGe Securities WebSocket client for real-time market data streaming.
Based on the pyintegrate library and DefinedGe WebSocket API documentation.
"""

import json
import threading
import time
import websocket
import ssl
import logging

logger = logging.getLogger(__name__)

class DefinedGeWebSocket:
    """DefinedGe Securities WebSocket client for real-time data streaming"""

    def __init__(self, auth_data):
        # Accept auth_data as dict (following Angel pattern)
        if isinstance(auth_data, dict):
            # Extract from dictionary
            auth_token = auth_data.get('auth_token', '')
            self.susertoken = auth_data.get('feed_token', '')  # feed_token contains susertoken
            self.uid = auth_data.get('uid', '')  # DefinEdge user ID
            self.actid = auth_data.get('actid', '')  # Account ID/UCC
            
            # Parse auth_token to get api_session_key
            if ":::" in auth_token:
                parts = auth_token.split(":::")
                self.api_session_key = parts[0] if len(parts) > 0 else ""
            else:
                self.api_session_key = auth_token
                
            # If actid is missing, use uid (they're same for DefinEdge)
            if self.uid and not self.actid:
                self.actid = self.uid
        else:
            # Backward compatibility - if auth_data is a string
            auth_token = auth_data
            if ":::" in auth_token:
                parts = auth_token.split(":::")
                self.api_session_key = parts[0] if len(parts) > 0 else ""
                self.susertoken = parts[1] if len(parts) > 1 else ""
                self.uid = ""
                self.actid = ""
            else:
                self.api_session_key = ""
                self.uid = ""
                self.actid = ""
                self.susertoken = auth_token

        # WebSocket connection
        self.ws = None
        self.ws_url = "wss://trade.definedgesecurities.com/NorenWSTRTP/"

        # Connection state
        self.connected = False
        self.authenticated = False
        self.should_reconnect = True  # Control auto-reconnect

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
        
        # Heartbeat management
        self.heartbeat_thread = None
        self.heartbeat_interval = 50  # 50 seconds as per API docs
        self.heartbeat_running = False

    def connect(self, ssl_verify=True):
        """Connect to DefinedGe WebSocket"""
        try:
            logger.info(f"Connecting to DefinedGe WebSocket at {self.ws_url}")

            # No headers required for initial connection per API docs
            self.ws = websocket.WebSocketApp(
                self.ws_url,
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
        """Disconnect from WebSocket and prevent reconnection"""
        try:
            # Disable auto-reconnect first
            self.should_reconnect = False
            
            # Stop heartbeat
            self.heartbeat_running = False
            if self.heartbeat_thread and self.heartbeat_thread.is_alive():
                self.heartbeat_thread.join(timeout=5)
            
            # Close WebSocket connection
            if self.ws:
                self.ws.close()
            
            # Reset connection state
            self.connected = False
            self.authenticated = False
            self.reconnect_attempts = 0
            
            # Clear subscriptions
            with self.subscription_lock:
                self.subscriptions.clear()
            
            logger.info("DefinedGe WebSocket disconnected and cleanup completed")
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

        # Only reconnect if should_reconnect is True (not manually disconnected)
        if self.should_reconnect and self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            logger.info(f"Attempting to reconnect... (attempt {self.reconnect_attempts})")
            time.sleep(self.reconnect_delay)
            self.connect()
        elif not self.should_reconnect:
            logger.info("Auto-reconnect disabled - not attempting reconnection")

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
            message_type = data.get('t', '')  # DefinEdge uses 't' for type

            # Handle different message types as per DefinEdge API
            if message_type == 'ck':  # Connect acknowledgement
                self._handle_auth_response(data)
            elif message_type == 'tk':  # Touchline acknowledgement
                self._handle_subscription_ack(data)
                # IMPORTANT: Also process as tick data to capture initial OHLC
                self._handle_tick_data(data)
            elif message_type == 'tf':  # Touchline feed
                self._handle_tick_data(data)
            elif message_type == 'dk':  # Depth acknowledgement
                self._handle_depth_ack(data)
                # IMPORTANT: Also process as depth data to capture initial OHLC
                self._handle_depth_data(data)
            elif message_type == 'df':  # Depth feed
                self._handle_depth_data(data)
            elif message_type == 'uk':  # Unsubscribe touchline acknowledgement
                self._handle_unsubscribe_ack(data)
            elif message_type == 'udk':  # Unsubscribe depth acknowledgement
                self._handle_unsubscribe_depth_ack(data)
            else:
                logger.debug(f"Unknown message type: {message_type}, data: {data}")

        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}, message: {message}")

    def _authenticate(self):
        """Authenticate WebSocket connection using DefinEdge format"""
        try:
            # Validate required fields
            if not self.uid or not self.susertoken:
                logger.error(f"Missing required auth fields - uid: {self.uid}, susertoken present: {bool(self.susertoken)}")
                return
            
            # Debug logging to see what we're sending
            logger.info(f"WebSocket Auth - uid: {self.uid}, actid: {self.actid}, susertoken length: {len(self.susertoken) if self.susertoken else 0}")
            
            # As per API docs, connect message format
            auth_message = {
                't': 'c',  # 'c' represents connect task
                'uid': self.uid,  # User ID
                'actid': self.actid,  # Account ID  
                'source': 'TRTP',  # Source should be TRTP
                'susertoken': self.susertoken  # User Session Token
            }

            logger.info(f"Sending auth message: t=c, uid={self.uid}, actid={self.actid}, source=TRTP")
            self.ws.send(json.dumps(auth_message))
            
            # Start heartbeat after authentication
            self._start_heartbeat()

        except Exception as e:
            logger.error(f"Error sending authentication: {e}")

    def _handle_auth_response(self, data):
        """Handle authentication response"""
        # As per API docs, 'ck' represents connect acknowledgement
        if data.get('t') == 'ck':
            status = data.get('s', '')
            if status == 'Ok' or status == 'OK':
                self.authenticated = True
                logger.info(f"WebSocket authentication successful for user: {data.get('uid', self.uid)}")
            else:
                # Log full response for debugging
                logger.error(f"WebSocket authentication failed. Status: {status}, Full response: {data}")
                # Check if there's an error message
                if 'emsg' in data:
                    logger.error(f"Error message: {data['emsg']}")
        else:
            logger.debug(f"Received auth-related message: {data}")

    def _handle_tick_data(self, data):
        """Handle tick data"""
        # Comprehensive logging to check OHLC presence
        token = data.get('tk')
        exchange = data.get('e')
        
        # Check all fields in the message
        logger.info(f"=== TICK DATA RECEIVED for {exchange}|{token} ===")
        logger.info(f"All fields in message: {list(data.keys())}")
        
        # Specifically check for OHLC fields
        ohlc_check = {
            'o (open)': data.get('o'),
            'h (high)': data.get('h'),
            'l (low)': data.get('l'),
            'c (close)': data.get('c'),
            'lp (ltp)': data.get('lp'),
            'v (volume)': data.get('v')
        }
        
        logger.info(f"OHLC field values: {ohlc_check}")
        
        # Check if any OHLC values are present and non-zero
        has_ohlc = any(data.get(field) not in [None, '', '0', 0] for field in ['o', 'h', 'l', 'c'])
        
        if has_ohlc:
            logger.info(f"✓ OHLC DATA PRESENT for {exchange}|{token}")
        else:
            logger.warning(f"✗ NO OHLC DATA for {exchange}|{token} - Broker not sending OHLC in touchline feed")
        
        # Log the complete raw message for debugging
        logger.debug(f"Full raw message: {data}")
        
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
    
    def _handle_subscription_ack(self, data):
        """Handle touchline subscription acknowledgement"""
        token = data.get('tk')
        exchange = data.get('e')
        
        logger.info(f"=== TOUCHLINE ACK for {exchange}|{token} ===")
        logger.info(f"All fields in acknowledgment: {list(data.keys())}")
        
        # Log raw acknowledgment for debugging
        logger.info(f"Raw ACK data: {json.dumps(data, indent=2)}")
        
        # Check what initial data we're getting
        initial_data = {
            'o (open)': data.get('o'),
            'h (high)': data.get('h'),
            'l (low)': data.get('l'),
            'c (close)': data.get('c'),
            'lp (ltp)': data.get('lp'),
            'v (volume)': data.get('v'),
            'pc (% change)': data.get('pc'),
            'ap (avg price)': data.get('ap')
        }
        
        logger.info(f"Initial data in ACK: {initial_data}")
        
        # Check if OHLC is provided in acknowledgment
        has_ohlc_in_ack = any(data.get(field) not in [None, '', '0', 0] for field in ['o', 'h', 'l', 'c'])
        
        if has_ohlc_in_ack:
            logger.info(f"✅ OHLC provided in subscription ACK for {exchange}|{token}")
        else:
            # Check current time to see if market is open
            import datetime
            now = datetime.datetime.now()
            market_open = now.replace(hour=9, minute=15, second=0)
            market_close = now.replace(hour=15, minute=30, second=0)
            
            if now < market_open or now > market_close:
                logger.warning(f"⏰ Market closed - No OHLC expected (Current: {now.strftime('%H:%M')})")
            else:
                logger.warning(f"⚠️ Market open but NO OHLC in ACK for {exchange}|{token}")
        
        logger.debug(f"Full ACK message: {data}")
        
    def _handle_depth_ack(self, data):
        """Handle depth subscription acknowledgement"""
        logger.info(f"Depth subscription acknowledged: {data.get('e')}|{data.get('tk')}")
        
    def _handle_unsubscribe_ack(self, data):
        """Handle touchline unsubscribe acknowledgement"""
        logger.info(f"Touchline unsubscribe acknowledged: {data.get('k')}")
        
    def _handle_unsubscribe_depth_ack(self, data):
        """Handle depth unsubscribe acknowledgement"""
        logger.info(f"Depth unsubscribe acknowledged: {data.get('k')}")
    
    def _start_heartbeat(self):
        """Start heartbeat thread to keep connection alive"""
        if self.heartbeat_running:
            return
            
        self.heartbeat_running = True
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        logger.info("Heartbeat thread started")
    
    def _heartbeat_loop(self):
        """Send heartbeat every 50 seconds to keep connection alive"""
        while self.heartbeat_running and self.connected:
            try:
                time.sleep(self.heartbeat_interval)
                if self.connected and self.ws:
                    heartbeat_msg = {"t": "h"}
                    self.ws.send(json.dumps(heartbeat_msg))
                    logger.debug("Heartbeat sent")
            except Exception as e:
                logger.error(f"Error sending heartbeat: {e}")

    def subscribe(self, subscription_type, tokens):
        """Subscribe to market data using DefinEdge format"""
        try:
            if not self.authenticated:
                logger.error("WebSocket not authenticated. Cannot subscribe.")
                return False

            with self.subscription_lock:
                # Build subscription key as per API: NSE|22#BSE|508123
                token_list = []
                for exchange, token in tokens:
                    token_list.append(f"{exchange}|{token}")
                
                subscription_key = "#".join(token_list)
                
                if subscription_type == self.SUBSCRIPTION_TYPE_TICK:
                    # Subscribe to touchline
                    subscribe_message = {
                        't': 't',  # 't' represents touchline task
                        'k': subscription_key  # Scrip list
                    }
                elif subscription_type == self.SUBSCRIPTION_TYPE_DEPTH:
                    # Subscribe to depth
                    subscribe_message = {
                        't': 'd',  # 'd' represents depth subscription
                        'k': subscription_key  # Scrip list
                    }
                else:
                    logger.warning(f"Unknown subscription type: {subscription_type}")
                    return False

                self.ws.send(json.dumps(subscribe_message))

                # Track subscriptions
                for exchange, token in tokens:
                    key = f"{exchange}:{token}"
                    if key not in self.subscriptions:
                        self.subscriptions[key] = set()
                    self.subscriptions[key].add(subscription_type)

                logger.info(f"Subscription request sent for {subscription_type}: {subscription_key}")
                return True

        except Exception as e:
            logger.error(f"Error subscribing: {e}")
            return False

    def unsubscribe(self, subscription_type, tokens):
        """Unsubscribe from market data using DefinEdge format"""
        try:
            if not self.authenticated:
                logger.error("WebSocket not authenticated. Cannot unsubscribe.")
                return False

            with self.subscription_lock:
                # Build subscription key as per API: NSE|22#BSE|508123
                token_list = []
                for exchange, token in tokens:
                    token_list.append(f"{exchange}|{token}")
                
                subscription_key = "#".join(token_list)
                
                if subscription_type == self.SUBSCRIPTION_TYPE_TICK:
                    # Unsubscribe from touchline
                    unsubscribe_message = {
                        't': 'u',  # 'u' represents Unsubscribe Touchline
                        'k': subscription_key  # Scrip list
                    }
                elif subscription_type == self.SUBSCRIPTION_TYPE_DEPTH:
                    # Unsubscribe from depth
                    unsubscribe_message = {
                        't': 'ud',  # 'ud' represents Unsubscribe depth
                        'k': subscription_key  # Scrip list
                    }
                else:
                    logger.warning(f"Unknown subscription type: {subscription_type}")
                    return False

                self.ws.send(json.dumps(unsubscribe_message))

                # Update subscription tracking
                for exchange, token in tokens:
                    key = f"{exchange}:{token}"
                    if key in self.subscriptions:
                        self.subscriptions[key].discard(subscription_type)
                        if not self.subscriptions[key]:
                            del self.subscriptions[key]

                logger.info(f"Unsubscribe request sent for {subscription_type}: {subscription_key}")
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
