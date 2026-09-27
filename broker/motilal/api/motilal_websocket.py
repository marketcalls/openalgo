"""
Motilal Oswal WebSocket Client Implementation
Handles connection to Motilal Oswal's market data streaming API

Note: Motilal Oswal uses BINARY packets for market data subscriptions,
not JSON. This is different from their Trade WebSocket which uses JSON.
"""

import json
import logging
import ssl
import struct
import threading
import time
from datetime import datetime, timedelta
from struct import pack, unpack
from typing import Dict, Optional

import websocket

from utils.logging import get_logger

from .baseurl import get_ws_feed_url

logger = get_logger(__name__)


class MotilalWebSocket:
    """
    WebSocket client for Motilal Oswal broker's market data API.
    Handles connection to the WebSocket server, authentication, subscription,
    and message parsing for market data.
    """

    # WebSocket endpoints. Both live in baseurl.py so the plugin has a single
    # source of truth for hosts.
    #
    # The broadcast (market data) feed is NOT documented: doc 33-websocket-
    # broadcast.md only shows SDK calls (Mofsl.connect(), Mofsl.Register(...))
    # and the decoded Python dicts they yield -- no URL, no wire format, no
    # heartbeat interval. The ``ws1feed`` host below comes from the official
    # SDK's jWebSocket transport, not from the docs.
    PRIMARY_URL = get_ws_feed_url(use_uat=False)
    UAT_URL = get_ws_feed_url(use_uat=True)

    # Note: Trade/Order WebSocket is at wss://openapi.motilaloswal.com/ws (uses JSON)

    # Maximum reconnection attempts
    MAX_RECONNECT_ATTEMPTS = 5

    # WebSocket version
    WEBSOCKET_VERSION = "1.0.0"

    def __init__(
        self,
        client_id: str,
        auth_token: str,
        api_key: str,
        use_uat: bool = False,
        token_provider=None,
    ):
        """
        Initialize the Motilal Oswal WebSocket client.

        Args:
            client_id (str): Motilal Oswal client ID
            auth_token (str): Authentication token obtained from login
            api_key (str): App API key (BROKER_API_KEY)
            use_uat (bool): Whether to use UAT environment (default: False)
            token_provider (callable): Optional zero-arg callable returning a fresh
                auth token from the database. Invoked before each reconnect attempt
                so daily token rollover (~3 AM IST) does not leave the feed dead.
        """
        self.client_id = client_id
        self.auth_token = auth_token
        self.api_key = api_key
        self.token_provider = token_provider
        self.use_uat = use_uat
        self.ws_url = get_ws_feed_url(use_uat)
        if use_uat:
            # The broadcast feed host is undocumented (see class docstring), so
            # the UAT host below is inferred, not verified. Say so loudly rather
            # than silently connecting somewhere the caller did not ask for --
            # the previous code aliased UAT to production, which meant
            # use_uat=True quietly streamed live production data.
            logger.warning(
                "Motilal broadcast feed UAT host %s is NOT documented and is unverified; "
                "if it fails, no UAT market-data feed is known to exist.",
                self.ws_url,
            )

        # Connection state
        self.ws = None
        self.is_connected = False
        self.reconnect_count = 0
        self.lock = threading.Lock()
        self.last_message_time = datetime.now()

        # Subscription tracking
        self.subscribed_scrips = {}  # Format: "exchange|exchange_type|scripcode" -> instrument info
        self.subscribed_indices = set()  # Set of subscribed indices (NSE, BSE)
        self.subscriptions = {}  # "<MOTILAL_EXCHANGE>|<scrip>" -> instrument info

        # KEY SCHEME (read this before touching any store below)
        # -----------------------------------------------------
        # Every store is keyed "<MOTILAL_EXCHANGE_NAME>:<scrip_code>", e.g.
        # "NSE:2885" / "NSEFO:35001" / "MCX:239484". The full Motilal exchange
        # name is used -- NOT the single wire character -- because NSE and NSEFO
        # share the wire character 'N' (they are told apart on the wire only by
        # the CASH/DERIVATIVES segment character, which the inbound broadcast
        # packet header does not carry). Keying on 'N' collided cash and F&O
        # tokens, and it also made the parser look up subscriptions under "NSE|"
        # while register_scrip() had stored them under "NSEFO|", so every F&O
        # packet resolved to symbol=None.
        #
        # data.py and motilal_adapter.py call get_quote()/get_market_depth()/
        # get_open_interest()/get_index() with the full Motilal exchange name,
        # so those accessors build the same key directly.
        #
        # Inbound packets carry only the wire character, so _scrip_exchange
        # below maps (wire_char, scrip_code) -> full exchange name using what
        # register_scrip() recorded. Registering the same numeric token under
        # both NSE and NSEFO is genuinely unresolvable from the packet alone;
        # the first registration wins and a warning is logged (in practice NSE
        # cash and NFO token ranges are disjoint).
        self._scrip_exchange = {}  # (exchange_char, scrip_code) -> exchange name

        # Data storage
        self.last_quotes = {}  # EXCHANGE:token -> quote data
        self.last_depth = {}  # EXCHANGE:token -> depth data
        self.last_oi = {}  # EXCHANGE:token -> OI data
        self.last_index = {}  # EXCHANGE:token -> index data

        # Threading
        self._connect_thread = None
        self._stop_event = threading.Event()
        self._heartbeat_thread = None
        # Pending delayed_reconnect daemons spawned from on_close(); tracked so
        # disconnect() can wait for them and so they exit early when _stop_event fires.
        self._reconnect_threads = []
        self._reconnect_threads_lock = threading.Lock()
        # Flag set while we are intentionally closing a stale WebSocketApp inside
        # the retry loop. The resulting on_close() callback must NOT spawn a
        # delayed_reconnect — the retry loop is already about to create a fresh
        # connection, and racing two connect()s corrupts subscription state.
        self._closing_old_ws = False

    def connect(self):
        """
        Establishes the WebSocket connection and starts the connection thread.
        """
        if self._connect_thread and self._connect_thread.is_alive():
            logger.info("Motilal WebSocket connection thread is already running")
            return

        # Reset the stop event
        self._stop_event.clear()

        # Start the connection in a separate thread
        self._connect_thread = threading.Thread(target=self._connect_with_retry)
        self._connect_thread.daemon = True
        self._connect_thread.start()

        # Start heartbeat thread
        self._start_heartbeat()

    def _connect_with_retry(self):
        """
        Attempts to connect to the WebSocket with exponential backoff retry logic.
        """
        attempt = 0

        # Indian broker tokens roll over daily (~3 AM IST). Re-read a fresh token
        # from the database before connecting so a reconnect after rollover uses
        # a live token instead of the dead construction-time one. Keep the
        # existing token if the provider returns nothing.
        if self.token_provider is not None:
            try:
                fresh_token = self.token_provider()
                if fresh_token:
                    self.auth_token = fresh_token
                else:
                    logger.warning(
                        "Motilal token_provider returned no token; keeping existing auth token"
                    )
            except Exception as token_err:
                logger.warning(
                    f"Motilal token_provider failed; keeping existing auth token: {token_err}"
                )

        while not self._stop_event.is_set() and attempt < self.MAX_RECONNECT_ATTEMPTS:
            try:
                logger.info(f"Connecting to Motilal Oswal WebSocket: {self.ws_url}")
                websocket.enableTrace(False)

                # Close the previous WebSocketApp before overwriting self.ws so
                # the underlying socket fd is released on retry attempts. Set
                # _closing_old_ws first so the on_close callback knows not to
                # schedule another reconnect (this loop already will).
                old_ws = self.ws
                if old_ws is not None:
                    self._closing_old_ws = True
                    try:
                        old_ws.close()
                    except Exception as close_err:
                        logger.debug(f"Error closing stale WebSocketApp: {close_err}")
                    finally:
                        self._closing_old_ws = False

                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                )

                # Reset reconnect count on successful connection attempt
                self.reconnect_count = 0

                # Run the WebSocket connection with SSL certificate verification disabled
                # Note: Disabled due to Motilal Oswal's expired SSL certificate
                self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

                # If we're here, the connection was closed
                if self.is_connected:
                    # If it was a clean disconnect, break the retry loop
                    break

            except Exception as e:
                logger.error(f"Error connecting to Motilal WebSocket: {str(e)}")

            # If we should stop or connection was successful, break the retry loop
            if self._stop_event.is_set() or self.is_connected:
                break

            # Exponential backoff for reconnection attempts
            attempt += 1
            sleep_time = min(2**attempt, 30)  # Max 30 seconds between retries
            logger.debug(
                f"Reconnection attempt {attempt}/{self.MAX_RECONNECT_ATTEMPTS} failed. Retrying in {sleep_time}s"
            )
            # Interruptible backoff so disconnect() doesn't wait out the full delay.
            if self._stop_event.wait(timeout=sleep_time):
                break

        if attempt >= self.MAX_RECONNECT_ATTEMPTS and not self.is_connected:
            logger.error(
                "Maximum reconnection attempts reached. Could not connect to Motilal WebSocket."
            )

    def disconnect(self):
        """
        Disconnects from the WebSocket and stops all threads.
        """
        self._stop_event.set()

        # Stop heartbeat thread (currently disabled in _start_heartbeat, but
        # join here so re-enabling it later doesn't silently leak a thread).
        if (
            self._heartbeat_thread
            and self._heartbeat_thread.is_alive()
            and self._heartbeat_thread is not threading.current_thread()
        ):
            self._heartbeat_thread.join(timeout=2)
            if self._heartbeat_thread.is_alive():
                logger.warning(
                    "Motilal heartbeat thread did not exit within 2s of disconnect"
                )
        self._heartbeat_thread = None

        if self.ws:
            logger.info("Closing Motilal WebSocket connection")
            # Send logout message before closing.
            # UNVERIFIED FRAME: this JSON is copied from doc 34-trade-websocket.md,
            # which describes the *trade* socket (wss://openapi.motilaloswal.com/ws).
            # The broadcast feed here is a different, binary transport and the docs
            # define no logout frame for it, so the server may well ignore this.
            # It is harmless (we close the socket immediately after) and is kept
            # only because nothing better is documented.
            try:
                logout_msg = {"clientid": self.client_id, "action": "logout"}
                self.ws.send(json.dumps(logout_msg))
            except Exception as e:
                logger.error(f"Error sending logout message: {str(e)}")

            self.ws.close()

        self.is_connected = False

        # Wait for any pending delayed_reconnect daemons to exit. _stop_event was
        # set above, so they short-circuit on _stop_event.wait() and return quickly.
        with self._reconnect_threads_lock:
            pending = [t for t in self._reconnect_threads if t.is_alive()]
            self._reconnect_threads = []
        for t in pending:
            t.join(timeout=2)
            if t.is_alive():
                logger.warning("Motilal delayed_reconnect thread did not exit within 2s")

        # Join the connect thread so run_forever() actually unwinds before we
        # declare the adapter disconnected. Without this the thread leaks one
        # OS thread per session teardown. Skip the join if disconnect() is
        # being invoked from within the connect thread itself (e.g. via an
        # on_close callback) to avoid a self-join deadlock.
        if (
            self._connect_thread
            and self._connect_thread.is_alive()
            and self._connect_thread is not threading.current_thread()
        ):
            self._connect_thread.join(timeout=5)
            if self._connect_thread.is_alive():
                logger.warning(
                    "Motilal connect thread did not exit within 5s of disconnect"
                )
        self._connect_thread = None

        logger.info("Motilal WebSocket disconnected")

    def on_open(self, ws):
        """
        Called when the WebSocket connection is established.
        Sends the BINARY 'Q' login packet that identifies this session.

        What the 'Q' packet actually carries (audited field by field against the
        struct format below): message type 'Q', a fixed 111, then the client code
        twice -- once length-prefixed in a 15-byte field and again length-prefixed
        in a 30-byte field -- then three flag bytes, the length-prefixed 10-byte
        client version, five more flag bytes and 45 bytes of spaces. 114 bytes
        total. So the frame DOES convey identity (the client code), but it does
        NOT carry ``self.auth_token`` or ``self.api_key``.

        Why no JSON auth frame is sent here:
          * doc 33-websocket-broadcast.md says "AuthValidation is necessary before
            using OpenAPI WebSocket Broadcast", i.e. you must have completed the
            REST login first -- it does not describe an in-band handshake, and it
            never shows one.
          * The only concrete handshake in the docs,
            {"clientid", "authtoken", "apikey"}, belongs to doc 34, which documents
            the *trade* socket at wss://openapi.motilaloswal.com/ws. That is a
            different transport (JSON), a different host and a different feed.
          * This binary socket currently works: the server answers the 'Q' packet
            with binary frames, which is what marks us authenticated in
            on_message(). Injecting a text frame the server was never documented
            to expect risks a protocol error / disconnect on a working path.
        Left as-is deliberately. If the feed ever starts rejecting logins, the
        30-byte field is the prime suspect: it is length-prefixed separately from
        the 15-byte client-code field, which is the shape of a credential slot
        (the SDK likely puts a password/token there) yet this code fills it with
        the client code again.

        Args:
            ws: WebSocket instance
        """
        logger.info("Motilal WebSocket connection opened")

        try:
            # Create binary login packet using struct.pack
            # Format: "=cHB15sB30sBBBB10sBBBBB45s"
            msg_type = b"Q"
            clientcode = self.client_id
            version = self.WEBSOCKET_VERSION

            # Pad strings to required lengths
            clientcode_15 = clientcode.ljust(15, " ").encode()
            clientcode_30 = clientcode.ljust(30, " ").encode()
            version_10 = version.ljust(10, " ").encode()
            padding_45 = (" " * 45).encode()

            # Build binary login packet
            login_packet = pack(
                "=cHB15sB30sBBBB10sBBBBB45s",
                msg_type,  # 'Q' for login
                111,  # Fixed value
                len(clientcode),  # Client code length
                clientcode_15,  # Client code (15 bytes)
                len(clientcode),  # Client code length (repeated)
                clientcode_30,  # Client code (30 bytes)
                1,
                1,
                1,  # Flags
                len(version),  # Version length
                version_10,  # Version (10 bytes)
                0,
                0,
                0,
                0,
                1,  # More flags
                padding_45,  # Padding (45 bytes)
            )

            # Send binary login packet
            ws.send(login_packet, opcode=websocket.ABNF.OPCODE_BINARY)
            logger.debug(f"Motilal WebSocket binary login packet sent ({len(login_packet)} bytes)")
            logger.debug(f"Login packet (hex): {login_packet.hex()}")

            # Don't mark as connected yet - wait for server response

        except Exception as e:
            logger.error(f"Error sending login packet: {str(e)}")

    def on_message(self, ws, message):
        """
        Called when a message is received from the WebSocket.
        Parses BINARY message and updates the appropriate data storage.

        Args:
            ws: WebSocket instance
            message: BINARY message received from the WebSocket
        """
        try:
            self.last_message_time = datetime.now()

            # Motilal sends BINARY data, not JSON
            if isinstance(message, bytes):
                logger.debug(f"Received binary message: {len(message)} bytes")
                logger.debug(f"Binary data (hex): {message.hex()}")

                # Mark as connected when we receive first message (login response)
                if not self.is_connected:
                    with self.lock:
                        self.is_connected = True
                    logger.info(
                        "Motilal WebSocket connection authenticated (received binary response)"
                    )

                    # Resubscribe to any previous subscriptions
                    self._resubscribe()

                # Parse binary market data packets
                # The exact format depends on the data type, but we can identify by message structure
                if len(message) > 0:
                    msg_type = chr(message[0]) if message[0] < 128 else f"0x{message[0]:02x}"
                    logger.debug(f"Binary message type: {msg_type}, length: {len(message)}")

                    # Try to parse if it looks like market data
                    self._parse_binary_market_data(message)

            else:
                # Might be a text response (error, etc.)
                logger.debug(f"Received text message: {message[:200]}")
                try:
                    data = json.loads(message)
                    if "status" in data and data.get("status") == "ERROR":
                        error_msg = data.get("message", "Unknown error")
                        logger.error(f"Motilal WebSocket error: {error_msg}")
                except (json.JSONDecodeError, ValueError):
                    pass

        except Exception as e:
            logger.error(f"Error processing WebSocket message: {str(e)}")

    def _parse_binary_market_data(self, message: bytes):
        """
        Parse binary market data packets from Motilal Oswal.

        Packet structure (30 bytes minimum):
        - Byte 0: Exchange (1 char)
        - Bytes 1-4: Scrip code (4 bytes, little-endian int)
        - Bytes 5-8: Timestamp (4 bytes, little-endian int)
        - Byte 9: Message type (1 char)
        - Bytes 10-29: Message body (20 bytes, varies by type)

        Args:
            message: Binary message bytes
        """
        try:
            # Handle bulk messages (multiple 30-byte packets)
            packet_size = 30
            num_packets = len(message) // packet_size

            for i in range(num_packets):
                offset = i * packet_size
                packet = message[offset : offset + packet_size]

                if len(packet) < packet_size:
                    continue

                # Parse header (10 bytes)
                exchange_byte = packet[0:1].decode("utf-8", errors="ignore")
                scrip = int.from_bytes(packet[1:5], byteorder="little", signed=True)
                timestamp = int.from_bytes(packet[5:9], byteorder="little", signed=True)
                msgtype = packet[9:10].decode("utf-8", errors="ignore")

                # Parse body (20 bytes) based on message type
                body = packet[10:30]

                # Resolve the wire character back to the full Motilal exchange
                # name recorded at registration time, so the store key matches
                # what register_scrip() used and what the accessors look up.
                # See the KEY SCHEME note in __init__.
                exchange_name = self._resolve_exchange_name(exchange_byte, scrip)
                key = self._store_key(exchange_name, scrip)

                # Look up the original subscription to get the symbol
                subscription_key = f"{exchange_name}|{scrip}"
                symbol = None
                with self.lock:
                    subscription = self.subscriptions.get(subscription_key)
                    if subscription is not None:
                        symbol = subscription.symbol

                # Log what we're parsing
                logger.debug(
                    f"Parsing packet: Exchange={exchange_byte}({exchange_name}), Scrip={scrip}, MsgType='{msgtype}', Key={key}, Symbol={symbol}"
                )

                # Detailed logging for subscribed scrips to analyze unknown packets
                if subscription is not None:
                    logger.debug(
                        f"SUBSCRIBED SCRIP DATA: {key} ({symbol}) - MsgType='{msgtype}' (ASCII {ord(msgtype) if msgtype else 'None'}), BodyHex={body.hex()}"
                    )

                # Parse based on message type
                # Message types from Motilal SDK:
                # 'A' = LTP, 'B'-'F' = Depth levels 1-5, 'G' = OHLC, 'H' = Index, 'm' = OI
                if msgtype in ["B", "C", "D", "E", "F"]:  # Market Depth levels 1-5
                    level = ord(msgtype) - ord("B") + 1  # B=1, C=2, D=3, E=4, F=5
                    logger.debug(
                        f"Parsing DEPTH level {level} (msgtype='{msgtype}') packet for {key}, Symbol: {symbol}"
                    )
                    self._parse_depth_level_packet(body, key, symbol, level)
                elif msgtype == "A":  # LTP
                    logger.debug(f"Parsing LTP packet for {key}")
                    self._parse_ltp_packet(body, key, symbol)
                elif msgtype == "G":  # Day OHLC
                    logger.debug(f"Parsing OHLC packet for {key}")
                    self._parse_ohlc_packet(body, key, symbol)
                elif msgtype == "H":  # Index data
                    logger.debug(f"Parsing INDEX packet for {key}")
                    self._parse_index_packet(body, key, symbol)
                elif msgtype == "m":  # Open Interest
                    logger.debug(f"Parsing OI packet for {key}")
                    self._parse_oi_packet(body, key, symbol)
                elif msgtype == "W":  # DPR (circuit limits)
                    logger.debug(f"Parsing DPR packet for {key}")
                    self._parse_dpr_packet(body, key, symbol)
                elif msgtype == "1":  # Heartbeat
                    logger.debug("Heartbeat received")
                elif msgtype == "X":  # Unknown - need to investigate
                    logger.debug(f"Received message type 'X' for {key} - investigating")
                elif msgtype == "g":  # Lowercase 'g' - possibly alternate OHLC or tick data
                    logger.debug(f"Packet 'g' for {key}: {body.hex()}")
                elif msgtype == "z":  # Lowercase 'z' - unknown supplementary data
                    logger.debug(f"Packet 'z' for {key}: {body.hex()}")
                elif msgtype == "Y":  # Uppercase 'Y' - exchange-specific data
                    logger.debug(f"Packet 'Y' for {key}: {body.hex()}")
                else:
                    # Debug, not warning: Motilal's broadcast feed carries
                    # undocumented supplementary packet types ('M' on index
                    # tokens, etc.) alongside the ones parsed above. They arrive
                    # per tick, so warning-level logging floods the log with
                    # thousands of identical lines while the feed is working
                    # perfectly - every field OpenAlgo needs comes from the
                    # packet types handled above. Kept at debug so the raw body
                    # is still recoverable when a new packet type has to be
                    # reverse-engineered (the feed protocol is undocumented -
                    # see this module's docstring).
                    logger.debug(
                        f"Unhandled message type '{msgtype}' "
                        f"(ASCII {ord(msgtype) if msgtype else 'None'}) for {key}, "
                        f"body: {body.hex()}"
                    )

        except Exception as e:
            logger.error(f"Error parsing binary market data: {str(e)}")

    def _map_exchange_back(self, exchange_char: str) -> str:
        """Map single wire character back to a full exchange name.

        Lossy by construction: 'N' is used on the wire by both NSE and NSEFO,
        so this returns "NSE". Only used as the fallback for packets that were
        never registered as scrips (e.g. index broadcasts). Registered scrips
        go through _resolve_exchange_name(), which is exact.
        """
        mapping = {"N": "NSE", "B": "BSE", "M": "MCX", "C": "NSECD", "D": "NCDEX", "G": "BSEFO"}
        return mapping.get(exchange_char, exchange_char)

    @staticmethod
    def _store_key(exchange_name: str, scrip_code) -> str:
        """Canonical key for last_quotes / last_depth / last_oi / last_index."""
        return f"{str(exchange_name).upper()}:{scrip_code}"

    def _resolve_exchange_name(self, exchange_char: str, scrip_code: int) -> str:
        """Full Motilal exchange name for an inbound packet's wire character.

        Uses the (char, scrip) -> exchange map that register_scrip() fills, so
        an NSEFO packet is stored under "NSEFO:<token>" and not "NSE:<token>".
        Falls back to the lossy character mapping for unregistered scrips.
        """
        with self.lock:
            resolved = self._scrip_exchange.get((exchange_char, scrip_code))
        return resolved or self._map_exchange_back(exchange_char)

    def _parse_depth_level_packet(self, body: bytes, key: str, symbol: str, level: int):
        """
        Parse market depth packet for a specific level (20 bytes).

        Args:
            body: 20-byte packet body
            key: Exchange:Scrip key
            symbol: Trading symbol
            level: Depth level (1-5)
        """
        try:
            # Market depth format (doc 33 MarketDepth field order:
            # BidRate, BidQty, BidOrder, OfferRate, OfferQty, OfferOrder):
            # Bytes 0-3: BidRate (float)
            # Bytes 4-7: BidQty (int)
            # Bytes 8-9: BidOrder (short)
            # Bytes 10-13: OfferRate (float)
            # Bytes 14-17: OfferQty (int)
            # Bytes 18-19: OfferOrder (short)
            # Rates are already in rupees (doc 33 sample: 'BidRate': 3636.8) --
            # do NOT divide by 100 here; the paisa scaling in doc 26 applies to
            # the REST LTP endpoint only.

            bid_rate = unpack("<f", body[0:4])[0]
            bid_qty = int.from_bytes(body[4:8], byteorder="little", signed=True)
            bid_order = int.from_bytes(body[8:10], byteorder="little", signed=True)
            offer_rate = unpack("<f", body[10:14])[0]
            offer_qty = int.from_bytes(body[14:18], byteorder="little", signed=True)
            offer_order = int.from_bytes(body[18:20], byteorder="little", signed=True)

            # Store depth data
            with self.lock:
                if key not in self.last_depth:
                    # Initialize with 5 empty levels
                    self.last_depth[key] = {
                        "bids": [None] * 5,
                        "asks": [None] * 5,
                        "symbol": symbol,
                    }

                # Create bid/ask data for this level
                bid_data = {"price": round(bid_rate, 2), "quantity": bid_qty, "orders": bid_order}
                ask_data = {
                    "price": round(offer_rate, 2),
                    "quantity": offer_qty,
                    "orders": offer_order,
                }

                # Store at the correct level index (level-1 for 0-indexed array)
                level_index = level - 1
                if 0 <= level_index < 5:
                    self.last_depth[key]["bids"][level_index] = bid_data
                    self.last_depth[key]["asks"][level_index] = ask_data
                    logger.debug(
                        f"Depth level {level} stored for {key} ({symbol}): Bid={bid_data['price']}@{bid_qty}, Ask={ask_data['price']}@{offer_qty}"
                    )

        except Exception as e:
            logger.error(f"Error parsing depth level {level} packet: {str(e)}")

    def _parse_ltp_packet(self, body: bytes, key: str, symbol: str):
        """Parse LTP packet (20 bytes = five 4-byte fields).

        doc 33-websocket-broadcast.md LTP structure, in this exact order:
            LTP_Rate            3636.8   -> float, rupees
            LTP_Qty             4        -> int, LAST TRADED quantity
            LTP_Cumulative Qty  75937    -> int, the day's cumulative volume
            LTP_AvgTradePrice   3627.39  -> float, rupees
            LTP_Open Interest   0        -> int

        Note the second field is the last traded quantity, NOT volume: volume is
        the third field. This parser previously read only the first two fields
        and stored LTP_Qty as "volume", so "volume" carried a single trade's size
        and the average price / OI never arrived at all.
        """
        try:
            rate = unpack("<f", body[0:4])[0]
            ltq = int.from_bytes(body[4:8], byteorder="little", signed=True)
            cumulative_qty = int.from_bytes(body[8:12], byteorder="little", signed=True)
            avg_trade_price = unpack("<f", body[12:16])[0]
            open_interest = int.from_bytes(body[16:20], byteorder="little", signed=True)

            with self.lock:
                if key not in self.last_quotes:
                    self.last_quotes[key] = {"symbol": symbol}
                self.last_quotes[key].update(
                    {
                        "ltp": round(rate, 2),
                        "ltq": ltq,
                        "volume": cumulative_qty,
                        "avg_trade_price": round(avg_trade_price, 2),
                        # Both spellings: motilal_adapter.py reads "oi",
                        # broker/motilal/api/data.py reads "open_interest".
                        "oi": open_interest,
                        "open_interest": open_interest,
                    }
                )

            logger.debug(
                f"LTP updated for {key}: ltp={rate} ltq={ltq} volume={cumulative_qty} "
                f"avg={avg_trade_price} oi={open_interest}"
            )
        except Exception as e:
            logger.error(f"Error parsing LTP packet: {str(e)}")

    def _parse_dpr_packet(self, body: bytes, key: str, symbol: str):
        """Parse DPR (Daily Price Range / circuit limits) packet.

        doc 33 DPR structure: {'UpperCktLimit': 3959.9, 'LowerCktLimit': 3240.0}
        -- two floats in rupees, in that order.
        """
        try:
            upper_circuit = unpack("<f", body[0:4])[0]
            lower_circuit = unpack("<f", body[4:8])[0]

            with self.lock:
                if key not in self.last_quotes:
                    self.last_quotes[key] = {"symbol": symbol}
                self.last_quotes[key].update(
                    {
                        "upper_circuit": round(upper_circuit, 2),
                        "lower_circuit": round(lower_circuit, 2),
                    }
                )

            logger.debug(f"DPR updated for {key}: upper={upper_circuit} lower={lower_circuit}")
        except Exception as e:
            logger.error(f"Error parsing DPR packet: {str(e)}")

    def _parse_ohlc_packet(self, body: bytes, key: str, symbol: str):
        """Parse Day OHLC packet.

        doc 33 DayOHLC structure: Open, High, Low, PrevDayClose -- four floats
        in rupees ('Open': 3610.0), in that order.
        """
        try:
            open_price = unpack("<f", body[0:4])[0]
            high_price = unpack("<f", body[4:8])[0]
            low_price = unpack("<f", body[8:12])[0]
            close_price = unpack("<f", body[12:16])[0]

            with self.lock:
                if key not in self.last_quotes:
                    self.last_quotes[key] = {"symbol": symbol}
                self.last_quotes[key].update(
                    {
                        "open": round(open_price, 2),
                        "high": round(high_price, 2),
                        "low": round(low_price, 2),
                        "prev_close": round(close_price, 2),
                    }
                )

            logger.debug(f"OHLC updated for {key}")
        except Exception as e:
            logger.error(f"Error parsing OHLC packet: {str(e)}")

    def _parse_oi_packet(self, body: bytes, key: str, symbol: str):
        """Parse Open Interest packet.

        doc 33 OpenInterest structure, in this order:
            'Open Interest', 'Open Interest High', 'Open Interest Low'
        -- three ints. Only the first was read before, so the high/low were lost.
        """
        try:
            oi = int.from_bytes(body[0:4], byteorder="little", signed=True)
            oi_high = int.from_bytes(body[4:8], byteorder="little", signed=True)
            oi_low = int.from_bytes(body[8:12], byteorder="little", signed=True)

            with self.lock:
                self.last_oi[key] = {
                    "symbol": symbol,
                    # Both spellings: motilal_adapter.py reads "oi",
                    # broker/motilal/api/data.py reads "open_interest".
                    "oi": oi,
                    "open_interest": oi,
                    "oi_high": oi_high,
                    "oi_low": oi_low,
                }

                # Keep the quote view in sync for consumers that read OI there.
                if key in self.last_quotes:
                    self.last_quotes[key]["oi"] = oi
                    self.last_quotes[key]["open_interest"] = oi

            logger.debug(f"OI updated for {key}: oi={oi} high={oi_high} low={oi_low}")
        except Exception as e:
            logger.error(f"Error parsing OI packet: {str(e)}")

    def _parse_index_packet(self, body: bytes, key: str, symbol: str):
        """Parse Index data packet (for index symbols like NIFTY, SENSEX).

        doc 33 Index structure: {'Rate': 16284.25} -- a single float in rupees.
        Written to both last_index (read by get_index()/data.py as "rate") and
        last_quotes (read as "ltp"). Previously only last_quotes was written
        while get_index() read last_index, so get_index() always returned None.
        """
        try:
            index_value = round(unpack("<f", body[0:4])[0], 2)

            with self.lock:
                if key not in self.last_quotes:
                    self.last_quotes[key] = {"symbol": symbol}
                self.last_quotes[key]["ltp"] = index_value

                self.last_index[key] = {
                    "symbol": symbol,
                    "rate": index_value,
                    "ltp": index_value,
                    "timestamp": datetime.now().isoformat(),
                }

            logger.debug(f"Index value updated for {key}: {index_value}")
        except Exception as e:
            logger.error(f"Error parsing index packet: {str(e)}")

    # ------------------------------------------------------------------
    # REMOVED: a dead parallel JSON implementation (_process_market_data and
    # its _process_dayohlc / _process_ltp / _process_dpr / _process_depth /
    # _process_oi / _process_index helpers). It had ZERO callers anywhere in
    # the repo -- this broadcast feed is binary, so nothing ever handed it a
    # dict -- yet it divided every price by 100 while the live binary parsers
    # above divide nothing. That contradiction inside one file was an invitation
    # to "fix" the live path in the wrong direction, so the dead path is gone.
    #
    # The live no-division path is the correct one: doc 33-websocket-broadcast.md
    # quotes rupees throughout ('LTP_Rate': 3636.8, 'Open': 3610.0,
    # 'BidRate': 3636.8, 'Rate': 16284.25). The paisa note in doc 26 applies to
    # the REST LTP endpoint, not to this feed.
    #
    # The one thing worth keeping was its field-name knowledge, now recorded in
    # the docstrings of the live parsers above -- in particular
    # volume == LTP_Cumulative Qty (not LTP_Qty), see _parse_ltp_packet.
    # ------------------------------------------------------------------

    def on_error(self, ws, error):
        """
        Called when an error occurs in the WebSocket connection.

        Args:
            ws: WebSocket instance
            error: Error information
        """
        logger.error(f"Motilal WebSocket error: {str(error)}")
        with self.lock:
            self.is_connected = False

    def on_close(self, ws, close_status_code, close_msg):
        """
        Called when the WebSocket connection is closed.

        Args:
            ws: WebSocket instance
            close_status_code: Status code for the close
            close_msg: Close message
        """
        with self.lock:
            self.is_connected = False

        logger.debug(f"Motilal WebSocket connection closed: {close_status_code}, {close_msg}")

        # Skip reconnect if we explicitly stopped, or if this on_close was
        # triggered by the retry loop intentionally closing a stale WebSocketApp
        # (in which case the retry loop is about to open a fresh one itself).
        if self._closing_old_ws:
            logger.debug("on_close from stale WebSocketApp closure; skipping reconnect")
            return

        if not self._stop_event.is_set():
            self.reconnect_count += 1

            # Reconnect with exponential backoff
            sleep_time = min(2**self.reconnect_count, 30)
            logger.info(f"Attempting to reconnect in {sleep_time} seconds")

            def delayed_reconnect():
                # wait() returns True if the stop event fires during the backoff,
                # so we abort instead of racing a fresh connect() against disconnect().
                if self._stop_event.wait(timeout=sleep_time):
                    return
                self.connect()

            with self._reconnect_threads_lock:
                # prune dead refs to keep the list bounded
                self._reconnect_threads = [
                    th for th in self._reconnect_threads if th.is_alive()
                ]
                # One pending reconnect is all that is ever useful: connect()
                # short-circuits while a connect thread is alive, so a burst of
                # on_close events (several WebSocketApps unwinding together, a
                # flapping link) would otherwise leave N threads sleeping on a
                # backoff of up to 30s each to accomplish one reconnect.
                if self._reconnect_threads:
                    logger.debug("A Motilal reconnect is already pending; not scheduling another")
                    return
                t = threading.Thread(target=delayed_reconnect, daemon=True)
                self._reconnect_threads.append(t)
            t.start()

    def register_scrip(
        self, exchange: str, exchange_type: str, scrip_code: int, symbol: str = None
    ):
        """
        Register a scrip for market data updates using BINARY packet.

        Args:
            exchange (str): Exchange code (BSE, NSE, NSEFO, NSECD, MCX, BSEFO)
            exchange_type (str): Exchange type (CASH, DERIVATIVES)
            scrip_code (int): Scrip code/token
            symbol (str): OpenAlgo symbol (optional, for reference)

        Returns:
            bool: True if registration successful, False otherwise
        """
        exchange_upper = exchange.upper()
        scrip_code = int(scrip_code)

        with self.lock:
            if not self.is_connected:
                logger.error("Cannot register scrip: WebSocket is not connected")
                return False

            # Create subscription key. Uses the full Motilal exchange name, which
            # is exactly what _parse_binary_market_data() resolves inbound packets
            # to -- see the KEY SCHEME note in __init__.
            subscription_key = f"{exchange_upper}|{scrip_code}"

            # Store subscription
            self.subscriptions[subscription_key] = type(
                "obj",
                (object,),
                {
                    "exchange": exchange_upper,
                    "exchange_type": exchange_type,
                    "scrip_code": scrip_code,
                    "symbol": symbol,
                },
            )()

            # Also store in subscribed_scrips for resubscription
            full_key = f"{exchange_upper}|{exchange_type}|{scrip_code}"
            self.subscribed_scrips[full_key] = {
                "exchange": exchange_upper,
                "exchange_type": exchange_type,
                "scrip_code": scrip_code,
                "symbol": symbol,
            }

            # Map exchange to the single wire character.
            # N=NSE and NSEFO, B=BSE, M=MCX, C=NSECD, D=NCDEX, G=BSEFO.
            exchange_char = self._map_exchange_to_char(exchange_upper)

            # Record how to resolve inbound packets for this scrip back to the
            # full exchange name (the packet header carries only the character).
            existing = self._scrip_exchange.get((exchange_char, scrip_code))
            if existing is None:
                self._scrip_exchange[(exchange_char, scrip_code)] = exchange_upper
            elif existing != exchange_upper:
                # e.g. the same numeric token registered under both NSE (CASH)
                # and NSEFO (DERIVATIVES). The broadcast header has no segment
                # byte, so the two are indistinguishable on the wire; keep the
                # first registration and say so rather than silently mixing them.
                logger.warning(
                    "Motilal scrip %s on wire exchange '%s' is already registered as %s; "
                    "%s packets cannot be told apart and will be stored under %s:%s",
                    scrip_code,
                    exchange_char,
                    existing,
                    exchange_upper,
                    existing,
                    scrip_code,
                )

            # Map exchange type to single character (C=CASH, D=DERIVATIVES)
            exchange_type_char = exchange_type.upper()[0]

            # Create binary register packet
            # Format: "=cHcciB" - msg_type, size, exchange, exchange_type, scrip_code, add_to_list
            try:
                msg_type = b"D"
                exchange_byte = exchange_char.encode()
                exchange_type_byte = exchange_type_char.encode()
                add_to_list = 1  # 1 for register, 0 for unregister

                register_packet = pack(
                    "=cHcciB",
                    msg_type,  # 'D' for data subscription
                    7,  # Fixed size
                    exchange_byte,  # Exchange (1 char)
                    exchange_type_byte,  # Exchange type (1 char)
                    scrip_code,  # Scrip code (int)
                    add_to_list,  # 1 to add
                )

                self.ws.send(register_packet, opcode=websocket.ABNF.OPCODE_BINARY)
                logger.debug(
                    f"Registered scrip: {exchange} {exchange_type} {scrip_code} (Symbol: {symbol})"
                )
                return True
            except Exception as e:
                logger.error(f"Error sending register packet: {str(e)}")
                return False

    def unregister_scrip(self, exchange: str, exchange_type: str, scrip_code: int):
        """
        Unregister a scrip from market data updates using BINARY packet.

        Args:
            exchange (str): Exchange code
            exchange_type (str): Exchange type (CASH, DERIVATIVES)
            scrip_code (int): Scrip code/token

        Returns:
            bool: True if unregistration successful, False otherwise
        """
        exchange_upper = exchange.upper()
        scrip_code = int(scrip_code)

        with self.lock:
            if not self.is_connected:
                logger.error("Cannot unregister scrip: WebSocket is not connected")
                return False

            # Remove from subscriptions (same key scheme as register_scrip)
            subscription_key = f"{exchange_upper}|{scrip_code}"
            if subscription_key in self.subscriptions:
                del self.subscriptions[subscription_key]

            full_key = f"{exchange_upper}|{exchange_type}|{scrip_code}"
            if full_key in self.subscribed_scrips:
                del self.subscribed_scrips[full_key]

            # Map exchange to the single wire character
            exchange_char = self._map_exchange_to_char(exchange_upper)

            # Drop the packet-resolution entry only if it still points at us, so
            # unregistering NSE does not orphan an NSEFO registration sharing 'N'.
            if self._scrip_exchange.get((exchange_char, scrip_code)) == exchange_upper:
                del self._scrip_exchange[(exchange_char, scrip_code)]

            # Drop the cached tick data for this scrip. These three dicts are
            # written on every inbound packet and used to be purged nowhere: the
            # entry outlived the subscription. That was survivable while each
            # request abandoned its own short-lived client, but the socket is
            # pooled per session now (see data.py's _WS_REGISTRY), so the caches
            # live as long as the login and would otherwise accumulate one entry
            # per distinct scrip ever quoted - an option-chain sweep touches
            # hundreds of strikes per refresh.
            store_key = self._store_key(exchange_upper, scrip_code)
            self.last_quotes.pop(store_key, None)
            self.last_depth.pop(store_key, None)
            self.last_oi.pop(store_key, None)

            # Map exchange type to single character
            exchange_type_char = exchange_type.upper()[0]

            # Create binary unregister packet (same format as register, but add_to_list = 0)
            try:
                msg_type = b"D"
                exchange_byte = exchange_char.encode()
                exchange_type_byte = exchange_type_char.encode()
                add_to_list = 0  # 0 for unregister

                unregister_packet = pack(
                    "=cHcciB",
                    msg_type,
                    7,
                    exchange_byte,
                    exchange_type_byte,
                    scrip_code,
                    add_to_list,  # 0 to remove
                )

                self.ws.send(unregister_packet, opcode=websocket.ABNF.OPCODE_BINARY)
                logger.debug(f"Unregistered scrip: {exchange} {exchange_type} {scrip_code}")
                return True
            except Exception as e:
                logger.error(f"Error sending unregister packet: {str(e)}")
                return False

    def register_index(self, exchange: str):
        """
        Register an index for market data updates.

        UNVERIFIED FRAME. doc 33-websocket-broadcast.md documents only the SDK
        call ``Mofsl.IndexRegister("NSE")`` -- it never shows the frame that call
        puts on the wire. The JSON below is an invention: it is sent as text on a
        socket whose every other message (login 'Q', scrip register 'D', all
        inbound quotes) is binary, and "IndexRegister" does not appear in doc 34's
        exhaustive action list (TradeSubscribe, TradeUnsubscribe, OrderSubscribe,
        OrderUnsubscribe, logout, heartbeat) either. The real frame is most likely
        a binary packet analogous to register_scrip()'s, but its layout is not
        documented anywhere, so it cannot be derived -- this is left as-is rather
        than replaced with a different guess.

        The signature is part of this module's contract: broker/motilal/api/data.py
        calls register_index(exchange) for NSE_INDEX / BSE_INDEX symbols.

        Args:
            exchange (str): Exchange code (NSE, BSE)

        Returns:
            bool: True if the frame was sent (NOT that the server accepted it)
        """
        with self.lock:
            if not self.is_connected:
                logger.error("Cannot register index: WebSocket is not connected")
                return False

            self.subscribed_indices.add(exchange)

            # Send index registration message (unverified, see docstring)
            index_msg = {
                "clientid": self.client_id,
                "action": "IndexRegister",
                "exchange": exchange,
            }

            try:
                self.ws.send(json.dumps(index_msg))
                logger.debug(f"Registered index: {exchange}")
                return True
            except Exception as e:
                logger.error(f"Error sending index register message: {str(e)}")
                return False

    def unregister_index(self, exchange: str):
        """
        Unregister an index from market data updates.

        UNVERIFIED FRAME -- same caveat as register_index(): doc 33 shows only
        ``Mofsl.IndexUnregister("NSE")``, never the wire frame, and this JSON
        action name is invented.

        Args:
            exchange (str): Exchange code (NSE, BSE)

        Returns:
            bool: True if the frame was sent (NOT that the server accepted it)
        """
        with self.lock:
            if not self.is_connected:
                logger.error("Cannot unregister index: WebSocket is not connected")
                return False

            self.subscribed_indices.discard(exchange)

            # Send index unregistration message (unverified, see docstring)
            index_msg = {
                "clientid": self.client_id,
                "action": "IndexUnregister",
                "exchange": exchange,
            }

            try:
                self.ws.send(json.dumps(index_msg))
                logger.debug(f"Unregistered index: {exchange}")
                return True
            except Exception as e:
                logger.error(f"Error sending index unregister message: {str(e)}")
                return False

    def _resubscribe(self):
        """
        Resubscribes to all previously subscribed scrips and indices after reconnection.
        """
        logger.debug(
            f"Resubscribing to {len(self.subscribed_scrips)} scrips and {len(self.subscribed_indices)} indices"
        )

        # Resubscribe to scrips
        for full_key, scrip_info in self.subscribed_scrips.items():
            self.register_scrip(
                scrip_info["exchange"],
                scrip_info["exchange_type"],
                scrip_info["scrip_code"],
                scrip_info.get("symbol"),
            )

        # Resubscribe to indices
        for exchange in self.subscribed_indices:
            self.register_index(exchange)

    def _start_heartbeat(self):
        """
        Start heartbeat thread to keep connection alive.
        Note: Disabled for now as Motilal's binary protocol heartbeat format is unclear.
        """
        # Heartbeat disabled - Motilal's market data WebSocket may not need it.
        # The official SDK uses auto-reconnection instead, and doc 33 specifies
        # no ping/pong or interval for the broadcast feed (doc 34's
        # {"action": "heartbeat"} belongs to the trade socket).
        # Caveat worth knowing: is_websocket_connected() declares the socket dead
        # after 60s without an inbound message, which is exactly how an illiquid
        # scrip with no keepalive looks. If spurious reconnects show up on quiet
        # instruments, this is the first place to look.
        logger.debug("Heartbeat disabled for binary WebSocket")

    def is_websocket_connected(self):
        """
        Checks if the WebSocket connection is currently active.

        Returns:
            bool: True if connected and receiving messages, False otherwise
        """
        with self.lock:
            if not self.is_connected:
                return False

            # Check if we've received messages in the last minute
            if self.last_message_time is None:
                return False

            time_since_last_message = datetime.now() - self.last_message_time
            return time_since_last_message < timedelta(minutes=1)

    def get_quote(self, exchange: str, scrip_code: str):
        """
        Get the latest quote for an instrument.

        Args:
            exchange (str): Exchange code (full name like NSE, MCX, etc.)
            scrip_code (str): Scrip code/token

        Returns:
            dict: Latest quote data or None if not available
        """
        key = self._store_key(exchange, scrip_code)
        with self.lock:
            quote = self.last_quotes.get(key)
            if quote:
                logger.debug(
                    f"Retrieved quote for {key} - LTP: {quote.get('ltp', 'N/A')}, Symbol: {quote.get('symbol', 'N/A')}"
                )
            else:
                logger.debug(f"No quote data available for {key}")
                logger.debug(f"Available quote keys: {list(self.last_quotes.keys())}")
            return quote

    def _map_exchange_to_char(self, exchange: str) -> str:
        """Map full exchange name to the single WIRE character.

        Used only when building outbound binary packets. It is deliberately NOT
        used to build storage keys: NSE and NSEFO share 'N', so keys built from
        it collided cash and F&O tokens (see the KEY SCHEME note in __init__).
        """
        mapping = {
            "NSE": "N",
            "BSE": "B",
            "MCX": "M",
            "NSECD": "C",
            "NCDEX": "D",
            "BSEFO": "G",
            "NSEFO": "N",  # NSEFO uses 'N' like NSE
        }
        exchange_upper = exchange.upper()
        return mapping.get(exchange_upper, exchange_upper[0] if exchange_upper else "")

    def get_market_depth(self, exchange: str, scrip_code: str):
        """
        Get the latest market depth for an instrument.

        Args:
            exchange (str): Exchange code (full name like NSE, MCX, etc.)
            scrip_code (str): Scrip code/token

        Returns:
            dict: Latest market depth data or None if not available
        """
        key = self._store_key(exchange, scrip_code)
        logger.debug(f"Looking up depth with key: {key}")

        with self.lock:
            depth = self.last_depth.get(key)
            logger.debug(
                f"Looking for depth with key '{key}'. Available keys: {list(self.last_depth.keys())}"
            )

            if depth:
                # Filter out None values from bids and asks arrays
                # Since we now store 5 levels, some may be None
                bids_raw = depth.get("bids", [])
                asks_raw = depth.get("asks", [])

                # Filter out None entries
                bids_filtered = [bid for bid in bids_raw if bid is not None]
                asks_filtered = [ask for ask in asks_raw if ask is not None]

                # Log detailed depth summary
                logger.debug(
                    f"Found depth data for {key}: {len(bids_filtered)} bid levels, {len(asks_filtered)} ask levels"
                )
                for i, bid in enumerate(bids_filtered, 1):
                    logger.debug(
                        f"  Bid Level {i}: Price={bid.get('price')}, Qty={bid.get('quantity')}, Orders={bid.get('orders')}"
                    )
                for i, ask in enumerate(asks_filtered, 1):
                    logger.debug(
                        f"  Ask Level {i}: Price={ask.get('price')}, Qty={ask.get('quantity')}, Orders={ask.get('orders')}"
                    )

                logger.debug(
                    f"Retrieved market depth for {key} - Bid levels: {len(bids_filtered)}, Ask levels: {len(asks_filtered)}, Symbol: {depth.get('symbol', 'N/A')}"
                )

                # Return filtered depth
                return {"bids": bids_filtered, "asks": asks_filtered, "symbol": depth.get("symbol")}
            else:
                logger.warning(f"No depth data found for key '{key}'")
                logger.debug(f"No market depth data available for {key}")
                logger.debug(f"Available depth keys: {list(self.last_depth.keys())}")
                return None

    def get_open_interest(self, exchange: str, scrip_code: str):
        """
        Get the latest open interest for an instrument.

        Args:
            exchange (str): Exchange code (full name like NSE, MCX, etc.)
            scrip_code (str): Scrip code/token

        Returns:
            dict: Latest OI data or None if not available
        """
        key = self._store_key(exchange, scrip_code)

        with self.lock:
            oi = self.last_oi.get(key)
            if oi:
                logger.debug(
                    f"Retrieved OI for {key} - OI: {oi.get('open_interest', 'N/A')}, Symbol: {oi.get('symbol', 'N/A')}"
                )
            else:
                logger.debug(f"No OI data available for {key}")
            return oi

    def get_index(self, exchange: str, index_code: str):
        """
        Get the latest index value.

        Args:
            exchange (str): Exchange code (full name like NSE, BSE, etc.)
            index_code (str): Index code

        Returns:
            dict: Latest index data or None if not available
        """
        key = self._store_key(exchange, index_code)
        with self.lock:
            index = self.last_index.get(key)
            if index:
                logger.debug(f"Retrieved index for {key} - Rate: {index.get('rate', 'N/A')}")
            else:
                logger.debug(f"No index data available for {key}")
            return index
