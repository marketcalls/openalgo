"""
Synchronous mstock WebSocket client using websocket-client library.

Uses sync websocket-client instead of async websockets to avoid asyncio
event loop conflicts with eventlet in gunicorn+eventlet deployments.
"""

import json
import math
import os
import ssl
import struct
import threading
import time
from typing import Any

import websocket

from utils.logging import get_logger

logger = get_logger(__name__)


def _env_float(name: str, default: float) -> float:
    """Read a tuning knob from the environment, falling back on a bad value.

    Non-finite values are rejected: "nan" and "inf" parse cleanly as floats but
    blow up the int() cast below, which would crash module import - and this
    module is imported at startup, so a stray .env value would take the whole
    app down rather than degrading one broker.
    """
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning(f"{name}={raw!r} is not a number; using {default}")
        return default
    if not math.isfinite(value):
        logger.warning(f"{name}={raw!r} is not finite; using {default}")
        return default
    return value


# Reconnect and keepalive tuning. Defaults match the previous hardcoded values;
# every one is overridable from .env so a deployment can tune without a patch.
RECONNECT_MAX_ATTEMPTS = max(1, int(_env_float("MSTOCK_WS_MAX_RECONNECT_ATTEMPTS", 10)))
RECONNECT_MAX_DELAY = _env_float("MSTOCK_WS_RECONNECT_MAX_DELAY", 60.0)
RECONNECT_BASE_DELAY = _env_float("MSTOCK_WS_RECONNECT_BASE_DELAY", 2.0)
PING_INTERVAL = _env_float("MSTOCK_WS_PING_INTERVAL", 20.0)
PING_TIMEOUT = _env_float("MSTOCK_WS_PING_TIMEOUT", 10.0)


class MstockWebSocket:
    """
    WebSocket client for mstock broker's market data API.
    Handles binary packet parsing as per mstock WebSocket protocol.
    Supports both one-off fetches and persistent streaming connections.
    """

    WS_URL = "wss://ws.mstock.trade"

    def __init__(self, auth_token: str, token_provider=None, auth_error_check=None):
        self.auth_token = auth_token
        # Optional zero-arg callable returning a fresh access token from the
        # database. Invoked before each reconnect so daily token rollover
        # (~3 AM IST) does not leave the feed dead with the construction-time token.
        self.token_provider = token_provider
        # Predicate deciding whether an error means the credential is dead.
        # The adapter passes BaseBrokerWebSocketAdapter.is_auth_error so the
        # 401/403 vocabulary has one definition across the fleet.
        self.auth_error_check = auth_error_check
        self.auth_failed = False
        self.auth_failure_reason = None
        self.api_key = os.getenv("BROKER_API_SECRET") or os.getenv("BROKER_API_KEY")
        self.ws_url = self._build_ws_url()

        # Streaming mode variables
        self.ws: websocket.WebSocketApp | None = None
        self.running = False
        self._connected = False
        self.data_callback = None
        # Optional zero-arg callable invoked after every successful login. The
        # adapter registers one so it can resubscribe from its own desired
        # state, which is authoritative: this dict only holds what was actually
        # sent, so a subscribe made while the socket was down is absent here.
        self.resync_callback = None
        # Optional zero-arg callable invoked when the feed gives up for good, so
        # the owner can stop advertising a connection that will never recover.
        self.auth_failure_callback = None
        # Set once the feed is terminally down, so the notice fires exactly
        # once however many terminal paths are reached.
        self._feed_dead = False
        self.subscriptions: dict[str, dict] = {}
        self._ws_thread: threading.Thread | None = None
        self._logged_in = False
        self._login_event = threading.Event()
        # Guards generation reads paired with a write to self.ws, so a retiring
        # thread cannot install its app after a newer one has published.
        self._state_lock = threading.Lock()
        # Set by disconnect_stream() to cut the reconnect backoff short. A plain
        # time.sleep() made teardown wait out the full delay - up to the max -
        # before the loop could notice it had been asked to stop.
        self._stop_event = threading.Event()
        # Bumped by every connect_stream(). A reconnect thread carries the
        # generation it was started for and exits as soon as that no longer
        # matches, so a stop/start during backoff cannot leave the old thread
        # driving or overwriting the new connection's WebSocketApp.
        self._generation = 0

    def _build_ws_url(self) -> str:
        """Build the WebSocket URL with the current API key and access token."""
        return f"{self.WS_URL}?API_KEY={self.api_key}&ACCESS_TOKEN={self.auth_token}"

    def _refresh_auth_token(self) -> bool:
        """
        Re-read a fresh access token from the database (via token_provider) and
        rebuild the URL baked with it. The construction-time token is dead after
        the daily rollover (~3 AM IST); keep the existing token if none returned.

        Returns:
            bool: True when a genuinely different token was obtained
        """
        if self.token_provider is None:
            return False
        try:
            fresh_token = self.token_provider()
        except Exception as token_err:
            logger.warning(
                f"mstock token_provider failed; keeping existing access token: {token_err}"
            )
            return False
        if fresh_token:
            changed = fresh_token != self.auth_token
            self.auth_token = fresh_token
            self.ws_url = self._build_ws_url()
            return changed
        logger.warning("mstock token_provider returned no token; keeping existing access token")
        return False

    @staticmethod
    def parse_binary_packet(data: bytes) -> dict | None:
        """
        Parse mstock binary quote packet.
        The packet can be:
        - 51 bytes (LTP mode - mode 1)
        - 123 bytes (Quote mode - mode 2)
        - 379 bytes (Full quote packet - mode 3)
        - 383+ bytes (4 byte header + quote packet)
        """
        try:
            if len(data) == 51:
                quote = {
                    "subscription_mode": data[0],
                    "exchange_type": data[1],
                    "token": data[2:27].decode("utf-8").strip("\x00"),
                    "sequence_number": struct.unpack("<Q", data[27:35])[0],
                    "exchange_timestamp": struct.unpack("<Q", data[35:43])[0],
                    "ltp": struct.unpack("<Q", data[43:51])[0] / 100.0,
                    "last_traded_qty": 0,
                    "avg_price": 0,
                    "volume": 0,
                    "total_buy_qty": 0,
                    "total_sell_qty": 0,
                    "open": 0,
                    "high": 0,
                    "low": 0,
                    "close": 0,
                    "last_traded_timestamp": 0,
                    "oi": 0,
                    "oi_percent": 0,
                    "upper_circuit": 0,
                    "lower_circuit": 0,
                    "week_52_high": 0,
                    "week_52_low": 0,
                    "bids": [],
                    "asks": [],
                }
                return quote

            elif len(data) == 123:
                quote = {
                    "subscription_mode": data[0],
                    "exchange_type": data[1],
                    "token": data[2:27].decode("utf-8").strip("\x00"),
                    "sequence_number": struct.unpack("<Q", data[27:35])[0],
                    "exchange_timestamp": struct.unpack("<Q", data[35:43])[0],
                    "ltp": struct.unpack("<Q", data[43:51])[0] / 100.0,
                    "last_traded_qty": struct.unpack("<Q", data[51:59])[0],
                    "avg_price": struct.unpack("<Q", data[59:67])[0] / 100.0,
                    "volume": struct.unpack("<Q", data[67:75])[0],
                    "total_buy_qty": struct.unpack("<d", data[75:83])[0],
                    "total_sell_qty": struct.unpack("<d", data[83:91])[0],
                    "open": struct.unpack("<Q", data[91:99])[0] / 100.0,
                    "high": struct.unpack("<Q", data[99:107])[0] / 100.0,
                    "low": struct.unpack("<Q", data[107:115])[0] / 100.0,
                    "close": struct.unpack("<Q", data[115:123])[0] / 100.0,
                    "last_traded_timestamp": 0,
                    "oi": 0,
                    "oi_percent": 0,
                    "upper_circuit": 0,
                    "lower_circuit": 0,
                    "week_52_high": 0,
                    "week_52_low": 0,
                    "bids": [],
                    "asks": [],
                }
                return quote

            elif len(data) == 379:
                packet = data
            elif len(data) >= 383:
                # Header-prefixed frame; parse_binary_message splits multi-packet
                # frames, so only the first packet is read here.
                packet = data[4 : 4 + 379]
            else:
                logger.error(f"Invalid packet size: {len(data)} bytes")
                return None

            # Parse full 379-byte quote packet
            quote = {
                "subscription_mode": packet[0],
                "exchange_type": packet[1],
                "token": packet[2:27].decode("utf-8").strip("\x00"),
                "sequence_number": struct.unpack("<Q", packet[27:35])[0],
                "exchange_timestamp": struct.unpack("<Q", packet[35:43])[0],
                "ltp": struct.unpack("<Q", packet[43:51])[0] / 100.0,
                "last_traded_qty": struct.unpack("<Q", packet[51:59])[0],
                "avg_price": struct.unpack("<Q", packet[59:67])[0] / 100.0,
                "volume": struct.unpack("<Q", packet[67:75])[0],
                "total_buy_qty": struct.unpack("<d", packet[75:83])[0],
                "total_sell_qty": struct.unpack("<d", packet[83:91])[0],
                "open": struct.unpack("<Q", packet[91:99])[0] / 100.0,
                "high": struct.unpack("<Q", packet[99:107])[0] / 100.0,
                "low": struct.unpack("<Q", packet[107:115])[0] / 100.0,
                "close": struct.unpack("<Q", packet[115:123])[0] / 100.0,
                "last_traded_timestamp": struct.unpack("<Q", packet[123:131])[0],
                "oi": struct.unpack("<Q", packet[131:139])[0],
                "oi_percent": struct.unpack("<Q", packet[139:147])[0] / 100.0,
                "upper_circuit": struct.unpack("<Q", packet[347:355])[0] / 100.0,
                "lower_circuit": struct.unpack("<Q", packet[355:363])[0] / 100.0,
                "week_52_high": struct.unpack("<Q", packet[363:371])[0] / 100.0,
                "week_52_low": struct.unpack("<Q", packet[371:379])[0] / 100.0,
            }

            # Parse market depth (bytes 147-347)
            depth_data = packet[147:347]
            quote["bids"] = []
            quote["asks"] = []

            for i in range(5):
                bid_offset = i * 20
                try:
                    qty = struct.unpack("<Q", depth_data[bid_offset + 2 : bid_offset + 10])[0]
                    price = (
                        struct.unpack("<Q", depth_data[bid_offset + 10 : bid_offset + 18])[0]
                        / 100.0
                    )
                    num_orders = struct.unpack("<H", depth_data[bid_offset + 18 : bid_offset + 20])[
                        0
                    ]
                    quote["bids"].append({"price": price, "quantity": qty, "orders": num_orders})
                except Exception:
                    quote["bids"].append({"price": 0, "quantity": 0, "orders": 0})

            for i in range(5):
                ask_offset = 100 + (i * 20)
                try:
                    qty = struct.unpack("<Q", depth_data[ask_offset + 2 : ask_offset + 10])[0]
                    price = (
                        struct.unpack("<Q", depth_data[ask_offset + 10 : ask_offset + 18])[0]
                        / 100.0
                    )
                    num_orders = struct.unpack("<H", depth_data[ask_offset + 18 : ask_offset + 20])[
                        0
                    ]
                    quote["asks"].append({"price": price, "quantity": qty, "orders": num_orders})
                except Exception:
                    quote["asks"].append({"price": 0, "quantity": 0, "orders": 0})

            return quote

        except Exception as e:
            logger.exception(f"Error parsing binary packet: {str(e)}")
            return None

    @staticmethod
    def parse_binary_message(data: bytes) -> list:
        """
        Parse a binary WebSocket frame into a list of quote dicts.

        A header-prefixed frame carries a 2-byte packet count and a 2-byte
        packet size, and may batch several tokens' packets into one frame.
        Bare frames (51/123/379 bytes) carry a single packet.

        Args:
            data: Raw binary frame received from the WebSocket

        Returns:
            list: Parsed quote dicts, empty when nothing could be parsed
        """
        # Branch on the exact bare packet sizes rather than a length threshold.
        # A header-prefixed LTP or Quote frame (4 + 51 = 55, 4 + 123 = 127, and
        # multiples when batched) is shorter than a bare snap quote, so a
        # "< 383 means bare" test dropped those frames entirely.
        if len(data) in (51, 123, 379):
            quote = MstockWebSocket.parse_binary_packet(data)
            return [quote] if quote else []

        if len(data) < 4:
            logger.error(f"Invalid frame size: {len(data)} bytes")
            return []

        try:
            num_packets = struct.unpack("<H", data[0:2])[0]
            packet_size = struct.unpack("<H", data[2:4])[0]
        except Exception as e:
            logger.exception(f"Error parsing binary frame header: {str(e)}")
            return []

        # When the header reports a size that cannot be right, treat the frame
        # as one packet filling the remaining bytes. Assuming 379 here would
        # discard a shorter LTP or Quote frame outright.
        if packet_size <= 0 or packet_size > len(data) - 4:
            fallback = len(data) - 4
            if fallback <= 0:
                # A header with no payload behind it; nothing to divide into.
                logger.error(f"Invalid frame size: {len(data)} bytes")
                return []
            logger.warning(
                f"Unexpected packet size {packet_size} in frame header; assuming {fallback}"
            )
            packet_size = fallback

        available = (len(data) - 4) // packet_size
        if num_packets < 1 or num_packets > available:
            if num_packets != available:
                logger.warning(
                    f"Frame header reports {num_packets} packets but {available} fit "
                    f"in {len(data)} bytes; parsing {available}"
                )
            num_packets = available

        quotes = []
        for i in range(num_packets):
            start = 4 + (i * packet_size)
            quote = MstockWebSocket.parse_binary_packet(data[start : start + packet_size])
            if quote:
                quotes.append(quote)

        return quotes

    # ==================== Streaming Mode Methods ====================

    def connect_stream(self, data_callback, resync_callback=None, auth_failure_callback=None):
        """
        Start persistent WebSocket connection for streaming data.
        Returns immediately — connection happens in background thread.

        Args:
            data_callback: Callback function(quote_data) called when data is received
        """
        self.data_callback = data_callback
        self.resync_callback = resync_callback
        self.auth_failure_callback = auth_failure_callback
        self.running = True
        self._logged_in = False
        self._feed_dead = False
        self._login_event.clear()
        self._stop_event.clear()

        # Close any socket left from a previous generation. Without this, a
        # thread still blocked in run_forever would hold that socket open
        # indefinitely once self.ws stopped pointing at it.
        previous = self.ws
        if previous is not None:
            try:
                previous.close()
            except Exception as close_err:
                logger.debug(f"Error closing previous WebSocket: {close_err}")

        with self._state_lock:
            self._generation += 1
            generation = self._generation
            app = self._build_app(generation)
            self.ws = app

        # The thread owns its own app reference: reading self.ws inside the loop
        # would let one generation drive another's connection.
        self._ws_thread = threading.Thread(
            target=self._run_websocket, args=(generation, app), daemon=True
        )
        self._ws_thread.start()
        logger.info(f"mstock WebSocket connection thread started (generation {generation})")

    def _run_websocket(self, generation: int, app):
        """
        Run the WebSocket connection with reconnection.

        Args:
            generation: The connect_stream() generation this thread serves
            app: The WebSocketApp this thread owns
        """
        self._reconnect_attempts = 0
        max_attempts = RECONNECT_MAX_ATTEMPTS

        while self.running and generation == self._generation:
            try:
                app.run_forever(
                    sslopt={"cert_reqs": ssl.CERT_NONE},
                    ping_interval=PING_INTERVAL,
                    ping_timeout=PING_TIMEOUT,
                )
            except Exception as e:
                logger.exception(f"WebSocket run_forever error: {e}")

            self._connected = False
            self._logged_in = False

            if not self.running or generation != self._generation:
                break

            # An expired credential is not a network hiccup: every retry is
            # another rejected handshake. Try a token refresh once, since the
            # daily rollover (~3 AM IST) is the common cause and the database
            # may already hold a live token; if that yields nothing new, stand
            # down and wait for a login rather than burning the backoff budget.
            if self.auth_failed:
                if self._refresh_auth_token():
                    logger.info("mstock auth failure; a fresh token was found, retrying once")
                    self.auth_failed = False
                    self.auth_failure_reason = None
                else:
                    self._notify_feed_dead(
                        f"auth failure with no fresh token available ({self.auth_failure_reason})",
                        generation=generation,
                    )
                    break

            self._reconnect_attempts += 1
            if self._reconnect_attempts >= max_attempts:
                # Just as terminal as a dead credential: the thread exits and
                # nothing reconnects, so the owner must stop advertising it.
                self._notify_feed_dead(
                    f"max reconnect attempts ({max_attempts}) reached", generation=generation
                )
                break

            delay = min(RECONNECT_BASE_DELAY * (1.5**self._reconnect_attempts), RECONNECT_MAX_DELAY)
            logger.info(f"Reconnecting in {delay:.0f}s (attempt {self._reconnect_attempts})...")
            # Waits on the stop event rather than sleeping, so disconnect_stream()
            # ends the backoff immediately instead of the thread lingering for
            # the remainder of the delay.
            if self._stop_event.wait(delay):
                logger.info("Reconnect backoff interrupted by disconnect")
                break

            # disconnect_stream(), or a stop/start pair, may have run during the
            # backoff. Testing self.running alone is not enough: a restart sets
            # it back to True, and this thread would then resume and overwrite
            # the new connection's WebSocketApp. The generation pins it to the
            # connect_stream() call that started it.
            if not self.running or generation != self._generation:
                break

            # Re-read a fresh access token before reconnecting so a reconnect
            # after the daily token rollover uses a live token. Both self.ws_url
            # and the LOGIN payload in _on_ws_open derive from self.auth_token.
            self._refresh_auth_token()

            # Close the outgoing app before replacing it. run_forever already
            # tears its socket down in a finally on every exit, so this is
            # belt-and-braces for an abnormal exit that skipped that path;
            # teardown() is guarded by has_done_teardown, so a second close is
            # a no-op rather than an error.
            previous = app
            try:
                previous.close()
            except Exception as close_err:
                logger.debug(f"Error closing previous WebSocket app: {close_err}")

            # Recreate WebSocketApp for reconnection. The generation check and
            # the publication happen under one lock: tested separately, a
            # retiring thread could pass the check and then overwrite an app a
            # newer connect_stream() had already installed.
            with self._state_lock:
                if not self.running or generation != self._generation:
                    break
                app = self._build_app(generation)
                self.ws = app

    def _build_app(self, generation: int):
        """Build a WebSocketApp whose callbacks are scoped to one generation.

        The handlers mutate shared flags (_connected, _logged_in). Bound
        directly, a retiring connection's close or error callback would clear
        the flags belonging to the connection that replaced it, leaving a live
        socket marked down.
        """

        def guard(handler):
            def wrapper(*args, **kwargs):
                if generation != self._generation:
                    logger.debug(
                        f"Ignoring {handler.__name__} from retired generation {generation}"
                    )
                    return None
                return handler(*args, **kwargs)

            return wrapper

        return websocket.WebSocketApp(
            self.ws_url,
            on_open=guard(self._on_ws_open),
            on_message=guard(self._on_ws_message),
            on_error=guard(self._on_ws_error),
            on_close=guard(self._on_ws_close),
        )

    def _notify_feed_dead(self, reason: str, generation: int | None = None) -> None:
        """Tell the owner the feed will not recover without a fresh login.

        Every terminal exit from the reconnect loop lands here: an expired
        credential and an exhausted retry budget both leave a client that is
        never coming back, and an owner still advertising connected=True keeps
        a cached adapter that cannot produce another tick.

        The caller passes the generation it serves, checked against the current
        one under the state lock. A worker retiring while a new connect_stream()
        has already started would otherwise clear the *new* connection's flags
        and fire its callback, killing a feed that had just come up. Idempotent
        within a generation, so overlapping terminal paths report once.

        Args:
            reason: What ended the feed, for the log
            generation: The connect_stream() generation the caller serves;
                None skips the check, for callers outside the reconnect loop
        """
        with self._state_lock:
            if generation is not None and generation != self._generation:
                logger.debug(
                    f"Ignoring feed-dead notice from retired generation {generation}: {reason}"
                )
                return
            if self._feed_dead:
                return
            self._feed_dead = True

            self.running = False
            self._connected = False
            self._logged_in = False

        logger.error(f"mstock feed is down and will not self-recover: {reason}")

        if self.auth_failure_callback is not None:
            try:
                self.auth_failure_callback()
            except Exception:
                logger.exception("mstock feed-dead callback failed")

    def _mark_logged_in(self, reason: str) -> None:
        """
        Mark the session usable and resubscribe, once per connection.

        mStock documents no acknowledgement for the LOGIN frame - the Market
        Data WebSocket page says only that the frame must be sent promptly or
        the socket is dropped, and that every response is binary. Waiting for a
        text reply therefore left is_connected() False for the life of the
        connection, so every subscribe was held locally and no tick ever
        arrived. Sending LOGIN is the handshake; any inbound frame confirms it.
        """
        if self._logged_in:
            return

        self._logged_in = True
        self._login_event.set()
        self.auth_failed = False
        self.auth_failure_reason = None
        self._reconnect_attempts = 0
        logger.info(f"mstock session ready ({reason})")

        # Prefer the owner's resync: this client's dict only records what was
        # actually sent, so replaying it would silently skip any subscription
        # made while the socket was down.
        if self.resync_callback is not None:
            try:
                self.resync_callback()
            except Exception:
                logger.exception("mstock resync callback failed")
        else:
            self._resubscribe_all()

    def _on_ws_open(self, ws):
        """Called when WebSocket connection is opened"""
        logger.info("mstock WebSocket connected")
        self._connected = True
        self._reconnect_attempts = 0

        # Send LOGIN message
        login_msg = f"LOGIN:{self.auth_token}"
        try:
            ws.send(login_msg)
        except Exception:
            # Without LOGIN the broker drops the socket; leave the session
            # unusable so the reconnect loop retries rather than subscribing
            # into a connection that is about to close.
            logger.exception("mstock LOGIN send failed; leaving session unauthenticated")
            return
        logger.debug("Sent LOGIN message")

        # The handshake is complete once LOGIN is away - there is no ACK to
        # wait for, and gating readiness on one stalls the feed permanently.
        self._mark_logged_in("LOGIN sent")

    def _on_ws_message(self, ws, message):
        """Called for both binary and text messages"""
        if isinstance(message, bytes):
            # Parse binary packet(s) — a header-prefixed frame may batch several
            # parse_binary_message decides what is parseable; gating on a fixed
            # set of sizes here dropped header-prefixed LTP/Quote frames before
            # the parser ever saw them.
            if message:
                # Data proves the session is live, whatever the handshake did.
                self._mark_logged_in("binary frame received")
                for quote_data in self.parse_binary_message(message):
                    if self.data_callback:
                        self.data_callback(quote_data)
        elif isinstance(message, str):
            logger.debug(f"Received string message: {message}")
            self._mark_logged_in("text frame received")

    def _is_auth_error(self, detail) -> bool:
        """True when the broker refused the handshake over a dead credential."""
        if self.auth_error_check is None or detail in (None, ""):
            return False
        try:
            return bool(self.auth_error_check(str(detail)))
        except Exception:
            logger.exception("mstock auth_error_check raised; treating as non-auth error")
            return False

    def _on_ws_error(self, ws, error):
        """Called on WebSocket error"""
        # logger.error, not logger.exception: this is a library callback, not an
        # except block, so there is no active exception and logger.exception
        # would append a useless "NoneType: None" traceback to every line.
        logger.error(f"WebSocket error: {error}")
        self._connected = False

        status = getattr(error, "status_code", None)
        if self._is_auth_error(error) or status in (401, 403):
            self.auth_failed = True
            self.auth_failure_reason = str(error)
            logger.error(f"mstock auth failure on WebSocket: {error}")

    def _on_ws_close(self, ws, close_status_code, close_msg):
        """Called when WebSocket is closed"""
        logger.info(f"WebSocket closed (code={close_status_code}, msg={close_msg})")
        self._connected = False
        self._logged_in = False

        if self._is_auth_error(close_msg) or self._is_auth_error(close_status_code):
            self.auth_failed = True
            self.auth_failure_reason = f"close code={close_status_code} msg={close_msg}"
            logger.error(f"mstock auth failure on close: {self.auth_failure_reason}")

    def _resubscribe_all(self):
        """
        Re-subscribe to all tracked subscriptions after reconnection.

        Grouped by mode so a reconnect with a large book costs a handful of
        frames instead of one per token.
        """
        with_mode = {}
        for correlation_id, sub in list(self.subscriptions.items()):
            with_mode.setdefault(sub["mode"], []).append(
                {
                    "correlation_id": correlation_id,
                    "token": sub["token"],
                    "exchange_type": sub["exchange_type"],
                }
            )

        for mode, subs in with_mode.items():
            try:
                self.subscribe_batch(subs, mode)
                logger.info(f"Re-subscribed {len(subs)} token(s) in mode {mode}")
            except Exception as e:
                logger.exception(f"Error re-subscribing {len(subs)} token(s) in mode {mode}: {e}")

    @staticmethod
    def build_token_list(subs: list) -> list:
        """
        Group subscription entries into the wire tokenList shape.

        mStock accepts several tokens per exchangeType and several
        exchangeType groups per message (see the subscribe example in the
        Market Data WebSocket docs), so a whole batch fits in one frame.

        Args:
            subs: Entries carrying "token" and "exchange_type"

        Returns:
            list: [{"exchangeType": int, "tokens": [str, ...]}, ...]
        """
        groups = {}
        for sub in subs:
            groups.setdefault(int(sub["exchange_type"]), []).append(str(sub["token"]))
        return [
            {"exchangeType": exchange_type, "tokens": tokens}
            for exchange_type, tokens in groups.items()
        ]

    def subscribe_batch(self, subs: list, mode: int) -> bool:
        """
        Subscribe to many tokens sharing one mode in a single frame.

        Each token is still registered under its own correlation_id, so
        unsubscribe_stream() and the reconnect path keep working per-token;
        only the wire message is batched.

        Args:
            subs: Entries with "correlation_id", "token" and "exchange_type"
            mode: Subscription mode shared by every entry

        Returns:
            bool: True when the frame was sent
        """
        if not subs:
            return True

        if not self._connected or not self.ws:
            logger.error("WebSocket not connected")
            return False

        try:
            token_list = self.build_token_list(subs)
            subscribe_msg = {
                "action": 1,
                "params": {"mode": mode, "tokenList": token_list},
            }

            self.ws.send(json.dumps(subscribe_msg))
            logger.info(
                f"Subscribed {len(subs)} token(s) in mode {mode} "
                f"across {len(token_list)} exchange-type group(s)"
            )

            for sub in subs:
                self.subscriptions[sub["correlation_id"]] = {
                    "token": sub["token"],
                    "exchange_type": sub["exchange_type"],
                    "mode": mode,
                }
            return True

        except Exception as e:
            logger.exception(f"Error subscribing batch of {len(subs)}: {str(e)}")
            return False

    def subscribe_stream(
        self, correlation_id: str, token: str, exchange_type: int, mode: int
    ) -> bool:
        """
        Subscribe to a single symbol on the persistent WebSocket connection.

        Args:
            correlation_id: Unique ID for this subscription
            token: Symbol token
            exchange_type: Exchange type code
            mode: Subscription mode
        """
        return self.subscribe_batch(
            [
                {
                    "correlation_id": correlation_id,
                    "token": token,
                    "exchange_type": exchange_type,
                }
            ],
            mode,
        )

    def unsubscribe_batch(self, correlation_ids: list) -> bool:
        """
        Unsubscribe many tracked subscriptions, one frame per mode.

        Args:
            correlation_ids: Correlation IDs to drop; unknown IDs are skipped

        Returns:
            bool: True when every known ID was dropped
        """
        if not correlation_ids:
            return True

        if not self._connected or not self.ws:
            return False

        by_mode = {}
        for correlation_id in correlation_ids:
            sub = self.subscriptions.get(correlation_id)
            if sub is None:
                continue
            by_mode.setdefault(sub["mode"], []).append((correlation_id, sub))

        if not by_mode:
            return False

        sent_all = True
        for mode, entries in by_mode.items():
            try:
                token_list = self.build_token_list([sub for _, sub in entries])
                unsubscribe_msg = {
                    "action": 0,
                    "params": {"mode": mode, "tokenList": token_list},
                }

                self.ws.send(json.dumps(unsubscribe_msg))
                logger.info(f"Unsubscribed {len(entries)} token(s) in mode {mode}")

                for correlation_id, _ in entries:
                    self.subscriptions.pop(correlation_id, None)

            except Exception as e:
                logger.exception(f"Error unsubscribing batch in mode {mode}: {str(e)}")
                sent_all = False

        return sent_all

    def unsubscribe_stream(self, correlation_id: str) -> bool:
        """
        Unsubscribe from a single symbol on the persistent WebSocket connection.

        Args:
            correlation_id: Unique ID of the subscription to remove
        """
        if correlation_id not in self.subscriptions:
            return False
        return self.unsubscribe_batch([correlation_id])

    def disconnect_stream(self):
        """Disconnect the persistent WebSocket connection"""
        self.running = False
        self._connected = False
        # Wake a thread parked in the reconnect backoff so teardown is prompt.
        self._stop_event.set()

        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                logger.debug(f"Error closing WebSocket: {e}")

        # Don't join threads — daemon threads stop on their own
        self._ws_thread = None
        logger.info("Streaming mode disconnected")

    def is_connected(self) -> bool:
        """Check if WebSocket is connected and logged in"""
        return self._connected and self._logged_in and self.running

    # ==================== One-off Fetch (sync) ====================

    def fetch_quote(self, token: str, exchange_type: int, mode: int = 3) -> dict | None:
        """
        Fetch a single quote synchronously using a temporary WebSocket connection.
        Uses websocket-client's create_connection for a simple request-response.
        """
        # The socket is closed in a finally, not after each return: a send that
        # fails mid-call (connection reset, broken pipe, timeout) used to jump
        # straight to the handler below and leak the descriptor. This runs per
        # depth request in a worker that never restarts, so a broker-side
        # disconnect leaked one descriptor per call until the process hit its
        # open-file limit.
        ws = None
        try:
            import websocket as ws_module

            ws = ws_module.create_connection(
                self.ws_url,
                sslopt={"cert_reqs": ssl.CERT_NONE},
                timeout=10,
            )

            # Send LOGIN
            ws.send(f"LOGIN:{self.auth_token}")

            # Wait for login response
            try:
                ws.recv()  # Login response
            except Exception:
                pass

            # Subscribe
            subscribe_msg = {
                "action": 1,
                "params": {
                    "mode": mode,
                    "tokenList": [{"exchangeType": exchange_type, "tokens": [str(token)]}],
                },
            }
            ws.send(json.dumps(subscribe_msg))

            # Wait for binary response
            for _ in range(3):
                try:
                    response = ws.recv()
                    if isinstance(response, bytes) and response:
                        quotes = self.parse_binary_message(response)
                        if quotes:
                            return quotes[0]
                except Exception:
                    break

            return None

        except Exception as e:
            logger.exception(f"Error fetching quote: {e}")
            return None

        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception as close_err:
                    # Closing an already-broken socket can raise; swallow it so
                    # this never replaces the value the caller is returning.
                    logger.debug(f"Error closing one-off quote socket: {close_err}")
