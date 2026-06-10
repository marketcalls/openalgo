"""Arrow standard market-data WebSocket client (wss://ds.arrow.trade).

Adapted from the Zerodha client. Uses sync `websocket-client` in a daemon
thread (NOT asyncio) to stay compatible with gunicorn+eventlet. Implements the
same resilience patterns:
  - keepalive via run_forever ping/pong + a data-stall health-check watchdog
  - automatic reconnection with interruptible exponential backoff
  - bounded auth-refresh on token failure (re-reads a fresh JWT from the DB for
    the ~3 AM IST daily token rollover) instead of dying until a restart
  - resubscribe-on-reconnect
  - daemon threads are never join()ed (eventlet raises Timeout on join)

Protocol specifics vs Zerodha:
  - URL bakes in credentials: wss://ds.arrow.trade?appID=<appID>&token=<JWT>
  - Subscribe is a JSON text frame whose instrument-array key EQUALS the mode:
        {"code": "sub", "mode": "ltpc", "ltpc": [26009, 256265]}
  - Binary feed sends ONE packet per message (no multi-packet framing); the
    mode is identified by packet length (ltp=13, ltpc=17, quote=93, full=249),
    big-endian.
"""

import json
import ssl
import struct
import sys
import threading
import time
from collections import deque
from collections.abc import Callable

import websocket

from broker.arrow.api.baseurl import WS_MARKET_DATA_URL
from database.auth_db import get_auth_token
from utils.logging import get_logger

logger = get_logger(__name__)

if "eventlet" in sys.modules:
    import eventlet

    _real_threading = eventlet.patcher.original("threading")
else:
    _real_threading = threading


class ArrowWebSocket:
    """Sync WebSocket client for Arrow's standard market-data stream."""

    # Arrow subscription modes.
    MODE_LTP = "ltp"
    MODE_LTPC = "ltpc"
    MODE_QUOTE = "quote"
    MODE_FULL = "full"

    # Packet sizes (bytes) -> mode. Full is 249B on the current stream
    # (8 reserved bytes before the depth block) and 241B on the legacy
    # layout; the parser handles both (per the official pyarrow-client SDK).
    _SIZE_TO_MODE = {13: MODE_LTP, 17: MODE_LTPC, 93: MODE_QUOTE, 249: MODE_FULL, 241: MODE_FULL}

    PING_INTERVAL = 30
    PING_TIMEOUT = 10
    KEEPALIVE_INTERVAL = 30
    DATA_TIMEOUT = 90  # force reconnect if no data for this long

    # Batching. Standard-stream per-connection / per-request caps are not
    # documented; use conservative values.
    # TODO(arrow): confirm max tokens per subscribe / per connection.
    MAX_TOKENS_PER_SUBSCRIBE = 100
    MAX_INSTRUMENTS_PER_CONNECTION = 1000
    SUBSCRIPTION_DELAY = 0.3

    # Reconnection. Arrow docs suggest a >=5s reconnect interval.
    RECONNECT_BASE_DELAY = 5
    RECONNECT_MAX_DELAY = 60
    RECONNECT_MAX_TRIES = 50

    def __init__(self, app_id, access_token, on_ticks=None, user_id=None):
        self.app_id = app_id
        self.access_token = access_token
        self.on_ticks: Callable | None = on_ticks
        # user_id lets reconnect re-read a fresh JWT after the daily rollover.
        self.user_id = user_id

        self.ws: websocket.WebSocketApp | None = None
        self.connected = False
        self.running = False
        self.logger = get_logger(__name__)
        self.lock = _real_threading.Lock()

        # Subscription state.
        self.subscribed_tokens: set[int] = set()
        self.mode_map: dict[int, str] = {}  # token -> arrow mode
        self.token_exchange_map: dict[int, str] = {}  # token -> OpenAlgo exchange
        self.pending_subscriptions: deque = deque()
        self._subscription_thread: threading.Thread | None = None

        # Connection / health.
        self.reconnect_attempts = 0
        self.reconnect_delay = self.RECONNECT_BASE_DELAY
        self.last_message_time: float | None = None
        self._ws_thread: threading.Thread | None = None
        self._health_check_thread: threading.Thread | None = None
        self._connection_ready = _real_threading.Event()
        self._stop_event = _real_threading.Event()

        # Auth-failure handling (bounded refresh-and-retry).
        self._fatal_error = False
        self._fatal_error_message = ""
        self._auth_refresh_retries = 0
        self._max_auth_refresh_retries = 3

        self.ws_url = self._build_url()

        # Optional external callbacks.
        self.on_connect: Callable | None = None
        self.on_disconnect: Callable | None = None
        self.on_error: Callable | None = None

        self.logger.info("Arrow WebSocket client initialized (sync)")

    def _build_url(self):
        return f"{WS_MARKET_DATA_URL}?appID={self.app_id}&token={self.access_token}"

    def set_token_exchange_mapping(self, token_exchange_map):
        with self.lock:
            self.token_exchange_map.update(token_exchange_map)

    # --- lifecycle ------------------------------------------------------

    def start(self):
        if self.running:
            return True
        self.running = True
        self._stop_event.clear()
        self._connection_ready.clear()
        self._fatal_error = False
        self._fatal_error_message = ""
        self._auth_refresh_retries = 0
        self._ws_thread = _real_threading.Thread(
            target=self._run_websocket, daemon=True, name="ArrowWS"
        )
        self._ws_thread.start()
        self.logger.info("Arrow WebSocket client started")
        return True

    def stop(self):
        try:
            self.running = False
            self._stop_event.set()
            if self.ws:
                try:
                    self.ws.close()
                except Exception as e:
                    self.logger.debug(f"Error closing WebSocket: {e}")
            # Never join daemon threads (eventlet raises Timeout on join).
            self._ws_thread = None
            self._health_check_thread = None
            self._subscription_thread = None
            self.connected = False
            self.logger.debug("Arrow WebSocket client stopped")
        except Exception as e:
            self.logger.error(f"Error stopping WebSocket client: {e}")

    def _refresh_access_token(self):
        """Re-read a fresh JWT from the DB (bypassing cache) and rebuild the URL.
        Returns True if the token changed (worth retrying)."""
        if not self.user_id:
            return False
        try:
            token = get_auth_token(self.user_id, bypass_cache=True)
            if not token:
                self.logger.warning("No fresh auth token on reconnect — keeping existing")
                return False
            with self.lock:
                changed = token != self.access_token
                self.access_token = token
                self.ws_url = self._build_url()
            self.logger.info("Refreshed Arrow access token from DB for reconnect")
            return changed
        except Exception as e:
            self.logger.error(f"Error refreshing access token: {e}")
            return False

    def _run_websocket(self):
        while self.running and not self._stop_event.is_set():
            try:
                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self._on_ws_open,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_ws_close,
                )
                # CERT_REQUIRED: credentials (appID + JWT) ride in the WS URL,
                # so accepting arbitrary certificates would hand them to any
                # MITM. Matches the deltaexchange adapter's verification.
                self.ws.run_forever(
                    sslopt={"cert_reqs": ssl.CERT_REQUIRED},
                    ping_interval=self.PING_INTERVAL,
                    ping_timeout=self.PING_TIMEOUT,
                )
            except Exception as e:
                self.logger.error(f"WebSocket run_forever error: {e}")

            self.connected = False
            if not self.running or self._stop_event.is_set():
                break

            # Auth/token failure: refresh from DB and retry a bounded number of
            # times rather than dying until a process restart.
            if self._fatal_error:
                if self._auth_refresh_retries >= self._max_auth_refresh_retries:
                    self.logger.error(
                        f"Stopping Arrow WS — auth failure persisted after "
                        f"{self._max_auth_refresh_retries} refreshes. {self._fatal_error_message}"
                    )
                    self.running = False
                    break
                self._auth_refresh_retries += 1
                if not self._refresh_access_token():
                    self.logger.error(
                        "Stopping Arrow WS — auth failure and DB token unchanged; needs re-login."
                    )
                    self.running = False
                    break
                self._fatal_error = False
                self._fatal_error_message = ""
                if self._stop_event.wait(self.reconnect_delay):
                    break
                continue

            self.reconnect_attempts += 1
            if self.reconnect_attempts >= self.RECONNECT_MAX_TRIES:
                self.logger.error("Max reconnect attempts reached")
                break

            delay = min(
                self.RECONNECT_BASE_DELAY * (1.5**self.reconnect_attempts),
                self.RECONNECT_MAX_DELAY,
            )
            self.logger.info(f"Reconnecting in {delay:.0f}s (attempt {self.reconnect_attempts})...")
            if self._stop_event.wait(delay):
                break
            # Refresh token before rebuilding the URL (daily rollover).
            self._refresh_access_token()

        self.logger.info("Arrow WebSocket thread exited")

    # --- subscription ---------------------------------------------------

    def subscribe_tokens(self, tokens, mode=MODE_QUOTE):
        if not self.running:
            self.logger.error("WebSocket client not running. Call start() first.")
            return
        try:
            tokens = [int(t) for t in tokens]
        except (ValueError, TypeError) as e:
            self.logger.error(f"Invalid token format: {e}")
            return
        if not tokens:
            return

        if len(self.subscribed_tokens) + len(tokens) > self.MAX_INSTRUMENTS_PER_CONNECTION:
            self.logger.error("Subscription would exceed per-connection instrument limit.")
            return

        with self.lock:
            for token in tokens:
                self.pending_subscriptions.append((token, mode))

        if not self._subscription_thread or not self._subscription_thread.is_alive():
            self._subscription_thread = _real_threading.Thread(
                target=self._process_pending_subscriptions, daemon=True
            )
            self._subscription_thread.start()

    def _process_pending_subscriptions(self):
        consecutive_failures = 0
        while self.pending_subscriptions and self.running:
            if not self.connected:
                consecutive_failures += 1
                if consecutive_failures > 3:
                    self.logger.error("Connection not ready; clearing pending subscriptions")
                    with self.lock:
                        self.pending_subscriptions.clear()
                    break
                if self._stop_event.wait(min(2 * consecutive_failures, 10)):
                    break
                continue
            consecutive_failures = 0

            batch_tokens = []
            batch_mode = None
            with self.lock:
                while (
                    self.pending_subscriptions and len(batch_tokens) < self.MAX_TOKENS_PER_SUBSCRIBE
                ):
                    token, mode = self.pending_subscriptions[0]
                    if batch_mode is None:
                        batch_mode = mode
                    elif batch_mode != mode:
                        break
                    self.pending_subscriptions.popleft()
                    batch_tokens.append(token)

            if batch_tokens:
                if not self._send_subscribe(batch_tokens, batch_mode):
                    with self.lock:
                        for token in batch_tokens:
                            self.pending_subscriptions.append((token, batch_mode))
                    if self._stop_event.wait(5):
                        break
                elif self.pending_subscriptions:
                    if self._stop_event.wait(self.SUBSCRIPTION_DELAY):
                        break

    def _send_subscribe(self, tokens, mode):
        try:
            if not self.connected or not self.ws:
                return False
            # Arrow frame: the instrument array key EQUALS the mode string.
            msg = {"code": "sub", "mode": mode, mode: tokens}
            self.ws.send(json.dumps(msg))
            with self.lock:
                for token in tokens:
                    self.mode_map[token] = mode
                    self.subscribed_tokens.add(token)
            self.logger.debug(f"Subscribed {len(tokens)} tokens in {mode} mode")
            return True
        except Exception as e:
            self.logger.error(f"Subscribe failed: {e}")
            return False

    def unsubscribe(self, tokens):
        try:
            if not self.connected or not self.ws:
                return False
            tokens = [int(t) for t in tokens]
            # Group by their current mode so the unsub frame mirrors the sub frame.
            by_mode = {}
            with self.lock:
                for token in tokens:
                    mode = self.mode_map.get(token, self.MODE_QUOTE)
                    by_mode.setdefault(mode, []).append(token)
            for mode, mtokens in by_mode.items():
                self.ws.send(json.dumps({"code": "unsub", "mode": mode, mode: mtokens}))
            with self.lock:
                for token in tokens:
                    self.subscribed_tokens.discard(token)
                    self.mode_map.pop(token, None)
                    self.token_exchange_map.pop(token, None)
            return True
        except Exception as e:
            self.logger.error(f"Error unsubscribing: {e}")
            return False

    def wait_for_connection(self, timeout=15.0):
        return self._connection_ready.wait(timeout=timeout)

    def is_connected(self):
        return self.connected and self.running

    # --- callbacks ------------------------------------------------------

    def _on_ws_open(self, ws):
        self.connected = True
        self.reconnect_attempts = 0
        self._auth_refresh_retries = 0
        self.reconnect_delay = self.RECONNECT_BASE_DELAY
        self.last_message_time = time.time()
        self._connection_ready.set()
        self.logger.info("Arrow WebSocket connected")
        self._start_health_check()
        if self.on_connect:
            try:
                self.on_connect()
            except Exception as e:
                self.logger.error(f"on_connect callback error: {e}")
        self._resubscribe_all()

    def _on_ws_message(self, ws, message):
        self.last_message_time = time.time()
        try:
            if isinstance(message, bytes):
                tick = self._parse_packet(message)
                if tick and self.on_ticks:
                    try:
                        self.on_ticks([tick])
                    except Exception as e:
                        self.logger.error(f"on_ticks callback error: {e}")
            elif isinstance(message, str):
                # Text frames are acks/errors.
                try:
                    data = json.loads(message)
                    if str(data.get("status", "")).lower() in ("error", "failure"):
                        self.logger.error(f"Arrow WS message: {data}")
                        if self._is_fatal_auth_error(message):
                            self._mark_fatal_error(message)
                    else:
                        self.logger.debug(f"Arrow WS text: {data}")
                except json.JSONDecodeError:
                    self.logger.debug(f"Non-JSON text: {message[:100]}")
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    _AUTH_FAILURE_INDICATORS = (
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "invalid token",
        "token expired",
        "session expired",
        "invalid appid",
    )

    def _is_fatal_auth_error(self, payload):
        if payload is None:
            return False
        text = str(payload).lower()
        return any(ind in text for ind in self._AUTH_FAILURE_INDICATORS)

    def _mark_fatal_error(self, message):
        if self._fatal_error:
            return
        self._fatal_error = True
        self._fatal_error_message = str(message)
        self.logger.error(f"Auth/token failure — will refresh and retry. {message}")

    def _on_ws_error(self, ws, error):
        self.logger.error(f"WebSocket error: {error}")
        self.connected = False
        if self._is_fatal_auth_error(error):
            self._mark_fatal_error(str(error))
        if self.on_error:
            try:
                self.on_error(error)
            except Exception:
                pass

    def _on_ws_close(self, ws, close_status_code, close_msg):
        self.logger.info(f"WebSocket closed (code={close_status_code}, msg={close_msg})")
        self.connected = False
        if not self._fatal_error and self._is_fatal_auth_error(close_msg):
            self._mark_fatal_error(f"close_msg={close_msg!r}")
        if self.on_disconnect:
            try:
                self.on_disconnect()
            except Exception as e:
                self.logger.error(f"on_disconnect callback error: {e}")

    # --- health check ---------------------------------------------------

    def _start_health_check(self):
        if self._health_check_thread and self._health_check_thread.is_alive():
            return
        self._health_check_thread = _real_threading.Thread(
            target=self._health_check_loop, daemon=True
        )
        self._health_check_thread.start()

    def _health_check_loop(self):
        while self.running and self.connected:
            if self._stop_event.wait(self.KEEPALIVE_INTERVAL):
                break
            if not self.running or not self.connected:
                break
            if (
                self.last_message_time
                and (time.time() - self.last_message_time) > self.DATA_TIMEOUT
            ):
                self.logger.error("Data stall detected — forcing reconnect")
                if self.ws:
                    try:
                        self.ws.close()
                    except Exception:
                        pass
                break

    def _resubscribe_all(self):
        with self.lock:
            if not self.subscribed_tokens:
                return
            by_mode: dict[str, list[int]] = {}
            for token in self.subscribed_tokens:
                by_mode.setdefault(self.mode_map.get(token, self.MODE_QUOTE), []).append(token)
        for mode, tokens in by_mode.items():
            for i in range(0, len(tokens), self.MAX_TOKENS_PER_SUBSCRIBE):
                batch = tokens[i : i + self.MAX_TOKENS_PER_SUBSCRIBE]
                try:
                    self.ws.send(json.dumps({"code": "sub", "mode": mode, mode: batch}))
                    if self._stop_event.wait(self.SUBSCRIPTION_DELAY):
                        return
                except Exception as e:
                    self.logger.error(f"Error re-subscribing batch: {e}")

    # --- binary parsing -------------------------------------------------
    #
    # Byte layout verified against the official pyarrow-client SDK
    # (pyarrow_client/sockets.py, MarketDataStream._parse_binary). All fields
    # are big-endian UNSIGNED integers; prices are in paise (divide by 100).
    #
    #   common : token 0:4, ltp 4:8. Bytes 8:13 carry the change flag +
    #            net-change, which the SDK ignores and recomputes.
    #   ltpc   : close 13:17  (17-byte packet only -- in larger packets
    #            13:17 is ltq, see below)
    #   quote  : ltq 13:17, avg_price 17:21, total_buy_qty 21:29,
    #            total_sell_qty 29:37, open 37:41, high 41:45, close 45:49,
    #            low 49:53, volume 53:61, ltt 61:65, time 65:69, oi 69:77,
    #            oi_day_high 77:85, oi_day_low 85:93
    #   full   : quote fields + lower_limit 93:97, upper_limit 97:101, then
    #            10 depth levels x 14B (qty u64, price u32, orders u16)
    #            starting at 109 (249B packet, 8 reserved bytes) or 101
    #            (legacy 241B packet). Levels 0-4 are bids, 5-9 asks.
    #
    # Hot path: precompiled Structs, ONE unpack per packet region, and no
    # lock acquisition (dict reads are GIL-atomic) -- this runs per tick.

    _HEADER = struct.Struct(">II")  # token, ltp
    _LTPC_CLOSE = struct.Struct(">I")  # close @13 (17B packet only)
    # token ltp [5 skip] ltq avg tbq tsq open high close low volume ltt time
    # oi oi_day_high oi_day_low  == 93 bytes
    _QUOTE = struct.Struct(">II5xIIQQIIIIQIIQQQ")
    _LIMITS = struct.Struct(">II")  # lower, upper @93
    _DEPTH_LEVEL = struct.Struct(">QIH")  # quantity, price, orders (14B x10)

    def _parse_packet(self, data: bytes) -> dict | None:
        """Parse one big-endian binary packet (one packet per WS message;
        mode identified by length)."""
        try:
            n = len(data)
            if n < 13:
                return None
            mode = self._SIZE_TO_MODE.get(n)
            if mode is None:
                # Unknown size: degrade to the richest layout we can parse.
                mode = self.MODE_FULL if n >= 241 else self.MODE_QUOTE if n >= 93 else self.MODE_LTP

            if n < 93:
                token, ltp_p = self._HEADER.unpack_from(data, 0)
                ltp = ltp_p / 100.0
                tick = {
                    "token": token,
                    "mode": mode,
                    "ltp": ltp,
                    "last_price": ltp,
                    "timestamp": int(time.time() * 1000),
                }
                if n == 17:
                    # ltpc: previous close (only in the dedicated 17B packet).
                    tick["close"] = self._LTPC_CLOSE.unpack_from(data, 13)[0] / 100.0
            else:
                (
                    token,
                    ltp_p,
                    ltq,
                    avg_p,
                    tbq,
                    tsq,
                    open_p,
                    high_p,
                    close_p,
                    low_p,
                    volume,
                    ltt,
                    feed_time,
                    oi,
                    oi_day_high,
                    oi_day_low,
                ) = self._QUOTE.unpack_from(data, 0)
                ltp = ltp_p / 100.0
                tick = {
                    "token": token,
                    "mode": mode,
                    "ltp": ltp,
                    "last_price": ltp,
                    "timestamp": feed_time * 1000 if feed_time else int(time.time() * 1000),
                    "ltq": ltq,
                    "average_price": avg_p / 100.0,
                    "total_buy_quantity": tbq,
                    "total_sell_quantity": tsq,
                    "open": open_p / 100.0,
                    "high": high_p / 100.0,
                    "close": close_p / 100.0,
                    "low": low_p / 100.0,
                    "volume": volume,
                    "oi": oi,
                    "oi_day_high": oi_day_high,
                    "oi_day_low": oi_day_low,
                }
                if ltt:
                    tick["ltt"] = ltt * 1000

                if n >= 241:
                    lower_p, upper_p = self._LIMITS.unpack_from(data, 93)
                    tick["lower_limit"] = lower_p / 100.0
                    tick["upper_limit"] = upper_p / 100.0
                    depth_offset = 109 if n >= 249 else 101
                    if n >= depth_offset + 140:
                        levels = [
                            {"quantity": q, "price": p / 100.0, "orders": o}
                            for q, p, o in self._DEPTH_LEVEL.iter_unpack(
                                data[depth_offset : depth_offset + 140]
                            )
                        ]
                        tick["depth"] = {"buy": levels[:5], "sell": levels[5:]}

            exchange = self.token_exchange_map.get(token)
            if exchange:
                tick["exchange"] = exchange
            return tick
        except Exception as e:
            self.logger.error(f"Error parsing packet (len={len(data)}): {e}")
            return None
