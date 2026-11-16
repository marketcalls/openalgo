"""
Sahi market-data WebSocket connection: one socket, one daemon thread, reconnects.

Uses the sync ``websocket-client`` low-level API (``create_connection`` plus a
``recv_data_frame`` loop) on a real daemon thread. Never asyncio.

Keepalive: the server pings every 30s and closes with 4408 if no pong arrives
within 15s; websocket-client answers pings inside ``recv_data_frame``. The read
timeout (STALL_TIMEOUT, twice the ping interval) counts pings as activity, so a
quiet market does not trip it but a half-open link does.

Close codes:
    1000 normal                 -> reconnect (we did not ask to stop)
    4401 / HTTP 401 token dead  -> re-read token from DB, bounded retries
    4403 / HTTP 403 forbidden   -> re-read token from DB once it changes, else stop
    4408 ping timeout           -> reconnect
    4409 slow consumer          -> reconnect
    4429 >5 connections/token   -> long backoff, bounded, then stop
Upgrade requests are rate limited (5/s, 250/min per user), so every reconnect
uses exponential backoff with jitter (1s start, 30s cap).

Subscriptions are connection-local and nothing is replayed, so ``on_open``
lets the owner resend every Subscribe on each (re)connect.
"""

import random
import time
from collections.abc import Callable

import websocket

from database.auth_db import get_auth_token
from utils import runtime as _runtime
from utils.logging import get_logger

# Real OS threading primitives (see utils.runtime): this client's thread does
# blocking socket reads and must not be a green thread.
_real_threading = _runtime.original("threading")

logger = get_logger(__name__)

SAHI_WS_URL = "wss://direct.sahi.com/v1/stream/marketdata"
# CloudFront refuses an upgrade with no User-Agent (HTTP 403).
USER_AGENT = "openalgo-sahi/1.0"

CLOSE_NORMAL = 1000
CLOSE_TOKEN_EXPIRED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_PING_TIMEOUT = 4408
CLOSE_SLOW_CONSUMER = 4409
CLOSE_TOO_MANY_CONNECTIONS = 4429

_AUTH_CODES = {CLOSE_TOKEN_EXPIRED, CLOSE_FORBIDDEN, 401, 403}
_LIMIT_CODES = {CLOSE_TOO_MANY_CONNECTIONS}


class SahiWebSocket:
    """Single Sahi market-data connection with automatic reconnect."""

    CONNECT_TIMEOUT = 10  # seconds for TCP + TLS + upgrade
    STALL_TIMEOUT = 60  # read timeout: 2x the server ping interval

    BACKOFF_BASE = 1.0
    BACKOFF_CAP = 30.0
    # A connection that lived this long resets the backoff counter, so a
    # server that accepts and immediately closes does not loop at 1s.
    STABLE_AFTER = 30.0

    MAX_AUTH_RETRIES = 3
    LIMIT_BACKOFF_BASE = 60.0
    LIMIT_BACKOFF_CAP = 300.0
    MAX_LIMIT_RETRIES = 5

    def __init__(
        self,
        access_token: str,
        user_id: str | None,
        on_message: Callable[[bytes], None],
        on_open: Callable[["SahiWebSocket"], None] | None = None,
        on_close: Callable[[int | None, str], None] | None = None,
    ):
        self.access_token = access_token
        self.user_id = user_id
        self.on_message = on_message
        self.on_open = on_open
        self.on_close = on_close

        self._lock = _real_threading.Lock()
        self._ws: websocket.WebSocket | None = None
        self._thread = None
        self._stop_event = _real_threading.Event()
        self._connected_event = _real_threading.Event()

        self.running = False
        self.connected = False
        self.fatal_error: str | None = None

        self._attempts = 0
        self._auth_retries = 0
        self._limit_retries = 0

        self.message_count = 0
        self.last_activity = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        if self.running:
            return True
        self.running = True
        self.fatal_error = None
        self._stop_event.clear()
        self._connected_event.clear()
        self._attempts = 0
        self._auth_retries = 0
        self._limit_retries = 0
        self._thread = _real_threading.Thread(target=self._run, daemon=True, name="SahiMarketWS")
        self._thread.start()
        logger.info("Sahi market-data WebSocket thread started")
        return True

    def stop(self) -> None:
        """Signal the thread to exit and close the socket. Never joins."""
        self.running = False
        self._stop_event.set()
        self._abort_socket()
        self.connected = False
        self._thread = None

    def wait_for_connection(self, timeout: float) -> bool:
        """Wait until connected, the client stops, or the timeout passes."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._connected_event.wait(0.25):
                return True
            if not self.running:
                return False
        return self._connected_event.is_set()

    def is_connected(self) -> bool:
        return self.connected and self.running

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send(self, frame: bytes) -> bool:
        """Send one binary ClientMessage. Returns False when not connected."""
        with self._lock:
            ws = self._ws
        if ws is None or not self.connected:
            return False
        try:
            ws.send_binary(frame)  # websocket-client serialises sends internally
            return True
        except Exception:
            logger.exception("Sahi stream send failed; will resubscribe on reconnect")
            self._abort_socket()
            return False

    # ------------------------------------------------------------------
    # Connection thread
    # ------------------------------------------------------------------

    def _abort_socket(self) -> None:
        with self._lock:
            ws = self._ws
        if ws is None:
            return
        try:
            # shutdown(SHUT_RDWR) wakes the reader thread blocked in recv; that
            # thread then closes the socket itself (close-before-reconnect).
            ws.abort()
        except Exception:
            pass

    def _connect_once(self) -> tuple[int | None, str]:
        """Open, read until closed. Returns (close_code_or_http_status, reason)."""
        headers = [
            f"Authorization: Bearer {self.access_token}",
            f"User-Agent: {USER_AGENT}",
        ]
        try:
            ws = websocket.create_connection(
                SAHI_WS_URL,
                timeout=self.CONNECT_TIMEOUT,
                header=headers,
                enable_multithread=True,
            )
        except websocket.WebSocketBadStatusException as e:
            return getattr(e, "status_code", None), "handshake refused"
        except Exception as e:
            return None, f"connect failed: {type(e).__name__}: {e}"

        opened_at = time.monotonic()
        with self._lock:
            self._ws = ws
        if self._stop_event.is_set():
            with self._lock:
                self._ws = None
            # stop() landed between the handshake and the read loop, whose
            # finally closes the socket on every other path: close it here,
            # not only shut it down, or it waits for the garbage collector.
            try:
                ws.shutdown()
            except Exception:
                pass
            return CLOSE_NORMAL, "stopped"

        code: int | None = None
        reason = ""
        try:
            ws.settimeout(self.STALL_TIMEOUT)
            self.connected = True
            self.last_activity = time.time()
            self._connected_event.set()
            logger.info("Sahi market-data WebSocket connected")

            if self.on_open:
                try:
                    self.on_open(self)
                except Exception:
                    logger.exception("Error in Sahi on_open callback")

            while not self._stop_event.is_set():
                try:
                    opcode, frame = ws.recv_data_frame(control_frame=True)
                except websocket.WebSocketTimeoutException:
                    reason = f"no data or ping for {self.STALL_TIMEOUT}s (stalled link)"
                    logger.warning("Sahi stream stalled: %s; reconnecting", reason)
                    break
                self.last_activity = time.time()

                if opcode == websocket.ABNF.OPCODE_BINARY:
                    self.message_count += 1
                    try:
                        self.on_message(frame.data)
                    except Exception:
                        logger.exception("Error handling Sahi stream message")
                elif opcode == websocket.ABNF.OPCODE_CLOSE:
                    data = frame.data or b""
                    if len(data) >= 2:
                        code = int.from_bytes(data[:2], "big")
                        reason = data[2:].decode("utf-8", errors="replace")
                    break
                elif opcode == websocket.ABNF.OPCODE_TEXT:
                    logger.debug("Unexpected text frame on Sahi stream ignored")
                # PING (auto-ponged by websocket-client) and PONG: activity only
        except websocket.WebSocketConnectionClosedException:
            reason = reason or "connection closed"
        except Exception as e:
            if not self._stop_event.is_set():
                reason = f"{type(e).__name__}: {e}"
                logger.warning("Sahi stream read error: %s", reason)
        finally:
            was_connected = self.connected
            self.connected = False
            self._connected_event.clear()
            with self._lock:
                self._ws = None
            try:
                # Close the socket without waiting on a close handshake: a server
                # close was already answered inside recv_data_frame, and a
                # stalled or aborted link will never answer one.
                ws.shutdown()
            except Exception:
                pass
            if time.monotonic() - opened_at >= self.STABLE_AFTER:
                # A connection that stayed up starts every retry count again.
                self._attempts = 0
                self._auth_retries = 0
                self._limit_retries = 0
            if was_connected and self.on_close:
                try:
                    self.on_close(code, reason)
                except Exception:
                    logger.exception("Error in Sahi on_close callback")
        return code, reason

    def _backoff(self) -> float:
        delay = min(self.BACKOFF_CAP, self.BACKOFF_BASE * (2 ** min(self._attempts, 10)))
        self._attempts += 1
        return delay / 2 + random.uniform(0, delay / 2)

    def _refresh_token(self) -> bool:
        """Re-read the token from the DB. True if it changed."""
        if not self.user_id:
            return False
        try:
            token = get_auth_token(self.user_id, bypass_cache=True)
        except Exception:
            logger.exception("Error re-reading Sahi auth token")
            return False
        if not token:
            logger.warning("No Sahi auth token in the database; keeping the current one")
            return False
        changed = token != self.access_token
        self.access_token = token
        return changed

    def _give_up(self, message: str) -> None:
        self.fatal_error = message
        self.running = False
        logger.error("Sahi market-data stream stopped: %s", message)

    def _run(self) -> None:
        while self.running and not self._stop_event.is_set():
            code, reason = self._connect_once()
            if not self.running or self._stop_event.is_set():
                break

            if code in _AUTH_CODES:
                label = (
                    "token expired or revoked"
                    if code in (CLOSE_TOKEN_EXPIRED, 401)
                    else "forbidden (scope)"
                )
                if self._auth_retries >= self.MAX_AUTH_RETRIES:
                    self._give_up(
                        f"auth failure ({code}, {label}) persisted after "
                        f"{self.MAX_AUTH_RETRIES} token refreshes; re-login required"
                    )
                    break
                self._auth_retries += 1
                if not self._refresh_token():
                    self._give_up(
                        f"auth failure ({code}, {label}) and the stored token has not "
                        "changed; re-login required"
                    )
                    break
                delay = self._backoff()
                logger.warning(
                    "Sahi stream auth failure (%s, %s); retrying with a fresh token in "
                    "%.1fs (attempt %d/%d)",
                    code,
                    label,
                    delay,
                    self._auth_retries,
                    self.MAX_AUTH_RETRIES,
                )
            elif code in _LIMIT_CODES:
                if self._limit_retries >= self.MAX_LIMIT_RETRIES:
                    self._give_up(
                        "more than 5 concurrent market-data connections for this Sahi "
                        "token (4429). Close other Sahi streaming apps or sessions, then "
                        "reconnect"
                    )
                    break
                delay = min(
                    self.LIMIT_BACKOFF_CAP,
                    self.LIMIT_BACKOFF_BASE * (2**self._limit_retries),
                )
                self._limit_retries += 1
                logger.error(
                    "Sahi rejected the stream: more than 5 concurrent connections for "
                    "this token (4429). Close other Sahi streaming apps or sessions. "
                    "Retrying in %.0fs (attempt %d/%d)",
                    delay,
                    self._limit_retries,
                    self.MAX_LIMIT_RETRIES,
                )
            else:
                delay = self._backoff()
                if code == 429:
                    # Upgrade rate limit (5/s, 250/min per user): wait the cap.
                    delay = self.BACKOFF_CAP
                logger.info(
                    "Sahi stream disconnected (code=%s, reason=%s); reconnecting in %.1fs",
                    code,
                    reason,
                    delay,
                )
                # Pick up a token rolled over in the DB (daily ~3 AM IST).
                self._refresh_token()

            if self._stop_event.wait(delay):
                break

        self.connected = False
        self._connected_event.clear()
        logger.info("Sahi market-data WebSocket thread exited")
