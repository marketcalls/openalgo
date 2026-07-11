"""
DefinedGe Securities WebSocket client for real-time market data streaming.
Based on the pyintegrate library and DefinedGe WebSocket API documentation.
"""

import json
import logging
import ssl
import threading
import time

import websocket

logger = logging.getLogger(__name__)


class DefinedGeWebSocket:
    """DefinedGe Securities WebSocket client for real-time data streaming"""

    def __init__(self, auth_data, token_provider=None):
        # Optional callable that returns a fresh auth_data dict from the DB.
        # Used to refresh susertoken/api_session_key before each reconnect,
        # since DefinEdge (Noren) tokens roll over daily at ~3 AM IST.
        self.token_provider = token_provider

        # Accept auth_data as dict (following Angel pattern)
        if isinstance(auth_data, dict):
            # Extract from dictionary
            auth_token = auth_data.get("auth_token", "")
            self.susertoken = auth_data.get("feed_token", "")  # feed_token contains susertoken
            self.uid = auth_data.get("uid", "")  # DefinEdge user ID
            self.actid = auth_data.get("actid", "")  # Account ID/UCC

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

        # Heartbeat management. API docs allow up to 50s between heartbeats;
        # fleet norm is 30s (see flattrade) for faster silent-stall detection.
        self.heartbeat_thread = None
        self.heartbeat_interval = 30
        self.heartbeat_timeout = 120  # close socket if no message received for this long
        self.heartbeat_running = False
        self._last_message_time = None
        self._last_message_lock = threading.Lock()

        # WS-level ping keeps NAT/proxy paths alive between app heartbeats
        self.ping_interval = 30
        self.ping_timeout = 10

        # Reconnection is owned exclusively by the adapter (single owner,
        # see issue #1359) - this layer only reports close via on_disconnect.

    def _refresh_tokens(self):
        """Re-read fresh auth tokens from the DB via token_provider.

        Updates susertoken and api_session_key in place so a reconnect uses
        the current day's token. On failure the existing tokens are kept.
        """
        if not self.token_provider:
            return
        try:
            fresh = self.token_provider()
            if not fresh or not isinstance(fresh, dict):
                logger.warning(
                    "Could not fetch fresh tokens on reconnect; using existing tokens"
                )
                return

            auth_token = fresh.get("auth_token", "")
            susertoken = fresh.get("feed_token", "")

            if susertoken:
                self.susertoken = susertoken
            if auth_token:
                if ":::" in auth_token:
                    parts = auth_token.split(":::")
                    self.api_session_key = parts[0] if len(parts) > 0 else ""
                else:
                    self.api_session_key = auth_token
            logger.info("Refreshed DefinedGe auth tokens before reconnect")
        except Exception as e:
            logger.error(f"Error refreshing tokens before reconnect: {e}")

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
                on_close=self._on_close,
            )

            # Start WebSocket connection in a separate thread.
            # WS-level ping/pong detects dead connections between app heartbeats.
            self.ws_thread = threading.Thread(
                target=self.ws.run_forever,
                kwargs={
                    "sslopt": {"cert_reqs": ssl.CERT_NONE} if not ssl_verify else {},
                    "ping_interval": self.ping_interval,
                    "ping_timeout": self.ping_timeout,
                },
            )
            self.ws_thread.daemon = True
            self.ws_thread.start()

            # Wait for connection
            timeout = 10
            start_time = time.time()
            while not self.connected and (time.time() - start_time) < timeout:
                time.sleep(0.1)

            if not self.connected:
                # Clean up the orphaned socket/thread on timeout
                if self.ws:
                    self.ws.close()
                raise Exception("WebSocket connection timeout")

            logger.info("DefinedGe WebSocket connected successfully")
            return True

        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from WebSocket"""
        try:
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
        self._update_last_message_time()

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

        # Stop the heartbeat for this dead connection; a fresh one starts on
        # the next successful authenticate.
        self.heartbeat_running = False

        # Reconnection is owned by the adapter's on_disconnect handler - do
        # NOT reconnect here as well, or two competing retry loops each spawn
        # their own socket (issue #1359, dual reconnect).
        if self.on_disconnect:
            try:
                self.on_disconnect(self, close_status_code, close_msg)
            except Exception as e:
                logger.error(f"Error in on_disconnect callback: {e}")

    def _on_error(self, ws, error):
        """WebSocket error occurred"""
        logger.error(f"DefinedGe WebSocket error: {error}")

        if self.on_error:
            try:
                self.on_error(self, error)
            except Exception as e:
                logger.error(f"Error in on_error callback: {e}")

    def _update_last_message_time(self):
        """Record the time of the last received message for stall detection"""
        with self._last_message_lock:
            self._last_message_time = time.time()

    def _on_message(self, ws, message):
        """Process incoming WebSocket message"""
        self._update_last_message_time()
        try:
            data = json.loads(message)
            message_type = data.get("t", "")  # DefinEdge uses 't' for type

            # Handle different message types as per DefinEdge API
            if message_type == "ck":  # Connect acknowledgement
                self._handle_auth_response(data)
            elif message_type == "tk":  # Touchline acknowledgement
                self._handle_subscription_ack(data)
                # IMPORTANT: Also process as tick data to capture initial OHLC
                self._handle_tick_data(data)
            elif message_type == "tf":  # Touchline feed
                self._handle_tick_data(data)
            elif message_type == "dk":  # Depth acknowledgement
                self._handle_depth_ack(data)
                # IMPORTANT: Also process as depth data to capture initial OHLC
                self._handle_depth_data(data)
            elif message_type == "df":  # Depth feed
                self._handle_depth_data(data)
            elif message_type == "uk":  # Unsubscribe touchline acknowledgement
                self._handle_unsubscribe_ack(data)
            elif message_type == "udk":  # Unsubscribe depth acknowledgement
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
                logger.error(
                    f"Missing required auth fields - uid: {self.uid}, susertoken present: {bool(self.susertoken)}"
                )
                return

            # Debug logging to see what we're sending
            logger.info(
                f"WebSocket Auth - uid: {self.uid}, actid: {self.actid}, susertoken length: {len(self.susertoken) if self.susertoken else 0}"
            )

            # As per API docs, connect message format
            auth_message = {
                "t": "c",  # 'c' represents connect task
                "uid": self.uid,  # User ID
                "actid": self.actid,  # Account ID
                "source": "TRTP",  # Source should be TRTP
                "susertoken": self.susertoken,  # User Session Token
            }

            logger.info(
                f"Sending auth message: t=c, uid={self.uid}, actid={self.actid}, source=TRTP"
            )
            self.ws.send(json.dumps(auth_message))

            # Start heartbeat after authentication
            self._start_heartbeat()

        except Exception as e:
            logger.error(f"Error sending authentication: {e}")

    def _handle_auth_response(self, data):
        """Handle authentication response"""
        # As per API docs, 'ck' represents connect acknowledgement
        if data.get("t") == "ck":
            status = data.get("s", "")
            if status == "Ok" or status == "OK":
                self.authenticated = True
                logger.info(
                    f"WebSocket authentication successful for user: {data.get('uid', self.uid)}"
                )
            else:
                # Log full response for debugging
                logger.error(
                    f"WebSocket authentication failed. Status: {status}, Full response: {data}"
                )
                # Check if there's an error message
                if "emsg" in data:
                    logger.error(f"Error message: {data['emsg']}")
        else:
            logger.debug(f"Received auth-related message: {data}")

    def _handle_tick_data(self, data):
        """Handle tick data"""
        # Comprehensive logging to check OHLC presence
        token = data.get("tk")
        exchange = data.get("e")

        # Log tick data at debug level to avoid flooding logs
        logger.debug(f"Tick data for {exchange}|{token}: lp={data.get('lp')}, fields={list(data.keys())}")

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
        token = data.get("tk")
        exchange = data.get("e")

        logger.info(f"Touchline subscription acknowledged: {exchange}|{token}")
        logger.debug(f"ACK fields: {list(data.keys())}")
        logger.debug(f"Raw ACK data: {json.dumps(data, indent=2)}")

        # Check if OHLC is provided in acknowledgment
        has_ohlc_in_ack = any(
            data.get(field) not in [None, "", "0", 0] for field in ["o", "h", "l", "c"]
        )

        if has_ohlc_in_ack:
            logger.debug(f"OHLC provided in ACK for {exchange}|{token}")
        else:
            # Expected outside market hours and for illiquid scrips; the
            # touchline feed backfills OHLC once trades occur
            logger.debug(f"No OHLC in ACK for {exchange}|{token}")

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
        """Send app heartbeat every 30s and detect silently-stalled connections"""
        while self.heartbeat_running and self.connected:
            try:
                time.sleep(self.heartbeat_interval)
                if not (self.heartbeat_running and self.connected and self.ws):
                    break

                heartbeat_msg = {"t": "h"}
                self.ws.send(json.dumps(heartbeat_msg))
                logger.debug("Heartbeat sent")

                # Stall detection: if nothing has arrived for heartbeat_timeout,
                # the connection is silently dead - close it so the adapter's
                # on_disconnect handler reconnects.
                with self._last_message_lock:
                    last = self._last_message_time
                if last and (time.time() - last) > self.heartbeat_timeout:
                    logger.error(
                        f"No messages received for {self.heartbeat_timeout}s - closing stalled connection"
                    )
                    if self.ws:
                        self.ws.close()
                    break
            except Exception as e:
                logger.error(f"Error sending heartbeat: {e}")
                break

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
                        "t": "t",  # 't' represents touchline task
                        "k": subscription_key,  # Scrip list
                    }
                elif subscription_type == self.SUBSCRIPTION_TYPE_DEPTH:
                    # Subscribe to depth
                    subscribe_message = {
                        "t": "d",  # 'd' represents depth subscription
                        "k": subscription_key,  # Scrip list
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

                logger.info(
                    f"Subscription request sent for {subscription_type}: {subscription_key}"
                )
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
                        "t": "u",  # 'u' represents Unsubscribe Touchline
                        "k": subscription_key,  # Scrip list
                    }
                elif subscription_type == self.SUBSCRIPTION_TYPE_DEPTH:
                    # Unsubscribe from depth
                    unsubscribe_message = {
                        "t": "ud",  # 'ud' represents Unsubscribe depth
                        "k": subscription_key,  # Scrip list
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
    SUBSCRIPTION_TYPE_TICK = "tick"
    SUBSCRIPTION_TYPE_ORDER = "order"
    SUBSCRIPTION_TYPE_DEPTH = "depth"

    # Exchange constants
    EXCHANGE_TYPE_NSE = "NSE"
    EXCHANGE_TYPE_BSE = "BSE"
    EXCHANGE_TYPE_NFO = "NFO"
    EXCHANGE_TYPE_CDS = "CDS"
    EXCHANGE_TYPE_MCX = "MCX"
