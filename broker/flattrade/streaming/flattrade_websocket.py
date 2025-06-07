# Flattrade WebSocket Client Blueprint (with more debugging)

import json
import websocket # Using websocket-client library
import threading
import time
import logging # Using Python's logging module

# --- IMPORTANT: Configure logging at the TOP of your main script ---
# import logging
# logging.basicConfig(level=logging.DEBUG) # Show all logs DEBUG and above
# This allows seeing logs from the websocket library too.
# --------------------------------------------------------------------

# Get a specific logger for this class
logger = logging.getLogger("FlattradeWebSocketClient")
# Ensure your main script's basicConfig sets a level that allows this logger's messages through
# For example, if basicConfig is DEBUG, this logger at INFO or DEBUG will show.
# If you want to control this logger's level independently:
# logger.setLevel(logging.DEBUG) 
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# ch = logging.StreamHandler()
# ch.setFormatter(formatter)
# logger.addHandler(ch)
# logger.propagate = False # Prevents duplicate logs if root logger is also configured

class FlattradeWebSocketClient:
    """
    A WebSocket client for Flattrade's streaming API.
    (Blueprint - with enhanced debugging)
    """

    WSS_URL = "wss://piconnect.flattrade.in/PiConnectWSTp/"
    SOURCE_API = "API"

    # Task types
    TASK_CONNECT = "c"
    TASK_SUBSCRIBE_TOUCHLINE = "t"
    TASK_UNSUBSCRIBE_TOUCHLINE = "u"
    TASK_SUBSCRIBE_DEPTH = "d"
    TASK_UNSUBSCRIBE_DEPTH = "ud"
    TASK_SUBSCRIBE_ORDER_UPDATE = "o"
    TASK_UNSUBSCRIBE_ORDER_UPDATE = "uo"

    # Message types
    TYPE_CONNECT_ACK = "ck"
    TYPE_TOUCHLINE_ACK = "tk"
    TYPE_UNSUBSCRIBE_TOUCHLINE_ACK = "uk"
    TYPE_DEPTH_ACK = "dk"
    TYPE_UNSUBSCRIBE_DEPTH_ACK = "udk"
    TYPE_ORDER_UPDATE_ACK = "ok"
    TYPE_UNSUBSCRIBE_ORDER_UPDATE_ACK = "uok"
    TYPE_TOUCHLINE_FEED = "tf"
    TYPE_DEPTH_FEED = "df"
    TYPE_ORDER_FEED = "om"


    def __init__(self, user_id: str, account_id: str, session_token: str, api_key: str = None):
        # If account_id is not provided, use user_id as account_id
        account_id = account_id or user_id
        
        logger.debug(f"Initializing FlattradeWebSocketClient with user_id: {user_id}, account_id: {account_id}")
        self.user_id = user_id
        self.account_id = account_id
        self.session_token = session_token
        self.api_key = api_key  # Store API key for authentication
        
        self.ws_app = None
        self.ws_thread = None
        self.is_connected = False  # Set to True when WebSocket is open
        self.is_authenticated = False  # Set to True when we receive a successful connection ack
        self.subscription_queue = []  # Queue to hold subscriptions until we're authenticated
        self.lock = threading.Lock()  # For thread safety
        
        logger.info(f"Initialized WebSocket client with user_id: {self.user_id}, account_id: {self.account_id}")

        # Callbacks
        self.on_open_callback = None
        self.on_close_callback = None
        self.on_error_callback = None
        self.on_message_callback = None 
        self.on_connect_ack_callback = None
        self.on_touchline_feed_callback = None
        self.on_depth_feed_callback = None
        self.on_order_update_feed_callback = None
        logger.debug("FlattradeWebSocketClient initialized.")

    def connect(self):
        logger.info("Attempting to connect WebSocket...")
        if self.ws_app and self.is_connected: # Check our client's connection view
            logger.info("Client believes it's already connected. Skipping connect.")
            return

        # --- CRITICAL FOR DEBUGGING ---
        websocket.enableTrace(True) 
        # This will print detailed logs from the websocket-client library itself.
        # -----------------------------

        self.ws_app = websocket.WebSocketApp(
            self.WSS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        logger.debug("WebSocketApp object created. Starting run_forever in a new thread.")
        # Added sslopt for potential SSL issues, common in some environments
        self.ws_thread = threading.Thread(target=lambda: self.ws_app.run_forever(sslopt={"check_hostname": False})) 
        self.ws_thread.daemon = True
        self.ws_thread.start()
        logger.info("WebSocket connection thread started.")

    def close(self):
        logger.info("Attempting to close WebSocket connection...")
        if self.ws_app:
            self.ws_app.close() # This should trigger _on_close
            logger.info("ws_app.close() called.")
        if self.ws_thread and self.ws_thread.is_alive():
            logger.debug("Joining WebSocket thread...")
            self.ws_thread.join(timeout=5)
            if self.ws_thread.is_alive():
                logger.warning("WebSocket thread did not terminate after join.")
            else:
                logger.debug("WebSocket thread terminated.")
        self.is_connected = False # Explicitly set our state

    def _send_json_message(self, payload: dict):
        if self.ws_app and self.is_connected: # Check our client's view of connection
            try:
                message_str = json.dumps(payload)
                logger.debug(f"Attempting to send message: {message_str}")
                self.ws_app.send(message_str)
                logger.info(f"Successfully sent message with task type: {payload.get('t')}")
            except Exception as e:
                logger.error(f"Error sending message: {e}", exc_info=True)
                if self.on_error_callback:
                    self.on_error_callback(self, e)
        else:
            logger.warning(f"WebSocket not connected (is_connected={self.is_connected}) or ws_app not initialized. Cannot send message: {payload.get('t')}")

    def _format_scrips(self, scrip_list: list) -> str:
        return "#".join(scrip_list)

    # --- Subscription Methods (logging added) ---
    def _execute_subscription(self, task_type, scrip_list=None, account_id=None):
        """Helper method to execute a subscription task."""
        if task_type == self.TASK_SUBSCRIBE_ORDER_UPDATE or task_type == self.TASK_UNSUBSCRIBE_ORDER_UPDATE:
            if not account_id:
                logger.error("account_id is required for order update subscriptions")
                return
            
            # For order updates, we only need 't' and 'actid' in the payload
            payload = {
                't': task_type,
                'actid': account_id
            }
            
            logger.info(f"Sending order update subscription payload: {payload}")
        else:
            payload = { 
                't': task_type, 
                'k': self._format_scrips(scrip_list) 
            }
            logger.info(f"Sending {task_type} for scrips: {scrip_list}")
        
        # Log the payload with sensitive data masked
        logged_payload = payload.copy()
        if 'susertoken' in logged_payload:
            logged_payload['susertoken'] = f"{logged_payload['susertoken'][:5]}...{logged_payload['susertoken'][-5:]}" if logged_payload['susertoken'] else ""
        if 'appkey' in logged_payload:
            logged_payload['appkey'] = f"{logged_payload['appkey'][:5]}...{logged_payload['appkey'][-5:]}" if logged_payload['appkey'] else ""
        logger.debug(f"Sending payload: {logged_payload}")
        
        self._send_json_message(payload)

    def subscribe_touchline(self, scrip_list: list):
        if not self._queue_subscription(self.subscribe_touchline, scrip_list):
            return
        self._execute_subscription(self.TASK_SUBSCRIBE_TOUCHLINE, scrip_list=scrip_list)

    def unsubscribe_touchline(self, scrip_list: list):
        if not self._queue_subscription(self.unsubscribe_touchline, scrip_list):
            return
        self._execute_subscription(self.TASK_UNSUBSCRIBE_TOUCHLINE, scrip_list=scrip_list)

    def subscribe_depth(self, scrip_list: list):
        if not self._queue_subscription(self.subscribe_depth, scrip_list):
            return
        self._execute_subscription(self.TASK_SUBSCRIBE_DEPTH, scrip_list=scrip_list)

    def unsubscribe_depth(self, scrip_list: list):
        if not self._queue_subscription(self.unsubscribe_depth, scrip_list):
            return
        self._execute_subscription(self.TASK_UNSUBSCRIBE_DEPTH, scrip_list=scrip_list)

    def subscribe_order_updates(self, account_id=None):
        # Ensure we have an account_id to use
        account_id = account_id or self.account_id
        if not account_id:
            logger.error("No account_id provided for order update subscription")
            return
            
        logger.info(f"Queueing order update subscription for account: {account_id}")
        if not self._queue_subscription(self.subscribe_order_updates, account_id=account_id):
            return
            
        logger.info(f"Executing order update subscription for account: {account_id}")
        self._execute_subscription(self.TASK_SUBSCRIBE_ORDER_UPDATE, account_id=account_id)

    def unsubscribe_order_updates(self, account_id=None):
        if not self._queue_subscription(self.unsubscribe_order_updates, account_id=account_id):
            return
        self._execute_subscription(self.TASK_UNSUBSCRIBE_ORDER_UPDATE, account_id=account_id or self.account_id)

    # --- WebSocket Event Handlers (_on_open, _on_message, etc.) ---
    def _on_open(self, ws):
        logger.info("WebSocket Event: _on_open triggered.")
        self.is_connected = True  # Set our state
        
        # Ensure user_id and account_id are set correctly
        if not self.user_id or self.user_id == 'root':
            logger.error("Invalid user_id detected. Cannot proceed with connection.")
            if self.on_error_callback:
                self.on_error_callback(self, Exception("Invalid user_id"))
            return
            
        # If account_id is not set or is 'root', use user_id as account_id
        if not self.account_id or self.account_id == 'root':
            self.account_id = self.user_id
            logger.warning(f"Using user_id '{self.user_id}' as account_id")
        
        connect_payload = {
            "t": self.TASK_CONNECT,
            "uid": self.user_id,
            "actid": self.account_id,
            "source": self.SOURCE_API,
            "susertoken": self.session_token,
            "appkey": self.api_key  # Required for authentication
        }
        
        # Log the payload with sensitive data masked
        logged_payload = connect_payload.copy()
        if 'susertoken' in logged_payload:
            logged_payload['susertoken'] = f"{logged_payload['susertoken'][:5]}...{logged_payload['susertoken'][-5:]}" if logged_payload['susertoken'] else ""
        if 'appkey' in logged_payload:
            logged_payload['appkey'] = f"{logged_payload['appkey'][:5]}...{logged_payload['appkey'][-5:]}" if logged_payload['appkey'] else ""
        
        logger.info(f"Sending connection payload: {logged_payload}")
        logger.info(f"Connecting with user_id: {self.user_id}, account_id: {self.account_id}")
        
        try:
            self._send_json_message(connect_payload)
            logger.info("Connection request sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send connection request: {e}", exc_info=True)
            if self.on_error_callback:
                self.on_error_callback(self, e)
        
        if self.on_open_callback:
            logger.debug("Calling user's on_open_callback.")
            try:
                self.on_open_callback(self)
            except Exception as e:
                logger.error(f"Error in user's on_open_callback: {e}", exc_info=True)
        
        logger.info("WebSocket Event: _on_open finished processing.")

    def _on_message(self, ws, message_str: str):
        logger.debug(f"WebSocket Event: _on_message triggered. Raw message string: '{message_str}'")
        
        try:
            message_data = json.loads(message_str)
            logger.info(f"Received and parsed message: {message_data}")
            
            # Handle different message types
            message_type = message_data.get('t')
            
            # Connection Acknowledgment
            if message_type == self.TYPE_CONNECT_ACK:
                status = message_data.get('s')
                logger.info(f"Connection acknowledgment received. Status: {status}")
                
                if status == 'OK':
                    self.is_authenticated = True
                    logger.info("Successfully connected and authenticated with Flattrade WebSocket server.")
                    
                    # Process any queued subscriptions
                    self._process_subscription_queue()
                else:
                    error_msg = message_data.get('emsg', 'No error message provided by server')
                    logger.error(f"Connection failed. Status: {status}, Error: {error_msg}")
                    if self.on_error_callback:
                        self.on_error_callback(self, Exception(f"Connection failed: {error_msg}"))
                
                if self.on_connect_ack_callback:
                    try:
                        self.on_connect_ack_callback(self, message_data)
                    except Exception as e:
                        logger.error(f"Error in on_connect_ack_callback: {e}", exc_info=True)
            
            # Touchline Feed
            elif message_type == self.TYPE_TOUCHLINE_FEED:
                logger.debug(f"Received Touchline Feed (type 'tf'): {message_data}")
                if self.on_touchline_feed_callback:
                    try:
                        self.on_touchline_feed_callback(self, message_data)
                    except Exception as e:
                        logger.error(f"Error in on_touchline_feed_callback: {e}", exc_info=True)
            
            # Depth Feed
            elif message_type == self.TYPE_DEPTH_FEED:
                logger.debug(f"Received Depth Feed (type 'df'): {message_data}")
                if self.on_depth_feed_callback:
                    try:
                        self.on_depth_feed_callback(self, message_data)
                    except Exception as e:
                        logger.error(f"Error in on_depth_feed_callback: {e}", exc_info=True)
            
            # Order Update Feed
            elif message_type == self.TYPE_ORDER_FEED:
                logger.debug(f"Received Order Feed (type 'om'): {message_data}")
                if self.on_order_update_feed_callback:
                    try:
                        self.on_order_update_feed_callback(self, message_data)
                    except Exception as e:
                        logger.error(f"Error in on_order_update_feed_callback: {e}", exc_info=True)
            
            # Handle order update subscription acknowledgment
            elif message_type == self.TYPE_ORDER_UPDATE_ACK:
                status = message_data.get('s', 'UNKNOWN')
                if status == 'OK':
                    logger.info(f"Successfully subscribed to order updates: {message_data}")
                    # Call the order update feed callback if set
                    if self.on_order_update_feed_callback:
                        try:
                            self.on_order_update_feed_callback(self, message_data)
                        except Exception as e:
                            logger.error(f"Error in on_order_update_feed_callback: {e}", exc_info=True)
                else:
                    error_msg = message_data.get('emsg', 'Unknown error')
                    logger.error(f"Failed to subscribe to order updates: {error_msg}")
                    if self.on_error_callback:
                        self.on_error_callback(self, Exception(f"Order update subscription failed: {error_msg}"))
            
            # Handle order update feed messages
            elif message_type == self.TYPE_ORDER_FEED:
                logger.debug(f"Received Order Feed (type 'om'): {message_data}")
                if self.on_order_update_feed_callback:
                    try:
                        self.on_order_update_feed_callback(self, message_data)
                    except Exception as e:
                        logger.error(f"Error in on_order_update_feed_callback: {e}", exc_info=True)
            
            # Handle other acknowledgment types
            elif message_type in [self.TYPE_TOUCHLINE_ACK, self.TYPE_UNSUBSCRIBE_TOUCHLINE_ACK, 
                                self.TYPE_DEPTH_ACK, self.TYPE_UNSUBSCRIBE_DEPTH_ACK,
                                self.TYPE_UNSUBSCRIBE_ORDER_UPDATE_ACK]:
                logger.info(f"Received Acknowledgment (type '{message_type}'): {message_data}")
                # Add specific ack callbacks if needed, or handle generally
            
            # Handle unknown message types
            else:
                logger.warning(f"Received message with unhandled type '{message_type}': {message_data}")
            
            # Call the general message callback if set
            if self.on_message_callback:
                try:
                    self.on_message_callback(self, message_data)
                except Exception as e:
                    logger.error(f"Error in on_message_callback: {e}", exc_info=True)
                
        except json.JSONDecodeError as e:
            error_msg = f"Failed to parse message as JSON: {message_str}"
            logger.error(error_msg, exc_info=True)
            if self.on_error_callback:
                try:
                    self.on_error_callback(self, Exception(error_msg))
                except Exception as callback_error:
                    logger.error(f"Error in on_error_callback: {callback_error}", exc_info=True)
        except Exception as e:
            error_msg = f"Error in _on_message: {e}"
            logger.error(error_msg, exc_info=True)
            if self.on_error_callback:
                try:
                    self.on_error_callback(self, Exception(error_msg))
                except Exception as callback_error:
                    logger.error(f"Error in on_error_callback: {callback_error}", exc_info=True)
        
        logger.debug("WebSocket Event: _on_message finished processing.")

    def _on_error(self, ws, error):
        # Note: [error](cci:1://file:///c:/Users/Karthik/Downloads/openalgo-main/broker/angel/streaming/smartWebSocketV2.py:493:4-494:12) can sometimes be an exception object, sometimes a string.
        logger.error(f"WebSocket Event: _on_error triggered. Error: {error}", exc_info=isinstance(error, Exception))
        self.is_connected = False # Assume connection is lost or problematic
        if self.on_error_callback:
            logger.debug("Calling user's on_error_callback.")
            try:
                self.on_error_callback(self, error)
            except Exception as e:
                logger.error(f"Error in user's on_error_callback (for WS error): {e}", exc_info=True)
        logger.debug("WebSocket Event: _on_error finished processing.")

    def _on_close(self, ws, close_status_code, close_msg):
        logger.info(f"WebSocket Event: _on_close triggered. Code: {close_status_code}, Msg: '{close_msg}'")
        self.is_connected = False  # Update our state
        self.is_authenticated = False
        
        # Clear any pending subscriptions on close
        with self.lock:
            if self.subscription_queue:
                logger.info(f"Clearing {len(self.subscription_queue)} pending subscriptions due to connection close")
                self.subscription_queue.clear()
        
        if self.on_close_callback:
            logger.debug("Calling user's on_close_callback.")
            try:
                self.on_close_callback(self, close_status_code, close_msg)
            except Exception as e:
                logger.error(f"Error in user's on_close_callback: {e}", exc_info=True)
                
    def _process_subscription_queue(self):
        """Process any subscriptions that were queued before authentication."""
        with self.lock:
            if not self.subscription_queue:
                return
                
            logger.info(f"Processing {len(self.subscription_queue)} queued subscriptions")
            for task in self.subscription_queue:
                try:
                    func, args, kwargs = task
                    logger.debug(f"Processing queued subscription: {func.__name__} with args={args}, kwargs={kwargs}")
                    func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Error processing queued subscription: {e}", exc_info=True)
            
            # Clear the queue after processing
            self.subscription_queue.clear()
    
    def _queue_subscription(self, func, *args, **kwargs):
        """Queue a subscription to be processed when the connection is ready."""
        with self.lock:
            if not self.is_authenticated:
                logger.info(f"Connection not authenticated. Queuing subscription: {func.__name__} with args={args}, kwargs={kwargs}")
                self.subscription_queue.append((func, args, kwargs))
                return False
        return True

    # --- Callback Setters ---
    def set_on_open_callback(self, callback_func): self.on_open_callback = callback_func
    def set_on_close_callback(self, callback_func): self.on_close_callback = callback_func
    def set_on_error_callback(self, callback_func): self.on_error_callback = callback_func
    def set_on_message_callback(self, callback_func): self.on_message_callback = callback_func
    def set_on_connect_ack_callback(self, callback_func): self.on_connect_ack_callback = callback_func
    def set_on_touchline_feed_callback(self, callback_func): self.on_touchline_feed_callback = callback_func
    def set_on_depth_feed_callback(self, callback_func): self.on_depth_feed_callback = callback_func
    def set_on_order_update_feed_callback(self, callback_func): self.on_order_update_feed_callback = callback_func
