"""
RMoney XTS WebSocket Client for Market Data Streaming

XTS API Market Data Streaming:
- Authentication: POST /auth/login with appKey and secretKey
- WebSocket: Socket.IO connection with token and userID
- Message Codes: 1501 (Touchline), 1502 (MarketDepth), 1505 (CandleData), 1510 (OpenInterest)

Exchange Segments (Numeric):
- NSECM = 1 (NSE Cash Market)
- NSEFO = 2 (NSE F&O)
- NSECD = 3 (NSE Currency Derivatives)
- BSECM = 11 (BSE Cash Market)
- BSEFO = 12 (BSE F&O)
- MCXFO = 51 (MCX F&O)
"""

import json
import logging
import struct
from typing import Dict, List
from urllib.parse import urlencode

import requests
import socketio

from broker.rmoney.baseurl import MARKET_DATA_BASE_URL


class RMoneyWebSocketClient:
    """
    RMoney XTS Socket.IO client for market data streaming.

    Uses the XTS Binary Market Data API for real-time market data.
    """

    # Socket.IO configuration
    # Use the JSON market data API path for proper JSON event streaming.
    # The binary path (/apibinarymarketdata) sends raw binary packets that require
    # complex struct parsing. The JSON path sends proper JSON via events like
    # 1501-json-full, 1502-json-full which are already handled.
    SOCKET_PATH = "/apimarketdata/socket.io"
    API_ROOT_PATH = "/apimarketdata"
    # Engine.IO write-loop timeout floor to avoid premature
    # "packet queue is empty, aborting" disconnects on quiet streams.
    MIN_ENGINEIO_ACTIVITY_TIMEOUT = 300

    # Subscription modes (mapped to XTS message codes)
    MODE_LTP = 1       # Last Traded Price - maps to 1501 (Touchline)
    MODE_QUOTE = 2     # Full Quote - maps to 1501
    MODE_DEPTH = 3     # Market Depth - maps to 1502

    # XTS Message Codes
    XTS_MESSAGE_CODES = {
        "TOUCHLINE": 1501,      # Touchline/Quote data
        "MARKET_DEPTH": 1502,   # Market depth (5 levels)
        "CANDLE_DATA": 1505,    # Candle/OHLC data
        "OPEN_INTEREST": 1510,  # Open interest
        # Symphony market-data spec primarily documents 1501 for touchline
        # (includes LTP), so LTP mode maps to touchline for compatibility.
        "LTP": 1501,
    }

    # Mode to XTS message code mapping
    MODE_TO_XTS_CODE = {
        # Symphony market-data doc: Touchline=1501, MarketDepth=1502.
        # Use 1501 for both LTP and Quote to ensure reliable streaming.
        1: 1501,  # LTP mode -> Touchline message
        2: 1501,  # Quote mode -> Touchline message
        3: 1502,  # Depth mode -> Market Depth message
    }

    # Exchange segments
    EXCHANGE_SEGMENTS = {
        "NSECM": 1,    # NSE Cash Market
        "NSEFO": 2,    # NSE Futures & Options
        "NSECD": 3,    # NSE Currency Derivatives
        "BSECM": 11,   # BSE Cash Market
        "BSEFO": 12,   # BSE Futures & Options
        "MCXFO": 51,   # MCX Futures & Options
    }

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        user_id: str,
        base_url: str = None,
    ):
        """
        Initialize the RMoney XTS Socket.IO client.

        Args:
            api_key: Market data API key (appKey)
            api_secret: Market data API secret (secretKey)
            user_id: User ID (client ID)
            base_url: Base URL for the API endpoints (optional)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.user_id = user_id
        self.base_url = (base_url or MARKET_DATA_BASE_URL).rstrip("/")

        # Dynamic market data API endpoints (avoid hardcoded BASE_URL binding)
        self.login_url = f"{self.base_url}{self.API_ROOT_PATH}/auth/login"
        self.subscription_url = (
            f"{self.base_url}{self.API_ROOT_PATH}/instruments/subscription"
        )

        # Authentication tokens
        self.market_data_token = None
        self.feed_token = None
        self.actual_user_id = None
        self.app_version = None
        self.expiry_date = None

        # Connection state
        self.sio = None
        self.connected = False
        self.running = False

        # Callbacks
        self.on_open = None
        self.on_close = None
        self.on_error = None
        self.on_data = None
        self.on_message = None

        # Logger
        self.logger = logging.getLogger("rmoney_websocket")

        # Subscriptions tracking
        self.subscriptions = {}
        self._binary_packet_seen = False

        # Reusable HTTP session for connection pooling (avoids FD churn)
        self._http_session = requests.Session()

        # Initialize Socket.IO client
        self._setup_socketio()

    def _setup_socketio(self):
        """Setup Socket.IO client with event handlers."""
        # Create Socket.IO client
        # IMPORTANT: Disable built-in reconnection - the adapter handles
        # reconnection via _on_close -> _connect_with_retry to avoid
        # race conditions between dual reconnection mechanisms.
        # Note: ping timeout/interval options are not accepted by
        # python-engineio client constructor, so keepalive tuning is
        # applied after connect via _apply_engineio_timeout_floor().
        self.sio = socketio.Client(
            logger=False,
            engineio_logger=False,
            reconnection=False,
        )

        # Pre-set Engine.IO ping timers so the write loop's first cycle
        # uses a safe timeout instead of the server's potentially low value.
        # This prevents "packet queue is empty, aborting" on the first cycle.
        if hasattr(self.sio, 'eio'):
            self.sio.eio.ping_interval = max(getattr(self.sio.eio, 'ping_interval', 0) or 0, 295)
            self.sio.eio.ping_timeout = max(getattr(self.sio.eio, 'ping_timeout', 0) or 0, 295)

        # Register connection event handlers
        self.sio.on("connect", self._on_connect)
        self.sio.on("disconnect", self._on_disconnect)
        self.sio.on("connect_error", self._on_connect_error)
        self.sio.on("message", self._on_message_handler)
        self.sio.on("joined", self._on_joined)  # XTS sends "joined" event after connection

        # Register XTS message handlers for different market data types
        # Touchline/Quote data (1501)
        self.sio.on("1501-json-full", self._on_touchline_full)
        self.sio.on("1501-json-partial", self._on_touchline_partial)

        # Market Depth data (1502)
        self.sio.on("1502-json-full", self._on_depth_full)
        self.sio.on("1502-json-partial", self._on_depth_partial)

        # Candle/OHLC data (1505)
        self.sio.on("1505-json-full", self._on_candle_full)
        self.sio.on("1505-json-partial", self._on_candle_partial)

        # Open Interest data (1510)
        self.sio.on("1510-json-full", self._on_oi_full)
        self.sio.on("1510-json-partial", self._on_oi_partial)

        # LTP data (1512)
        self.sio.on("1512-json-full", self._on_ltp_full)
        self.sio.on("1512-json-partial", self._on_ltp_partial)

        # Binary market data (1105) - legacy format
        self.sio.on("1105-json-partial", self._on_binary_partial)
        self.sio.on("1105-json-full", self._on_binary_full)
        # Some XTS servers publish ticks via this binary socket event.
        self.sio.on("xts-binary-packet", self._on_xts_binary_packet)
        self.logger.info("[SETUP] Registered xts-binary-packet handler")

        # Catch-all handler for unhandled events
        self.sio.on("*", self._on_catch_all)

    def _apply_engineio_timeout_floor(self) -> None:
        """
        Increase Engine.IO ping timers if server-provided values are too low.

        python-engineio's write loop aborts when its send queue is idle for:
            max(ping_interval, ping_timeout) + 5 seconds
        On some broker endpoints this can be too aggressive and causes
        transient disconnects with "packet queue is empty, aborting".
        """
        try:
            if not self.sio or not getattr(self.sio, "eio", None):
                return

            eio_client = self.sio.eio
            current_interval = float(getattr(eio_client, "ping_interval", 0) or 0)
            current_timeout = float(getattr(eio_client, "ping_timeout", 0) or 0)
            current_activity_timeout = max(current_interval, current_timeout) + 5

            if current_activity_timeout >= self.MIN_ENGINEIO_ACTIVITY_TIMEOUT:
                self.logger.info(
                    "[SOCKET.IO] Engine.IO activity timeout already sufficient: "
                    f"{current_activity_timeout:.0f}s"
                )
                return

            target = max(1, self.MIN_ENGINEIO_ACTIVITY_TIMEOUT - 5)
            eio_client.ping_interval = max(current_interval, target)
            eio_client.ping_timeout = max(current_timeout, target)

            new_activity_timeout = max(eio_client.ping_interval, eio_client.ping_timeout) + 5
            self.logger.info(
                "[SOCKET.IO] Applied Engine.IO timeout floor: "
                f"{current_activity_timeout:.0f}s -> {new_activity_timeout:.0f}s"
            )
        except Exception as e:
            self.logger.warning(f"[SOCKET.IO] Failed to apply Engine.IO timeout floor: {e}")

    def marketdata_login(self) -> bool:
        """
        Login to XTS market data API to get authentication tokens.

        API: POST /auth/login
        Request: {"secretKey": "...", "appKey": "..."}
        Response: {"type": "success", "result": {"token": "...", "userID": "..."}}

        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            # Prepare login payload as per XTS API docs
            login_payload = {
                "secretKey": self.api_secret,
                "appKey": self.api_key,
            }

            headers = {"Content-Type": "application/json"}

            self.logger.info(f"[MARKET DATA LOGIN] Attempting login to: {self.login_url}")

            response = self._http_session.post(
                self.login_url,
                json=login_payload,
                headers=headers,
                timeout=30
            )
            try:
                if response.status_code == 200:
                    result = response.json()
                    self.logger.debug(f"[MARKET DATA LOGIN] Response: {result}")

                    if result.get("type") == "success":
                        login_result = result.get("result", {})
                        self.market_data_token = login_result.get("token")
                        self.actual_user_id = login_result.get("userID")
                        self.app_version = login_result.get("appVersion")
                        self.expiry_date = login_result.get("application_expiry_date")

                        if self.market_data_token and self.actual_user_id:
                            self.logger.info(
                                f"[MARKET DATA LOGIN] Success! UserID: {self.actual_user_id}"
                            )
                            return True
                        else:
                            self.logger.error("[MARKET DATA LOGIN] Missing token or userID in response")
                            return False
                    else:
                        self.logger.error(f"[MARKET DATA LOGIN] API returned error: {result}")
                        return False
                else:
                    self.logger.error(
                        f"[MARKET DATA LOGIN] HTTP Error: {response.status_code}, Response: {response.text}"
                    )
                    return False
            finally:
                response.close()

        except requests.exceptions.Timeout:
            self.logger.error("[MARKET DATA LOGIN] Request timeout")
            return False
        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"[MARKET DATA LOGIN] Connection error: {e}")
            return False
        except Exception as e:
            self.logger.error(f"[MARKET DATA LOGIN] Exception: {e}")
            return False

    def connect(self) -> None:
        """
        Establish Socket.IO connection with proper authentication.

        Connection URL format:
        {BASE_URL}/?token={token}&userID={userID}&publishFormat=<format>&broadcastMode=<mode>
        """
        try:
            # Disconnect and discard old Socket.IO client to clear stale state
            # (prevents 'packet queue is empty' from leftover ping/pong timers)
            if self.sio:
                try:
                    if self.sio.connected:
                        self.sio.disconnect()
                except Exception:
                    pass
                # Force-kill Engine.IO transport to release its FD and threads
                try:
                    eio = getattr(self.sio, "eio", None)
                    if eio and hasattr(eio, "disconnect"):
                        eio.disconnect(abort=True)
                except Exception:
                    pass
                self.sio = None
                self.connected = False

            # Create fresh Socket.IO client to avoid stale internal state
            saved_subscriptions = self.subscriptions
            self._setup_socketio()
            self.subscriptions = saved_subscriptions

            # Login to get authentication tokens
            if not self.marketdata_login():
                raise Exception("Market data login failed - check API credentials")

            # Build connection URL with authentication parameters
            connection_params = {
                "token": self.market_data_token,
                "userID": self.actual_user_id,
                "publishFormat": "JSON",
                "broadcastMode": "Full",
            }

            # Build query string
            query_string = urlencode(connection_params)
            connection_url = f"{self.base_url}/?{query_string}"

            self.logger.info(f"[SOCKET.IO] Connecting to: {self.base_url}{self.SOCKET_PATH}")

            # Connect to Socket.IO server
            self.sio.connect(
                connection_url,
                headers={},
                transports=["websocket"],
                namespaces=None,
                socketio_path=self.SOCKET_PATH,
                wait_timeout=10,
            )

            self.running = True
            self.logger.info("[SOCKET.IO] Connection initiated successfully")

        except Exception as e:
            self.logger.error(f"[SOCKET.IO] Connection failed: {e}")
            if self.on_error:
                self.on_error(self, e)
            raise

    def disconnect(self) -> None:
        """Disconnect from Socket.IO server."""
        self.running = False
        self.connected = False

        if self.sio:
            try:
                if self.sio.connected:
                    self.sio.disconnect()
                    self.logger.info("[SOCKET.IO] Disconnected successfully")
            except Exception as e:
                self.logger.warning(f"[SOCKET.IO] Error during disconnect: {e}")
            # Force-kill Engine.IO transport to release its FD and threads
            try:
                eio = getattr(self.sio, "eio", None)
                if eio and hasattr(eio, "disconnect"):
                    eio.disconnect(abort=True)
            except Exception:
                pass
            self.sio = None

        # Clear subscriptions
        self.subscriptions.clear()

    def close(self) -> None:
        """Full teardown: disconnect Socket.IO and release HTTP session."""
        self.disconnect()
        if self._http_session:
            self._http_session.close()
            self.logger.info("[CLEANUP] HTTP session closed")

    def subscribe(self, correlation_id: str, mode: int, instruments: List[Dict]) -> None:
        """
        Subscribe to market data using XTS HTTP API.

        API: POST /instruments/subscription
        Request: {"instruments": [...], "xtsMessageCode": code}

        Args:
            correlation_id: Unique identifier for this subscription
            mode: Subscription mode (1=LTP, 2=Quote, 3=Depth)
            instruments: List of instruments to subscribe
                [{"exchangeSegment": 1, "exchangeInstrumentID": 2885}, ...]
        """
        if not self.connected:
            raise RuntimeError("Socket.IO not connected")

        # Map mode to XTS message code
        xts_message_code = self.MODE_TO_XTS_CODE.get(mode, self.XTS_MESSAGE_CODES["TOUCHLINE"])

        # Prepare subscription request as per API docs
        subscription_request = {
            "instruments": instruments,
            "xtsMessageCode": xts_message_code,
        }

        # Store subscription for reconnection
        self.subscriptions[correlation_id] = {
            "mode": mode,
            "instruments": instruments,
            "xts_message_code": xts_message_code,
        }

        # Send subscription via HTTP POST
        try:
            headers = {
                "authorization": self.market_data_token,
                "Content-Type": "application/json",
            }

            self.logger.info(
                f"[SUBSCRIBE] Code: {xts_message_code}, Instruments: {len(instruments)}"
            )

            response = self._http_session.post(
                self.subscription_url,
                json=subscription_request,
                headers=headers,
                timeout=10,
            )
            try:
                if response.status_code == 200:
                    result = response.json()
                    self.logger.debug(f"[SUBSCRIBE] Response: {result}")
                    if result.get("type") != "success":
                        error_desc = result.get("description") or result.get("message") or str(result)
                        self.logger.error(f"[SUBSCRIBE] API error response: {error_desc}")
                        raise RuntimeError(error_desc)

                    # Process initial quote data if available
                    if "result" in result:
                        list_quotes = result["result"].get("listQuotes", [])
                        self.logger.info(
                            f"[SUBSCRIBE] Initial quote payload count: {len(list_quotes)} for code {xts_message_code}"
                        )
                        for quote_str in list_quotes:
                            try:
                                quote_data = (
                                    json.loads(quote_str) if isinstance(quote_str, str) else quote_str
                                )
                                self.logger.debug(f"[INITIAL QUOTE] {quote_data}")
                                if isinstance(quote_data, dict) and "MessageCode" not in quote_data:
                                    quote_data["MessageCode"] = xts_message_code
                                if self.on_data:
                                    self.on_data(self, quote_data)
                            except json.JSONDecodeError as e:
                                self.logger.error(f"[INITIAL QUOTE] Parse error: {e}")

                    self.logger.info(
                        f"[SUBSCRIBE] Success - {len(instruments)} instruments, code {xts_message_code}"
                    )
                else:
                    error_msg = f"[SUBSCRIBE] Failed - Status: {response.status_code}, Response: {response.text}"
                    # "Instrument Already Subscribed" is non-fatal (expected after reconnect)
                    if "Already Subscribed" in response.text or "e-session-0002" in response.text:
                        self.logger.info(f"[SUBSCRIBE] Instrument already subscribed (non-fatal)")
                        return
                    # Handle Invalid Token by re-authenticating and retrying once.
                    # This happens when data.py refreshes the feed token, which creates
                    # a new market data session and invalidates our current token.
                    if "Invalid Token" in response.text or "e-session-0007" in response.text:
                        self.logger.warning(
                            "[SUBSCRIBE] Token invalidated (likely by feed token refresh). Re-authenticating..."
                        )
                        if self.marketdata_login():
                            # Retry with new token
                            retry_headers = {
                                "authorization": self.market_data_token,
                                "Content-Type": "application/json",
                            }
                            retry_response = self._http_session.post(
                                self.subscription_url,
                                json=subscription_request,
                                headers=retry_headers,
                                timeout=10,
                            )
                            try:
                                if retry_response.status_code == 200:
                                    retry_result = retry_response.json()
                                    if retry_result.get("type") == "success":
                                        self.logger.info(
                                            f"[SUBSCRIBE] Retry succeeded after re-auth - {len(instruments)} instruments"
                                        )
                                        # Process initial quotes from retry
                                        if "result" in retry_result:
                                            list_quotes = retry_result["result"].get("listQuotes", [])
                                            for quote_str in list_quotes:
                                                try:
                                                    quote_data = (
                                                        json.loads(quote_str)
                                                        if isinstance(quote_str, str)
                                                        else quote_str
                                                    )
                                                    if isinstance(quote_data, dict) and "MessageCode" not in quote_data:
                                                        quote_data["MessageCode"] = xts_message_code
                                                    if self.on_data:
                                                        self.on_data(self, quote_data)
                                                except json.JSONDecodeError:
                                                    pass
                                        return
                            finally:
                                retry_response.close()
                        self.logger.error("[SUBSCRIBE] Re-auth retry also failed")
                    self.logger.error(error_msg)
                    raise RuntimeError(f"Subscribe failed: {response.text}")
            finally:
                response.close()

        except Exception as e:
            self.logger.error(f"[SUBSCRIBE] Exception: {e}")
            raise

    def unsubscribe(self, correlation_id: str, mode: int, instruments: List[Dict]) -> bool:
        """
        Unsubscribe from market data using XTS HTTP API.

        API: PUT /instruments/subscription
        Request: {"instruments": [...], "xtsMessageCode": code}

        Args:
            correlation_id: Unique identifier for this subscription
            mode: Subscription mode
            instruments: List of instruments to unsubscribe
        """
        if not self.connected:
            return False

        # Get XTS message code from stored subscription
        subscription = self.subscriptions.get(correlation_id, {})
        xts_message_code = subscription.get("xts_message_code", self.XTS_MESSAGE_CODES["TOUCHLINE"])

        # Prepare unsubscription request
        unsubscription_request = {
            "instruments": instruments,
            "xtsMessageCode": xts_message_code,
        }

        # Remove from subscriptions
        if correlation_id in self.subscriptions:
            del self.subscriptions[correlation_id]

        # Send unsubscription via HTTP PUT
        try:
            headers = {
                "authorization": self.market_data_token,
                "Content-Type": "application/json",
            }

            self.logger.info(
                f"[UNSUBSCRIBE] Code: {xts_message_code}, Instruments: {len(instruments)}"
            )

            response = self._http_session.put(
                self.subscription_url,
                json=unsubscription_request,
                headers=headers,
                timeout=10,
            )
            try:
                if response.status_code == 200:
                    result = response.json()
                    if result.get("type") == "success":
                        self.logger.info(f"[UNSUBSCRIBE] Success - {len(instruments)} instruments")
                        return True
                    else:
                        self.logger.error(f"[UNSUBSCRIBE] API error response: {result}")
                        return False
                else:
                    self.logger.error(
                        f"[UNSUBSCRIBE] Failed - Status: {response.status_code}"
                    )
                    return False
            finally:
                response.close()

        except Exception as e:
            self.logger.error(f"[UNSUBSCRIBE] Exception: {e}")
            return False

    # Socket.IO event handlers
    def _on_connect(self):
        """Handle Socket.IO connect event."""
        self.connected = True
        self.logger.info("[SOCKET.IO EVENT] Connected to server")
        self._apply_engineio_timeout_floor()

        if self.on_open:
            self.on_open(self)

    def _on_joined(self, data):
        """Handle Socket.IO joined event from XTS server."""
        self.logger.info(f"[SOCKET.IO EVENT] Joined stream: {data}")

    def _on_disconnect(self):
        """Handle Socket.IO disconnect event."""
        self.connected = False
        self.logger.info("[SOCKET.IO EVENT] Disconnected from server")

        if self.on_close:
            self.on_close(self)

    def _on_connect_error(self, data):
        """Handle Socket.IO connection error."""
        self.logger.error(f"[SOCKET.IO EVENT] Connection error: {data}")

        if self.on_error:
            self.on_error(self, data)

    def _on_message_handler(self, data):
        """Handle general Socket.IO message."""
        self.logger.debug(f"[SOCKET.IO MESSAGE] {data}")

        if self.on_message:
            self.on_message(self, data)

        # Some XTS deployments send market data over the generic "message" event.
        # Parse and forward these payloads so ticks are not dropped.
        try:
            if isinstance(data, str) and data.startswith("t:"):
                self._process_binary_format(data)
                return

            payload = data
            if isinstance(data, str):
                payload = json.loads(data)

            if isinstance(payload, dict):
                message_code = self._extract_message_code(payload, "message")
                if message_code in {1501, 1502, 1505, 1510, 1512}:
                    self.logger.info(
                        f"[SOCKET.IO EVENT] Routing market payload from generic message channel (code {message_code})"
                    )
                    self._process_market_data(payload, message_code)
        except Exception:
            # Keep message handler non-fatal; explicit event handlers continue to work.
            pass

    # XTS message handlers - Touchline (1501)
    def _on_touchline_full(self, data):
        """Handle 1501 JSON full messages (Touchline/Quote data)."""
        self.logger.debug(f"[1501-FULL] Touchline data: {data}")
        self._process_market_data(data, 1501)

    def _on_touchline_partial(self, data):
        """Handle 1501 JSON partial messages."""
        self.logger.debug(f"[1501-PARTIAL] Touchline update: {data}")
        self._process_market_data(data, 1501)

    # XTS message handlers - Market Depth (1502)
    def _on_depth_full(self, data):
        """Handle 1502 JSON full messages (Market Depth)."""
        self.logger.debug(f"[1502-FULL] Market depth: {data}")
        self._process_market_data(data, 1502)

    def _on_depth_partial(self, data):
        """Handle 1502 JSON partial messages."""
        self.logger.debug(f"[1502-PARTIAL] Depth update: {data}")
        self._process_market_data(data, 1502)

    # XTS message handlers - Candle Data (1505)
    def _on_candle_full(self, data):
        """Handle 1505 JSON full messages (Candle/OHLC data)."""
        self.logger.debug(f"[1505-FULL] Candle data: {data}")
        self._process_market_data(data, 1505)

    def _on_candle_partial(self, data):
        """Handle 1505 JSON partial messages."""
        self.logger.debug(f"[1505-PARTIAL] Candle update: {data}")
        self._process_market_data(data, 1505)

    # XTS message handlers - Open Interest (1510)
    def _on_oi_full(self, data):
        """Handle 1510 JSON full messages (Open Interest)."""
        self.logger.debug(f"[1510-FULL] Open interest: {data}")
        self._process_market_data(data, 1510)

    def _on_oi_partial(self, data):
        """Handle 1510 JSON partial messages."""
        self.logger.debug(f"[1510-PARTIAL] OI update: {data}")
        self._process_market_data(data, 1510)

    # XTS message handlers - LTP (1512)
    def _on_ltp_full(self, data):
        """Handle 1512 JSON full messages (LTP)."""
        self.logger.debug(f"[1512-FULL] LTP data: {data}")
        self._process_market_data(data, 1512)

    def _on_ltp_partial(self, data):
        """Handle 1512 JSON partial messages."""
        self.logger.debug(f"[1512-PARTIAL] LTP update: {data}")
        self._process_market_data(data, 1512)

    # Legacy binary format handlers (1105)
    def _on_binary_full(self, data):
        """Handle 1105 JSON full messages (Binary market data format)."""
        self.logger.debug(f"[1105-FULL] Binary data: {data}")
        self._process_binary_format(data)

    def _on_binary_partial(self, data):
        """Handle 1105 JSON partial messages."""
        self.logger.debug(f"[1105-PARTIAL] Binary update: {data}")
        self._process_binary_format(data)

    def _on_xts_binary_packet(self, data):
        """
        Handle XTS binary market data packets emitted via `xts-binary-packet`.
        """
        try:
            # Handle non-bytes payload variants first
            if isinstance(data, str):
                if data.startswith("t:"):
                    self._process_binary_format(data)
                    return
                try:
                    payload = json.loads(data)
                    if isinstance(payload, dict):
                        message_code = self._extract_message_code(payload, "xts-binary-packet")
                        if message_code in {1501, 1502, 1505, 1510, 1512}:
                            self._process_market_data(payload, message_code)
                    return
                except Exception:
                    return

            if isinstance(data, (bytearray, memoryview)):
                data = bytes(data)

            if not isinstance(data, bytes) or len(data) < 16:
                return

            if not self._binary_packet_seen:
                self._binary_packet_seen = True
                self.logger.info("[XTS-BINARY] Received first xts-binary-packet tick stream payload")

            packet_type = struct.unpack("<H", data[0:2])[0]
            header_msg_code = struct.unpack("<H", data[2:4])[0]
            exchange_segment = struct.unpack("<h", data[4:6])[0]
            instrument_id = struct.unpack("<i", data[6:10])[0]

            # Skip unsolicited instruments
            if not self._is_instrument_subscribed(exchange_segment, instrument_id):
                return

            # Skip compressed packets for now (parser currently handles uncompressed payloads)
            is_compressed = (packet_type & 0x100) != 0
            if is_compressed:
                self.logger.debug(
                    f"[XTS-BINARY] Compressed packet received (type={packet_type}), skipping"
                )
                return

            payload = data[16:]
            if len(payload) < 2:
                return

            message_code = header_msg_code or struct.unpack("<H", payload[0:2])[0]
            if message_code not in {1501, 1502, 1505, 1510, 1512}:
                return

            market_data = {
                "ExchangeSegment": exchange_segment,
                "ExchangeInstrumentID": instrument_id,
                "MessageCode": message_code,
            }

            ltp = self._extract_ltp_from_binary_payload(payload, message_code)
            if ltp is None:
                return

            market_data["LastTradedPrice"] = ltp
            market_data.update(self._extract_quote_fields_from_binary_payload(payload, message_code))
            if self.on_data:
                self.on_data(self, market_data)

        except Exception as e:
            self.logger.error(f"[XTS-BINARY] Error handling xts-binary-packet: {e}")

    def _extract_ltp_from_binary_payload(self, payload: bytes, message_code: int):
        """
        Best-effort LTP extraction from uncompressed XTS binary payload.
        """
        offsets_by_code = {
            1512: [2, 10, 18, 26, 34, 42],
            1501: [48, 52, 92, 156, 164, 172, 180],
            1502: [166, 164, 170, 174],
        }
        default_offsets = [2, 10, 18, 26, 34, 42, 48, 52, 85, 92, 156, 164, 166, 172, 180]

        for off in offsets_by_code.get(message_code, default_offsets):
            if off + 8 > len(payload):
                continue
            try:
                value = struct.unpack("<d", payload[off : off + 8])[0]
                if 0.01 < value < 500000:
                    return round(value, 2)
            except Exception:
                continue

        # Fallback scan
        max_scan = min(len(payload) - 7, 220)
        for off in range(max_scan):
            try:
                value = struct.unpack("<d", payload[off : off + 8])[0]
                if 0.01 < value < 500000:
                    return round(value, 2)
            except Exception:
                continue
        return None

    def _extract_quote_fields_from_binary_payload(self, payload: bytes, message_code: int) -> dict:
        """
        Best-effort extraction of quote fields from binary payload.
        """
        result = {}

        # Based on XTS-like touchline packet observations used across brokers.
        if message_code == 1501:
            ohlc_offsets = {"Open": 156, "High": 164, "Low": 172, "Close": 180}
            for field, off in ohlc_offsets.items():
                if off + 8 > len(payload):
                    continue
                try:
                    value = struct.unpack("<d", payload[off : off + 8])[0]
                    if 0.01 < value < 500000:
                        result[field] = round(value, 2)
                except Exception:
                    continue

        # Volume can vary by broker packet layout; try a few safe candidates.
        for off in (188, 196, 204, 120, 128, 136):
            if off + 8 <= len(payload):
                try:
                    value = struct.unpack("<Q", payload[off : off + 8])[0]
                    if 0 < value < 10_000_000_000:
                        result["TotalTradedQuantity"] = int(value)
                        break
                except Exception:
                    pass
            if "TotalTradedQuantity" in result:
                break
            if off + 4 <= len(payload):
                try:
                    value = struct.unpack("<I", payload[off : off + 4])[0]
                    if 0 < value < 10_000_000_000:
                        result["TotalTradedQuantity"] = int(value)
                        break
                except Exception:
                    pass

        return result

    def _process_market_data(self, data, message_code: int):
        """
        Process market data from XTS and forward to callback.

        Args:
            data: Market data (dict or JSON string)
            message_code: XTS message code (1501, 1502, 1505, 1510, 1512)
        """
        try:
            # Parse JSON string if needed
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError as e:
                    self.logger.error(f"[PROCESS] JSON decode error: {e}")
                    return

            # Add message code to data for mode detection
            if isinstance(data, dict):
                data["MessageCode"] = message_code

            # Forward to callback
            if self.on_data:
                self.on_data(self, data)

        except Exception as e:
            self.logger.error(f"[PROCESS] Error processing market data: {e}")

    def _process_binary_format(self, data):
        """
        Process legacy binary format: t:exchangeSegment_instrumentID,field:value,...

        Format: t:12_1140025,110:2067.75,111:516.95,...
        """
        try:
            if not isinstance(data, str) or not data.startswith("t:"):
                return

            # Parse instrument info
            parts = data.split(",")
            if len(parts) < 2:
                return

            instrument_part = parts[0][2:]  # Remove 't:'
            if "_" not in instrument_part:
                return

            exchange_segment, instrument_id = instrument_part.split("_", 1)
            exchange_segment_int = int(exchange_segment)
            instrument_id_int = int(instrument_id)

            # Check if subscribed
            is_subscribed = self._is_instrument_subscribed(exchange_segment_int, instrument_id_int)
            if not is_subscribed:
                return

            # Field mapping for binary format
            field_mapping = {
                "110": "LastTradedPrice",
                "111": "LastTradedQuantity",
                "112": "TotalTradedQuantity",
                "113": "AverageTradedPrice",
                "114": "Open",
                "115": "High",
                "116": "Low",
                "117": "Close",
                "118": "TotalBuyQuantity",
                "119": "TotalSellQuantity",
            }

            # Parse field values
            market_data = {
                "ExchangeSegment": exchange_segment_int,
                "ExchangeInstrumentID": instrument_id_int,
                "MessageCode": 1512,  # Treat as LTP
            }

            for part in parts[1:]:
                if ":" in part:
                    field_code, value = part.split(":", 1)
                    field_name = field_mapping.get(field_code, f"Field_{field_code}")
                    try:
                        market_data[field_name] = float(value)
                    except ValueError:
                        market_data[field_name] = value

            # Forward to callback
            if self.on_data:
                self.on_data(self, market_data)

        except Exception as e:
            self.logger.error(f"[BINARY] Error processing binary format: {e}")

    def _is_instrument_subscribed(self, exchange_segment: int, instrument_id: int) -> bool:
        """Check if an instrument is in the subscription list."""
        for sub in self.subscriptions.values():
            for instrument in sub.get("instruments", []):
                if (
                    instrument.get("exchangeSegment") == exchange_segment
                    and str(instrument.get("exchangeInstrumentID")) == str(instrument_id)
                ):
                    return True
        return False

    def _extract_message_code(self, payload, event_name=None) -> int | None:
        """Extract XTS message code from payload or event name."""
        if isinstance(payload, dict):
            for key in ("MessageCode", "messageCode", "xtsMessageCode", "XtsMessageCode"):
                value = payload.get(key)
                if isinstance(value, int):
                    return value
                if isinstance(value, str) and value.strip().isdigit():
                    return int(value.strip())

        if isinstance(event_name, int):
            return event_name

        if isinstance(event_name, str) and event_name:
            prefix = event_name.split("-", 1)[0]
            if prefix.isdigit():
                return int(prefix)

        # Defensive fallback for non-string event types.
        if event_name is not None:
            event_name_str = str(event_name)
            prefix = event_name_str.split("-", 1)[0]
            if prefix.isdigit():
                return int(prefix)

        return None

    def _on_catch_all(self, event, *args):
        """Catch-all handler for unhandled Socket.IO events."""
        if event in {"connect", "disconnect", "joined", "message"}:
            return

        # Avoid duplicate processing for events with dedicated handlers.
        known_market_events = {
            "1501-json-full",
            "1501-json-partial",
            "1502-json-full",
            "1502-json-partial",
            "1505-json-full",
            "1505-json-partial",
            "1510-json-full",
            "1510-json-partial",
            "1512-json-full",
            "1512-json-partial",
            "1105-json-full",
            "1105-json-partial",
        }
        if event in known_market_events:
            return

        payload = args[0] if args else None
        message_code = self._extract_message_code(payload, event)
        if message_code in {1501, 1502, 1505, 1510, 1512} and payload is not None:
            self.logger.info(f"[SOCKET.IO EVENT] Routing market payload from event: {event}")
            self._process_market_data(payload, message_code)
            return

        if event in {"error", "warning", "success"}:
            self.logger.info(f"[SOCKET.IO EVENT] {event}: {payload}")
            return

        self.logger.debug(f"[CATCH-ALL] Unhandled event: {event}, args: {args[:100] if args else ''}")

    def resubscribe_all(self):
        """Resubscribe to all stored subscriptions after reconnection."""
        for correlation_id, sub_data in self.subscriptions.items():
            try:
                self.subscribe(correlation_id, sub_data["mode"], sub_data["instruments"])
            except Exception as e:
                self.logger.error(f"[RESUBSCRIBE] Error for {correlation_id}: {e}")
