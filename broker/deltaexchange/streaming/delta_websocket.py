"""
delta_websocket.py
Low-level WebSocket client for Delta Exchange real-time feed.

Delta runs two endpoints and this client is instantiated once per endpoint:

  wss://public-socket.india.delta.exchange   market data, no auth
  wss://socket.india.delta.exchange          account channels, auth required

Public market-data channels used to live on the private endpoint under the
names v2/ticker / l1_orderbook / l2_orderbook.  Delta migrated them to the
public endpoint (ticker / ob_l1 / ob_l2) and scheduled the old names for
removal on 31 July 2026; the legacy l2_orderbook also silently caps a
connection at 20 symbols, which is fewer than one option chain needs.  Both
reasons make the public endpoint the only viable target.

Protocol : JSON over secure WebSocket
Auth msg : { "type": "key-auth", "payload": { "api-key": "...", "signature": "...", "timestamp": "..." } }
Signature: HMAC-SHA256(api_secret, "GET" + timestamp + "/live")

Channel names:
  ticker      -> price/OI/quote snapshot, published every 5s (public endpoint)
  ob_l2       -> top-15 order book, published every 500ms (public endpoint)
  orders      -> order updates (private endpoint, requires auth)
  positions   -> position updates (private endpoint, requires auth)
  margins     -> wallet / margin updates (private endpoint, requires auth)

Subscribe / unsubscribe frame (same shape on both endpoints):
  { "type": "subscribe", "payload": { "channels": [{ "name": "ticker", "symbols": ["BTCUSD"] }] } }

Incoming message examples:
  Ticker:  { "type": "ticker", "sy": "BTCUSD", "sp": "63860.7", "ts": 1786521801671015,
             "d": [{ "s": "BTCUSD", "m": "63838.06", "ohlc": [open, high, low, close],
                     "oi": [oi_contracts, oi_change_usd_6h],
                     "q": [best_ask, ask_size, best_bid, bid_size, impact_mid],
                     "g": [delta, gamma, rho, theta, vega],
                     "qiv": [ask_iv, bid_iv, mark_iv] }] }

  Order book: { "type": "ob_l2", "sy": "BTCUSD", "ts": 1786521801671015,
                "a": [["63834", "718"], ...],    // asks, price + size, best first
                "b": [["63833", "4388"], ...] }  // bids

References: https://docs.delta.exchange/#public-channels
"""

import hashlib
import hmac
import json
import os
import ssl
import threading
import time

import websocket

from utils.logging import get_logger

logger = get_logger("delta_websocket")


class DeltaWebSocket:
    """
    Thin WebSocket client for the Delta Exchange streaming API.

    Usage
    -----
    md = DeltaWebSocket(url=DeltaWebSocket.PUBLIC_WS_URL, authenticate=False, on_message=cb)
    md.connect()
    md.subscribe_ticker(["BTCUSD", "ETHUSD"])
    md.subscribe_orderbook(["BTCUSD"])
    ...
    md.close_connection()
    """

    # ── constants ─────────────────────────────────────────────────────────────
    PUBLIC_WS_URL      = "wss://public-socket.india.delta.exchange"
    PRIVATE_WS_URL     = "wss://socket.india.delta.exchange"
    HEARTBEAT_INTERVAL = 30      # seconds between pings
    MSG_TYPE_AUTH      = "key-auth"
    MSG_TYPE_SUB       = "subscribe"
    MSG_TYPE_UNSUB     = "unsubscribe"
    # Public channels — new public endpoint only
    CHANNEL_TICKER     = "ticker"
    CHANNEL_OB_L2      = "ob_l2"
    # Symbols Delta accepts in a single subscribe frame, per channel.
    # None = no limit found (ticker took 150 in one frame, verified live
    # 2026-08-12); ob_l2 rejects anything above one symbol outright.
    MAX_SYMBOLS_PER_FRAME = {
        CHANNEL_TICKER: None,
        CHANNEL_OB_L2:  1,
    }
    # Private authenticated channels (require auth message to be sent first)
    CHANNEL_ORDERS    = "orders"      # real-time order fill / cancel / modify events
    CHANNEL_POSITIONS = "positions"   # real-time position updates
    CHANNEL_MARGINS   = "margins"     # real-time margin / wallet changes

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        on_message=None,
        on_error=None,
        on_open=None,
        on_close=None,
        max_retry_attempt: int = 5,
        retry_delay: int = 5,
        retry_multiplier: int = 2,
        url: str | None = None,
        authenticate: bool = True,
        name: str = "private",
    ):
        self.api_key    = api_key
        self.api_secret = api_secret
        # One client per endpoint; `name` only tags log lines so the two are
        # distinguishable in the log stream.
        self.url          = url or self.PRIVATE_WS_URL
        self.authenticate = authenticate
        self.name         = name

        # User-supplied callbacks
        self.on_message = on_message  or (lambda ws, msg: None)
        self.on_error   = on_error    or (lambda ws, err: None)
        self.on_open    = on_open     or (lambda ws: None)
        self.on_close   = on_close    or (lambda ws: None)

        self.max_retry_attempt = max_retry_attempt
        self.retry_delay       = retry_delay
        self.retry_multiplier  = retry_multiplier

        self.wsapp:  websocket.WebSocketApp | None = None
        self._lock   = threading.Lock()
        self._connected = False
        self._stop_flag = False
        # Set by _ws_on_open; the retry loop reads it to tell "this connection
        # was healthy and later dropped" apart from "we never got through".
        self._connect_succeeded = False
        # Persistent subscription registry, tracked per symbol rather than per
        # sent frame.  Serves two purposes:
        #   1. Pre-connect buffer: symbols accumulate here and are subscribed in
        #      _ws_on_open when the socket first connects.
        #   2. Reconnect replay: the registry is NEVER cleared, so every reconnect
        #      re-subscribes everything still active, restoring all streams
        #      without the caller needing to re-subscribe.
        # Tracking symbols (not frames) is what lets one symbol be dropped out of
        # a batch: a frame-keyed registry would keep replaying the whole batch.
        self._active_symbols: dict[str, set[str]] = {}   # channel → symbols
        self._active_private: dict[str, str] = {}        # channel → raw message

    @property
    def is_connected(self) -> bool:
        """True while this endpoint's socket is up and able to carry frames."""
        return self._connected

    # ── auth helper ───────────────────────────────────────────────────────────

    def _build_auth_msg(self) -> str:
        """Build HMAC-SHA256 authenticated auth message."""
        timestamp = str(int(time.time()))
        message   = f"GET{timestamp}/live"
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        payload = {
            "type": self.MSG_TYPE_AUTH,
            "payload": {
                "api-key":   self.api_key,
                "signature": signature,
                "timestamp": timestamp,
            },
        }
        return json.dumps(payload)

    # ── subscribe / unsubscribe helpers ──────────────────────────────────────

    def _build_sub_msg(self, channel: str, symbols: list[str], unsub=False) -> str:
        msg = {
            "type": self.MSG_TYPE_UNSUB if unsub else self.MSG_TYPE_SUB,
            "payload": {
                "channels": [{"name": channel, "symbols": symbols}]
            },
        }
        return json.dumps(msg)

    def _frames(self, channel: str, symbols: list[str], unsub: bool = False) -> list[str]:
        """Split a symbol list into as few frames as the channel allows.

        `ticker` takes the whole list in one frame — 150 symbols verified live.
        `ob_l2` rejects any frame carrying more than one symbol
        ("subscription forbidden on this channel with more than 1 symbol"), so
        it always costs one frame per symbol.
        """
        size = self.MAX_SYMBOLS_PER_FRAME.get(channel)
        if not size or size >= len(symbols):
            return [self._build_sub_msg(channel, symbols, unsub=unsub)] if symbols else []
        return [
            self._build_sub_msg(channel, symbols[i:i + size], unsub=unsub)
            for i in range(0, len(symbols), size)
        ]

    def _send_all_locked(self, msgs: list[str]) -> None:
        """Send frames, or drop them when the socket is down. Caller must hold _lock.

        Why the lock spans both the registry write AND the sends:
          It prevents the TOCTOU race where _ws_on_close flips _connected=False
          between our check and the send, causing frames to be dropped from the
          wire while the registry still claims they are active. It also keeps
          wire order matching registry order — otherwise an overlapping
          subscribe and unsubscribe for the same symbol could update the
          registry in one order and reach Delta in the other, leaving the
          exchange streaming a symbol the registry says was dropped.
        """
        if not self._connected or not self.wsapp:
            logger.debug("DeltaWS[%s] buffered %s frame(s) (not connected)",
                         self.name, len(msgs))
            return
        for msg in msgs:
            try:
                self.wsapp.send(msg)
            except Exception as exc:
                logger.error("DeltaWS[%s] _send error: %s", self.name, exc)
                # Send failed mid-flight; the symbol is already in
                # _active_symbols and will be replayed on reconnect.

    # ── public API ────────────────────────────────────────────────────────────

    def _subscribe(self, channel: str, symbols: list[str]) -> None:
        with self._lock:
            self._active_symbols.setdefault(channel, set()).update(symbols)
            self._send_all_locked(self._frames(channel, symbols))

    def _unsubscribe(self, channel: str, symbols: list[str]) -> None:
        with self._lock:
            active = self._active_symbols.get(channel)
            if active:
                active.difference_update(symbols)
            self._send_all_locked(self._frames(channel, symbols, unsub=True))

    def subscribe_ticker(self, symbols: list[str]) -> None:
        """Subscribe to the ticker channel for the given symbols."""
        self._subscribe(self.CHANNEL_TICKER, symbols)

    def subscribe_orderbook(self, symbols: list[str]) -> None:
        """Subscribe to the ob_l2 (top-15 order book) channel for the given symbols."""
        self._subscribe(self.CHANNEL_OB_L2, symbols)

    def unsubscribe_ticker(self, symbols: list[str]) -> None:
        self._unsubscribe(self.CHANNEL_TICKER, symbols)

    def unsubscribe_orderbook(self, symbols: list[str]) -> None:
        self._unsubscribe(self.CHANNEL_OB_L2, symbols)

    def forget_subscriptions(self) -> None:
        """Drop the replay registry.

        The registry deliberately survives a dropped connection so the retry
        loop can restore every stream on reconnect.  An explicit teardown is
        different: the subscriptions are gone, so anything left here would be
        resubscribed by a later connect() with no client behind it.
        """
        with self._lock:
            self._active_symbols.clear()
            self._active_private.clear()

    # ── private (authenticated) channel subscriptions ─────────────────────────

    def _build_private_sub_msg(self, channel: str, unsub: bool = False) -> str:
        """Build a subscribe/unsubscribe message for account-level channels.

        'orders' and 'positions' require "symbols": ["all"] or Delta Exchange
        sends no data (per API docs).  'margins' works without a symbols list.
        """
        channel_entry: dict = {"name": channel}
        if channel in (self.CHANNEL_ORDERS, self.CHANNEL_POSITIONS):
            channel_entry["symbols"] = ["all"]
        return json.dumps({
            "type": self.MSG_TYPE_UNSUB if unsub else self.MSG_TYPE_SUB,
            "payload": {"channels": [channel_entry]},
        })

    def _subscribe_private(self, channel: str) -> None:
        """Register and send an account-channel subscription."""
        msg = self._build_private_sub_msg(channel)
        with self._lock:
            self._active_private[channel] = msg
            self._send_all_locked([msg])

    def subscribe_orders_channel(self) -> None:
        """Subscribe to the authenticated 'orders' channel.

        Delivers real-time order fill, cancel, and modify events for the
        authenticated user.  The WebSocket session must be authenticated first
        (the auth message is sent automatically in _ws_on_open).
        """
        self._subscribe_private(self.CHANNEL_ORDERS)

    def subscribe_positions_channel(self) -> None:
        """Subscribe to the authenticated 'positions' channel.

        Delivers real-time position updates (size, entry price, PnL) whenever
        a position changes for the authenticated user.
        """
        self._subscribe_private(self.CHANNEL_POSITIONS)

    def subscribe_margins_channel(self) -> None:
        """Subscribe to the authenticated 'margins' channel.

        Delivers real-time wallet and margin balance updates whenever a fill,
        funding payment, or realised-PnL event changes the account balance.
        """
        self._subscribe_private(self.CHANNEL_MARGINS)

    def connect(self) -> None:
        """Start the WebSocket connection (blocking — run in a thread)."""
        self._stop_flag = False
        retry_attempts = 0
        delay = self.retry_delay

        while not self._stop_flag and retry_attempts <= self.max_retry_attempt:
            try:
                logger.info("DeltaWS[%s] connecting to %s (attempt %s)",
                            self.name, self.url, retry_attempts + 1)
                self.wsapp = websocket.WebSocketApp(
                    self.url,
                    on_open    = self._ws_on_open,
                    on_message = self._ws_on_message,
                    on_error   = self._ws_on_error,
                    on_close   = self._ws_on_close,
                )
                self.wsapp.run_forever(
                    sslopt={"cert_reqs": ssl.CERT_REQUIRED},
                    ping_interval=self.HEARTBEAT_INTERVAL,
                    ping_timeout=10,
                )
                # run_forever returns when connection closes
                if self._stop_flag:
                    break
                # A connection that came up healthy and only later dropped
                # restores the full retry budget.  Without this the counter is
                # cumulative over the process lifetime, so a long-lived feed
                # that reconnects once a day silently exhausts the budget after
                # max_retry_attempt drops and never comes back.
                if self._connect_succeeded:
                    self._connect_succeeded = False
                    retry_attempts = 0
                    delay = self.retry_delay
                retry_attempts += 1
                logger.warning("DeltaWS[%s] disconnected; retry in %ss", self.name, delay)
                time.sleep(delay)
                delay = min(delay * self.retry_multiplier, 60)

            except Exception as exc:
                logger.error("DeltaWS[%s] connect error: %s", self.name, exc)
                retry_attempts += 1
                time.sleep(delay)
                delay = min(delay * self.retry_multiplier, 60)

        if retry_attempts > self.max_retry_attempt:
            logger.error("DeltaWS[%s] max reconnect attempts reached; giving up", self.name)

    def close_connection(self) -> None:
        """Cleanly stop the WebSocket."""
        self._stop_flag = True
        if self.wsapp:
            try:
                self.wsapp.close()
            except Exception:
                pass

    # ── internal WS callbacks ─────────────────────────────────────────────────

    def _ws_on_open(self, wsapp) -> None:
        logger.info("DeltaWS[%s] connected", self.name)

        # Authenticate (required for order/position channels).  The public
        # market-data endpoint rejects auth frames, so only the private
        # connection sends one.
        if self.authenticate:
            try:
                wsapp.send(self._build_auth_msg())
            except Exception as exc:
                logger.error("DeltaWS[%s] auth send error: %s", self.name, exc)

        # Set _connected and replay all active subscriptions atomically.
        # The registry serves as both the pre-connect buffer (symbols registered
        # before the socket was up) AND the reconnect replay list (symbols
        # registered during a previous session that must be resubscribed after a
        # disconnect).  It is never cleared, so every reconnect restores all
        # streams automatically.  Replay is re-framed from scratch, so a whole
        # ticker book goes back up in one frame however it was subscribed.
        with self._lock:
            self._connected = True
            self._connect_succeeded = True
            to_replay = list(self._active_private.values())
            for channel, symbols in self._active_symbols.items():
                if symbols:
                    to_replay.extend(self._frames(channel, sorted(symbols)))

        for msg in to_replay:
            try:
                wsapp.send(msg)
            except Exception as exc:
                logger.error("DeltaWS[%s] subscription replay send error: %s", self.name, exc)

        self.on_open(wsapp)

    def _ws_on_message(self, wsapp, raw) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            logger.debug("DeltaWS[%s] non-JSON message: %s", self.name, raw[:120])
            return

        msg_type = msg.get("type", "")

        if msg_type in ("key-auth", "subscriptions"):
            logger.debug("DeltaWS[%s] ack: %s", self.name, msg_type)
            return

        if msg_type in ("error",):
            logger.error("DeltaWS[%s] server error: %s", self.name, msg)
            return

        logger.debug("DeltaWS[%s] dispatching: type=%s symbol=%s",
                     self.name, msg_type, msg.get("sy") or msg.get("symbol", ""))
        self.on_message(wsapp, msg)

    def _ws_on_error(self, wsapp, error) -> None:
        logger.error("DeltaWS[%s] error: %s", self.name, error)
        self.on_error(wsapp, error)

    def _ws_on_close(self, wsapp, *args) -> None:
        logger.info("DeltaWS[%s] closed", self.name)
        # Acquire the lock before clearing _connected so that any subscribe
        # call currently deciding whether to send vs. queue (also under the
        # same lock via _queue_or_send) completes atomically before we flip
        # the flag.  Without this, _ws_on_close could clear _connected between
        # the lock release in the old send_now pattern and the actual send,
        # silently dropping the message from both the wire and the queue.
        with self._lock:
            self._connected = False
        self.on_close(wsapp)
