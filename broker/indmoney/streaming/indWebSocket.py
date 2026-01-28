import json
import logging
import os
import ssl
import time

import logzero
import websocket
from logzero import logger


class IndWebSocket:
    """
    INDmoney WebSocket Client for Real-time Market Data
    """

    # WebSocket endpoints
    PRICE_FEED_URI = "wss://ws-prices.indstocks.com/api/v1/ws/prices"
    ORDER_UPDATES_URI = "wss://ws-order-updates.indstocks.com"

    HEART_BEAT_MESSAGE = "ping"
    HEART_BEAT_INTERVAL = 30  # 30 seconds
    RESUBSCRIBE_FLAG = False

    # Available Actions
    SUBSCRIBE_ACTION = "subscribe"
    UNSUBSCRIBE_ACTION = "unsubscribe"

    # Subscription Modes
    LTP_MODE = "ltp"
    QUOTE_MODE = "quote"

    wsapp = None
    input_request_dict = {}
    current_retry_attempt = 0

    def __init__(
        self,
        access_token,
        max_retry_attempt=5,
        retry_strategy=0,
        retry_delay=10,
        retry_multiplier=2,
        retry_duration=60,
    ):
        """
        Initialize the IndWebSocket instance

        Parameters
        ----------
        access_token: string
            Access token from INDstocks authentication
        max_retry_attempt: int
            Maximum number of retry attempts on connection failure
        retry_strategy: int
            0 for simple retry, 1 for exponential backoff
        retry_delay: int
            Initial delay between retries in seconds
        retry_multiplier: int
            Multiplier for exponential backoff strategy
        retry_duration: int
            Maximum duration for retries in minutes
        """
        self.access_token = access_token
        self.DISCONNECT_FLAG = True
        self.last_pong_timestamp = None
        self.MAX_RETRY_ATTEMPT = max_retry_attempt
        self.retry_strategy = retry_strategy
        self.retry_delay = retry_delay
        self.retry_multiplier = retry_multiplier
        self.retry_duration = retry_duration

        # Create log folder based on current date
        log_folder = time.strftime("%Y-%m-%d", time.localtime())
        log_folder_path = os.path.join("logs", log_folder)
        os.makedirs(log_folder_path, exist_ok=True)
        log_path = os.path.join(log_folder_path, "indmoney_ws.log")
        logzero.logfile(log_path, loglevel=logging.INFO)

        if not self._sanity_check():
            logger.error("Invalid initialization parameters. Provide valid access token.")
            raise Exception("Provide valid access token")

    def _sanity_check(self):
        """Validate initialization parameters"""
        if not self.access_token:
            return False
        return True

    def _on_message(self, wsapp, message):
        """Handle incoming WebSocket messages"""
        # Log ALL messages including pings
        logger.info(f"<< WEBSOCKET MESSAGE RECEIVED: Type={type(message)}")

        # Only log full content for non-ping messages (avoid spam)
        if message != "pong":
            logger.info(f"   Content: {message}")

        # Handle heartbeat responses
        if message == "pong":
            logger.debug("[HEARTBEAT] Pong received")
            self.on_message(wsapp, message)
            self._on_pong(wsapp, message)
            return

        try:
            # Parse JSON message
            logger.info("[PARSING] Attempting to parse as JSON")
            parsed_message = json.loads(message)
            logger.info(f"[OK] JSON parsed: {parsed_message}")
            logger.info("[CALLBACK] Calling on_data with parsed message")
            self.on_data(wsapp, parsed_message)
        except json.JSONDecodeError as e:
            logger.error(f"[ERROR] Failed to parse JSON: {e}")
            logger.error(f"   Raw message: {message}")
            self.on_message(wsapp, message)

    def _on_data(self, wsapp, data, data_type, continue_flag):
        """Handle binary data (if any)"""
        if data_type == 2:  # Binary data
            try:
                parsed_message = json.loads(data)
                self.on_data(wsapp, parsed_message)
            except json.JSONDecodeError:
                logger.warning("Received binary data that couldn't be parsed")

    def _on_open(self, wsapp):
        """Handle WebSocket connection open event"""
        logger.info("WebSocket connection opened")
        if self.RESUBSCRIBE_FLAG:
            self.resubscribe()
        else:
            self.on_open(wsapp)

    def _on_pong(self, wsapp, data):
        """Handle pong response from heartbeat"""
        if data == "pong":
            timestamp = time.time()
            formatted_timestamp = time.strftime("%d-%m-%y %H:%M:%S", time.localtime(timestamp))
            logger.info(f"Heartbeat pong received, Timestamp: {formatted_timestamp}")
            self.last_pong_timestamp = timestamp

    def _on_ping(self, wsapp, data):
        """Handle ping from server"""
        timestamp = time.time()
        formatted_timestamp = time.strftime("%d-%m-%y %H:%M:%S", time.localtime(timestamp))
        logger.info(f"Ping received from server, Timestamp: {formatted_timestamp}")

    def subscribe(self, instruments, mode="ltp"):
        """
        Subscribe to market data for specified instruments

        Parameters
        ----------
        instruments: list of strings
            List of instrument tokens in format "SEGMENT:TOKEN"
            Examples: ["NSE:2885", "BSE:500325", "NFO:51011"]
        mode: string
            Subscription mode - "ltp" or "quote"
        """
        try:
            if mode not in [self.LTP_MODE, self.QUOTE_MODE]:
                error_message = f"Invalid mode: {mode}. Must be 'ltp' or 'quote'"
                logger.error(error_message)
                raise ValueError(error_message)

            request_data = {
                "action": self.SUBSCRIBE_ACTION,
                "mode": mode,
                "instruments": instruments,
            }

            # Log the subscription request for debugging
            logger.info(">> SENDING SUBSCRIPTION REQUEST:")
            logger.info(f"   Action: {request_data['action']}")
            logger.info(f"   Mode: {request_data['mode']}")
            logger.info(f"   Instruments: {request_data['instruments']}")
            logger.info(f"   Full JSON: {json.dumps(request_data)}")

            # Store subscription for reconnection
            if mode not in self.input_request_dict:
                self.input_request_dict[mode] = []

            # Add instruments to subscription list (avoid duplicates)
            for instrument in instruments:
                if instrument not in self.input_request_dict[mode]:
                    self.input_request_dict[mode].append(instrument)

            # Send subscription request
            if self.wsapp:
                self.wsapp.send(json.dumps(request_data))
                logger.info(f"[OK] Subscribed to {len(instruments)} instruments in {mode} mode")
                self.RESUBSCRIBE_FLAG = True
            else:
                logger.warning(
                    "[WARN] WebSocket not connected. Subscription will be applied on connect."
                )

        except Exception as e:
            logger.error(f"Error during subscribe: {e}")
            raise e

    def unsubscribe(self, instruments, mode="ltp"):
        """
        Unsubscribe from market data for specified instruments

        Parameters
        ----------
        instruments: list of strings
            List of instrument tokens to unsubscribe from
        mode: string
            Subscription mode - "ltp" or "quote"
        """
        try:
            request_data = {
                "action": self.UNSUBSCRIBE_ACTION,
                "mode": mode,
                "instruments": instruments,
            }

            # Remove from subscription list
            if mode in self.input_request_dict:
                for instrument in instruments:
                    if instrument in self.input_request_dict[mode]:
                        self.input_request_dict[mode].remove(instrument)

            # Send unsubscribe request
            if self.wsapp:
                self.wsapp.send(json.dumps(request_data))
                logger.info(f"Unsubscribed from {len(instruments)} instruments in {mode} mode")

        except Exception as e:
            logger.error(f"Error during unsubscribe: {e}")
            raise e

    def resubscribe(self):
        """Resubscribe to all previously subscribed instruments"""
        try:
            for mode, instruments in self.input_request_dict.items():
                if instruments:
                    request_data = {
                        "action": self.SUBSCRIBE_ACTION,
                        "mode": mode,
                        "instruments": instruments,
                    }
                    self.wsapp.send(json.dumps(request_data))
                    logger.info(f"Resubscribed to {len(instruments)} instruments in {mode} mode")
        except Exception as e:
            logger.error(f"Error during resubscribe: {e}")
            raise e

    def connect(self):
        """Establish WebSocket connection to price feed"""
        headers = {"Authorization": self.access_token}

        try:
            self.wsapp = websocket.WebSocketApp(
                self.PRICE_FEED_URI,
                header=headers,
                on_open=self._on_open,
                on_error=self._on_error,
                on_close=self._on_close,
                on_message=self._on_message,
                on_ping=self._on_ping,
                on_pong=self._on_pong,
            )

            logger.info("Connecting to INDmoney WebSocket...")
            self.wsapp.run_forever(
                sslopt={"cert_reqs": ssl.CERT_NONE},
                ping_interval=self.HEART_BEAT_INTERVAL,
                ping_payload=self.HEART_BEAT_MESSAGE,
            )

        except Exception as e:
            logger.error(f"Error during WebSocket connection: {e}")
            raise e

    def close_connection(self):
        """Close the WebSocket connection"""
        self.RESUBSCRIBE_FLAG = False
        self.DISCONNECT_FLAG = True
        if self.wsapp:
            self.wsapp.close()
            logger.info("WebSocket connection closed")

    def _on_error(self, wsapp, error):
        """Handle WebSocket errors with retry logic"""
        self.RESUBSCRIBE_FLAG = True
        logger.error(f"WebSocket error: {error}")

        if self.current_retry_attempt < self.MAX_RETRY_ATTEMPT:
            logger.warning(f"Attempting to reconnect (Attempt {self.current_retry_attempt + 1})...")
            self.current_retry_attempt += 1

            # Calculate delay based on retry strategy
            if self.retry_strategy == 0:  # Simple retry
                time.sleep(self.retry_delay)
            elif self.retry_strategy == 1:  # Exponential backoff
                delay = self.retry_delay * (
                    self.retry_multiplier ** (self.current_retry_attempt - 1)
                )
                time.sleep(delay)
            else:
                logger.error(f"Invalid retry strategy {self.retry_strategy}")
                raise Exception(f"Invalid retry strategy {self.retry_strategy}")

            try:
                self.close_connection()
                self.connect()
            except Exception as e:
                logger.error(f"Error during reconnect: {e}")
                if hasattr(self, "on_error"):
                    self.on_error("Reconnect Error", str(e) if str(e) else "Unknown error")
        else:
            self.close_connection()
            if hasattr(self, "on_error"):
                self.on_error("Max retry attempt reached", "Connection closed")

            if (
                self.retry_duration is not None
                and self.last_pong_timestamp is not None
                and time.time() - self.last_pong_timestamp > self.retry_duration * 60
            ):
                logger.warning("Connection closed due to inactivity.")
            else:
                logger.warning("Connection closed due to max retry attempts reached.")

    def _on_close(self, wsapp, close_status_code=None, close_msg=None):
        """Handle WebSocket connection close event"""
        logger.info(f"WebSocket closed. Status: {close_status_code}, Message: {close_msg}")
        self.on_close(wsapp)

    # Callback methods to be overridden by user
    def on_message(self, wsapp, message):
        """Override this method to handle text messages"""
        pass

    def on_data(self, wsapp, data):
        """Override this method to handle market data"""
        pass

    def on_close(self, wsapp):
        """Override this method to handle connection close"""
        pass

    def on_open(self, wsapp):
        """Override this method to handle connection open"""
        pass

    def on_error(self, wsapp, error):
        """Override this method to handle errors"""
        pass
