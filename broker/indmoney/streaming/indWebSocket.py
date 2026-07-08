import json
import ssl
import time

import websocket

from utils.logging import get_logger

logger = get_logger(__name__)


class IndWebSocket:
    """
    INDmoney WebSocket Client for Real-time Market Data
    """

    # WebSocket endpoints
    PRICE_FEED_URI = "wss://ws-prices.indstocks.com/api/v1/ws/prices"
    ORDER_UPDATES_URI = "wss://ws-order-updates.indstocks.com/api/v1/ws/trades"

    HEART_BEAT_MESSAGE = "ping"
    HEART_BEAT_INTERVAL = 30  # 30 seconds
    HEART_BEAT_TIMEOUT = 10  # seconds to wait for a pong before dropping the socket

    # Available Actions
    SUBSCRIBE_ACTION = "subscribe"
    UNSUBSCRIBE_ACTION = "unsubscribe"

    # Subscription Modes
    LTP_MODE = "ltp"
    QUOTE_MODE = "quote"

    # Subscription batching. INDstocks allows up to 3000 instruments per
    # connection; a single subscribe frame is chunked so a large subscription
    # (e.g. a full option chain) is split across several frames.
    MAX_INSTRUMENTS_PER_SUBSCRIBE = 1000
    MAX_INSTRUMENTS_PER_CONNECTION = 3000

    def __init__(
        self,
        access_token,
        max_retry_attempt=5,
        retry_strategy=0,
        retry_delay=10,
        retry_multiplier=2,
        retry_duration=60,
        token_provider=None,
    ):
        """
        Initialize the IndWebSocket instance

        Parameters
        ----------
        access_token: string
            Access token from INDstocks authentication
        token_provider: callable
            Optional zero-arg callable returning a fresh access token from the
            DB. Called before each reconnect so a daily-rolled token (~3 AM IST)
            is picked up instead of reusing the dead construction-time token.
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
        self.token_provider = token_provider
        self.DISCONNECT_FLAG = True
        self.last_pong_timestamp = None
        self.MAX_RETRY_ATTEMPT = max_retry_attempt
        self.retry_strategy = retry_strategy
        self.retry_delay = retry_delay
        self.retry_multiplier = retry_multiplier
        self.retry_duration = retry_duration

        # Per-instance state (previously class-level mutable attrs, which leaked
        # subscription state across users). Each client owns its own socket,
        # subscription list, retry counter and resubscribe flag.
        self.wsapp = None
        self.input_request_dict = {}
        self.current_retry_attempt = 0
        self.RESUBSCRIBE_FLAG = False

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

            if not instruments:
                return

            # Store subscription for reconnection (dedup)
            if mode not in self.input_request_dict:
                self.input_request_dict[mode] = []

            new_instruments = [
                i for i in instruments if i not in self.input_request_dict[mode]
            ]
            if not new_instruments:
                logger.debug(f"All {len(instruments)} instruments already subscribed in {mode} mode")
                return

            # Enforce the per-connection instrument cap
            current_total = sum(len(v) for v in self.input_request_dict.values())
            if current_total + len(new_instruments) > self.MAX_INSTRUMENTS_PER_CONNECTION:
                logger.error(
                    f"Cannot subscribe {len(new_instruments)} instruments: would exceed the "
                    f"{self.MAX_INSTRUMENTS_PER_CONNECTION}-instrument per-connection limit "
                    f"(currently {current_total})"
                )
                raise ValueError("Per-connection instrument limit exceeded")

            self.input_request_dict[mode].extend(new_instruments)

            # Send the subscription in chunks
            if self.wsapp:
                self._send_subscribe_chunks(new_instruments, mode)
                self.RESUBSCRIBE_FLAG = True
            else:
                logger.warning(
                    "[WARN] WebSocket not connected. Subscription will be applied on connect."
                )

        except Exception as e:
            logger.error(f"Error during subscribe: {e}")
            raise e

    def _send_subscribe_chunks(self, instruments, mode):
        """Send a subscribe request in chunks of MAX_INSTRUMENTS_PER_SUBSCRIBE."""
        if not self.wsapp:
            return
        total = len(instruments)
        for start in range(0, total, self.MAX_INSTRUMENTS_PER_SUBSCRIBE):
            chunk = instruments[start : start + self.MAX_INSTRUMENTS_PER_SUBSCRIBE]
            request_data = {
                "action": self.SUBSCRIBE_ACTION,
                "mode": mode,
                "instruments": chunk,
            }
            self.wsapp.send(json.dumps(request_data))
            logger.info(
                f"[OK] Subscribed to {len(chunk)} instruments in {mode} mode "
                f"(chunk {start // self.MAX_INSTRUMENTS_PER_SUBSCRIBE + 1}, {total} total)"
            )

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
        """Resubscribe to all previously subscribed instruments (chunked)."""
        try:
            for mode, instruments in self.input_request_dict.items():
                if instruments:
                    self._send_subscribe_chunks(instruments, mode)
                    logger.info(f"Resubscribed to {len(instruments)} instruments in {mode} mode")
        except Exception as e:
            logger.error(f"Error during resubscribe: {e}")
            raise e

    def _refresh_access_token(self):
        """Re-read a fresh access token from the DB via token_provider before a
        reconnect. Keeps the existing token if the provider yields nothing."""
        if not self.token_provider:
            return
        try:
            fresh = self.token_provider()
            if fresh:
                self.access_token = fresh
                logger.info("Refreshed INDmoney access token before reconnect")
            else:
                logger.warning(
                    "No fresh INDmoney access token available; reusing existing token"
                )
        except Exception as e:
            logger.error(f"Error refreshing access token: {e}")

    def connect(self):
        """Establish WebSocket connection to price feed"""
        headers = {"Authorization": self.access_token}

        # Close any existing socket first so we never leak an orphaned
        # run_forever/socket by overwriting self.wsapp.
        if self.wsapp is not None:
            try:
                self.wsapp.close()
            except Exception as e:
                logger.warning(f"Error closing previous WebSocket before reconnect: {e}")
            self.wsapp = None

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
            # ping_timeout (< ping_interval) lets websocket-client detect a
            # half-open connection and close the socket promptly instead of
            # holding the FD until the OS TCP timeout.
            self.wsapp.run_forever(
                sslopt={"cert_reqs": ssl.CERT_NONE},
                ping_interval=self.HEART_BEAT_INTERVAL,
                ping_timeout=self.HEART_BEAT_TIMEOUT,
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
            try:
                self.wsapp.close()
                logger.info("WebSocket connection closed")
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")
            finally:
                # Drop the reference so the socket/thread can be GC'd and a
                # later connect() starts clean.
                self.wsapp = None

    def _on_error(self, wsapp, error):
        """Handle WebSocket errors.

        This callback runs *inside* run_forever's dispatch, so it must NOT call
        connect()/run_forever() itself — doing so nested the run loops and
        stacked live sockets on every error. Reconnection is owned by the
        adapter (driven by the on_close callback); here we only flag the need
        to resubscribe and surface the error to the adapter.
        """
        self.RESUBSCRIBE_FLAG = True
        logger.error(f"WebSocket error: {error}")
        try:
            self.on_error(wsapp, error)
        except Exception as e:
            logger.error(f"Error in on_error callback: {e}")

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
