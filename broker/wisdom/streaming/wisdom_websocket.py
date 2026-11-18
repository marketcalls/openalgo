import json
import threading
import time
from collections.abc import Callable
from typing import Any, Dict, List, Optional

import requests
import socketio

from broker.wisdom.baseurl import BASE_URL, INTERACTIVE_URL, MARKET_DATA_URL
from utils.logging import get_logger


class WisdomWebSocketClient:
    """
    Wisdom XTS Socket.IO client for market data streaming
    Based on the XTS Python SDK architecture using Socket.IO

    One instance serves the adapter for its whole life, but every connect()
    builds a new socketio.Client: the previous one is closed first, a fresh
    market data login is made, and the new socket is opened with the new
    token. Socket.IO's own reconnection is off (reconnection=False); the
    adapter's feed thread is the only thing that reconnects. Running both
    raced two reconnects on one client, and python-socketio's reconnect task
    is not stopped by disconnect(), so it reopened the socket with the old
    token after the adapter had shut down.

    Events are tied to the socketio.Client that raised them. Once connect()
    or disconnect() has replaced or released a client, its late connect and
    close events are ignored, so a close of an old socket can never be taken
    for a close of the new one.
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

    # Mode to XTS message code, shared by subscribe and unsubscribe so the two
    # cannot disagree. Unsubscribe used to read the code back from the entry
    # stored under its correlation id and fall back to 1501, which sent a
    # depth unsubscribe (its id carries the depth level) as a quote one.
    #   1501 = Touchline / full market data, 1502 = market depth,
    #   1505 = candle data, 1510 = open interest, 1512 = LTP
    MODE_TO_XTS_CODE = {
        1: 1512,  # LTP mode
        2: 1501,  # Quote mode
        3: 1502,  # Depth mode
    }

    # Instruments per subscription request. The XTS market data docs publish
    # no per-request cap, only a per-app-key total (each reply carries
    # Remaining_Subscription_Count); 50 is what the XTS siblings rmoney and
    # fivepaisaxts send per request.
    MAX_INSTRUMENTS_PER_REQUEST = 50

    # How long sio.connect() waits for the namespace acknowledgement. The
    # library default of 1 second fails a connect to a slow server.
    CONNECT_WAIT_TIMEOUT = 10

    # Engine.IO write-loop timeout floor, as in the rmoney client. The
    # official XTS SDK pins python-socketio 4.6, the client for the older
    # protocol, in which the client sends the pings; a server that expects
    # that may never ping this newer client, whose write loop then aborts
    # with "packet queue is empty" after max(ping_interval, ping_timeout) + 5
    # seconds without sending anything.
    MIN_ENGINEIO_ACTIVITY_TIMEOUT = 300

    # Exchange Types (matching XTS API)
    NSE_EQ = 1
    NSE_FO = 2
    BSE_EQ = 3
    BSE_FO = 4
    MCX_FO = 5

    def __init__(self, api_key: str, api_secret: str, user_id: str, base_url: str = None):
        """
        Initialize the Wisdom XTS Socket.IO client

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

        # Connection state. self.sio is the live socketio.Client, or None
        # between connections; it and _stopped change under _lock.
        self.sio = None
        self.connected = False
        self.running = False
        self._lock = threading.Lock()
        self._stopped = False

        # Callbacks
        self.on_open = None
        self.on_close = None
        self.on_error = None
        self.on_data = None
        self.on_message = None

        # Logger
        self.logger = get_logger("wisdom_websocket")

        # Instruments the server has confirmed, one entry per
        # (xts code, segment, instrument id), so repeated subscribes of the
        # same instrument never grow it.
        self.subscriptions = {}

    def _new_socketio(self, ended: threading.Event):
        """Build a socketio.Client for one connection.

        Args:
            ended: Set when this connection closes, so the adapter's feed
                thread can wait for exactly this connection.
        """
        sio = socketio.Client(logger=False, engineio_logger=False, reconnection=False)

        # Connect and close are bound to this client, so events from a
        # client that has been replaced can be told apart and ignored.
        # python-socketio passes a reason to the disconnect handler.
        sio.on("connect", lambda: self._on_connect(sio))
        sio.on("disconnect", lambda *_reason: self._on_disconnect(sio, ended))
        sio.on("message", self._on_message_handler)

        # Register XTS specific message handlers
        sio.on("1501-json-full", self._on_message_1501_json_full)
        sio.on("1501-json-partial", self._on_message_1501_json_partial)
        sio.on("1502-json-full", self._on_message_1502_json_full)
        sio.on("1502-json-partial", self._on_message_1502_json_partial)
        sio.on("1505-json-full", self._on_message_1505_json_full)
        sio.on("1505-json-partial", self._on_message_1505_json_partial)
        sio.on("1510-json-full", self._on_message_1510_json_full)
        sio.on("1510-json-partial", self._on_message_1510_json_partial)
        sio.on("1512-json-full", self._on_message_1512_json_full)
        sio.on("1512-json-partial", self._on_message_1512_json_partial)

        # Register handler for 1105 events (binary market data)
        sio.on("1105-json-partial", self._on_message_1105_json_partial)
        sio.on("1105-json-full", self._on_message_1105_json_full)

        # Add catch-all handler for any unhandled events
        sio.on("*", self._on_catch_all)
        return sio

    def _close_socketio(self, sio) -> None:
        """Close a socketio.Client and its Engine.IO transport.

        The caller has already detached it from self.sio, so the close event
        it raises is ignored. Safe to call on a client that never connected
        or has already closed.
        """
        if sio is None:
            return
        try:
            if sio.connected:
                sio.disconnect()
        except Exception as e:
            self.logger.warning(f"Error during Wisdom XTS Socket.IO disconnect: {e}")
        # A transport that dropped mid-connect is not marked connected, so
        # abort Engine.IO directly to release its socket and threads.
        try:
            eio = getattr(sio, "eio", None)
            if eio is not None:
                eio.disconnect(abort=True)
        except Exception as e:
            self.logger.warning(f"Error closing the Wisdom XTS Engine.IO transport: {e}")

    def _apply_engineio_timeout_floor(self, sio) -> None:
        """Raise Engine.IO's ping timers to the floor if the server set them low.

        Only the write loop's idle timeout reads these after the handshake;
        the read timeout that detects a dead connection keeps the server's
        values.
        """
        try:
            eio = getattr(sio, "eio", None)
            if eio is None:
                return
            interval = float(getattr(eio, "ping_interval", 0) or 0)
            timeout = float(getattr(eio, "ping_timeout", 0) or 0)
            if max(interval, timeout) + 5 >= self.MIN_ENGINEIO_ACTIVITY_TIMEOUT:
                return
            target = max(1, self.MIN_ENGINEIO_ACTIVITY_TIMEOUT - 5)
            eio.ping_interval = max(interval, target)
            eio.ping_timeout = max(timeout, target)
            self.logger.debug(
                f"Raised the Engine.IO idle timeout from {max(interval, timeout) + 5:.0f}s "
                f"to {self.MIN_ENGINEIO_ACTIVITY_TIMEOUT}s"
            )
        except Exception as e:
            self.logger.warning(f"Could not raise the Engine.IO idle timeout: {e}")

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

            self.logger.debug(f"[MARKET DATA LOGIN] Attempting login to: {login_url}")

            response = requests.post(login_url, json=login_payload, headers=headers, timeout=30)

            if response.status_code == 200:
                result = response.json()
                self.logger.debug(f"[MARKET DATA LOGIN] Response type: {result.get('type')}")

                if result.get("type") == "success":
                    login_result = result.get("result", {})
                    self.market_data_token = login_result.get("token")
                    self.actual_user_id = login_result.get("userID")

                    if self.market_data_token and self.actual_user_id:
                        self.logger.debug(
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

    def connect(self) -> threading.Event:
        """Open a new Socket.IO connection, closing the previous one first.

        Logs in to the market data API again on every call, so a reconnect
        always uses a fresh token.

        Returns:
            threading.Event: Set when this connection closes.

        Raises:
            Exception: The login or the connection failed, or disconnect()
                stopped this client while it was connecting.
        """
        try:
            # Close before reconnect. The old client is detached first, so
            # the close event it raises is ignored instead of being taken
            # for a close of the connection about to open.
            with self._lock:
                if self._stopped:
                    raise RuntimeError("The Wisdom XTS feed was stopped")
                previous, self.sio = self.sio, None
                self.connected = False
            self._close_socketio(previous)
            # A new login is a new session; the adapter resubscribes its book
            self.subscriptions.clear()

            # First, login to market data API to get proper tokens
            if not self.marketdata_login():
                raise Exception("Market data login failed")

            # Build connection URL with proper market data token and user ID
            publish_format = "JSON"
            broadcast_mode = "FULL"  # or 'PARTIAL'

            # Use the market data token and actual user ID from login response
            connection_url = f"{self.base_url}/?token={self.market_data_token}&userID={self.actual_user_id}&publishFormat={publish_format}&broadcastMode={broadcast_mode}"

            ended = threading.Event()
            sio = self._new_socketio(ended)
            with self._lock:
                if self._stopped:
                    raise RuntimeError("The Wisdom XTS feed was stopped")
                self.sio = sio

            self.logger.debug(f"Connecting to Wisdom XTS Socket.IO: {self.base_url}")

            # Connect to Socket.IO server
            try:
                sio.connect(
                    connection_url,
                    headers={},
                    transports=["websocket"],
                    namespaces=None,
                    socketio_path=self.SOCKET_PATH,
                    wait_timeout=self.CONNECT_WAIT_TIMEOUT,
                )
            except Exception:
                with self._lock:
                    if self.sio is sio:
                        self.sio = None
                        self.connected = False
                self._close_socketio(sio)
                raise

            # disconnect() may have run while the socket was opening and
            # found nothing connected to close; close it here instead.
            with self._lock:
                stopped = self._stopped or self.sio is not sio
            if stopped:
                self._close_socketio(sio)
                raise RuntimeError("The Wisdom XTS feed was stopped")

            self.running = True
            return ended

        except Exception as e:
            self.logger.error(f"Failed to connect to Wisdom XTS Socket.IO: {e}")
            if self.on_error:
                self.on_error(self, e)
            raise

    def disconnect(self):
        """Close the connection for good and release transport resources.

        A connect() still in progress on another thread gives up and closes
        whatever it opened.
        """
        with self._lock:
            self._stopped = True
            sio, self.sio = self.sio, None
            self.connected = False
        self.running = False

        # Release the socketio.Client so its engine-io transport threads end
        self._close_socketio(sio)

        # Clear subscriptions
        self.subscriptions.clear()

        self.logger.debug("Disconnected from Wisdom XTS Socket.IO")

    def transport_alive(self) -> bool:
        """Whether the current connection's Engine.IO transport is still up."""
        with self._lock:
            sio = self.sio
        eio = getattr(sio, "eio", None)
        return eio is not None and getattr(eio, "state", None) == "connected"

    @staticmethod
    def _instrument_key(instrument: dict) -> tuple:
        """Identity of an instrument, normalised to strings."""
        return (
            str(instrument.get("exchangeSegment")),
            str(instrument.get("exchangeInstrumentID")),
        )

    def _remember(self, mode: int, xts_message_code: int, instruments: list[dict]) -> None:
        for instrument in instruments:
            self.subscriptions[(xts_message_code, *self._instrument_key(instrument))] = {
                "mode": mode,
                "instruments": [instrument],
                "xts_message_code": xts_message_code,
            }

    def _forget(self, xts_message_code: int, instruments: list[dict]) -> None:
        for instrument in instruments:
            self.subscriptions.pop((xts_message_code, *self._instrument_key(instrument)), None)

    def subscribe_batch(
        self,
        mode: int,
        instruments: list[dict],
        still_wanted: Callable[[dict], bool] | None = None,
        subscribed: list[dict] | None = None,
    ) -> list[dict]:
        """
        Subscribe instruments of one mode using XTS HTTP API

        Sends at most MAX_INSTRUMENTS_PER_REQUEST instruments per request. When
        the server refuses a request of several instruments (one of them
        already subscribed after a reconnect, or one it does not accept), the
        same instruments are sent one at a time, so one refusal does not cost
        the others their subscription.

        Args:
            mode: Subscription mode (1=LTP, 2=Quote, 3=Depth)
            instruments: Instruments to subscribe
            still_wanted: Asked before each request; an instrument it reports
                as no longer wanted (unsubscribed while an earlier request of
                this batch was in flight) is not sent.
            subscribed: Filled in as the server confirms instruments, so the
                caller still learns what was subscribed when a later request
                raises.

        Returns:
            list[dict]: The instruments the server confirmed (or reported as
            already subscribed).

        Raises:
            RuntimeError: Socket.IO is not connected.
            requests.RequestException: A request could not be sent; the
                caller retries the instruments.
        """
        if subscribed is None:
            subscribed = []
        if not self.connected:
            raise RuntimeError("Socket.IO not connected")

        def wanted(items: list[dict]) -> list[dict]:
            return items if still_wanted is None else [i for i in items if still_wanted(i)]

        xts_message_code = self.MODE_TO_XTS_CODE.get(mode, 1501)
        step = self.MAX_INSTRUMENTS_PER_REQUEST
        for offset in range(0, len(instruments), step):
            chunk = wanted(instruments[offset : offset + step])
            if not chunk:
                continue
            outcome = self._send_subscription(xts_message_code, chunk)
            if outcome == "ok" or (outcome == "duplicate" and len(chunk) == 1):
                self._remember(mode, xts_message_code, chunk)
                subscribed.extend(chunk)
                continue
            if len(chunk) == 1:
                continue
            self.logger.info(
                f"[SUBSCRIPTION] Request of {len(chunk)} instruments refused; "
                "sending them one at a time"
            )
            for instrument in chunk:
                if not self.connected:
                    raise RuntimeError("Socket.IO not connected")
                # Each request here can take seconds; an instrument
                # unsubscribed meanwhile is left out.
                if not wanted([instrument]):
                    continue
                if self._send_subscription(xts_message_code, [instrument]) in ("ok", "duplicate"):
                    self._remember(mode, xts_message_code, [instrument])
                    subscribed.append(instrument)

        self.logger.debug(
            f"Subscribed to {len(subscribed)} of {len(instruments)} instruments with XTS code "
            f"{xts_message_code} (mode {mode})"
        )
        return subscribed

    def _send_subscription(self, xts_message_code: int, instruments: list[dict]) -> str:
        """POST one subscription request.

        Returns:
            str: "ok", "duplicate" (already subscribed) or "refused".
        """
        # Prepare subscription request
        subscription_request = {"instruments": instruments, "xtsMessageCode": xts_message_code}

        # Send subscription via HTTP POST (like the official XTS SDK)
        headers = {"Authorization": self.market_data_token, "Content-Type": "application/json"}

        response = requests.post(
            self.API_BASE_URL, json=subscription_request, headers=headers, timeout=10
        )

        if response.status_code == 200:
            result = response.json()
            if result.get("type") == "success":
                self.logger.debug(
                    f"[SUBSCRIPTION SUCCESS] Code: {xts_message_code}, Instruments: {len(instruments)}, Response: {result}"
                )

                # Process initial quote data from listQuotes if available
                list_quotes = (result.get("result") or {}).get("listQuotes", [])
                for quote_str in list_quotes:
                    try:
                        quote_data = json.loads(quote_str)
                        self.logger.debug(f"[INITIAL QUOTE] Processing initial quote: {quote_data}")
                        if self.on_data:
                            self.on_data(self, quote_data)
                    except json.JSONDecodeError as e:
                        self.logger.error(f"Error parsing initial quote: {e}")
                return "ok"
            text = json.dumps(result)
        else:
            text = response.text

        lowered = text.lower()
        if "already subscribed" in lowered or "e-session-0002" in lowered:
            self.logger.debug(
                f"[SUBSCRIPTION] {len(instruments)} instrument(s) already subscribed (code {xts_message_code})"
            )
            return "duplicate"

        self.logger.error(f"[SUBSCRIPTION ERROR] Status: {response.status_code}, Response: {text}")
        return "refused"

    def unsubscribe(self, mode: int, instruments: list[dict]):
        """
        Unsubscribe from market data using XTS HTTP API

        Args:
            mode: Subscription mode
            instruments: List of instruments to unsubscribe from
        """
        # Derive the code from the mode, the same way subscribe_batch() does
        xts_message_code = self.MODE_TO_XTS_CODE.get(mode, 1501)

        # Remove from subscriptions, connected or not: the bookkeeping must
        # not outlive the subscription
        self._forget(xts_message_code, instruments)

        if not self.connected:
            return

        # Prepare unsubscription request
        unsubscription_request = {"instruments": instruments, "xtsMessageCode": xts_message_code}

        # Send unsubscription via HTTP PUT (different from subscription POST)
        try:
            headers = {"Authorization": self.market_data_token, "Content-Type": "application/json"}

            # Use PUT method for unsubscription as per XTS API
            response = requests.put(
                self.API_UNSUBSCRIBE_URL, json=unsubscription_request, headers=headers, timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                self.logger.debug(
                    f"[UNSUBSCRIPTION SUCCESS] Code: {xts_message_code}, Instruments: {len(instruments)}, Response: {result}"
                )
            else:
                self.logger.error(
                    f"[UNSUBSCRIPTION ERROR] Status: {response.status_code}, Response: {response.text}"
                )

        except Exception as e:
            self.logger.error(f"[UNSUBSCRIPTION EXCEPTION] Error: {e}")

        self.logger.debug(f"Unsubscribed from {len(instruments)} instruments")

    def _on_connect(self, sio):
        """Socket.IO connect event handler"""
        with self._lock:
            current = sio is self.sio
            if current:
                self.connected = True
        if not current:
            self.logger.debug("Ignoring a connect event from a replaced Wisdom XTS connection")
            return

        self.logger.info("Connected to Wisdom XTS Socket.IO")
        self._apply_engineio_timeout_floor(sio)

        # Call external callback
        if self.on_open:
            self.on_open(self)

    def _on_disconnect(self, sio, ended: threading.Event):
        """Socket.IO disconnect event handler

        python-socketio delivers events on its own threads (Engine.IO starts
        one per incoming message), so this can race a connect() that is
        replacing `sio`. Only the live connection's close reaches the adapter;
        `ended` is set either way, last, so the feed thread wakes once the
        adapter has seen the close.
        """
        try:
            with self._lock:
                current = sio is self.sio
                if current:
                    self.connected = False
            if not current:
                self.logger.debug("Ignoring a close event from a replaced Wisdom XTS connection")
                return

            self.logger.info("Disconnected from Wisdom XTS Socket.IO")

            # Call external callback
            if self.on_close:
                self.on_close(self)
        finally:
            ended.set()

    def _on_message_handler(self, data):
        """General message handler"""
        self.logger.debug(f"[GENERAL MESSAGE] Received: {data}")
        if self.on_message:
            self.on_message(self, data)

    # XTS specific message handlers for different market data types
    def _on_message_1501_json_full(self, data):
        """Handle 1501 JSON full messages (LTP)"""
        self.logger.debug(f"[1501-JSON-FULL] Received LTP data: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1501_json_partial(self, data):
        """Handle 1501 JSON partial messages"""
        self.logger.debug(f"[1501-JSON-PARTIAL] Received LTP partial: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1502_json_full(self, data):
        """Handle 1502 JSON full messages (Market Depth)"""
        self.logger.debug(f"[1502-JSON-FULL] Received Market Depth data: {data}")
        # Parse JSON string if needed
        if isinstance(data, str):
            try:
                data = json.loads(data)
                self.logger.debug(f"[1502-JSON-FULL] Parsed depth data: {data}")
            except json.JSONDecodeError as e:
                self.logger.error(f"[1502-JSON-FULL] Failed to parse JSON: {e}")
                return
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1502_json_partial(self, data):
        """Handle 1502 JSON partial messages (Market Depth updates)"""
        self.logger.debug(f"[1502-JSON-PARTIAL] Received Market Depth partial: {data}")
        # Parse JSON string if needed
        if isinstance(data, str):
            try:
                data = json.loads(data)
                self.logger.debug(f"[1502-JSON-PARTIAL] Parsed depth update: {data}")
            except json.JSONDecodeError as e:
                self.logger.error(f"[1502-JSON-PARTIAL] Failed to parse JSON: {e}")
                return
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1505_json_full(self, data):
        """Handle 1505 JSON full messages (Market depth)"""
        self.logger.debug(f"[1505-JSON-FULL] Received Market depth: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1505_json_partial(self, data):
        """Handle 1505 JSON partial messages"""
        self.logger.debug(f"[1505-JSON-PARTIAL] Received Depth partial: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1510_json_full(self, data):
        """Handle 1510 JSON full messages (Open interest)"""
        self.logger.debug(f"[1510-JSON-FULL] Received Open interest: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1510_json_partial(self, data):
        """Handle 1510 JSON partial messages"""
        self.logger.debug(f"[1510-JSON-PARTIAL] Received OI partial: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1512_json_full(self, data):
        """Handle 1512 JSON full messages (Full market data)"""
        self.logger.debug(f"[1512-JSON-FULL] Received Full market data: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1512_json_partial(self, data):
        """Handle 1512 JSON partial messages"""
        self.logger.debug(f"[1512-JSON-PARTIAL] Received Full data partial: {data}")
        if self.on_data:
            self.on_data(self, data)

    def _on_message_1105_json_full(self, data):
        """Handle 1105 JSON full messages (Binary market data)"""
        self.logger.debug(f"[1105-JSON-FULL] Received binary market data: {data}")
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

            # Check if we have any subscription for this instrument
            is_subscribed = False
            for sub in self.subscriptions.values():
                # Get instruments from the subscription
                for instrument in sub.get("instruments", []):
                    if (
                        instrument.get("exchangeSegment") == exchange_segment_int
                        and instrument.get("exchangeInstrumentID") == instrument_id_int
                    ):
                        is_subscribed = True
                        break
                if is_subscribed:
                    break

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

            self.logger.debug(f"[1105-PROCESSED] Subscribed instrument data: {market_data}")

            # Call the standard data handler
            if self.on_data:
                self.on_data(self, market_data)

        except Exception as e:
            self.logger.error(f"Error processing 1105 data '{data}': {e}")

    def _on_catch_all(self, event, *args):
        """Catch-all handler for any unhandled Socket.IO events"""
        # Don't log connect/disconnect/joined events as they are handled separately
        if event not in ["connect", "disconnect", "joined", "message"]:
            self.logger.debug(f"[CATCH-ALL] Unhandled event: {event}")
            if args:
                for i, arg in enumerate(args):
                    self.logger.debug(f"  Arg[{i}]: Type={type(arg)}, Value={str(arg)[:200]}...")
