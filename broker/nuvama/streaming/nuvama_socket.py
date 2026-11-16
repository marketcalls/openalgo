"""Nuvama streaming client: one TCP socket, newline-delimited JSON both ways.

Protocol, from the official SDK (feed/feed.py, feed/reduced_quotes_feed.py,
feed/depth_feed.py):

- connect to ncst.nuvamawealth.com:9443 (plain TCP)
- every request is one JSON object plus "\\n":
  {"request": {"streaming_type": "quote" | "quote2" | ..., "data": {"accType":
  ..., "symbols": [{"symbol": "2885_NSE"}, ...]}, "formFactor": "P", "appID":
  ..., "response_format": "json", "request_type": "subscribe" |
  "unsubscribe"}, "echo": {}}
- a subscribe request REPLACES the symbol set of its streaming type (checked
  live: subscribing BANKNIFTY alone after NIFTY stopped NIFTY), so the whole
  set always goes in one request and is never split into chunks; one request
  of 545 NFO options was accepted. An unsubscribe carries no symbols and
  ends that type
- requests sent back to back can be dropped by the server (seen live: a
  quote subscribe sent milliseconds after a quote2 one was sometimes ignored)

Subscriptions are therefore batched: set_symbols() only records the wanted
set, and the socket thread sends it once the changes have been quiet for
BATCH_QUIET seconds (or BATCH_MAX_WAIT after the first change, so a long
burst still goes out), one request per streaming type, at least SEND_GAP
apart. An option chain subscribing hundreds of symbols one call at a time
becomes one request per type instead of a growing request every half second.
- "{}\\n" every 30 seconds keeps the socket open
- every answer line is {"response": {"streaming_type": ..., "data": {...}}}

This runs in the websocket proxy process, which is never monkey-patched, so the
threads and locks here are real ones.
"""

import json
import socket
import threading
import time

from broker.nuvama.api.baseurl import STREAM_HOST, STREAM_PORT
from utils.logging import get_logger

logger = get_logger(__name__)

HEARTBEAT_SECONDS = 30
# With symbols subscribed and nothing at all received for this long, reconnect.
STALL_SECONDS = 180
SEND_GAP = 0.5
BATCH_QUIET = 0.5
BATCH_MAX_WAIT = 2.0
READ_TIMEOUT = 0.25
CONNECT_TIMEOUT = 15
MAX_BACKOFF = 30


class NuvamaStreamClient:
    """Keeps the socket up and the subscriptions sent; hands each packet to on_packet."""

    def __init__(
        self,
        app_id,
        account_type,
        on_packet,
        on_connect=None,
        on_disconnect=None,
        standing_requests=None,
        name="nuvama-stream",
    ):
        self.app_id = app_id
        self.account_type = account_type
        self.on_packet = on_packet
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        # Requests (JSON lines) sent on every connect, such as the order feed's
        # one subscription, which carries no symbol set.
        self.standing_requests = list(standing_requests or [])
        self.name = name

        self._sock = None
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._thread = None
        self._last_packet = 0.0
        # streaming_type -> set of streaming symbols
        self._wanted = {"quote": set(), "quote2": set()}
        # streaming types whose set changed and has not been sent on this socket
        self._dirty = set()
        # streaming types this socket has subscribed (so an empty set unsubscribes)
        self._active = set()
        # monotonic times of the first and the latest change still waiting to go
        self._first_change = None
        self._last_change = 0.0

    # --- lifecycle --------------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._close()

    def is_connected(self):
        return self._connected.is_set()

    def wait_for_connection(self, timeout):
        return self._connected.wait(timeout)

    # --- subscriptions ----------------------------------------------------------

    def set_symbols(self, streaming_type, symbols):
        """Replace the symbol set of one streaming type; the socket thread sends it."""
        new = set(symbols)
        with self._state_lock:
            if new == self._wanted[streaming_type]:
                return
            self._wanted[streaming_type] = new
            self._dirty.add(streaming_type)
            now = time.monotonic()
            self._last_change = now
            if self._first_change is None:
                self._first_change = now

    def _flush_one(self, now):
        """Send one queued streaming type once the batch has settled. Socket thread only."""
        with self._state_lock:
            if not self._dirty:
                self._first_change = None
                return False
            settled = now - self._last_change >= BATCH_QUIET
            overdue = self._first_change is not None and now - self._first_change >= BATCH_MAX_WAIT
            if not (settled or overdue):
                return False
            streaming_type = sorted(self._dirty)[0]
            self._dirty.discard(streaming_type)
            symbols = sorted(self._wanted[streaming_type])
            if not symbols and streaming_type not in self._active:
                return False
        self._send_type(streaming_type, symbols)
        logger.info(f"Nuvama {streaming_type} subscription sent with {len(symbols)} symbols")
        if symbols:
            self._active.add(streaming_type)
        else:
            self._active.discard(streaming_type)
        return True

    def _request(self, streaming_type, symbols, request_type):
        body = {
            "request": {
                "streaming_type": streaming_type,
                "data": {
                    "accType": self.account_type,
                    "symbols": [{"symbol": s} for s in symbols],
                },
                "formFactor": "P",
                "appID": self.app_id,
                "response_format": "json",
                "request_type": request_type,
            },
            "echo": {},
        }
        return json.dumps(body) + "\n"

    def _send_type(self, streaming_type, symbols):
        if symbols:
            self._send(self._request(streaming_type, symbols, "subscribe"))
        else:
            self._send(self._request(streaming_type, [], "unsubscribe"))

    def _send(self, line):
        with self._write_lock:
            sock = self._sock
            if sock is None:
                return False
            try:
                sock.sendall(line.encode("utf-8"))
                return True
            except OSError as exc:
                logger.warning(f"Nuvama stream write failed: {exc}")
                return False

    # --- connection loop ----------------------------------------------------------

    def _open(self):
        sock = socket.create_connection((STREAM_HOST, STREAM_PORT), timeout=CONNECT_TIMEOUT)
        # Short reads so the loop can send queued subscriptions and check stop.
        sock.settimeout(READ_TIMEOUT)
        with self._write_lock:
            self._sock = sock
        self._last_packet = time.monotonic()
        # A new socket has nothing subscribed: queue every non-empty set.
        with self._state_lock:
            self._active = set()
            self._dirty = {k for k, v in self._wanted.items() if v}
            # A fresh socket sends what is wanted at once.
            self._first_change = None
            self._last_change = 0.0
        self._connected.set()
        logger.info(f"Nuvama stream connected ({self.name})")
        for line in self.standing_requests:
            self._send(line)
        if self.on_connect:
            self.on_connect()

    def _close(self):
        was_connected = self._connected.is_set()
        self._connected.clear()
        with self._write_lock:
            sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if was_connected and self.on_disconnect:
            self.on_disconnect()

    def _run(self):
        backoff = 1
        while not self._stop.is_set():
            try:
                self._open()
                backoff = 1
                self._read_loop()
            except OSError as exc:
                if not self._stop.is_set():
                    logger.warning(f"Nuvama stream connection lost: {exc}")
            except Exception:
                logger.exception("Nuvama stream loop failed")
            finally:
                self._close()
            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 2, MAX_BACKOFF)
        logger.info("Nuvama stream stopped")

    def _read_loop(self):
        next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
        next_send = 0.0
        sock = self._sock
        pending = b""
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_send and self._flush_one(now):
                next_send = now + SEND_GAP
                # Data starts after a subscribe; the wait before it is not a stall.
                self._last_packet = max(self._last_packet, now)
            if now >= next_heartbeat:
                self._send("{}\n")
                next_heartbeat = now + HEARTBEAT_SECONDS
            if self._active and now - self._last_packet > STALL_SECONDS:
                raise OSError(f"no data for {STALL_SECONDS} seconds")
            try:
                chunk = sock.recv(65536)
            except TimeoutError:
                continue
            if not chunk:
                raise OSError("socket closed by Nuvama")
            self._last_packet = time.monotonic()
            pending += chunk
            *lines, pending = pending.split(b"\n")
            for raw in lines:
                self._handle_line(raw)

    def _handle_line(self, raw):
        line = raw.strip()
        if not line or line == b"{}":
            return
        try:
            packet = json.loads(line)
        except ValueError:
            return
        response = packet.get("response") if isinstance(packet, dict) else None
        if isinstance(response, dict):
            try:
                self.on_packet(response.get("streaming_type"), response.get("data") or {})
            except Exception:
                logger.exception("Nuvama stream packet handler failed")
