"""Kotak SFeed market-data WebSocket client.

A drop-in replacement for KotakWebSocket (the legacy HSM client), exposing the
same method surface and emitting the same normalized dicts, so kotak_adapter.py
and everything downstream of it are unchanged. What differs is entirely below
that line: a different host, a different binary protocol (see sfeed_protocol.py)
and a JSON control plane instead of HSM's binary request frames.

Deliberately threaded, not async. Kotak's own SFeed client is asyncio-only, but
OpenAlgo's broker adapters are threads talking to ZMQ, and an event loop bolted
into one adapter would have to be owned, shut down and reconnected by code that
has no loop of its own. Replicating the protocol over websocket-client keeps
the concurrency model the adapter already understands.

Three differences from HSM shape the code here:

1. Prices are scaled by a per-exchange divider that arrives once, in the auth
   response - not by a precision carried in each tick. Nothing can be decoded
   before authentication completes, so subscriptions queue until it does.
2. The trading symbol is not in the tick. It arrives once per subscribe, in the
   acknowledgement (code 1109), and has to be remembered and attached.
3. One binary frame carries several packets. Every read is a batch.
"""

import json
import threading
import time

import websocket

from broker.kotak.streaming.sfeed_protocol import (
    EXCHANGE_NAME_TO_ID,
    LEVEL_DEPTH,
    LEVEL_FULL_DEPTH,
    LEVEL_TOUCH_LINE,
    MSG_AUTH_RESPONSE_CODES,
    MSG_SUBSCRIBE_ACK,
    decode_packet,
    split_batch,
)
from utils.logging import get_logger

logger = get_logger(__name__)

# HSM sub_type -> SFeed control-plane event. The adapter speaks HSM's
# vocabulary (mws/dps/ifs and their unsubscribes) and keeps doing so; the
# translation stops here rather than rippling into kotak_adapter.py.
_SUBSCRIBE_EVENTS = {
    "mws": "subscribeScrips",
    "dps": "subscribeDepth",
    "ifs": "subscribeIndices",
}
_UNSUBSCRIBE_EVENTS = {
    "mwu": "unsubscribeScrips",
    "dpu": "unsubscribeDepth",
    "ifu": "unsubscribeIndices",
}
# Which subscribe an unsubscribe undoes, so the bookkeeping in
# unsubscribe_batch removes the entry subscribe_batch actually added.
_UNSUBSCRIBE_CLEARS = {"mwu": "mws", "dpu": "dps", "ifu": "ifs"}

# Documented SFeed cap: 3000 input tokens subscribed at once, counted across
# every subscribe intent. A request that would cross it is rejected server-side
# and nothing is sent, so it is worth catching here where we can say which
# request was refused and why.
MAX_SUBSCRIPTIONS = 3000

AUTH_TIMEOUT_SECONDS = 15

# Backstop on frames queued while unauthenticated. _handle_close already clears
# the queue per connection, so reaching this means frames are being queued
# against a socket that never opened at all.
MAX_PENDING_FRAMES = 256


class KotakSFeedWebSocket:
    """SFeed client with KotakWebSocket's interface.

    Args:
        auth_config: dict carrying at least "sid". The SFeed auth frame wants
            the session sid as its "auth" credential and the UCC as "user" -
            note it does not use the session token that the REST APIs and the
            order feed authenticate with.
        ws_url: market-data endpoint. Resolve it with
            kotak_feed_config.fetch_feed_config() rather than hardcoding, since
            which host serves an account depends on its data centre.
        ucc: Unique Client Code, the "user" credential. Kotak's SDK falls back
            to the placeholder "neome" when it has none; we do the same so a
            missing UCC degrades rather than refusing to connect.
    """

    # SFeed takes every token in one comma-separated "inputtoken" and has no
    # documented per-frame cap - Kotak's own client joins the whole list into a
    # single frame and never chunks. Setting this to the total subscription cap
    # means the adapter's chunking loop runs once, matching that behaviour,
    # while still going through the same code path as HSM's 100.
    MAX_BATCH_SIZE = MAX_SUBSCRIPTIONS

    def __init__(self, auth_config, ws_url, ucc=None):
        self.auth_config = auth_config
        self.ws_url = ws_url
        self.ucc = ucc

        self._lock = threading.RLock()
        self._ws = None
        self._thread = None
        self._should_run = True
        self._is_connected = False
        self._is_authenticated = False
        self._auth_event = threading.Event()

        # exchange_id -> price divider, from the auth response. Empty until
        # authenticated, which is why decoding cannot start before then.
        self._dividers = {}
        # "<exchange>|<token>" -> trading symbol, from subscribe acks.
        self._symbols = {}

        # (exchange, token, sub_type) for everything currently subscribed, so a
        # reconnect can replay it. Same bookkeeping the HSM client keeps.
        self._subscriptions = set()
        # Frames built before authentication finished, sent once it does.
        self._pending_frames = []

        self._on_quote = None
        self._on_depth = None
        self._on_index = None
        self._on_error = None
        self._on_open = None
        self._on_close = None
        # SFeed-only message types. The adapter has no channel for these, so
        # they default to None and are logged rather than dispatched - but the
        # hooks exist so market status and CAS are reachable without reopening
        # the protocol layer.
        self._on_market_status = None
        self._on_cas = None

    # ------------------------------------------------------------------
    # Interface shared with KotakWebSocket
    # ------------------------------------------------------------------

    def set_callbacks(
        self,
        on_quote=None,
        on_depth=None,
        on_index=None,
        on_error=None,
        on_open=None,
        on_close=None,
        on_market_status=None,
        on_cas=None,
    ):
        self._on_quote = on_quote
        self._on_depth = on_depth
        self._on_index = on_index
        self._on_error = on_error
        self._on_open = on_open
        self._on_close = on_close
        self._on_market_status = on_market_status
        self._on_cas = on_cas

    def is_connected(self):
        with self._lock:
            return self._is_connected and self._is_authenticated

    def connect(self):
        """Start the connection in a background thread. Idempotent."""

        def _run():
            try:
                self._ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self._handle_open,
                    on_message=self._handle_message,
                    on_error=self._handle_error,
                    on_close=self._handle_close,
                )
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                logger.error(f"KotakSFeedWebSocket connection error: {e}")
                if self._on_error:
                    self._on_error(e)

        thread = threading.Thread(target=_run, daemon=True, name="kotak-sfeed")

        # Claim the thread slot under the lock. is_connected() stays False for
        # the whole handshake, so a caller cannot guard this itself - without
        # the check a second connect() in that window starts a second socket
        # and orphans the first, which nothing would then close.
        with self._lock:
            if not self._should_run:
                logger.warning("connect() called on a closed KotakSFeedWebSocket, ignoring")
                return
            if self._thread is not None and self._thread.is_alive():
                logger.warning("connect() called while already connecting, ignoring")
                return
            self._thread = thread

        thread.start()

    def close(self):
        with self._lock:
            if not self._should_run:
                return
            self._should_run = False
            self._is_connected = False
            self._is_authenticated = False
            # Silence callbacks before teardown. The adapter owns reconnection;
            # firing on_close here would have it schedule a reconnect for a
            # socket the caller deliberately closed.
            self._on_close = None
            self._on_error = None
            self._on_open = None
            ws = self._ws
            thread = self._thread
            self._thread = None

        self._auth_event.set()  # release anything waiting on authentication
        if ws:
            try:
                ws.close()
            except Exception as e:
                logger.warning(f"Error closing SFeed socket: {e}")
        if thread:
            thread.join(timeout=5)

        with self._lock:
            self._subscriptions.clear()
            self._pending_frames.clear()
            self._symbols.clear()
            self._dividers.clear()

    def subscribe(self, exchange, token, sub_type="mws", channelnum="1"):
        """Subscribe one scrip. channelnum is accepted and ignored - SFeed has
        no channel concept, unlike HSM's 16 channels. The parameter stays in
        the signature so the adapter's call sites are unchanged."""
        self.subscribe_batch([(exchange, token)], sub_type=sub_type, channelnum=channelnum)

    def unsubscribe(self, exchange, token, sub_type="mwu", channelnum="1"):
        self.unsubscribe_batch([(exchange, token)], sub_type=sub_type, channelnum=channelnum)

    def subscribe_batch(self, scrips, sub_type="mws", channelnum="1"):
        """Subscribe several scrips in one frame."""
        scrips = list(scrips)
        if not scrips:
            return

        event = _SUBSCRIBE_EVENTS.get(sub_type)
        if not event:
            logger.error(f"Unknown SFeed subscribe sub_type {sub_type!r}, ignoring")
            return

        with self._lock:
            new = {(ex, tk, sub_type) for ex, tk in scrips} - self._subscriptions
            projected = len(self._subscriptions) + len(new)
            if projected > MAX_SUBSCRIPTIONS:
                logger.error(
                    f"Refusing SFeed subscribe: {len(new)} new tokens would take the total "
                    f"to {projected}, past the {MAX_SUBSCRIPTIONS} cap. Kotak rejects the "
                    "whole request server-side, so nothing was sent."
                )
                return
            self._subscriptions |= new

        frame = {
            "event": event,
            "inputtoken": ",".join(f"{ex}|{tk}" for ex, tk in scrips),
            # Ask for the token -> trading symbol map. Without it every tick
            # would carry an empty ts, since SFeed does not put the symbol in
            # the tick the way HSM does.
            "ack_symbol": True,
        }
        logger.info(f"[KOTAK SFEED] {event} count={len(scrips)}")
        self._send(frame)

    def unsubscribe_batch(self, scrips, sub_type="mwu", channelnum="1"):
        scrips = list(scrips)
        if not scrips:
            return

        event = _UNSUBSCRIBE_EVENTS.get(sub_type)
        if not event:
            logger.error(f"Unknown SFeed unsubscribe sub_type {sub_type!r}, ignoring")
            return

        paired = _UNSUBSCRIBE_CLEARS[sub_type]
        with self._lock:
            self._subscriptions -= {(ex, tk, paired) for ex, tk in scrips}
            # Drop the trading symbols too. This map only exists because SFeed
            # does not put the symbol in the tick the way HSM did, so an entry
            # is worth exactly as long as a subscription to that token - and
            # its key space is every instrument subscribed for the life of the
            # process, which a symbol-rotating scanner grows all session.
            # Only once no intent still holds the token: quote and depth
            # subscribe separately and share one symbol entry.
            still_held = {(ex, tk) for ex, tk, _ in self._subscriptions}
            for ex, tk in scrips:
                if (ex, tk) not in still_held:
                    self._symbols.pop(f"{ex}|{tk}", None)

        frame = {"event": event, "inputtoken": ",".join(f"{ex}|{tk}" for ex, tk in scrips)}
        logger.info(f"[KOTAK SFEED] {event} count={len(scrips)}")
        self._send(frame)

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _send(self, frame):
        """Send a control frame, or hold it until authentication completes."""
        with self._lock:
            if not (self._is_connected and self._is_authenticated):
                if len(self._pending_frames) >= MAX_PENDING_FRAMES:
                    # Nothing is draining this, so the queue is the symptom of
                    # a socket that is not coming back rather than a backlog
                    # about to be flushed. Drop the oldest instead of growing.
                    dropped = self._pending_frames.pop(0)
                    logger.warning(
                        f"SFeed pending-frame queue full at {MAX_PENDING_FRAMES}; "
                        f"dropped the oldest ({dropped.get('event')}). The adapter "
                        "replays subscriptions on reconnect, so this is recoverable."
                    )
                self._pending_frames.append(frame)
                logger.debug("SFeed not authenticated yet, queued control frame")
                return
            ws = self._ws
        try:
            ws.send(json.dumps(frame))
        except Exception as e:
            logger.error(f"Failed to send SFeed control frame: {e}")
            if self._on_error:
                self._on_error(e)

    def _build_auth_frame(self):
        """The native_batch authentication frame.

        These values mirror what Kotak's client sends. version/sdk_version/
        sdk_date are build markers the server records rather than validates -
        they are sent because the frame is rejected without the fields, not
        because any particular value is required.
        """
        return {
            "user": self.ucc or "neome",
            "auth": self.auth_config.get("sid") or "1",
            "format": "native_batch",
            "source": "NEOTRADEAPI",
            "platform": "Web",
            "version": "1.2.3",
            "sdk_version": 2,
            "sdk_date": "2026-08-07T09:41:17.667Z",
            "conn_req_time": int(time.time() * 1000),
            "sessionValidation": False,
        }

    def _handle_open(self, ws):
        logger.info(f"SFeed transport open to {self.ws_url}, authenticating")
        with self._lock:
            self._is_connected = True
            self._is_authenticated = False
        self._auth_event.clear()
        try:
            ws.send(json.dumps(self._build_auth_frame()))
        except Exception as e:
            logger.error(f"Failed to send SFeed auth frame: {e}")
            if self._on_error:
                self._on_error(e)
            return

        # The socket stays open on a rejected auth, so a failure looks exactly
        # like a quiet market. Time it out and close, which turns silence into
        # a logged failure plus the adapter's normal reconnect.
        threading.Thread(target=self._watch_auth, args=(ws,), daemon=True).start()

    def _watch_auth(self, ws):
        if self._auth_event.wait(timeout=AUTH_TIMEOUT_SECONDS):
            return
        with self._lock:
            still_ours = self._ws is ws and self._should_run
            authed = self._is_authenticated
        if authed or not still_ours:
            return
        logger.error(
            f"No SFeed auth response within {AUTH_TIMEOUT_SECONDS}s; closing so the "
            "adapter reconnects"
        )
        try:
            ws.close()
        except Exception:
            pass

    def _handle_message(self, ws, message):
        try:
            if isinstance(message, (bytes, bytearray)):
                self._handle_binary(bytes(message))
            else:
                self._handle_text(message)
        except Exception as e:
            logger.error(f"Error handling SFeed message: {e}")

    def _handle_text(self, raw):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.info(f"SFeed non-JSON text frame: {raw!r}")
            return
        if not isinstance(data, dict):
            return

        code = data.get("message_code")

        if code in MSG_AUTH_RESPONSE_CODES:
            self._handle_auth_response(data)
            return

        if code == MSG_SUBSCRIBE_ACK:
            self._handle_subscribe_ack(data)
            return

        logger.debug(f"SFeed control frame: {data}")

    def _handle_auth_response(self, data):
        if data.get("format") == "native_fallback":
            # The server refused native_batch and offered the older format
            # instead. sfeed_protocol.py cannot read that, so continuing would
            # decode every packet into nonsense.
            logger.error(
                "SFeed downgraded the connection to native_fallback, which this decoder "
                "does not implement. Closing rather than decoding garbage."
            )
            if self._on_error:
                self._on_error(RuntimeError("SFeed downgraded to native_fallback"))
            self._auth_event.set()
            return

        # Price dividers, keyed by exchange id. Prefer the id the response
        # states for each exchange over our own static name -> id map, so a
        # server-side renumbering does not silently misscale a whole segment.
        dividers = {}
        for name, info in (data.get("exchanges") or {}).items():
            if not isinstance(info, dict):
                continue
            exch_id = info.get("value", EXCHANGE_NAME_TO_ID.get(name))
            if exch_id is not None:
                dividers[int(exch_id)] = info.get("divider", 100)

        with self._lock:
            self._dividers = dividers
            self._is_authenticated = True
            pending = list(self._pending_frames)
            self._pending_frames.clear()
            ws = self._ws

        self._auth_event.set()
        logger.info(f"SFeed authenticated, dividers for {len(dividers)} exchanges")

        for frame in pending:
            try:
                ws.send(json.dumps(frame))
            except Exception as e:
                logger.error(f"Failed to flush queued SFeed frame: {e}")

        if self._on_open:
            self._on_open()

    def _handle_subscribe_ack(self, data):
        """Record the token -> trading symbol map from a subscribe ack."""
        symbols = data.get("trading_symbols") or data.get("tradingSymbols") or {}
        if not isinstance(symbols, dict):
            return
        with self._lock:
            self._symbols.update({str(k): str(v) for k, v in symbols.items()})
        logger.debug(f"SFeed subscribe ack mapped {len(symbols)} trading symbols")

    def _handle_binary(self, frame):
        with self._lock:
            dividers = self._dividers
            authenticated = self._is_authenticated

        if not authenticated:
            # Prices would all be scaled by the fallback divider, which is
            # right for some exchanges and wrong for others. A wrong price is
            # worse than a late one.
            logger.debug("Dropping SFeed binary frame received before authentication")
            return

        for packet in split_batch(frame):
            decoded = decode_packet(packet, dividers)
            if decoded is not None:
                self._dispatch(decoded)

    def _handle_error(self, ws, error):
        logger.error(f"SFeed WebSocket error: {error}")
        if self._on_error:
            self._on_error(error)

    def _handle_close(self, ws, status_code=None, msg=None):
        logger.info(f"SFeed WebSocket closed (status={status_code}, msg={msg})")
        with self._lock:
            self._is_connected = False
            self._is_authenticated = False
            # Queued frames belonged to the connection that just died. The
            # adapter resubscribes from its own record on reconnect, so
            # keeping these would re-send subscriptions that are about to be
            # sent again anyway - and during an outage the queue would grow by
            # one full replay per reconnect attempt, unbounded.
            if self._pending_frames:
                logger.debug(
                    f"Discarding {len(self._pending_frames)} queued SFeed frames "
                    "belonging to the closed connection"
                )
                self._pending_frames.clear()
        self._auth_event.set()
        if self._on_close:
            self._on_close()

    # ------------------------------------------------------------------
    # Normalization to OpenAlgo's shape
    # ------------------------------------------------------------------

    def _dispatch(self, decoded):
        kind = decoded.get("type")

        if kind == "scrip":
            level = decoded.get("level")
            if level in (LEVEL_DEPTH, LEVEL_FULL_DEPTH):
                if self._on_depth:
                    self._on_depth(self._to_depth(decoded))
            elif self._on_quote:
                self._on_quote(self._to_quote(decoded))
            return

        if kind == "scrip_lite":
            if self._on_quote:
                self._on_quote(self._to_quote_lite(decoded))
            return

        if kind == "index":
            payload = self._to_index(decoded)
            # HSM delivered indices down the quote path, and the adapter has no
            # separate index channel. Keep that routing so index subscriptions
            # behave the same as they did before the migration.
            handler = self._on_index or self._on_quote
            if handler:
                handler(payload)
            return

        if kind == "market_status":
            if self._on_market_status:
                self._on_market_status(decoded)
            else:
                logger.info(
                    f"SFeed market status: {decoded.get('exchange_segment')} "
                    f"{decoded.get('status')} (code {decoded.get('status_code')})"
                )
            return

        if kind == "cas":
            if self._on_cas:
                self._on_cas(decoded)
            else:
                logger.debug(f"SFeed CAS update: {decoded}")

    def _symbol_for(self, decoded):
        key = f"{decoded.get('exchange_segment')}|{decoded.get('instrument_token')}"
        with self._lock:
            return self._symbols.get(key, "")

    def _to_quote(self, decoded):
        """Market picture at touch-line level -> OpenAlgo's quote dict.

        Field names are HSM's, not SFeed's, because that is what the adapter
        and everything past it already read.
        """
        buy = decoded.get("buy") or []
        sell = decoded.get("sell") or []
        return {
            "bid": buy[0]["price"] if buy else 0.0,
            "ask": sell[0]["price"] if sell else 0.0,
            "open": decoded.get("open_price", 0.0),
            "high": decoded.get("high_price", 0.0),
            "low": decoded.get("low_price", 0.0),
            "ltp": decoded.get("last_traded_price", 0.0),
            "prev_close": decoded.get("close_price", 0.0),
            "volume": decoded.get("volume_traded_today", 0),
            "ts": self._symbol_for(decoded),
            "tk": decoded.get("instrument_token", ""),
            "e": decoded.get("exchange_segment", ""),
        }

    def _to_quote_lite(self, decoded):
        """Mini touch line. Carries no OHLC or book, only a traded price.

        The absent fields are sent as 0.0 rather than omitted: the adapter
        treats a zero price field as "no update" and merges the last known
        value over it, so zeros are how you say "unchanged" in this contract.
        """
        return {
            "bid": 0.0,
            "ask": 0.0,
            "open": 0.0,
            "high": 0.0,
            "low": 0.0,
            "ltp": decoded.get("last_traded_price", 0.0),
            "prev_close": decoded.get("close_price", 0.0),
            "volume": 0,
            "ts": self._symbol_for(decoded),
            "tk": decoded.get("instrument_token", ""),
            "e": decoded.get("exchange_segment", ""),
        }

    def _to_depth(self, decoded):
        """Depth levels, padded to the 5 rows the adapter expects."""
        quote = self._to_quote(decoded)
        quote["bids"] = self._depth_rows(decoded.get("buy") or [])
        quote["asks"] = self._depth_rows(decoded.get("sell") or [])
        return quote

    @staticmethod
    def _depth_rows(rows):
        out = [
            {
                "price": row.get("price", 0.0),
                "quantity": row.get("quantity", 0),
                "orders": row.get("orders", 0),
            }
            for row in rows[:5]
        ]
        while len(out) < 5:
            out.append({"price": 0.0, "quantity": 0, "orders": 0})
        return out

    def _to_index(self, decoded):
        return {
            "bid": 0.0,
            "ask": 0.0,
            "open": decoded.get("open_price", 0.0),
            "high": decoded.get("high_price", 0.0),
            "low": decoded.get("low_price", 0.0),
            "ltp": decoded.get("last_traded_price", 0.0),
            "prev_close": decoded.get("close_price", 0.0),
            "volume": 0,
            "ts": decoded.get("name", "") or self._symbol_for(decoded),
            "tk": decoded.get("instrument_token", ""),
            "e": decoded.get("exchange_segment", ""),
        }
