"""
delta_adapter.py
OpenAlgo WebSocket adapter for Delta Exchange.

Two upstream connections, because Delta splits its feed across two endpoints:

  public  (wss://public-socket.india.delta.exchange, no auth)
      ticker — mark price + 24h OHLC + OI + best bid/ask with sizes
      ob_l2  — top-15 order book (depth mode)

  private (wss://socket.india.delta.exchange, HMAC-SHA256 auth on every
           (re)connect, signature = HMAC-SHA256(api_secret, "GET" + ts + "/live"))
      orders / positions / margins — account-level events

Every symbol subscription carries a ticker subscription, including depth mode:
ob_l2 has prices and sizes but no traded price, OI or OHLC, so a depth-only
subscriber would publish those as zero.
"""

import json
import logging
import threading
import time
from typing import Any

from broker.deltaexchange.streaming.delta_websocket import DeltaWebSocket
from broker.deltaexchange.streaming.delta_mapping import (
    DeltaCapabilityRegistry,
    DeltaExchangeMapper,
    DeltaModeMapper,
)
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper


def _f(value, default: float = 0.0) -> float:
    """Parse a Delta numeric field, which may arrive as a string or null."""
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _i(value, default: int = 0) -> int:
    """Parse a Delta size/quantity field, which may arrive as a string or null."""
    try:
        return int(float(value)) if value is not None else default
    except (TypeError, ValueError):
        return default


class DeltaWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Delta Exchange–specific implementation of the BaseBrokerWebSocketAdapter."""

    def __init__(self):
        super().__init__()
        self.logger       = logging.getLogger("delta_websocket_adapter")
        self.ws_client    = None   # private endpoint: orders / positions / margins
        self.public_ws    = None   # public endpoint: ticker / ob_l2
        self.user_id      = None
        self.broker_name  = "deltaexchange"
        self.running      = False
        self._lock        = threading.Lock()
        self.last_values: dict[str, dict] = {}

        # Batch subscription management — coalesce the burst of per-symbol
        # subscribe calls the proxy makes (one per symbol) into a single flush,
        # so an option chain costs one ticker frame instead of one per strike
        # (zerodha pattern).  ob_l2 still costs a frame per symbol: Delta
        # rejects any order-book frame carrying more than one.
        self.subscription_queue: list[tuple[str, str]] = []    # (channel, br_symbol)
        self.unsubscription_queue: list[tuple[str, str]] = []
        self.batch_timer: threading.Timer | None = None
        self.batch_delay  = 0.5   # seconds to collect subscriptions before flushing

    # ── BaseBrokerWebSocketAdapter interface ──────────────────────────────────

    def initialize(
        self,
        broker_name: str,
        user_id: str,
        auth_data: dict | None = None,
    ) -> None:
        """
        Fetch credentials and build the DeltaWebSocket client.

        auth_data may carry:
            api_key    / access_token — the Delta Exchange API key
            api_secret               — the Delta Exchange API secret
        """
        self.user_id     = user_id
        self.broker_name = broker_name

        if auth_data:
            api_key    = auth_data.get("api_key") or auth_data.get("access_token", "")
            api_secret = auth_data.get("api_secret", "")
        else:
            # OpenAlgo stores the api_key as the auth token
            api_key    = get_auth_token(user_id, bypass_cache=True) or ""
            api_secret = os.getenv("BROKER_API_SECRET", "")

        if not api_key:
            raise ValueError(f"No API key found for user {user_id}")

        self.ws_client = DeltaWebSocket(
            api_key    = api_key,
            api_secret = api_secret,
            url        = DeltaWebSocket.PRIVATE_WS_URL,
            authenticate = True,
            name       = "private",
            on_open    = self._on_private_open,
            on_message = self._on_data,
            on_error   = self._on_error,
            on_close   = self._on_close,
            max_retry_attempt = 5,
            retry_delay       = 5,
            retry_multiplier  = 2,
        )

        # Market data moved to Delta's public endpoint, which takes no auth
        # frame — sending one there is rejected, so it gets its own client.
        self.public_ws = DeltaWebSocket(
            api_key    = api_key,
            api_secret = api_secret,
            url        = DeltaWebSocket.PUBLIC_WS_URL,
            authenticate = False,
            name       = "public",
            on_open    = self._on_public_open,
            on_message = self._on_data,
            on_error   = self._on_error,
            on_close   = self._on_close,
            max_retry_attempt = 5,
            retry_delay       = 5,
            retry_multiplier  = 2,
        )

        self.running = True
        self.logger.info("DeltaWebSocketAdapter initialised for user %s", user_id)

    def connect(self) -> None:
        """Spin up both WebSocket connections in daemon threads."""
        if not self.ws_client or not self.public_ws:
            self.logger.error("Call initialize() before connect()")
            return
        threading.Thread(target=self.public_ws.connect, daemon=True).start()
        threading.Thread(target=self.ws_client.connect, daemon=True).start()

    def disconnect(self) -> None:
        """Close both connections and clean up ZeroMQ resources."""
        self.running = False

        # Cancel the batch timer and drop queued work — the socket is going
        # away, so nothing queued can still reach the wire.
        with self._lock:
            if self.batch_timer:
                self.batch_timer.cancel()
                self.batch_timer = None
            self.subscription_queue.clear()
            self.unsubscription_queue.clear()

        for client in (self.public_ws, self.ws_client):
            if client:
                # Drop the replay registry too. It exists to restore streams
                # after a dropped connection, but this is an explicit teardown:
                # a queued unsubscribe was just discarded above, so replaying
                # the registry on a later connect() would resubscribe symbols
                # that no longer have a subscriber.
                client.forget_subscriptions()
                client.close_connection()
        self.cleanup_zmq()

    def subscribe(
        self,
        symbol: str,
        exchange: str,
        mode: int = 2,
        depth_level: int = 1,
    ) -> dict[str, Any]:
        """
        Subscribe to market data for a single symbol.

        Modes:
          1 — LTP         → ticker
          2 — Quote       → ticker  (includes bid/ask with sizes and OI)
          3 — Depth       → ob_l2 + ticker
        """
        if not DeltaCapabilityRegistry.supports_mode(mode):
            return self._create_error_response(
                "INVALID_MODE",
                f"Mode {mode} not supported by Delta Exchange. Supported: {DeltaCapabilityRegistry.subscription_modes}",
            )

        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND", f"{symbol} not found for exchange {exchange}"
            )

        br_symbol = get_br_symbol(symbol, exchange) or symbol
        channels  = DeltaModeMapper.get_channels(mode)
        corr_id   = f"{symbol}_{exchange}_{mode}"

        with self._lock:
            self.subscriptions[corr_id] = {
                "symbol":    symbol,
                "exchange":  exchange,
                "br_symbol": br_symbol,
                "mode":      mode,
                "channels":  channels,
                "depth_level": depth_level,
            }

        # Queued, not sent: the proxy subscribes one symbol at a time, so a
        # 41-strike option chain would otherwise be 41 ticker frames.  The flush
        # coalesces them.  DeltaWebSocket keeps its own symbol registry, so a
        # subscription queued before the socket is up is still replayed on
        # connect.
        if self.public_ws:
            try:
                with self._lock:
                    for channel in channels:
                        self._queue_op(self.subscription_queue,
                                       self.unsubscription_queue, channel, br_symbol)
                self.logger.info("Subscribed: %s.%s mode=%s channels=%s",
                                 symbol, exchange, mode, ",".join(channels))
            except Exception as exc:
                self.logger.error("subscribe error %s.%s: %s", symbol, exchange, exc)
                return self._create_error_response("SUBSCRIPTION_ERROR", str(exc))

        return self._create_success_response(
            f"Subscription requested for {symbol}.{exchange}",
            symbol=symbol, exchange=exchange, mode=mode, channel=channels[0],
        )

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict[str, Any]:
        """Unsubscribe from market data for a symbol."""
        channels = DeltaModeMapper.get_channels(mode)
        corr_id  = f"{symbol}_{exchange}_{mode}"

        stale_channels: list[str] = []
        with self._lock:
            # Read the stored br_symbol that was resolved at subscribe() time
            # before removing the entry.  This guarantees the upstream unsubscribe
            # uses exactly the same symbol string that was passed to the WebSocket
            # at subscription time (brexchange_symbol → token → symbol fallback
            # chain), avoiding a mismatch when brexchange_symbol is absent and
            # the token was used instead.
            stored = self.subscriptions.pop(corr_id, None)
            br_symbol = (stored or {}).get("br_symbol") or symbol

            remaining = list(self.subscriptions.values())

            # Only send the upstream unsubscribe for channels no remaining
            # subscription still needs (e.g. every mode subscribes to ticker,
            # so dropping one must not kill the shared stream).
            stale_channels = [
                channel for channel in channels
                if not any(
                    s.get("br_symbol") == br_symbol and channel in s.get("channels", ())
                    for s in remaining
                )
            ]

            # Only drop the LTP cache when no other mode for this symbol/exchange
            # remains (the cache is keyed on symbol_exchange, shared across modes).
            cache_key = f"{symbol}_{exchange}"
            if not any(
                s.get("symbol") == symbol and s.get("exchange") == exchange
                for s in remaining
            ):
                self.last_values.pop(cache_key, None)

        if self.public_ws and stale_channels:
            try:
                with self._lock:
                    for channel in stale_channels:
                        self._queue_op(self.unsubscription_queue,
                                       self.subscription_queue, channel, br_symbol)
            except Exception as exc:
                self.logger.error("unsubscribe error %s.%s: %s", symbol, exchange, exc)
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(exc))

        # Deliberately NOT disconnecting when the last subscription goes away.
        # The connection pool (websocket_proxy/connection_manager.py) owns this
        # adapter's lifecycle and keeps reusing the same instance: dropping to
        # zero symbols is routine (an option chain switching expiry/strikes
        # unsubscribes every symbol before subscribing the new set).  Tearing
        # the sockets down here left the pool holding a dead adapter — the WS
        # retry loop exits on _stop_flag and the ZMQ publisher is closed, so
        # every later subscribe was accepted, queued, and silently buffered
        # with no socket to carry it and no path back to connected.  An idle
        # connection with no subscriptions costs nothing; explicit teardown
        # still happens through disconnect().

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}", symbol=symbol, exchange=exchange, mode=mode
        )

    # ── subscription batching ─────────────────────────────────────────────────

    def _queue_op(self, queue: list, opposite: list, channel: str, br_symbol: str) -> None:
        """Queue one channel/symbol operation. Caller must hold self._lock.

        An entry still sitting in the opposite queue has not reached the wire
        yet, so the two cancel out: a subscribe followed by an unsubscribe
        inside the same window sends nothing at all, rather than sending both
        and relying on the order they land in.
        """
        entry = (channel, br_symbol)
        if entry in opposite:
            opposite.remove(entry)
            return
        if entry not in queue:
            queue.append(entry)
        if self.batch_timer is None:
            # The window runs from the first queued item rather than sliding
            # with each new one, so a steady stream still flushes on time.
            self.batch_timer = threading.Timer(self.batch_delay, self._process_batch)
            self.batch_timer.daemon = True
            self.batch_timer.start()

    def _process_batch(self) -> None:
        """Flush queued work: one frame per channel where the channel allows it."""
        with self._lock:
            self.batch_timer = None
            subs   = self._group_by_channel(self.subscription_queue)
            unsubs = self._group_by_channel(self.unsubscription_queue)
            self.subscription_queue.clear()
            self.unsubscription_queue.clear()
            client = self.public_ws

        if not client:
            return

        for channel, symbols in unsubs.items():
            self._send_batch(client, channel, symbols, subscribe=False)
        for channel, symbols in subs.items():
            self._send_batch(client, channel, symbols, subscribe=True)

    @staticmethod
    def _group_by_channel(queue: list) -> dict[str, list[str]]:
        """Collapse a queue of (channel, symbol) pairs into channel → symbols."""
        grouped: dict[str, list[str]] = {}
        for channel, br_symbol in queue:
            grouped.setdefault(channel, []).append(br_symbol)
        return grouped

    def _send_batch(self, client, channel: str, symbols: list[str], subscribe: bool) -> None:
        verb = "subscribing" if subscribe else "unsubscribing"
        try:
            # %s only: SensitiveDataFilter stringifies every log arg, so a %d
            # here would raise and the line would print unformatted.
            self.logger.info("Batch %s %s %s symbols", verb, len(symbols), channel)
            if channel == DeltaWebSocket.CHANNEL_TICKER:
                (client.subscribe_ticker if subscribe else client.unsubscribe_ticker)(symbols)
            else:
                (client.subscribe_orderbook if subscribe else client.unsubscribe_orderbook)(symbols)
        except Exception as exc:
            self.logger.error("Batch %s failed for %s: %s", verb, channel, exc)

    # ── internal callbacks ────────────────────────────────────────────────────

    def _on_public_open(self, wsapp) -> None:
        """Called after the market-data connection (re)connects.

        Channel replay is handled automatically by DeltaWebSocket._ws_on_open,
        which re-subscribes its whole symbol registry before invoking this
        callback.  Manually re-subscribing here would only duplicate frames.
        """
        self.logger.info("DeltaWS public connection opened")
        self.connected = True

    def _on_private_open(self, wsapp) -> None:
        """Called after the authenticated connection (re)connects.

        Private feeds are bootstrapped here on first connect; DeltaWebSocket
        registers them so subsequent reconnects replay them automatically
        without needing another explicit call.
        """
        self.logger.info("DeltaWS private connection opened")
        self._subscribe_private_feeds()

    def _on_error(self, wsapp, error) -> None:
        self.logger.error("DeltaWS error: %s", error)

    def _on_close(self, wsapp) -> None:
        self.logger.info("DeltaWS closed")
        # Market data is what `connected` reports on; the private connection
        # closing does not stop ticks from reaching subscribers.
        if not (self.public_ws and self.public_ws.is_connected):
            self.connected = False
        # No manual reconnect here — DeltaWebSocket.connect() runs a blocking
        # retry loop that handles all reconnection with proper backoff and the
        # configured max_retry_attempt limit.  Spawning another connect() thread
        # from this callback (which is invoked mid-loop, before run_forever
        # returns) would create a second competing retry loop with a reset
        # counter, bypassing max_retry_attempt and risking duplicate connections.

    def _on_data(self, wsapp, msg: dict) -> None:
        """
        Route incoming messages to the appropriate normaliser.

        Delta ticker shape (one frame can carry several contracts in "d"):
          { "type": "ticker", "sy": "BTCUSD", "sp": "63860.7",
            "d": [{ "s": "BTCUSD", "m": "63838.06",
                    "ohlc": [64025.0, 64475.5, 63217.5, 63839.0],
                    "oi": ["1407713", "307138.71"],
                    "q": ["63834", "718", "63833", "4388", null] }] }

        Delta ob_l2 shape (asks and bids, price + size, best first):
          { "type": "ob_l2", "sy": "BTCUSD",
            "a": [["63834", "718"], ...],
            "b": [["63833", "4388"], ...] }

        Private order event shape:
          { "type": "orders", "action": "fill",
            "id": 12345, "product_id": 27, "product_symbol": "BTCUSD",
            "size": 1, "side": "buy", "average_fill_price": "67000",
            "state": "filled", "client_order_id": "..." }

        Private position update shape:
          { "type": "positions", "product_id": 27, "product_symbol": "BTCUSD",
            "size": 2, "entry_price": "66800", "realized_pnl": "100",
            "unrealized_pnl": "400" }
        """
        try:
            msg_type = msg.get("type", "")

            # ── Private / account-level events (no symbol-level subscription needed) ─────
            if msg_type in ("orders", "positions", "margins"):
                self._handle_private_event(msg_type, msg)
                return

            if msg_type == DeltaWebSocket.CHANNEL_TICKER:
                updates = self._normalise_ticker(msg)
            elif msg_type == DeltaWebSocket.CHANNEL_OB_L2:
                updates = self._normalise_orderbook(msg)
            else:
                self.logger.debug("Unhandled message type: %s", msg_type)
                return

            ts = int(time.time() * 1000)
            for br_symbol, fields in updates:
                if not br_symbol:
                    continue

                # Find ALL OpenAlgo subscriptions matching this broker symbol +
                # channel.  Several modes can share one channel (every mode
                # subscribes to ticker), so we fan out to every subscriber.
                subscriptions = self._find_subscriptions_by_br_symbol(br_symbol, msg_type)
                if not subscriptions:
                    self.logger.debug("No subscription for br_symbol=%s type=%s", br_symbol, msg_type)
                    continue

                # All subscriptions for a br_symbol share one cache entry, which
                # accumulates the last known value of every field across both
                # channels.  Publishing the merged entry is what lets a depth
                # subscriber carry ltp/oi/ohlc (ob_l2 has none of them) and a
                # quote subscriber carry depth.
                cache_key   = f"{subscriptions[0]['symbol']}_{subscriptions[0]['exchange']}"
                merged      = self._merge_into_cache(cache_key, fields)

                for subscription in subscriptions:
                    oa_symbol   = subscription["symbol"]
                    oa_exchange = subscription["exchange"]
                    oa_mode     = subscription["mode"]
                    mode_str    = DeltaModeMapper.get_mode_str(oa_mode)
                    topic       = f"{oa_exchange}_{oa_symbol}_{mode_str}"

                    market_data = dict(merged)  # shallow copy per subscriber
                    market_data.update({
                        "symbol":    oa_symbol,
                        "exchange":  oa_exchange,
                        "mode":      oa_mode,
                        "timestamp": ts,
                    })

                    self.publish_market_data(topic, market_data)

        except Exception as exc:
            self.logger.error("_on_data error: %s", exc, exc_info=True)

    # ── private feed helpers ──────────────────────────────────────────────────

    def _subscribe_private_feeds(self) -> None:
        """Subscribe to authenticated order / position / margin channels.

        Called automatically after every WebSocket (re)connect.  These channels
        deliver fill confirmations, position changes, and wallet updates without
        the need to poll REST endpoints.  Requires that the WebSocket session
        has been authenticated (the auth frame is sent in DeltaWebSocket._ws_on_open).
        """
        if not self.ws_client:
            return
        try:
            self.ws_client.subscribe_orders_channel()
            self.ws_client.subscribe_positions_channel()
            self.ws_client.subscribe_margins_channel()
            self.logger.info("Subscribed to private feeds: orders, positions, margins")
        except Exception as exc:
            self.logger.error("Failed to subscribe to private feeds: %s", exc)

    def _handle_private_event(self, event_type: str, msg: dict) -> None:
        """Normalise and publish an account-level private event.

        Private events are published on a fixed per-type topic so that any
        OpenAlgo service can subscribe to them via ZeroMQ:

          Topic pattern: ``deltaexchange_{event_type}``
          Examples:      ``deltaexchange_orders``, ``deltaexchange_positions``,
                         ``deltaexchange_margins``

        The raw message dict is forwarded as-is; callers can inspect
        ``msg["action"]`` (e.g. "fill", "create", "cancel") for order events
        and ``msg["size"]`` / ``msg["entry_price"]`` for position events.
        """
        topic = f"deltaexchange_{event_type}"
        payload = dict(msg)
        payload["timestamp"] = int(time.time() * 1000)
        self.publish_market_data(topic, payload)
        self.logger.debug("Private event published: type=%s topic=%s", event_type, topic)

    # ── normalisation ─────────────────────────────────────────────────────────

    def _normalise_ticker(self, msg: dict) -> list[tuple[str, dict]]:
        """
        Map a ticker frame to OpenAlgo market data, one entry per contract.

        Field mapping (compact keys, per the public-endpoint schema):
            ltp        ← d[].m        mark price, matching the REST quote path
            open/high/
            low/close  ← d[].ohlc     rolling 24h window
            oi         ← d[].oi[0]    open interest in contracts
            bid_price  ← d[].q[2]     best bid
            bid_qty    ← d[].q[3]     bid size
            ask_price  ← d[].q[0]     best ask
            ask_qty    ← d[].q[1]     ask size

        The channel publishes no traded volume — REST /v2/tickers still does,
        so anything polling quotes keeps showing it.

        A field Delta omits is left out of the update entirely rather than sent
        as 0.  The two are not the same thing: a genuine zero bid size has to
        reach subscribers (the book really is empty), while a missing mark
        price must not overwrite the last good LTP with 0.
        """
        entries = msg.get("d")
        if not isinstance(entries, list):
            entries = []
        # Spot price is per-frame, not per-contract; it is the LTP fallback for
        # instruments that publish no mark price.
        spot = msg.get("sp")

        def _at(seq, idx):
            return seq[idx] if isinstance(seq, (list, tuple)) and len(seq) > idx else None

        def _put(fields, key, raw, cast=_f):
            """Record a scalar field only when Delta actually sent a value."""
            if raw is not None:
                fields[key] = cast(raw)

        def _put_from(fields, container, key, raw, cast=_f):
            """Record a field carried inside an array.

            A present array is authoritative: a null element inside it means
            "no value right now" (an emptied side of the book quotes null for
            best_ask), so it publishes as 0 instead of leaving the last traded
            size on screen forever.  A missing array says nothing at all, so
            its fields are omitted and the previous values stand.
            """
            if container is not None:
                fields[key] = cast(raw)

        updates: list[tuple[str, dict]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            br_symbol = entry.get("s") or msg.get("sy") or ""
            ohlc      = entry.get("ohlc")
            oi        = entry.get("oi")
            quotes    = entry.get("q")

            fields: dict = {"average_price": 0, "oi_change": 0}

            _put(fields, "ltp", entry.get("m") if entry.get("m") is not None else spot)
            _put_from(fields, ohlc, "open",  _at(ohlc, 0))
            _put_from(fields, ohlc, "high",  _at(ohlc, 1))
            _put_from(fields, ohlc, "low",   _at(ohlc, 2))
            _put_from(fields, ohlc, "close", _at(ohlc, 3))
            _put_from(fields, oi, "oi",      _at(oi, 0))
            _put_from(fields, quotes, "bid_price", _at(quotes, 2))
            _put_from(fields, quotes, "bid_qty",   _at(quotes, 3), _i)
            _put_from(fields, quotes, "ask_price", _at(quotes, 0))
            _put_from(fields, quotes, "ask_qty",   _at(quotes, 1), _i)

            updates.append((br_symbol, fields))

        return updates

    def _normalise_orderbook(self, msg: dict) -> list[tuple[str, dict]]:
        """
        Map an ob_l2 frame to OpenAlgo depth format.

        Delta publishes the top 15 levels per side as ["price", "size"] pairs,
        best first; OpenAlgo consumes the top 5.
        """
        def _parse_levels(side_list, n=5):
            levels = []
            for lvl in (side_list or [])[:n]:
                if isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
                    levels.append({"price": _f(lvl[0]), "quantity": _i(lvl[1])})
            while len(levels) < n:
                levels.append({"price": 0.0, "quantity": 0})
            return levels

        bids = _parse_levels(msg.get("b"))
        asks = _parse_levels(msg.get("a"))

        return [(msg.get("sy") or "", {
            "depth": {
                "buy":  bids,
                "sell": asks,
            },
            "totalbuyqty":  sum(lvl["quantity"] for lvl in bids),
            "totalsellqty": sum(lvl["quantity"] for lvl in asks),
        })]

    def _merge_into_cache(self, cache_key: str, fields: dict) -> dict:
        """Fold a normalised update into the symbol's cache and return the whole.

        Every field present in the update is written, zeros included — an empty
        book or a zero bid size is real information and must reach subscribers.
        Absent fields are what the normalisers omit, so a ticker frame that
        carries no mark price cannot blank the last good LTP.  The two channels
        write disjoint key sets (ticker: price/OI/quotes, ob_l2: depth), so
        neither can overwrite the other's values.
        """
        with self._lock:
            cached = self.last_values.setdefault(cache_key, {})
            cached.update(fields)
            return dict(cached)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _find_subscriptions_by_br_symbol(self, br_symbol: str, msg_type: str) -> list[dict]:
        """Return ALL subscriptions whose br_symbol and channel match the incoming message.

        Multiple subscription modes map to the same channel — every mode
        subscribes to ticker, and depth mode additionally subscribes to ob_l2.
        Returning every match ensures each subscriber receives its own publish
        call.
        """
        with self._lock:
            matched = [
                sub for sub in self.subscriptions.values()
                if sub.get("br_symbol") == br_symbol and msg_type in sub.get("channels", ())
            ]
            if not matched:
                # Fallback: any sub with matching br_symbol regardless of channel
                matched = [
                    sub for sub in self.subscriptions.values()
                    if sub.get("br_symbol") == br_symbol
                ]
        return matched
