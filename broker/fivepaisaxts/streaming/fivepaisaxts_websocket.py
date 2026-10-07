import json
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
import socketio

from broker.fivepaisaxts.baseurl import BASE_URL, INTERACTIVE_URL, MARKET_DATA_URL
from utils.logging import get_logger


class FivepaisaXTSWebSocketClient:
    """
    Fivepaisa XTS Socket.IO client for market data streaming
    Based on the XTS Python SDK architecture using Socket.IO
    """

    # Base URL
    BASE_URL = BASE_URL

    # Socket.IO endpoints - Updated based on XTS API documentation

    SOCKET_PATH = "/apimarketdata/socket.io"
    API_BASE_URL = f"{MARKET_DATA_URL}/instruments/subscription"
    API_UNSUBSCRIBE_URL = (
        f"{MARKET_DATA_URL}/instruments/subscription"  # Same endpoint, different method
    )

    # Available Actions
    SUBSCRIBE_ACTION = 1
    UNSUBSCRIBE_ACTION = 0

    # Subscription Modes
    LTP_MODE = 1
    QUOTE_MODE = 2
    DEPTH_MODE = 3

    # Mode to XTS message code, per the XTS documentation:
    # 1501 = Touchline / full market data, 1502 = market depth,
    # 1505 = full market data, 1510 = open interest, 1512 = LTP.
    #
    # Shared by subscribe() and unsubscribe() so the two cannot disagree:
    # unsubscribe used to read the code back from its correlation id's stored
    # entry and silently fall back to 1501, which unsubscribed the wrong feed
    # for LTP and depth as soon as subscriptions were batched under ids of
    # their own.
    MODE_TO_XTS_CODE = {
        1: 1512,  # LTP
        2: 1501,  # Quote
        3: 1502,  # Market depth
    }

    # Exchange Types (matching XTS API)
    NSE_EQ = 1
    NSE_FO = 2
    BSE_EQ = 3
    BSE_FO = 4
    MCX_FO = 5

    # Data-stall watchdog. XTS has no heartbeat on the data channel and the feed
    # is legitimately silent outside trading hours, so silence only counts while
    # a subscribed exchange's session is open (see _stall_reference).
    HEALTH_CHECK_INTERVAL = 30
    DATA_TIMEOUT = 90
    # IST session windows in minutes after midnight. MCX segment ids are 5 in
    # the class constants above and 51 in XTS proper; accept both.
    _EQUITY_SESSION = (9 * 60 + 15, 15 * 60 + 30)
    _MCX_SESSION = (9 * 60, 23 * 60 + 30)
    _MCX_SEGMENTS = {"5", "51"}
    _IST = timezone(timedelta(hours=5, minutes=30))

    def __init__(self, api_key: str, api_secret: str, user_id: str, base_url: str = None):
        """
        Initialize the Fivepaisa XTS Socket.IO client

        Args:
            api_key: Market data API key
            api_secret: Market data API secret
            user_id: User ID (client ID)
            base_url: Base URL for the Socket.IO endpoint
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.user_id = user_id
        self.base_url = base_url or self.BASE_URL

        # Authentication tokens
        self.market_data_token = None
        self.feed_token = None
        self.actual_user_id = None

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
        self.logger = get_logger("fivepaisaxts_websocket")

        # Subscriptions tracking
        self.subscriptions = {}

        # Data-stall watchdog state
        self.last_message_time: float | None = None
        self._health_thread: threading.Thread | None = None
        self._health_stop = threading.Event()

        # Create Socket.IO client
        self._setup_socketio()

    def _setup_socketio(self):
        """Setup Socket.IO client with event handlers"""
        self.sio = socketio.Client(logger=False, engineio_logger=False)

        # Register event handlers
        self.sio.on("connect", self._on_connect)
        self.sio.on("disconnect", self._on_disconnect)
        self.sio.on("message", self._on_message_handler)

        # Register XTS specific message handlers. Each goes through
        # _stamped so the stall watchdog sees every market-data event,
        # including ones the handler later filters out.
        for event, handler in (
            ("1501-json-full", self._on_message_1501_json_full),
            ("1501-json-partial", self._on_message_1501_json_partial),
            ("1502-json-full", self._on_message_1502_json_full),
            ("1502-json-partial", self._on_message_1502_json_partial),
            ("1505-json-full", self._on_message_1505_json_full),
            ("1505-json-partial", self._on_message_1505_json_partial),
            ("1510-json-full", self._on_message_1510_json_full),
            ("1510-json-partial", self._on_message_1510_json_partial),
            ("1512-json-full", self._on_message_1512_json_full),
            ("1512-json-partial", self._on_message_1512_json_partial),
            # 1105 events (binary market data)
            ("1105-json-partial", self._on_message_1105_json_partial),
            ("1105-json-full", self._on_message_1105_json_full),
        ):
            self.sio.on(event, self._stamped(handler))

        # Add catch-all handler for any unhandled events
        self.sio.on("*", self._on_catch_all)

    def marketdata_login(self):
        """
        Login to XTS market data API to get authentication tokens

        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            login_url = f"{self.base_url}/apibinarymarketdata/auth/login"

            login_payload = {
                "appKey": self.api_key,
                "secretKey": self.api_secret,
                "source": "WebAPI",
            }

            headers = {"Content-Type": "application/json"}

            self.logger.info(f"[MARKET DATA LOGIN] Attempting login to: {login_url}")

            response = requests.post(login_url, json=login_payload, headers=headers, timeout=30)

            if response.status_code == 200:
                result = response.json()
                self.logger.info(f"[MARKET DATA LOGIN] Response: {result}")

                if result.get("type") == "success":
                    login_result = result.get("result", {})
                    self.market_data_token = login_result.get("token")
                    self.actual_user_id = login_result.get("userID")

                    if self.market_data_token and self.actual_user_id:
                        self.logger.info(
                            f"[MARKET DATA LOGIN] Success! Token obtained, UserID: {self.actual_user_id}"
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

        except Exception as e:
            self.logger.error(f"[MARKET DATA LOGIN] Exception: {e}")
            return False

    def connect(self):
        """Establish Socket.IO connection with proper authentication"""
        try:
            # Re-create Socket.IO client if it was released by a prior disconnect()
            if self.sio is None:
                self._setup_socketio()

            # First, login to market data API to get proper tokens
            if not self.marketdata_login():
                raise Exception("Market data login failed")

            # Build connection URL with proper market data token and user ID
            publish_format = "JSON"
            broadcast_mode = "FULL"  # or 'PARTIAL'

            # Use the market data token and actual user ID from login response
            connection_url = f"{self.base_url}/?token={self.market_data_token}&userID={self.actual_user_id}&publishFormat={publish_format}&broadcastMode={broadcast_mode}"

            self.logger.info(f"Connecting to Fivepaisa XTS Socket.IO: {connection_url}")

            # Connect to Socket.IO server
            self.sio.connect(
                connection_url,
                headers={},
                transports=["websocket"],
                namespaces=None,
                socketio_path=self.SOCKET_PATH,
            )

            self.running = True

        except Exception as e:
            self.logger.error(f"Failed to connect to Fivepaisa XTS Socket.IO: {e}")
            if self.on_error:
                self.on_error(self, e)
            raise

    def disconnect(self):
        """Disconnect from Socket.IO and release transport resources"""
        self.running = False
        self.connected = False
        self._stop_health_check()

        try:
            if self.sio and self.sio.connected:
                self.sio.disconnect()
                self.logger.info("Socket.IO client disconnected")
        except Exception as e:
            self.logger.warning(f"Error during Socket.IO disconnect: {e}")

        # Release the socketio.Client so its engine-io transport threads can be GC'd
        self.sio = None

        # Clear subscriptions
        self.subscriptions.clear()

        self.logger.info("Disconnected from Fivepaisa XTS Socket.IO")

    def subscribe(self, correlation_id: str, mode: int, instruments: list[dict]):
        """
        Subscribe to market data using XTS HTTP API

        Args:
            correlation_id: Unique identifier for this subscription
            mode: Subscription mode (1=LTP, 2=Quote, 3=Depth)
            instruments: List of instruments to subscribe to
        """
        if not self.connected:
            raise RuntimeError("Socket.IO not connected")

        xts_message_code = self.MODE_TO_XTS_CODE.get(mode, 1501)

        # Prepare subscription request
        subscription_request = {"instruments": instruments, "xtsMessageCode": xts_message_code}

        # Store subscription for reconnection
        self.subscriptions[correlation_id] = {
            "mode": mode,
            "instruments": instruments,
            "xts_message_code": xts_message_code,
        }

        # Send subscription via HTTP POST (like the official XTS SDK)
        try:
            headers = {"Authorization": self.market_data_token, "Content-Type": "application/json"}

            response = requests.post(
                self.API_BASE_URL, json=subscription_request, headers=headers, timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                self.logger.info(
                    f"[SUBSCRIPTION SUCCESS] Code: {xts_message_code}, Instruments: {len(instruments)}, Response: {result}"
                )

                # Process initial quote data from listQuotes if available
                if result.get("type") == "success" and "result" in result:
                    list_quotes = result["result"].get("listQuotes", [])
                    for quote_str in list_quotes:
                        try:
                            quote_data = json.loads(quote_str)
                            self.logger.info(
                                f"[INITIAL QUOTE] Processing initial quote: {quote_data}"
                            )
                            if self.on_data:
                                self.on_data(self, quote_data)
                        except json.JSONDecodeError as e:
                            self.logger.error(f"Error parsing initial quote: {e}")
            else:
                self.logger.error(
                    f"[SUBSCRIPTION ERROR] Status: {response.status_code}, Response: {response.text}"
                )

        except Exception as e:
            self.logger.error(f"[SUBSCRIPTION EXCEPTION] Error: {e}")

        self.logger.info(
            f"Subscribed to {len(instruments)} instruments with XTS code {xts_message_code} (mode {mode})"
        )

    @staticmethod
    def _instrument_key(instrument: dict) -> tuple:
        """Identity of an instrument, normalised to strings.

        XTS carries the segment as an int and the instrument id as a string in
        some paths and the reverse in others, so comparing raw values misses
        matches that are the same instrument.
        """
        return (
            str(instrument.get("exchangeSegment")),
            str(instrument.get("exchangeInstrumentID")),
        )

    def _forget_instruments(self, xts_message_code: int, instruments: list[dict]) -> None:
        """Remove `instruments` from every stored entry using the same code."""
        targets = {self._instrument_key(i) for i in instruments}
        for correlation_id in list(self.subscriptions):
            entry = self.subscriptions[correlation_id]
            if entry.get("xts_message_code") != xts_message_code:
                continue
            kept = [
                i for i in entry.get("instruments", []) if self._instrument_key(i) not in targets
            ]
            if not kept:
                del self.subscriptions[correlation_id]
            else:
                entry["instruments"] = kept

    def unsubscribe(self, correlation_id: str, mode: int, instruments: list[dict]):
        """
        Unsubscribe from market data using XTS HTTP API

        Args:
            correlation_id: Unique identifier for this subscription
            mode: Subscription mode
            instruments: List of instruments to unsubscribe from
        """
        if not self.connected:
            return

        # Derive the code from the mode, the same way subscribe() does. Reading
        # it back from `correlation_id` only worked while every subscribe used
        # a per-symbol id; batched subscribes are stored under a batch id, so
        # the lookup missed and every unsubscribe fell back to 1501.
        xts_message_code = self.MODE_TO_XTS_CODE.get(mode, 1501)

        # Prepare unsubscription request
        unsubscription_request = {"instruments": instruments, "xtsMessageCode": xts_message_code}

        # Drop these instruments from whichever stored entries hold them,
        # deleting an entry once it is empty. `self.subscriptions` is also the
        # tick filter (see _process_1105_data), so an instrument left behind
        # here keeps being accepted after it was unsubscribed.
        self._forget_instruments(xts_message_code, instruments)
        if correlation_id in self.subscriptions:
            del self.subscriptions[correlation_id]

        # Send unsubscription via HTTP PUT (different from subscription POST)
        try:
            headers = {"Authorization": self.market_data_token, "Content-Type": "application/json"}

            # Use PUT method for unsubscription as per XTS API
            response = requests.put(
                self.API_UNSUBSCRIBE_URL, json=unsubscription_request, headers=headers, timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                self.logger.info(
                    f"[UNSUBSCRIPTION SUCCESS] Code: {xts_message_code}, Instruments: {len(instruments)}, Response: {result}"
                )
            else:
                self.logger.error(
                    f"[UNSUBSCRIPTION ERROR] Status: {response.status_code}, Response: {response.text}"
                )

        except Exception as e:
            self.logger.error(f"[UNSUBSCRIPTION EXCEPTION] Error: {e}")

        self.logger.info(f"Unsubscribed from {len(instruments)} instruments")

    def _stamped(self, handler):
        """Wrap a market-data handler so it records when data last arrived."""

        def wrapper(*args, **kwargs):
            self.last_message_time = time.time()
            return handler(*args, **kwargs)

        return wrapper

    def _stall_reference(self, now: float) -> float | None:
        """Instant silence should be measured from, or None if no session is open.

        The later of the last message and the open of the earliest live session:
        a socket connected at 08:00 has a stale last_message_time by 09:15, and
        measuring from it would reconnect the moment the market opens.
        """
        ist_now = datetime.fromtimestamp(now, self._IST)
        if ist_now.weekday() >= 5:
            return None

        with_segments = {
            str(instrument.get("exchangeSegment"))
            for sub in list(self.subscriptions.values())
            for instrument in sub.get("instruments", [])
        }
        if not with_segments:
            return None

        minute = ist_now.hour * 60 + ist_now.minute
        midnight = ist_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        opens = []
        for segment in with_segments:
            start, end = self._MCX_SESSION if segment in self._MCX_SEGMENTS else self._EQUITY_SESSION
            if start <= minute < end:
                opens.append(midnight + start * 60)
        if not opens:
            return None
        return max(self.last_message_time or 0.0, min(opens))

    def _start_health_check(self):
        if (
            self._health_thread
            and self._health_thread.is_alive()
            and not self._health_stop.is_set()
        ):
            return
        # A fresh stop event per worker: clearing a shared one would resurrect a
        # stopping predecessor instead of replacing it.
        self._health_stop = threading.Event()
        self._health_thread = threading.Thread(
            target=self._health_check_loop,
            args=(self._health_stop,),
            daemon=True,
            name="fivepaisaxts-health-check",
        )
        self._health_thread.start()

    def _stop_health_check(self):
        self._health_stop.set()

    def _health_check_loop(self, stop_event: threading.Event):
        while not stop_event.wait(self.HEALTH_CHECK_INTERVAL):
            if not self.connected:
                return
            reference = self._stall_reference(time.time())
            if reference is None:
                continue
            silent_for = time.time() - reference
            if silent_for > self.DATA_TIMEOUT:
                self.logger.error(
                    f"Data stall detected - no market data for {silent_for:.0f}s "
                    "during an open session. Forcing reconnect..."
                )
                # Drop only the transport. The adapter's close callback reconnects
                # and replays its own subscription book; disconnect() would also
                # clear this client's subscriptions and stop the reconnect.
                try:
                    if self.sio:
                        self.sio.disconnect()
                except Exception as e:
                    self.logger.warning(f"Error closing stalled Socket.IO connection: {e}")
                return

    def _on_connect(self):
        """Socket.IO connect event handler"""
        self.connected = True
        self.last_message_time = time.time()
        self.logger.info("Connected to Fivepaisa XTS Socket.IO")
        self._start_health_check()

        # Call external callback
        if self.on_open:
            self.on_open(self)

    def _on_disconnect(self):
        """Socket.IO disconnect event handler"""
        self.connected = False
        self._stop_health_check()
        self.logger.info("Disconnected from Fivepaisa XTS Socket.IO")

        # Call external callback
        if self.on_close:
            self.on_close(self)

    def _on_message_handler(self, data):
        """General message handler"""
        self.logger.info(f"[GENERAL MESSAGE] Received: {data}")
        if self.on_message:
            self.on_message(self, data)

    # XTS specific message handlers for different market data types
    def _on_message_1501_json_full(self, data):
        """Handle 1501 JSON full messages (LTP)"""
        self.logger.info(f"[1501-JSON-FULL] Received LTP data: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1501_json_partial(self, data):
        """Handle 1501 JSON partial messages"""
        self.logger.info(f"[1501-JSON-PARTIAL] Received LTP partial: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1502_json_full(self, data):
        """Handle 1502 JSON full messages (Market Depth)"""
        self.logger.info(f"[1502-JSON-FULL] Received Market Depth data: {data}")
        # Parse JSON string if needed
        if isinstance(data, str):
            try:
                data = json.loads(data)
                self.logger.info(f"[1502-JSON-FULL] Parsed depth data: {data}")
            except json.JSONDecodeError as e:
                self.logger.error(f"[1502-JSON-FULL] Failed to parse JSON: {e}")
                return
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1502_json_partial(self, data):
        """Handle 1502 JSON partial messages (Market Depth updates)"""
        self.logger.info(f"[1502-JSON-PARTIAL] Received Market Depth partial: {data}")
        # Parse JSON string if needed
        if isinstance(data, str):
            try:
                data = json.loads(data)
                self.logger.info(f"[1502-JSON-PARTIAL] Parsed depth update: {data}")
            except json.JSONDecodeError as e:
                self.logger.error(f"[1502-JSON-PARTIAL] Failed to parse JSON: {e}")
                return
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1505_json_full(self, data):
        """Handle 1505 JSON full messages (Market depth)"""
        self.logger.info(f"[1505-JSON-FULL] Received Market depth: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1505_json_partial(self, data):
        """Handle 1505 JSON partial messages"""
        self.logger.info(f"[1505-JSON-PARTIAL] Received Depth partial: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1510_json_full(self, data):
        """Handle 1510 JSON full messages (Open interest)"""
        self.logger.info(f"[1510-JSON-FULL] Received Open interest: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1510_json_partial(self, data):
        """Handle 1510 JSON partial messages"""
        self.logger.info(f"[1510-JSON-PARTIAL] Received OI partial: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1512_json_full(self, data):
        """Handle 1512 JSON full messages (Full market data)"""
        self.logger.info(f"[1512-JSON-FULL] Received Full market data: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1512_json_partial(self, data):
        """Handle 1512 JSON partial messages"""
        self.logger.info(f"[1512-JSON-PARTIAL] Received Full data partial: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1105_json_full(self, data):
        """Handle 1105 JSON full messages (Binary market data)"""
        self.logger.info(f"[1105-JSON-FULL] Received binary market data: {data}")
        self._process_1105_data(data)

    def _on_message_1105_json_partial(self, data):
        """Handle 1105 JSON partial messages (Binary market data)"""
        self.logger.debug(f"[1105-JSON-PARTIAL] Received binary partial: {data}")
        self._process_1105_data(data)

    def _process_1105_data(self, data):
        """Process 1105 binary market data format: t:exchangeSegment_instrumentID,field:value,field:value"""
        try:
            if not isinstance(data, str):
                return

            # Parse format: t:12_1140025,110:2067.75,111:516.95
            parts = data.split(",")
            if not parts or not parts[0].startswith("t:"):
                return

            # Extract instrument info from first part
            instrument_part = parts[0][2:]  # Remove 't:'
            if "_" not in instrument_part:
                return

            exchange_segment, instrument_id = instrument_part.split("_", 1)

            # FILTER: Only process data for subscribed instruments
            exchange_segment_int = int(exchange_segment)
            instrument_id_int = int(instrument_id)

            # Check if we have any subscription for this instrument. Compare on
            # the normalised key: the adapter stores exchangeInstrumentID as a
            # string, so the previous `== instrument_id_int` could never match
            # and every 1105 tick was dropped here.
            wanted = (str(exchange_segment_int), str(instrument_id_int))
            is_subscribed = any(
                self._instrument_key(instrument) == wanted
                for sub in self.subscriptions.values()
                for instrument in sub.get("instruments", [])
            )

            if not is_subscribed:
                # Skip processing for unsubscribed instruments
                return

            # Parse field-value pairs only for subscribed instruments
            market_data = {
                "ExchangeSegment": exchange_segment_int,
                "ExchangeInstrumentID": instrument_id_int,
            }

            # Map common field codes to standard names
            field_mapping = {
                "110": "LastTradedPrice",  # LTP
                "111": "LastTradedQuantity",  # LTQ
                "112": "TotalTradedQuantity",  # Volume
                "113": "AverageTradedPrice",
                "114": "Open",
                "115": "High",
                "116": "Low",
                "117": "Close",
                "118": "TotalBuyQuantity",
                "119": "TotalSellQuantity",
            }

            for part in parts[1:]:
                if ":" in part:
                    field_code, value = part.split(":", 1)
                    field_name = field_mapping.get(field_code, f"Field_{field_code}")
                    try:
                        market_data[field_name] = float(value)
                    except ValueError:
                        market_data[field_name] = value

            self.logger.info(f"[1105-PROCESSED] Subscribed instrument data: {market_data}")

            # Call the standard data handler
            if self.on_data:
                self.on_data(self, market_data)

        except Exception as e:
            self.logger.error(f"Error processing 1105 data '{data}': {e}")

    def _on_catch_all(self, event, *args):
        """Catch-all handler for any unhandled Socket.IO events"""
        # Don't log connect/disconnect/joined events as they are handled separately
        if event not in ["connect", "disconnect", "joined", "message"]:
            self.logger.info(f"[CATCH-ALL] Unhandled event: {event}")
            if args:
                for i, arg in enumerate(args):
                    self.logger.info(f"  Arg[{i}]: Type={type(arg)}, Value={str(arg)[:200]}...")

    def resubscribe_all(self):
        """Resubscribe to all stored subscriptions after reconnection"""
        for correlation_id, sub_data in self.subscriptions.items():
            try:
                self.subscribe(correlation_id, sub_data["mode"], sub_data["instruments"])
            except Exception as e:
                self.logger.error(f"Error resubscribing {correlation_id}: {e}")
