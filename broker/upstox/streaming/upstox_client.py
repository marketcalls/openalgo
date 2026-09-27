# broker/upstox/streaming/upstox_client.py
"""
Synchronous Upstox V3 WebSocket client using websocket-client library.

Uses the same sync pattern as Angel/Dhan adapters to avoid asyncio event loop
conflicts with eventlet in gunicorn deployments.
"""
import json
import ssl
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import requests
import websocket
from google.protobuf.json_format import MessageToDict

from database.auth_db import get_auth_token
from utils.logging import get_logger

from . import MarketDataFeedV3_pb2


class UpstoxWebSocketClient:
    """
    Upstox V3 WebSocket client implementation (synchronous).

    Uses websocket-client (sync) instead of websockets (async) to avoid
    creating a second asyncio event loop which conflicts with eventlet
    in gunicorn+eventlet deployments.
    """

    API_URL = "https://api.upstox.com/v3"
    AUTH_ENDPOINT = f"{API_URL}/feed/market-data-feed/authorize"

    # HTTP request timeout
    HTTP_TIMEOUT = 10

    # Health check settings - detect silent stalls
    HEALTH_CHECK_INTERVAL = 30
    DATA_TIMEOUT = 90

    # Granularity of the reconnect backoff sleep. The loop waits in slices of
    # this size so disconnect() is noticed within it instead of at the end of a
    # full 2-30s backoff (see _run_websocket).
    BACKOFF_SLICE = 0.2

    # Per-mode "individual" key caps from Upstox V3's connection & subscription
    # limits table (upstox-api-docs/21a-websocket-market-data-v3.md). Keyed by the
    # Upstox mode STRING, not by OpenAlgo's internal mode int — OpenAlgo mode 3
    # (depth) maps to `full`, NOT to `full_d30` (see
    # UpstoxWebSocketAdapter._get_upstox_mode), so capping "depth" at 50 would
    # throttle every depth subscription to 1/40th of what Upstox actually allows.
    # `full_d30` is the dangerous row: 50 keys, 40x smaller than plain `full`, so a
    # depth-30 subscription that is harmless in any other mode breaches its cap at
    # the 51st symbol.
    MODE_KEY_LIMITS = {
        "ltpc": 5000,
        "option_greeks": 3000,
        "full": 2000,
        "full_d30": 50,
    }
    # An unrecognised / future mode is treated as `full`, the tightest of the
    # non-d30 rows, so a new mode string cannot slip through uncapped.
    DEFAULT_MODE_KEY_LIMIT = 2000

    # The "combined" column of the same table. The doc does not define the word,
    # so this takes the conservative reading: once MORE THAN ONE mode is live on a
    # connection, the total key count across all of them is capped by the smallest
    # combined figure among the modes in use. Never applied while a single mode is
    # in use, where the individual cap above is the operative one.
    MODE_COMBINED_LIMITS = {
        "ltpc": 2000,
        "option_greeks": 2000,
        "full": 1500,
        "full_d30": 1500,
    }
    DEFAULT_MODE_COMBINED_LIMIT = 1500

    # A socket that has never completed a handshake is a different failure from one
    # that dropped; say so after this many consecutive failed attempts rather than
    # retrying quietly for the full budget.
    NEVER_CONNECTED_ALERT_AFTER = 3

    def __init__(self, auth_token: str, user_id: str | None = None):
        self.auth_token = auth_token
        # user_id is used on reconnect to re-read a fresh bearer token from the
        # database. Indian broker tokens roll over daily at ~3 AM IST, so the
        # reconnect must NOT sign the new authorize request with the dead
        # construction-time token.
        self.user_id = user_id
        self.ws: websocket.WebSocketApp | None = None
        self.logger = get_logger("upstox_websocket")
        self._subscriptions: set = set()
        self.running = False
        self._ws_thread: threading.Thread | None = None
        self._health_check_thread: threading.Thread | None = None
        self._last_message_time: float | None = None
        self._connected = False

        # Live key count per Upstox mode string, used to enforce the subscription
        # caps above. Reset on every handshake (see `_on_ws_open`) because Upstox
        # drops all server-side subscriptions when the socket closes, and the
        # adapter replays them from scratch.
        self._keys_by_mode: dict[str, set] = {}

        # True once any handshake has ever succeeded. Distinguishes "the feed
        # dropped" from "the feed was never allowed to open" (issue: an over-limit
        # 3rd connection on an Upstox Standard account).
        self._ever_connected = False

        # Set by _force_reconnect() so _run_websocket can log the next
        # reconnect attempt as STALL-TRIGGERED instead of looking identical
        # to a network-induced reconnect (issue #1357).
        self._stall_triggered_reconnect = False
        self.callbacks: dict[str, Callable | None] = {
            "on_connect": None,
            "on_message": None,
            "on_error": None,
            "on_close": None,
        }
        # Per-disconnection reconnect budget. The counter is reset to 0 on
        # every successful handshake (see `_on_ws_open`) — so this value caps
        # how many back-to-back failures we'll tolerate within one
        # disconnection storm, not the lifetime total. 5 was too aggressive
        # under the cold-start race + 90s data-stall watchdog combination
        # (the watchdog reconnected 5× during a slow start, then gave up).
        self._reconnect_config = {"max_attempts": 50, "base_delay": 2, "max_delay": 30}

        # Serialises connect() against itself. Nothing else takes it — in
        # particular _run_websocket never does — so it cannot deadlock the feed.
        self._connect_lock = threading.Lock()

    def connect(self) -> bool:
        """Establish WebSocket connection in a background thread.

        Returns immediately after starting the connection thread (same as Angel).
        The actual connection happens asynchronously - do NOT block with wait()
        as that causes eventlet timeout issues in gunicorn+eventlet deployments.

        Re-entrant calls are refused rather than honoured. A second connect()
        while a loop is alive would build a second WebSocketApp, overwrite
        `self.ws` and leave the first socket and thread with nothing holding a
        handle to either — an unrecoverable leak, because the orphan stays
        blocked inside run_forever() for the life of the process. Refusing is
        the right half of that trade: tearing the live socket down instead
        would drop a working feed (Upstox discards every server-side
        subscription on close) for what is almost always a redundant
        "make sure we are connected" call, and it could not be done safely
        anyway — threads are not joined here (see disconnect()), so the old
        loop could still be inside run_forever() when the new one starts, which
        is precisely the two-loop state this guard exists to prevent. A caller
        that genuinely wants a fresh socket calls disconnect() first.
        """
        with self._connect_lock:
            # NOTE: this guard cannot interfere with the reconnect inside
            # _run_websocket. That loop rebuilds the WebSocketApp inline and
            # calls run_forever() again on the SAME iteration of the same
            # thread — it never re-enters connect() — so reconnection is
            # untouched by anything decided here.
            if self.running and self._ws_thread is not None and self._ws_thread.is_alive():
                self.logger.info(
                    "Connect ignored - a WebSocket loop is already running "
                    "(connected or reconnecting)"
                )
                return True

            if not self._is_valid_auth_token():
                self._trigger_error("Invalid or missing access token")
                return False

            ws_url = self._get_websocket_url()
            if not ws_url:
                self._trigger_error("Failed to get WebSocket URL")
                return False

            self.running = True

            # Create WebSocketApp with callbacks
            # Use on_message only (not on_data) — on_message receives both
            # text (str) and binary (bytes) messages reliably
            self.ws = websocket.WebSocketApp(
                ws_url,
                on_open=self._on_ws_open,
                on_message=self._on_ws_message,
                on_error=self._on_ws_error,
                on_close=self._on_ws_close,
                on_ping=self._on_ws_ping,
                on_pong=self._on_ws_pong,
            )

            # Run WebSocket in a daemon thread (same pattern as Angel/Dhan)
            # Return immediately - connection happens in background
            self._ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
            self._ws_thread.start()

        self.logger.info("Upstox WebSocket connection thread started")
        return True

    def _run_websocket(self):
        """Run the WebSocket connection with reconnection logic"""
        self._reconnect_attempts = 0
        while self.running:
            try:
                # Enable keepalive pings (same as Dhan/Flattrade which work reliably).
                # websocket-client needs explicit pings to keep the connection alive,
                # unlike the async websockets library which has internal keepalive.
                self.ws.run_forever(
                    sslopt={"cert_reqs": ssl.CERT_NONE},
                    ping_interval=30,
                    ping_timeout=10,
                )
            except Exception as e:
                self.logger.error(f"WebSocket run_forever error: {e}")

            self._connected = False

            if not self.running:
                break

            self._reconnect_attempts += 1
            if self._reconnect_attempts >= self._reconnect_config["max_attempts"]:
                self.logger.error("Max reconnect attempts reached")
                self._trigger_error("Max reconnect attempts reached")
                break

            # A socket that has NEVER completed a handshake is not a reconnect, it
            # is a connection that Upstox refused — most often an over-limit one
            # (Upstox allows 2 concurrent market-data connections on Standard, 5 on
            # Plus, while the pool opens up to MAX_WEBSOCKET_CONNECTIONS). Left to
            # the plain reconnect path this is invisible: the adapter has already
            # reported "connected", every subscribe reports "queued", the batch
            # timer defers against a dead socket, and no tick ever arrives while
            # the loop retries for ~25 minutes. Raise it through the error callback
            # once, with the cause named.
            if (
                not self._ever_connected
                and self._reconnect_attempts == self.NEVER_CONNECTED_ALERT_AFTER
            ):
                self._trigger_error(
                    f"Upstox WebSocket has never completed a handshake after "
                    f"{self._reconnect_attempts} attempts - no market data will arrive on "
                    f"this connection. Most likely cause: this connection is over the "
                    f"Upstox per-user limit (2 concurrent market-data connections on "
                    f"Standard, 5 on Plus). MAX_WEBSOCKET_CONNECTIONS in .env decides how "
                    f"many the pool opens; its generic default of 3 is one too many for a "
                    f"Standard account - set MAX_WEBSOCKET_CONNECTIONS=2 there."
                )

            delay = self._calculate_backoff_delay(self._reconnect_attempts)
            # Distinguish stall-triggered from network-triggered reconnects
            # in the logs so operators can diagnose root cause from a single
            # log line rather than chasing across multiple files (issue #1357).
            if self._stall_triggered_reconnect:
                self.logger.warning(
                    f"Reconnecting due to DATA STALL "
                    f"(no ticks for >{self.DATA_TIMEOUT}s) — "
                    f"in {delay}s (attempt {self._reconnect_attempts})..."
                )
                self._stall_triggered_reconnect = False  # reset for next cycle
            else:
                self.logger.info(
                    f"Reconnecting in {delay}s (attempt {self._reconnect_attempts})..."
                )
            # Sleep in slices and re-test `running`. A single sleep(delay) means
            # a disconnect() landing inside this 2-30s window still wakes the
            # loop into a database read (_refresh_auth_token) and an outbound
            # HTTPS authorize, both on behalf of an adapter that is already torn
            # down, before the `while` finally notices. Same shape as
            # websocket_proxy/order_adapter.py's interruptible backoff. The
            # total delay is unchanged while the client is running, so the
            # backoff curve and the 50-attempt budget are untouched.
            slept = 0.0
            while slept < delay and self.running:
                time.sleep(min(self.BACKOFF_SLICE, delay - slept))
                slept += self.BACKOFF_SLICE

            if not self.running:
                break

            # Re-read a fresh bearer token from the database before re-fetching
            # the WebSocket URL. _get_websocket_url() signs the authorize request
            # with self.auth_token; without this refresh a reconnect after the
            # ~3 AM IST daily token rollover would sign with the dead
            # construction-time token and the feed would stay dead until a
            # process restart.
            self._refresh_auth_token()

            # Re-fetch WebSocket URL for reconnection
            ws_url = self._get_websocket_url()
            if ws_url:
                self.ws = websocket.WebSocketApp(
                    ws_url,
                    on_open=self._on_ws_open,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_ws_close,
                    on_ping=self._on_ws_ping,
                    on_pong=self._on_ws_pong,
                )

    def subscribe(self, instrument_keys: list[str], mode: str = "ltpc") -> bool:
        """Subscribe to market data for given instrument keys.

        Every subscribe — batched, replayed after a reconnect, or issued directly —
        funnels through here, so this is the one place the Upstox subscription caps
        can be enforced without a caller being able to bypass them. Keys within the
        cap are sent in chunks of at most `MODE_KEY_LIMITS[mode]`; keys beyond it
        are dropped with an error, because a cap on how many keys may be *subscribed*
        cannot be satisfied by splitting the same keys across more messages.
        """
        if not self._connected or not self.ws:
            self.logger.error("WebSocket not connected")
            return False

        keys, dropped = self._enforce_key_limits(instrument_keys, mode)
        if not keys:
            # Nothing left to send: either every key is already live in this mode
            # (a no-op, e.g. OpenAlgo modes 2 and 3 both mapping to `full` for the
            # same symbol) or the caps left no room at all, which is a failure.
            return not dropped

        limit = self.MODE_KEY_LIMITS.get(mode, self.DEFAULT_MODE_KEY_LIMIT)
        try:
            for start in range(0, len(keys), limit):
                chunk = keys[start : start + limit]
                message = self._create_subscription_message(chunk, mode, "sub")
                # Send as binary frame — original async code used:
                # await websocket.send(json.dumps(msg).encode("utf-8"))
                self.ws.send(
                    json.dumps(message).encode("utf-8"), opcode=websocket.ABNF.OPCODE_BINARY
                )
                self._subscriptions.update(chunk)
                self._keys_by_mode.setdefault(mode, set()).update(chunk)
            self.logger.debug(f"Subscribed to {len(keys)} instruments in {mode} mode")
            return True
        except Exception as e:
            self.logger.error(f"Subscribe error: {e}")
            return False

    def _enforce_key_limits(self, instrument_keys: list[str], mode: str) -> tuple[list[str], int]:
        """Trim a subscribe request down to what Upstox's caps actually permit.

        Returns (keys to send, number of keys dropped) — the keys in the order they
        were requested. Anything dropped is logged at ERROR naming the cap it hit;
        silently sending an over-cap request is worse, because Upstox rejects the
        whole message and the operator sees only a dead feed.
        """
        already = self._keys_by_mode.get(mode, set())
        # De-duplicate against what this connection already carries in this mode,
        # otherwise a repeat subscribe would count the same key twice against the
        # cap and start rejecting live symbols.
        seen: set = set()
        new_keys = []
        for key in instrument_keys:
            if key in already or key in seen:
                continue
            seen.add(key)
            new_keys.append(key)
        if not new_keys:
            # Nothing new — a successful no-op for the caller, nothing dropped.
            return [], 0

        dropped = 0

        # Individual cap: total keys allowed in this mode on this connection.
        limit = self.MODE_KEY_LIMITS.get(mode, self.DEFAULT_MODE_KEY_LIMIT)
        room = max(limit - len(already), 0)
        if len(new_keys) > room:
            dropped = len(new_keys) - room
            self.logger.error(
                f"Upstox {mode} subscription cap reached: {limit} keys per connection "
                f"({len(already)} already subscribed). Dropping {dropped} of "
                f"{len(new_keys)} requested key(s). Lower MAX_SYMBOLS_PER_WEBSOCKET so "
                f"the pool spreads symbols across connections before this cap is hit."
            )
            new_keys = new_keys[:room]
            if not new_keys:
                return [], dropped

        # Combined cap: only bites once a second mode is live on this connection.
        modes_in_use = set(self._keys_by_mode) | {mode}
        if len(modes_in_use) > 1:
            budget = min(
                self.MODE_COMBINED_LIMITS.get(m, self.DEFAULT_MODE_COMBINED_LIMIT)
                for m in modes_in_use
            )
            total = sum(len(v) for v in self._keys_by_mode.values())
            room = max(budget - total, 0)
            if len(new_keys) > room:
                dropped += len(new_keys) - room
                self.logger.error(
                    f"Upstox combined subscription cap reached: {budget} keys total across "
                    f"modes {sorted(modes_in_use)} ({total} already subscribed). Dropping "
                    f"{len(new_keys) - room} of {len(new_keys)} requested {mode} key(s)."
                )
                new_keys = new_keys[:room]

        return new_keys, dropped

    def unsubscribe(self, instrument_keys: list[str]) -> bool:
        """Unsubscribe from market data"""
        if not self._connected or not self.ws:
            return False

        try:
            message = self._create_subscription_message(instrument_keys, method="unsub")
            self.ws.send(json.dumps(message).encode("utf-8"), opcode=websocket.ABNF.OPCODE_BINARY)
            self._subscriptions.difference_update(instrument_keys)
            # Free the cap budget too, otherwise a long-running session that churns
            # symbols would count every key it has ever held and start refusing new
            # subscriptions well below the real limit.
            for keys in self._keys_by_mode.values():
                keys.difference_update(instrument_keys)
            self.logger.debug(f"Unsubscribed from {len(instrument_keys)} instruments")
            return True
        except Exception as e:
            self.logger.error(f"Unsubscribe error: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from WebSocket.

        Sets flags and closes the socket — does NOT join threads.
        Thread.join() under eventlet causes Timeout exceptions because
        eventlet converts joins to green waits. Daemon threads will
        terminate naturally when the flags are set.
        """
        self.running = False
        self._connected = False

        # Close WebSocket — this will cause run_forever() to return
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                self.logger.debug(f"Error closing WebSocket: {e}")

        # Don't join threads — daemon threads will stop on their own
        # join() causes eventlet.timeout.Timeout in gunicorn+eventlet
        self._health_check_thread = None

        # KEEP the _run_websocket handle. Nulling it destroyed the only evidence
        # that a loop existed, so nothing could ever detect or reap one it had
        # lost track of; connect()'s re-entrancy guard tests it. A finished
        # Thread object holds no descriptor and CPython clears its target, so
        # retaining it costs nothing, and the guard also tests `running` (False
        # from here on) so a legitimate reconnect after disconnect() is allowed.

        self._subscriptions.clear()
        self._keys_by_mode.clear()
        self._last_message_time = None
        self.logger.info("Disconnected from WebSocket")

    # WebSocket callbacks
    def _on_ws_open(self, ws):
        """Called when WebSocket connection is opened"""
        self.logger.debug("Upstox WebSocket connection opened")
        self._connected = True
        self._ever_connected = True
        self._reconnect_attempts = 0
        self._last_message_time = time.time()

        # Upstox drops every server-side subscription when the socket closes, so the
        # cap accounting must start from zero on each handshake — the adapter's
        # on_connect callback below replays the whole subscription set, and stale
        # counts here would make that replay look like a cap breach.
        self._keys_by_mode.clear()
        self._subscriptions.clear()

        # Start health check thread
        self._start_health_check()

        # Notify adapter
        if self.callbacks.get("on_connect"):
            self.callbacks["on_connect"]()

    def _on_ws_pong(self, ws, message):
        """Treat a WebSocket pong as proof the connection is alive.

        Upstox sends no application-level heartbeat, so during a quiet or
        closed market ``_last_message_time`` would otherwise freeze and the
        data-stall watchdog (``_health_check_loop``) would force a needless
        reconnect every ``DATA_TIMEOUT`` seconds — looping through the whole
        pre-open/overnight window and re-hitting the authorize endpoint on
        every cycle. The protocol ping/pong (``ping_interval=30``) keeps the
        socket alive regardless of market activity, so we feed the liveness
        clock from it — exactly as Zerodha's 1-byte heartbeat feeds its
        identical watchdog — making the watchdog fire only when the socket is
        genuinely dead (no data AND no pong).
        """
        self._last_message_time = time.time()

    def _on_ws_ping(self, ws, message):
        """A server-initiated ping also proves the socket is alive."""
        self._last_message_time = time.time()

    def _on_ws_message(self, ws, message):
        """Called for both binary (protobuf) and text (JSON) messages"""
        self._last_message_time = time.time()
        self.logger.debug(f"Received message: type={type(message).__name__}, size={len(message) if message else 0}")
        if isinstance(message, bytes):
            self._process_binary_message(message)
        else:
            self._process_text_message(message)

    def _on_ws_error(self, ws, error):
        """Called on WebSocket error"""
        self.logger.error(f"WebSocket error: {error}")
        self._connected = False
        self._trigger_error(str(error))

    def _on_ws_close(self, ws, close_status_code, close_msg):
        """Called when WebSocket is closed"""
        self.logger.info(f"WebSocket closed (code={close_status_code}, msg={close_msg})")
        self._connected = False
        if self.callbacks.get("on_close"):
            self.callbacks["on_close"]()

    # Health check
    def _start_health_check(self):
        """Start health check thread to detect silent stalls"""
        if self._health_check_thread and self._health_check_thread.is_alive():
            return

        self._health_check_thread = threading.Thread(
            target=self._health_check_loop, daemon=True
        )
        self._health_check_thread.start()

    def _health_check_loop(self):
        """Health check loop - detects silent stalls"""
        self.logger.debug("Health check started")
        while self.running and self._connected:
            time.sleep(self.HEALTH_CHECK_INTERVAL)

            if not self.running or not self._connected:
                break

            if self._last_message_time:
                elapsed = time.time() - self._last_message_time
                if elapsed > self.DATA_TIMEOUT:
                    self.logger.error(
                        f"Data stall detected - no data for {elapsed:.1f}s "
                        f"(threshold {self.DATA_TIMEOUT}s). Forcing reconnect..."
                    )
                    self._force_reconnect()
                    break
                else:
                    self.logger.debug(f"Health check OK - last data {elapsed:.1f}s ago")

        self.logger.debug("Health check loop exited")

    def _force_reconnect(self):
        """Force reconnection by closing the current WebSocket.

        Sets _stall_triggered_reconnect so _run_websocket can log the
        next reconnect attempt distinguishably from a network-induced one
        (issue #1357).
        """
        self.logger.info("Forcing WebSocket reconnection (stall-triggered)...")
        self._stall_triggered_reconnect = True
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                self.logger.warning(f"Error closing WebSocket during force reconnect: {e}")

    # Message processing
    def _process_binary_message(self, message: bytes):
        """Process binary (protobuf) message"""
        try:
            data = self._decode_protobuf_to_dict(message)
            self.logger.debug(f"Decoded protobuf message")
            if self.callbacks.get("on_message"):
                self.callbacks["on_message"](data)
        except Exception as e:
            self.logger.error(f"Failed to process binary message: {e}")

    def _process_text_message(self, message: str):
        """Process text (JSON) message"""
        try:
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            data = json.loads(message)
            self.logger.debug(f"Received JSON message")

            if data.get("status") == "failed" and data.get("error"):
                method = data.get("method", "unknown")
                self._trigger_error(f"{method} failed: {data['error']}")
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON message: {e}")

    def _decode_protobuf_to_dict(self, buffer: bytes) -> dict[str, Any]:
        """Decode protobuf FeedResponse to dictionary.

        The default `MessageToDict` options are load-bearing — do not add
        `always_print_fields_with_no_presence` / `including_default_value_fields`
        or `preserving_proto_field_name` here:

        - Keys stay camelCase (`marketOHLC`, `bidAskQuote`, `iiqTotal`), which is
          what every consumer in upstox_adapter reads.
        - Defaulted proto3 scalars are omitted, so the CAS / pre-open fields
          (iep, rp, ieq, iiqTotal, iiqM, casEligible) are simply absent outside an
          auction window instead of arriving as a misleading 0 / False.
        - `LTPC.iep` is a DoubleValue wrapper, so json_format emits it if and only
          if `HasField('iep')` is true and flattens it to the bare `.value`;
          printing no-presence fields would destroy that signal.
        - int64 fields render as strings (`"vtt"`, `"ltt"`, `"iiqTotal"`); the
          adapter int()s them, which preserves a negative iiqTotal.
        """
        feed_response = MarketDataFeedV3_pb2.FeedResponse()
        feed_response.ParseFromString(buffer)
        return MessageToDict(feed_response)

    # Helpers
    def _is_valid_auth_token(self) -> bool:
        return bool(
            self.auth_token and isinstance(self.auth_token, str) and len(self.auth_token) >= 10
        )

    def _refresh_auth_token(self):
        """Re-read a fresh bearer token from the database before a reconnect.

        Indian broker tokens roll over daily at ~3 AM IST. On reconnect we must
        re-read the current token from the database (bypassing the auth cache,
        which can hold a stale token after rollover) so the authorize request is
        signed with the live bearer. If no fresh token is available, keep the
        existing one rather than crashing.
        """
        if not self.user_id:
            return
        try:
            fresh_token = get_auth_token(self.user_id, bypass_cache=True)
            if not fresh_token:
                self.logger.warning(
                    "No fresh auth token found on reconnect - keeping existing token"
                )
                return
            self.auth_token = fresh_token
            self.logger.info("Refreshed Upstox auth token from database for reconnect")
        except Exception as e:
            self.logger.error(f"Error refreshing auth token on reconnect: {e}")

    def _get_websocket_url(self) -> str | None:
        """Get WebSocket URL from Upstox authorization endpoint"""
        try:
            headers = {"Accept": "application/json", "Authorization": f"Bearer {self.auth_token}"}
            response = requests.get(
                self.AUTH_ENDPOINT, headers=headers, timeout=self.HTTP_TIMEOUT
            )
            response.raise_for_status()
            auth_data = response.json()
            ws_url = auth_data.get("data", {}).get("authorized_redirect_uri")
            if ws_url:
                self.logger.debug(
                    f"Received WebSocket URL: {urlsplit(ws_url)._replace(query='').geturl()}"
                )
                return ws_url
            else:
                self.logger.error("No WebSocket URL in auth response")
                return None
        except requests.Timeout:
            self.logger.error(f"Timeout getting WebSocket authorization")
            return None
        except requests.HTTPError as e:
            # raise_for_status() throws the response BODY away, and the body is
            # where Upstox puts the actual reason (errors[].errorCode / message) —
            # including a refusal because the account is already at its concurrent
            # connection limit. Without this, an over-limit 3rd connection on a
            # Standard account reads as a generic network failure.
            status = e.response.status_code if e.response is not None else "?"
            body = (e.response.text or "")[:500] if e.response is not None else ""
            self.logger.error(f"WebSocket authorize rejected: HTTP {status} {body}")
            if status == 429 or "limit" in body.lower():
                self.logger.error(
                    "Upstox refused the market-data feed authorization. Upstox permits 2 "
                    "concurrent market-data connections on Standard and 5 on Plus; "
                    "MAX_WEBSOCKET_CONNECTIONS in .env decides how many the pool opens "
                    "(generic default 3, which is one too many for Standard). Set "
                    "MAX_WEBSOCKET_CONNECTIONS=2 on a Standard account."
                )
            return None
        except Exception as e:
            self.logger.error(f"Failed to get WebSocket authorization: {e}")
            return None

    def _calculate_backoff_delay(self, attempt: int) -> int:
        delay = self._reconnect_config["base_delay"] * (2 ** (attempt - 1))
        return min(delay, self._reconnect_config["max_delay"])

    def _create_subscription_message(
        self, instrument_keys: list[str], mode: str = None, method: str = "sub"
    ) -> dict[str, Any]:
        message = {
            "guid": str(uuid.uuid4()).replace("-", "")[:20],
            "method": method,
            "data": {"instrumentKeys": instrument_keys},
        }
        if mode and method == "sub":
            message["data"]["mode"] = mode
        return message

    def _trigger_error(self, error_message: str):
        """Trigger error callback"""
        self.logger.error(error_message)
        if self.callbacks.get("on_error"):
            self.callbacks["on_error"](error_message)
