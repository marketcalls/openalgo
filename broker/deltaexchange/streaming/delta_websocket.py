"""
delta_websocket.py
Low-level WebSocket client for Delta Exchange real-time feed.

Endpoint : wss://socket.india.delta.exchange
Protocol : JSON over secure WebSocket
Auth msg : { "type": "auth", "payload": { "api-key": "...", "signature": "...", "timestamp": "..." } }
Signature: HMAC-SHA256(api_secret, "GET" + timestamp + "/live")

Public channels  (no auth needed):
  subscribe:  { "type": "subscribe", "payload": { "channels": [{ "name": "v2/ticker", "symbols": ["BTCUSD"] }] } }
  unsubscribe: { "type": "unsubscribe", ... }

Channel names:
  v2/ticker          -> ticker updates (mark_price, open, high, low, volume, oi, best_bid, best_ask)
  l2_orderbook       -> level-2 order book (buy/sell lists with price+size)
  orders             -> order updates (requires auth)
  positions          -> position updates (requires auth)

Incoming message examples:
  Ticker:  { "type": "v2/ticker", "symbol": "BTCUSD",
             "mark_price": "67000", "open": 66000, "high": 68000,
             "low": 65000, "close": 66500, "volume": 1234,
             "oi": "5000", "quotes": { "best_bid": "66990", "best_ask": "67010" } }

  L2 book: { "type": "l2_orderbook", "symbol": "BTCUSD",
             "buy":  [{"price": "66990", "size": 1000, "depth": 1}, ...],
             "sell": [{"price": "67010", "size":  800, "depth": 1}, ...] }

References: https://docs.delta.exchange/#websocket-channels
"""

import hashlib
import hmac
import json
import logging
import os
import ssl
import threading
import time

import websocket

logger = logging.getLogger("delta_websocket")


class DeltaWebSocket:
    """
    Thin WebSocket client for the Delta Exchange streaming API.

    Usage
    -----
    ws = DeltaWebSocket(api_key="...", api_secret="...", on_message=cb)
    ws.connect()
    ws.subscribe_ticker(["BTCUSD", "ETHUSD"])
    ws.subscribe_l2_orderbook(["BTCUSD"])
    ...
    ws.close()
    """

    # ── constants ─────────────────────────────────────────────────────────────
    WS_URL            = "wss://socket.india.delta.exchange"
    HEARTBEAT_INTERVAL = 30      # seconds between pings
    MSG_TYPE_AUTH      = "auth"
    MSG_TYPE_SUB       = "subscribe"
    MSG_TYPE_UNSUB     = "unsubscribe"
    CHANNEL_TICKER     = "v2/ticker"
    CHANNEL_L2_BOOK    = "l2_orderbook"
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
    ):
        self.api_key    = api_key
        self.api_secret = api_secret

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
        self._pending_subscriptions: list[dict] = []   # buffered before connect

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

    def _send(self, text: str) -> None:
        if self.wsapp and self._connected:
            try:
                self.wsapp.send(text)
            except Exception as exc:
                logger.error("DeltaWS _send error: %s", exc)

    # ── public API ────────────────────────────────────────────────────────────

    def subscribe_ticker(self, symbols: list[str]) -> None:
        """Subscribe to v2/ticker channel for the given symbols."""
        msg = self._build_sub_msg(self.CHANNEL_TICKER, symbols)
        if self._connected:
            self._send(msg)
        else:
            with self._lock:
                self._pending_subscriptions.append(msg)

    def subscribe_l2_orderbook(self, symbols: list[str]) -> None:
        """Subscribe to l2_orderbook channel for the given symbols."""
        msg = self._build_sub_msg(self.CHANNEL_L2_BOOK, symbols)
        if self._connected:
            self._send(msg)
        else:
            with self._lock:
                self._pending_subscriptions.append(msg)

    def unsubscribe_ticker(self, symbols: list[str]) -> None:
        self._send(self._build_sub_msg(self.CHANNEL_TICKER, symbols, unsub=True))

    def unsubscribe_l2_orderbook(self, symbols: list[str]) -> None:
        self._send(self._build_sub_msg(self.CHANNEL_L2_BOOK, symbols, unsub=True))

    # ── private (authenticated) channel subscriptions ─────────────────────────

    def _build_private_sub_msg(self, channel: str, unsub: bool = False) -> str:
        """Build a subscribe/unsubscribe message for account-level channels.

        Account channels such as 'orders', 'positions', and 'margins' do not
        filter by symbol — they deliver all events for the authenticated user.
        Delta Exchange expects the channels list entry to have no 'symbols' key.
        """
        return json.dumps({
            "type": self.MSG_TYPE_UNSUB if unsub else self.MSG_TYPE_SUB,
            "payload": {"channels": [{"name": channel}]},
        })

    def subscribe_orders_channel(self) -> None:
        """Subscribe to the authenticated 'orders' channel.

        Delivers real-time order fill, cancel, and modify events for the
        authenticated user.  The WebSocket session must be authenticated first
        (the auth message is sent automatically in _ws_on_open).
        """
        msg = self._build_private_sub_msg(self.CHANNEL_ORDERS)
        if self._connected:
            self._send(msg)
        else:
            with self._lock:
                self._pending_subscriptions.append(msg)

    def subscribe_positions_channel(self) -> None:
        """Subscribe to the authenticated 'positions' channel.

        Delivers real-time position updates (size, entry price, PnL) whenever
        a position changes for the authenticated user.
        """
        msg = self._build_private_sub_msg(self.CHANNEL_POSITIONS)
        if self._connected:
            self._send(msg)
        else:
            with self._lock:
                self._pending_subscriptions.append(msg)

    def subscribe_margins_channel(self) -> None:
        """Subscribe to the authenticated 'margins' channel.

        Delivers real-time wallet and margin balance updates whenever a fill,
        funding payment, or realised-PnL event changes the account balance.
        """
        msg = self._build_private_sub_msg(self.CHANNEL_MARGINS)
        if self._connected:
            self._send(msg)
        else:
            with self._lock:
                self._pending_subscriptions.append(msg)

    def connect(self) -> None:
        """Start the WebSocket connection (blocking — run in a thread)."""
        self._stop_flag = False
        retry_attempts = 0
        delay = self.retry_delay

        while not self._stop_flag and retry_attempts <= self.max_retry_attempt:
            try:
                logger.info("DeltaWS connecting to %s (attempt %s)", self.WS_URL, retry_attempts + 1)
                self.wsapp = websocket.WebSocketApp(
                    self.WS_URL,
                    on_open    = self._ws_on_open,
                    on_message = self._ws_on_message,
                    on_error   = self._ws_on_error,
                    on_close   = self._ws_on_close,
                )
                self.wsapp.run_forever(
                    sslopt={"cert_reqs": ssl.CERT_NONE},
                    ping_interval=self.HEARTBEAT_INTERVAL,
                    ping_timeout=10,
                )
                # run_forever returns when connection closes
                if self._stop_flag:
                    break
                retry_attempts += 1
                logger.warning("DeltaWS disconnected; retry in %ss", delay)
                time.sleep(delay)
                delay = min(delay * self.retry_multiplier, 60)

            except Exception as exc:
                logger.error("DeltaWS connect error: %s", exc)
                retry_attempts += 1
                time.sleep(delay)
                delay = min(delay * self.retry_multiplier, 60)

        if retry_attempts > self.max_retry_attempt:
            logger.error("DeltaWS max reconnect attempts reached; giving up")

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
        logger.info("DeltaWS connected")
        self._connected = True

        # Authenticate (required for order/position channels)
        try:
            wsapp.send(self._build_auth_msg())
        except Exception as exc:
            logger.error("DeltaWS auth send error: %s", exc)

        # Flush buffered subscriptions
        with self._lock:
            pending = list(self._pending_subscriptions)
            self._pending_subscriptions.clear()

        for msg in pending:
            try:
                wsapp.send(msg)
            except Exception as exc:
                logger.error("DeltaWS pending sub send error: %s", exc)

        self.on_open(wsapp)

    def _ws_on_message(self, wsapp, raw) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            logger.debug("DeltaWS non-JSON message: %s", raw[:120])
            return

        msg_type = msg.get("type", "")

        if msg_type in ("auth_ack", "subscribe_ack", "unsubscribe_ack"):
            logger.info("DeltaWS ack: %s", msg_type)
            return

        if msg_type in ("error",):
            logger.error("DeltaWS server error: %s", msg)
            return

        self.on_message(wsapp, msg)

    def _ws_on_error(self, wsapp, error) -> None:
        logger.error("DeltaWS error: %s", error)
        self.on_error(wsapp, error)

    def _ws_on_close(self, wsapp, *args) -> None:
        logger.info("DeltaWS closed")
        self._connected = False
        self.on_close(wsapp)
