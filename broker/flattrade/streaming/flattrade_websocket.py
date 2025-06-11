# Flattrade WebSocket Client Blueprint (with more debugging)

import json
import websocket
import threading
import logging

logger = logging.getLogger("FlattradeWebSocketClient")

class FlattradeWebSocketClient:
    """
    A WebSocket client for Flattrade's streaming API.
    (Blueprint - with enhanced debugging)
    """

    WSS_URL = "wss://piconnect.flattrade.in/PiConnectWSTp/"
    SOURCE_API = "API"

    # Task types and message types simplified (unused ones removed)
    TASK_CONNECT = "c"
    TASK_SUBSCRIBE_TOUCHLINE = "t"
    TASK_UNSUBSCRIBE_TOUCHLINE = "u"
    TASK_SUBSCRIBE_DEPTH = "d"
    TASK_UNSUBSCRIBE_DEPTH = "ud"
    # Order update subscription uses literal "o" in our adapter
    
    TYPE_CONNECT_ACK = "ck"
    TYPE_TOUCHLINE_FEED = "tf"
    TYPE_DEPTH_FEED = "df"
    TYPE_ORDER_FEED = "om"
    TYPE_ORDER_UPDATE_ACK = "ok"

    def __init__(self, user_id: str, account_id: str, session_token: str, api_key: str = None):
        # If account_id is not provided, use user_id as account_id
        account_id = account_id or user_id
        
        logger.debug(f"Initializing with user_id: {user_id}, account_id: {account_id}")
        self.user_id = user_id
        self.account_id = account_id
        self.session_token = session_token
        self.api_key = api_key  # Store API key for authentication
        
        self.ws_app = None
        self.ws_thread = None
        self.is_connected = False  # Set to True when WebSocket is open
        self.is_authenticated = False  # Set to True when we receive a successful connection ack
        
        logger.info(f"Initialized client; user_id: {self.user_id}, account_id: {self.account_id}")
        # Callback placeholders:
        self.on_open_callback = None
        self.on_close_callback = None
        self.on_error_callback = None
        self.on_message_callback = None 
        self.on_connect_ack_callback = None
        self.on_touchline_feed_callback = None
        self.on_depth_feed_callback = None
        self.on_order_update_feed_callback = None

    def connect(self):
        logger.info("Connecting WebSocket...")
        if self.ws_app and self.is_connected:
            logger.info("Already connected")
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
        logger.info("WebSocket thread started.")

    def close(self):
        logger.info("Closing WebSocket...")
        if self.ws_app:
            self.ws_app.close() # This should trigger _on_close
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
                message = json.dumps(payload)
                logger.debug(f"Sending: {message}")
                self.ws_app.send(message)
            except Exception as e:
                logger.error(f"Send error: {e}", exc_info=True)
                if self.on_error_callback:
                    self.on_error_callback(self, e)
        else:
            logger.warning("WebSocket not connected; message not sent.")

    def _execute_subscription(self, task_type, scrip_list=None, account_id=None):
        payload = {'t': task_type}
        if scrip_list:
            payload['k'] = "#".join(scrip_list)
        if account_id:
            payload['actid'] = account_id
        logger.info(f"Subscription payload: {payload}")
        self._send_json_message(payload)

    def subscribe_touchline(self, scrip_list: list):
        self._execute_subscription(self.TASK_SUBSCRIBE_TOUCHLINE, scrip_list=scrip_list)

    def unsubscribe_touchline(self, scrip_list: list):
        self._execute_subscription(self.TASK_UNSUBSCRIBE_TOUCHLINE, scrip_list=scrip_list)

    def subscribe_depth(self, scrip_list: list):
        self._execute_subscription(self.TASK_SUBSCRIBE_DEPTH, scrip_list=scrip_list)

    def unsubscribe_depth(self, scrip_list: list):
        self._execute_subscription(self.TASK_UNSUBSCRIBE_DEPTH, scrip_list=scrip_list)

    def subscribe_order_updates(self, account_id=None):
        account_id = account_id or self.account_id
        if not account_id:
            logger.error("No account_id for order updates")
            return
        logger.info(f"Subscribing to order updates for account: {account_id}")
        self._execute_subscription("o", account_id=account_id)

    def unsubscribe_order_updates(self, account_id=None):
        account_id = account_id or self.account_id
        logger.info(f"Unsubscribing order updates for account: {account_id}")
        # This method could be expanded similarly if needed.

    def _on_open(self, ws):
        logger.info("WebSocket open")
        self.is_connected = True
        # Ensure user_id and account_id are set correctly
        if not self.user_id or self.user_id == 'root':
            err = Exception("Invalid user_id")
            logger.error("Invalid user_id")
            if self.on_error_callback:
                self.on_error_callback(self, err)
            return
        # If account_id is not set or is 'root', use user_id as account_id
        if not self.account_id or self.account_id == 'root':
            self.account_id = self.user_id
            logger.warning("Using user_id as account_id")
        connect_payload = {
            "t": self.TASK_CONNECT,
            "uid": self.user_id,
            "actid": self.account_id,
            "source": self.SOURCE_API,
            "susertoken": self.session_token,
            "appkey": self.api_key
        }
        logger.info(f"Connection payload: {connect_payload}")
        try:
            self._send_json_message(connect_payload)
        except Exception as e:
            logger.error(f"Connection send failed: {e}", exc_info=True)
            if self.on_error_callback:
                self.on_error_callback(self, e)
        if self.on_open_callback:
            try:
                self.on_open_callback(self)
            except Exception as e:
                logger.error(f"on_open_callback error: {e}", exc_info=True)

    def _on_message(self, ws, message_str: str):
        logger.debug(f"Message received: {message_str}")
        try:
            message = json.loads(message_str)
            logger.info(f"Parsed message: {message}")
            msg_type = message.get('t')
            if msg_type == self.TYPE_CONNECT_ACK:
                if message.get('s') == 'OK':
                    self.is_authenticated = True
                    logger.info("Connection acknowledged")
                else:
                    err = message.get('emsg', 'Unknown error')
                    logger.error(f"Connection failed: {err}")
                    if self.on_error_callback:
                        self.on_error_callback(self, Exception(err))
                if self.on_connect_ack_callback:
                    self.on_connect_ack_callback(self, message)
            elif msg_type == self.TYPE_TOUCHLINE_FEED:
                if self.on_touchline_feed_callback:
                    self.on_touchline_feed_callback(self, message)
            elif msg_type == self.TYPE_DEPTH_FEED:
                if self.on_depth_feed_callback:
                    self.on_depth_feed_callback(self, message)
            elif msg_type == self.TYPE_ORDER_FEED:
                if self.on_order_update_feed_callback:
                    self.on_order_update_feed_callback(self, message)
            else:
                logger.warning(f"Unhandled message type: {msg_type}")
            if self.on_message_callback:
                self.on_message_callback(self, message)
        except Exception as e:
            logger.error(f"Error in _on_message: {e}", exc_info=True)
            if self.on_error_callback:
                self.on_error_callback(self, e)

    def _on_error(self, ws, error):
        logger.error(f"WebSocket error: {error}", exc_info=isinstance(error, Exception))
        self.is_connected = False
        if self.on_error_callback:
            self.on_error_callback(self, error)

    def _on_close(self, ws, close_status_code, close_msg):
        logger.info(f"WebSocket closed. Code: {close_status_code}, Msg: {close_msg}")
        self.is_connected = False
        if self.on_close_callback:
            self.on_close_callback(self, close_status_code, close_msg)

    # --- Callback Setters ---
    def set_on_open_callback(self, callback_func): self.on_open_callback = callback_func
    def set_on_close_callback(self, callback_func): self.on_close_callback = callback_func
    def set_on_error_callback(self, callback_func): self.on_error_callback = callback_func
    def set_on_message_callback(self, callback_func): self.on_message_callback = callback_func
    def set_on_connect_ack_callback(self, callback_func): self.on_connect_ack_callback = callback_func
    def set_on_touchline_feed_callback(self, callback_func): self.on_touchline_feed_callback = callback_func
    def set_on_depth_feed_callback(self, callback_func): self.on_depth_feed_callback = callback_func
    def set_on_order_update_feed_callback(self, callback_func): self.on_order_update_feed_callback = callback_func
