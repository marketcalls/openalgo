"""Rupeezy Vortex market-data websocket client (wss://wire.rupeezy.in/ws).

Sync `websocket-client` on a daemon thread (never asyncio, see CLAUDE.md),
with:
  - protocol ping/pong keepalive (the official vortex_api SDK pings every
    2.5s and drops the link when pongs stop; the server answers pings)
  - reconnect with interruptible exponential backoff
  - a fresh access token re-read from the DB on every reconnect (daily
    ~3 AM IST rollover) and a bounded retry on auth failure
  - resubscribe-on-reconnect
  - daemon threads are never join()ed

Protocol (docs/latest/feed + vortex_api/vortex_feed.py):
  - URL carries the token: wss://wire.rupeezy.in/ws?auth_token=<token>
  - subscribe/unsubscribe are JSON text frames, one per instrument:
        {"ticker": "NSE:RELIANCE", "mode": "full", "message_type": "subscribe"}
  - price frames are binary, little-endian: uint16 packet count, then per
    packet a uint16 length and the packet. The length identifies the mode:
    22 = ltp, 62 = ohlcv, 266 = full. Every packet starts with a 10-byte
    exchange string ("NSE_EQ") and an int32 token.
  - text frames carry order postbacks; they are not used here.
  - at most 1000 instruments per connection, 3 connections per token.
"""

import json
import ssl
import struct
import threading
import time
from collections.abc import Callable

import websocket

from broker.rupeezy.api.baseurl import WS_URL
from database.auth_db import get_auth_token
from utils import runtime as _runtime
from utils.logging import get_logger

logger = get_logger(__name__)

_real_threading = _runtime.original("threading")

# Packet layouts, verified against vortex_api 2.1.8 VortexFeed._parse_binary.
_LTP = struct.Struct("<10sid")  # exchange, token, ltp  -> 22 bytes
# exchange token ltp ltt open high low close volume -> 62 bytes
_OHLCV = struct.Struct("<10sididdddi")
# ... + last_update_time ltq avg_price total_buy_qty total_sell_qty oi
_FULL_HEAD = struct.Struct("<10sididdddiiidqqi")  # 98 bytes
_DEPTH_LEVEL = struct.Struct("<dii")  # price, quantity, orders -> 16 bytes x 10
_DPR = struct.Struct("<ii")  # dpr_high, dpr_low in paise
_U16 = struct.Struct("<H")

LTP_SIZE = _LTP.size
OHLCV_SIZE = _OHLCV.size
FULL_SIZE = _FULL_HEAD.size + 10 * _DEPTH_LEVEL.size + _DPR.size
assert (LTP_SIZE, OHLCV_SIZE, FULL_SIZE) == (22, 62, 266)


def parse_packet(packet):
    """Parse one Vortex price packet into a tick dict, or None if unknown size."""
    n = len(packet)
    if n == LTP_SIZE:
        exchange, token, ltp = _LTP.unpack(packet)
        return {
            "mode": "ltp",
            "exchange": exchange.rstrip(b"\x00").decode(),
            "token": token,
            "ltp": ltp,
        }
    if n == OHLCV_SIZE:
        exchange, token, ltp, ltt, op, hi, lo, cl, vol = _OHLCV.unpack(packet)
        return {
            "mode": "ohlcv",
            "exchange": exchange.rstrip(b"\x00").decode(),
            "token": token,
            "ltp": ltp,
            "ltt": ltt,
            "open": op,
            "high": hi,
            "low": lo,
            "close": cl,
            "volume": vol,
        }
    if n == FULL_SIZE:
        (exchange, token, ltp, ltt, op, hi, lo, cl, vol, lut, ltq, avg, tbq, tsq, oi) = (
            _FULL_HEAD.unpack_from(packet, 0)
        )
        levels = [
            {"price": p, "quantity": q, "orders": o}
            for p, q, o in _DEPTH_LEVEL.iter_unpack(
                packet[_FULL_HEAD.size : _FULL_HEAD.size + 10 * _DEPTH_LEVEL.size]
            )
        ]
        dpr_high, dpr_low = _DPR.unpack_from(packet, n - _DPR.size)
        return {
            "mode": "full",
            "exchange": exchange.rstrip(b"\x00").decode(),
            "token": token,
            "ltp": ltp,
            "ltt": ltt,
            "open": op,
            "high": hi,
            "low": lo,
            "close": cl,
            "volume": vol,
            "last_update_time": lut,
            "ltq": ltq,
            "average_price": avg,
            "total_buy_quantity": tbq,
            "total_sell_quantity": tsq,
            "oi": oi,
            "depth": {"buy": levels[:5], "sell": levels[5:]},
            "upper_limit": dpr_high / 100.0,
            "lower_limit": dpr_low / 100.0,
        }
    return None


def split_message(message):
    """Split a binary frame into its packets. Frames under 2 bytes are heartbeats."""
    if len(message) < 2:
        return []
    count = _U16.unpack_from(message, 0)[0]
    packets = []
    offset = 2
    for _ in range(count):
        if offset + 2 > len(message):
            break
        length = _U16.unpack_from(message, offset)[0]
        offset += 2
        packets.append(message[offset : offset + length])
        offset += length
    return packets


class RupeezyWebSocket:
    """Sync client for the Vortex price feed."""

    PING_INTERVAL = 10
    PING_TIMEOUT = 5

    MAX_INSTRUMENTS_PER_CONNECTION = 1000

    RECONNECT_BASE_DELAY = 2
    RECONNECT_MAX_DELAY = 60
    RECONNECT_MAX_TRIES = 50
    MAX_AUTH_REFRESH_RETRIES = 3

    _AUTH_FAILURE_INDICATORS = (
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "invalid token",
        "expired",
    )

    def __init__(self, access_token, on_ticks=None, user_id=None):
        self.access_token = access_token
        self.user_id = user_id
        self.on_ticks: Callable | None = on_ticks
        self.on_connect: Callable | None = None
        self.on_disconnect: Callable | None = None

        self.ws: websocket.WebSocketApp | None = None
        self.connected = False
        self.running = False
        self.lock = _real_threading.Lock()

        # ticker -> vortex mode, replayed on reconnect.
        self.subscriptions: dict[str, str] = {}

        self._ws_thread = None
        self._connection_ready = _real_threading.Event()
        self._stop_event = _real_threading.Event()
        self.reconnect_attempts = 0
        self._auth_failed = False
        self._auth_refresh_retries = 0

    def _url(self):
        return f"{WS_URL}?auth_token={self.access_token}"

    # --- lifecycle ------------------------------------------------------

    def start(self):
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self._connection_ready.clear()
        self._ws_thread = _real_threading.Thread(target=self._run, daemon=True, name="RupeezyWS")
        self._ws_thread.start()

    def stop(self):
        self.running = False
        self._stop_event.set()
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                logger.debug(f"Error closing Rupeezy websocket: {e}")
        # Never join daemon threads (eventlet raises Timeout on join).
        self._ws_thread = None
        self.connected = False

    def wait_for_connection(self, timeout=15.0):
        return self._connection_ready.wait(timeout=timeout)

    def is_connected(self):
        return self.connected and self.running

    def _refresh_access_token(self):
        """Re-read the token from the DB. True if it changed."""
        if not self.user_id:
            return False
        try:
            token = get_auth_token(self.user_id, bypass_cache=True)
        except Exception:
            logger.exception("Error refreshing Rupeezy access token")
            return False
        if not token:
            return False
        changed = token != self.access_token
        self.access_token = token
        return changed

    def _run(self):
        while self.running and not self._stop_event.is_set():
            try:
                self.ws = websocket.WebSocketApp(
                    self._url(),
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                # CERT_REQUIRED: the access token rides in the URL.
                self.ws.run_forever(
                    sslopt={"cert_reqs": ssl.CERT_REQUIRED},
                    ping_interval=self.PING_INTERVAL,
                    ping_timeout=self.PING_TIMEOUT,
                )
            except Exception:
                logger.exception("Rupeezy websocket run_forever error")

            self.connected = False
            if not self.running or self._stop_event.is_set():
                break

            if self._auth_failed:
                self._auth_failed = False
                self._auth_refresh_retries += 1
                if (
                    self._auth_refresh_retries > self.MAX_AUTH_REFRESH_RETRIES
                    or not self._refresh_access_token()
                ):
                    logger.error(
                        "Rupeezy feed stopped: the broker session has expired. Log in again."
                    )
                    self.running = False
                    break
                if self._stop_event.wait(self.RECONNECT_BASE_DELAY):
                    break
                continue

            self.reconnect_attempts += 1
            if self.reconnect_attempts >= self.RECONNECT_MAX_TRIES:
                logger.error("Rupeezy feed stopped after too many reconnect attempts")
                self.running = False
                break
            delay = min(
                self.RECONNECT_BASE_DELAY * (1.5**self.reconnect_attempts), self.RECONNECT_MAX_DELAY
            )
            logger.info(
                f"Rupeezy feed reconnecting in {delay:.0f}s (attempt {self.reconnect_attempts})"
            )
            if self._stop_event.wait(delay):
                break
            self._refresh_access_token()

        logger.info("Rupeezy websocket thread exited")

    # --- subscriptions --------------------------------------------------

    def _send(self, ticker, mode, message_type):
        payload = {"ticker": ticker, "mode": mode, "message_type": message_type}
        self.ws.send(json.dumps(payload))

    def _try_send(self, ticker, mode, message_type):
        """Send one subscription frame. Called with self.lock held, so the
        frame and the bookkeeping it reflects can never interleave with
        another subscribe, unsubscribe or replay. False if the socket was not
        writable; the subscription state still holds, so a subscribe is
        replayed on the next connect."""
        if not (self.connected and self.ws):
            return False
        try:
            self._send(ticker, mode, message_type)
            return True
        except Exception as e:
            logger.warning(
                f"Rupeezy {message_type} for {ticker} not sent ({e}); will retry on reconnect"
            )
            return False

    def subscribe(self, ticker, mode):
        """Subscribe (or change mode). Recorded first, so it is replayed on
        (re)connect even if the socket is down or drops mid-send."""
        with self.lock:
            if (
                ticker not in self.subscriptions
                and len(self.subscriptions) >= self.MAX_INSTRUMENTS_PER_CONNECTION
            ):
                raise ValueError("Rupeezy allows at most 1000 instruments per connection.")
            self.subscriptions[ticker] = mode
            self._try_send(ticker, mode, "subscribe")

    def unsubscribe(self, ticker):
        with self.lock:
            mode = self.subscriptions.pop(ticker, None)
            if mode:
                self._try_send(ticker, mode, "unsubscribe")

    def _resubscribe_all(self):
        with self.lock:
            tickers = list(self.subscriptions)
        for ticker in tickers:
            if self._stop_event.is_set() or not self.connected:
                return
            with self.lock:
                # Re-read under the lock: an unsubscribe since the snapshot
                # must not be undone by a stale replay.
                mode = self.subscriptions.get(ticker)
                if mode and not self._try_send(ticker, mode, "subscribe"):
                    return

    # --- callbacks ------------------------------------------------------

    def _on_open(self, ws):
        self.connected = True
        self.reconnect_attempts = 0
        self._auth_refresh_retries = 0
        self._connection_ready.set()
        logger.info("Rupeezy websocket connected")
        if self.on_connect:
            try:
                self.on_connect()
            except Exception:
                logger.exception("Rupeezy on_connect callback error")
        self._resubscribe_all()

    def _on_message(self, ws, message):
        if not isinstance(message, bytes):
            # Order postbacks and acks arrive as JSON text.
            logger.debug(f"Rupeezy websocket text: {str(message)[:200]}")
            return
        ticks = []
        for packet in split_message(message):
            try:
                tick = parse_packet(packet)
            except Exception as e:
                logger.error(f"Error parsing Rupeezy packet (len={len(packet)}): {e}")
                continue
            if tick:
                ticks.append(tick)
        if ticks and self.on_ticks:
            try:
                self.on_ticks(ticks)
            except Exception:
                logger.exception("Rupeezy on_ticks callback error")

    def _is_auth_error(self, value):
        text = str(value).lower()
        return any(ind in text for ind in self._AUTH_FAILURE_INDICATORS)

    def _on_error(self, ws, error):
        logger.error(f"Rupeezy websocket error: {error}")
        self.connected = False
        if self._is_auth_error(error):
            self._auth_failed = True

    def _on_close(self, ws, code, msg):
        logger.info(f"Rupeezy websocket closed (code={code}, msg={msg})")
        self.connected = False
        if msg and self._is_auth_error(msg):
            self._auth_failed = True
        if self.on_disconnect:
            try:
                self.on_disconnect()
            except Exception:
                logger.exception("Rupeezy on_disconnect callback error")
