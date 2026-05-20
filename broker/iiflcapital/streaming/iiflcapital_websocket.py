"""
High-level IIFL Capital market-data feed client.

Sits on top of `iiflcapital_mqtt.IiflMqttClient` and exposes the same
broker-feed surface that other OpenAlgo adapters consume (Zerodha-style):

    client = IiflcapitalWebSocket(user_session=<jwt>)
    client.on_ticks = lambda ticks: ...
    client.start()
    client.subscribe(brexchange="NSEEQ", token="2885", mode="full")

The IIFL feed publishes a single 188-byte "MWBOCombined" packet per market
update — it always contains LTP + OHLC + L5 depth + bid/ask totals + timestamp.
OpenAlgo's WebSocket proxy still wants three distinct modes (LTP/Quote/Depth),
so we subscribe ONCE per (segment, token) at the MQTT layer and let the
adapter slice the decoded dict into the right shape for each subscribed mode.
That is the same trade-off the Zerodha adapter makes with its `full` mode.

Stream coverage:
    * Market Feed (prod/marketfeed/mw/v1/) — primary, 188-byte structure
    * Index Feed  (prod/marketfeed/index/v1/) — same structure, separate prefix
    * Open Interest (prod/marketfeed/oi/v1/) — 16-byte OI packet, surfaced as
      the `oi`/`open_interest` field on the next Quote/Depth tick
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import struct
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime

from utils.logging import get_logger

from .iiflcapital_mqtt import CONNACK_ACCEPTED, CONNACK_REASONS, IiflMqttClient

# MQTT topic prefixes mirrored from bridgePy/connector.py.
TOPIC_MARKET_FEED = "prod/marketfeed/mw/v1/"
TOPIC_INDEX_FEED = "prod/marketfeed/index/v1/"
TOPIC_OPEN_INTEREST = "prod/marketfeed/oi/v1/"

# Modes are local to the IIFL client. They DO NOT correspond 1:1 with
# OpenAlgo's mode ints — the adapter layer translates 1/2/3 → "ltp"/"quote"/"full".
MODE_LTP = "ltp"
MODE_QUOTE = "quote"
MODE_FULL = "full"

# Conservative subscribe batching. The IIFL broker tolerates up to 1024 topics
# in a single SUBSCRIBE per the bridgePy validation; 100 keeps individual
# frames under the typical broker buffer and yields fast feedback.
MAX_TOKENS_PER_SUBSCRIBE = 100

# IIFL caps a single client at 6000 subscriptions (per docs). We keep some
# headroom below that to avoid edge-case rejections.
MAX_INSTRUMENTS_PER_CONNECTION = 5800


# ---------------------------------------------------------------------------
# Binary packet structures — mirrored from bridgePy/examples/main.py.
# IIFL's MWBOCombined packet is laid out for a C# struct with Pack=2 and
# native little-endian byte order. We reproduce it with ctypes so the layout
# stays in sync with the broker's wire format.
# ---------------------------------------------------------------------------
class _Depth(ctypes.Structure):
    _fields_ = [
        ("quantity", ctypes.c_uint32),
        ("price", ctypes.c_int32),
        ("orders", ctypes.c_int16),
        ("transactionType", ctypes.c_int16),  # 1 = bid, 2 = ask (per IIFL)
    ]


class _MWBOCombined(ctypes.Structure):
    _pack_ = 2
    _fields_ = [
        ("ltp", ctypes.c_int32),
        ("lastTradedQuantity", ctypes.c_uint32),
        ("tradedVolume", ctypes.c_uint32),
        ("high", ctypes.c_int32),
        ("low", ctypes.c_int32),
        ("open", ctypes.c_int32),
        ("close", ctypes.c_int32),
        ("averageTradedPrice", ctypes.c_int32),
        ("reserved", ctypes.c_uint16),
        ("bestBidQuantity", ctypes.c_uint32),
        ("bestBidPrice", ctypes.c_int32),
        ("bestAskQuantity", ctypes.c_uint32),
        ("bestAskPrice", ctypes.c_int32),
        ("totalBidQuantity", ctypes.c_uint32),
        ("totalAskQuantity", ctypes.c_uint32),
        ("priceDivisor", ctypes.c_int32),
        ("lastTradedTime", ctypes.c_int32),
        ("marketDepth", _Depth * 10),
    ]


_MWBOCombined_SIZE = ctypes.sizeof(_MWBOCombined)  # 186 bytes with _pack_=2


def _decode_jwt_username(token: str) -> str:
    """
    Extract `preferred_username` from a JWT (matches bridgePy's
    __get_user_name). The JWT payload (middle segment) is URL-safe base64
    without padding, so we pad it before decoding.

    Raises ValueError on malformed/expired tokens — the previous "tester"
    fallback silently masqueraded as a hardcoded username and masked
    misconfiguration.
    """
    try:
        payload_segment = token.split(".")[1]
        padding_needed = (4 - len(payload_segment) % 4) % 4
        padded = payload_segment + ("=" * padding_needed)
        decoded = base64.urlsafe_b64decode(padded)
        claims = json.loads(decoded)
    except Exception as exc:
        raise ValueError(f"Invalid IIFL user_session JWT: {type(exc).__name__}") from exc

    username = claims.get("preferred_username")
    if not username:
        raise ValueError("IIFL JWT missing 'preferred_username' claim")
    return str(username)


def _decode_market_feed(payload: bytes) -> dict | None:
    """
    Decode an MWBOCombined packet to a flat dict. Returns None if the
    payload is shorter than the expected structure size.

    Prices are integer-paise / priceDivisor; we apply the divisor here so
    downstream consumers always see floats in rupees.
    """
    if len(payload) < _MWBOCombined_SIZE:
        return None

    # IIFL's MWBOCombined is 186 bytes but the broker publishes 188-byte
    # frames in production (2 trailing bytes are slack). Slice to size.
    pkt = _MWBOCombined.from_buffer_copy(payload[:_MWBOCombined_SIZE])

    divisor = pkt.priceDivisor or 100  # never divide by zero
    inv = 1.0 / divisor

    # IIFL doc: "Bytes 66-185 contain: 5 bid levels - 5 ask levels". The
    # `transactionType` field in each Depth entry is informational and not a
    # reliable side selector (it stays 0 on many segments — MCX FUT, indices,
    # certain commodity futures), so we slice positionally instead.
    levels = pkt.marketDepth
    depth_buy = [
        {
            "quantity": int(level.quantity),
            "price": float(level.price) * inv,
            "orders": int(level.orders),
        }
        for level in levels[:5]
    ]
    depth_sell = [
        {
            "quantity": int(level.quantity),
            "price": float(level.price) * inv,
            "orders": int(level.orders),
        }
        for level in levels[5:10]
    ]

    ltt_unix = int(pkt.lastTradedTime) if pkt.lastTradedTime else 0

    return {
        "ltp": float(pkt.ltp) * inv,
        "last_traded_quantity": int(pkt.lastTradedQuantity),
        "volume": int(pkt.tradedVolume),
        "high": float(pkt.high) * inv,
        "low": float(pkt.low) * inv,
        "open": float(pkt.open) * inv,
        "close": float(pkt.close) * inv,
        "average_price": float(pkt.averageTradedPrice) * inv,
        "best_bid_quantity": int(pkt.bestBidQuantity),
        "best_bid_price": float(pkt.bestBidPrice) * inv,
        "best_ask_quantity": int(pkt.bestAskQuantity),
        "best_ask_price": float(pkt.bestAskPrice) * inv,
        "total_buy_quantity": int(pkt.totalBidQuantity),
        "total_sell_quantity": int(pkt.totalAskQuantity),
        "ltt": ltt_unix,
        "timestamp": int(time.time() * 1000),
        "depth": {"buy": depth_buy, "sell": depth_sell},
    }


def _decode_open_interest(payload: bytes) -> dict | None:
    """
    16-byte OI packet — four signed 32-bit integers in native byte order.
    Matches the `format = "iiii"` decode in bridgePy's example handler.
    """
    if len(payload) < 16:
        return None
    oi, day_high_oi, day_low_oi, prev_oi = struct.unpack("iiii", payload[:16])
    return {
        "open_interest": oi,
        "day_high_oi": day_high_oi,
        "day_low_oi": day_low_oi,
        "previous_oi": prev_oi,
    }


def _topic_key(segment: str, token: str | int) -> str:
    """Lowercase segment/token, e.g. ('NSEEQ', 2885) → 'nseeq/2885'."""
    return f"{segment.lower()}/{token}"


class IiflcapitalWebSocket:
    """
    Subscriber-side IIFL Capital market-data client.

    Public callbacks:
        on_ticks(list[dict])   — receives decoded ticks; each dict carries
                                  segment, token, mode, and the merged
                                  feed/OI fields.
        on_connect()           — fired after a successful broker handshake.
        on_disconnect()        — fired when the socket drops.
        on_error(Exception)    — surfaced reader/transport failures.
    """

    # Topic-payload size hint for OI vs market feed routing — used only by
    # the message dispatcher to skip OI decoding on undersized payloads.
    _OI_TOPIC_PREFIX = TOPIC_OPEN_INTEREST
    _MW_TOPIC_PREFIX = TOPIC_MARKET_FEED
    _IDX_TOPIC_PREFIX = TOPIC_INDEX_FEED

    # Reconnection settings (mirror the Zerodha client for parity).
    RECONNECT_MAX_DELAY = 60
    RECONNECT_MAX_TRIES = 50
    SUBSCRIPTION_DELAY = 0.3  # seconds between successive subscribe batches

    def __init__(
        self,
        user_session: str,
        host: str = "bridge.iiflcapital.com",
        port: int = 8883,
        on_ticks: Callable[[list[dict]], None] | None = None,
    ) -> None:
        if not user_session:
            raise ValueError("user_session is required")

        self.user_session = user_session
        self.host = host
        self.port = port
        self.on_ticks = on_ticks
        self.logger = get_logger("iiflcapital_websocket")

        # Microsecond timestamp + 4 bytes entropy avoids client_id collisions
        # when two reconnects fire on the same host within the same microsecond
        # (broker drops the older session with CONNACK rc=2 on collision).
        self.client_id = (
            "openalgo"
            + datetime.now().strftime("%d%m%y%H%M%S%f")
            + os.urandom(4).hex()
        )
        self.username = _decode_jwt_username(user_session)
        self.password = f"OPENID~~{user_session}~"  # bridgePy format

        self._mqtt: IiflMqttClient | None = None
        self._lock = threading.Lock()
        self.running = False
        self.connected = False

        # Subscription state, keyed by `segment/token` (the topic suffix).
        # Each entry: {"mode": "full"|"quote"|"ltp", "is_index": bool, "oi": bool}
        self._subscriptions: dict[str, dict] = {}

        # Cache the most recent OI per (segment, token) so we can merge it
        # into outbound market-feed ticks without round-trip latency.
        self._oi_cache: dict[str, dict] = {}

        # Pending subscribe queue (drained on a worker thread to batch large
        # bursts, same pattern as the Zerodha client).
        self._pending: deque = deque()
        self._sub_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Lifecycle callbacks for the adapter layer.
        self.on_connect: Callable[[], None] | None = None
        self.on_disconnect: Callable[[], None] | None = None
        self.on_error: Callable[[Exception], None] | None = None

        # Reconnect state.
        self._reconnect_attempts = 0
        self._reconnect_thread: threading.Thread | None = None

        # Fatal-error short-circuit — set on CONNACK auth rejections so the
        # reconnect loop bails out rather than hammering a known-bad token.
        self._fatal_error = False
        self._fatal_error_message = ""

    # ----------------------------------------------------------------- lifecycle
    def start(self) -> bool:
        """Open the MQTT connection. Returns True on accepted CONNACK."""
        if self.running and self.connected:
            return True

        self.running = True
        self._stop_event.clear()
        self._fatal_error = False
        self._fatal_error_message = ""

        return self._do_connect()

    def _do_connect(self) -> bool:
        try:
            self._mqtt = IiflMqttClient(
                host=self.host,
                port=self.port,
                client_id=self.client_id,
                username=self.username,
                password=self.password,
                keepalive=20,
            )
            self._mqtt.on_message = self._on_mqtt_message
            self._mqtt.on_disconnect = self._on_mqtt_disconnect
            self._mqtt.on_error = self._on_mqtt_error

            rc = self._mqtt.connect(timeout=15.0)
            if rc != CONNACK_ACCEPTED:
                reason = CONNACK_REASONS.get(rc, f"CONNACK rc={rc}")
                self.logger.error(f"IIFL CONNACK refused: {reason}")
                # rc 4/5 are auth failures — token is bad, do not retry.
                if rc in (4, 5):
                    self._fatal_error = True
                    self._fatal_error_message = reason
                    self.running = False
                return False

            self.connected = True
            self._reconnect_attempts = 0
            self.logger.info(
                f"IIFL Capital MQTT connected (client_id={self.client_id}, user={self.username})"
            )

            if self.on_connect:
                try:
                    self.on_connect()
                except Exception as e:
                    self.logger.exception(f"on_connect callback raised: {e}")

            # Re-subscribe to anything that survived a reconnect.
            self._resubscribe_all()
            return True

        except Exception as e:
            self.logger.exception(f"IIFL Capital MQTT connect failed: {e}")
            return False

    def stop(self) -> None:
        """Cleanly tear down the connection and worker threads."""
        self.running = False
        self._stop_event.set()
        if self._mqtt is not None:
            try:
                self._mqtt.disconnect()
            except Exception as e:
                self.logger.debug(f"Error during MQTT disconnect: {e}")
            self._mqtt = None
        self.connected = False

    def wait_for_connection(self, timeout: float = 15.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.connected:
                return True
            if self._fatal_error:
                return False
            time.sleep(0.05)
        return self.connected

    def is_connected(self) -> bool:
        return self.connected and self._mqtt is not None and self._mqtt.is_connected()

    # ----------------------------------------------------------------- subscribe
    def subscribe_instruments(
        self,
        instruments: list[tuple[str, str | int]],
        mode: str = MODE_FULL,
        is_index: bool = False,
        include_oi: bool = False,
    ) -> None:
        """
        Queue a batch of (segment, token) pairs for subscription.

        Args:
            instruments: list of (segment, token) tuples. Segment is the
                IIFL brexchange ('NSEEQ', 'NSEFO', 'BSEEQ', ...).
            mode: "ltp" / "quote" / "full" — affects which OpenAlgo modes the
                adapter will publish, not which broker topic we hit (the
                broker only has one packet shape per stream).
            is_index: True for NSE_INDEX/BSE_INDEX symbols; routes to the
                index topic prefix instead of the market-feed prefix.
            include_oi: subscribe to the OI stream alongside the market feed
                (only meaningful for derivatives).
        """
        if not instruments:
            return

        # Cap check must count only NEW keys — duplicates within the call or
        # symbols already in _subscriptions are re-subscribes (no new broker
        # slot consumed). Computing this under the lock keeps the count
        # consistent with the dict update that follows.
        incoming_keys = {_topic_key(seg, tok) for seg, tok in instruments}

        with self._lock:
            new_keys = incoming_keys - self._subscriptions.keys()
            total_after = len(self._subscriptions) + len(new_keys)
            if total_after > MAX_INSTRUMENTS_PER_CONNECTION:
                self.logger.error(
                    f"Cannot subscribe to {len(new_keys)} new instruments — "
                    f"would exceed {MAX_INSTRUMENTS_PER_CONNECTION} per-connection cap "
                    f"(currently {len(self._subscriptions)})"
                )
                return

            for segment, token in instruments:
                key = _topic_key(segment, token)
                self._subscriptions[key] = {
                    "mode": mode,
                    "is_index": is_index,
                    "oi": include_oi,
                    "segment": segment.lower(),
                    "token": str(token),
                }
                # Queue both feed and OI topics for sending in a batch.
                prefix = self._IDX_TOPIC_PREFIX if is_index else self._MW_TOPIC_PREFIX
                self._pending.append(prefix + key)
                if include_oi and not is_index:
                    self._pending.append(self._OI_TOPIC_PREFIX + key)

        if not self._sub_thread or not self._sub_thread.is_alive():
            self._sub_thread = threading.Thread(
                target=self._drain_pending, daemon=True, name="IiflSubscribeDrain"
            )
            self._sub_thread.start()

    def unsubscribe_instruments(self, instruments: list[tuple[str, str | int]]) -> None:
        """Send UNSUBSCRIBE for each (segment, token) and drop local state.

        Local state is cleared even when the socket is down — otherwise the
        next reconnect would re-subscribe to symbols the caller already
        dropped via _resubscribe_all(). The network UNSUBSCRIBE is best-
        effort and skipped when disconnected; the broker drops our
        subscriptions on reconnect anyway because we use clean_session=True.
        """
        if not instruments:
            return

        topics_to_drop: list[str] = []
        with self._lock:
            for segment, token in instruments:
                key = _topic_key(segment, token)
                sub = self._subscriptions.pop(key, None)
                self._oi_cache.pop(key, None)
                if sub is None:
                    continue
                prefix = self._IDX_TOPIC_PREFIX if sub["is_index"] else self._MW_TOPIC_PREFIX
                topics_to_drop.append(prefix + key)
                if sub.get("oi"):
                    topics_to_drop.append(self._OI_TOPIC_PREFIX + key)

        # Network UNSUBSCRIBE only when we have a live broker session. When
        # offline we have already updated local state above; the broker will
        # not redeliver these topics on reconnect (clean_session=True).
        if topics_to_drop and self._mqtt is not None and self.is_connected():
            try:
                self._mqtt.unsubscribe(topics_to_drop)
            except Exception as e:
                self.logger.exception(f"Unsubscribe failed: {e}")

    def _drain_pending(self) -> None:
        """Send queued subscribes in batches with light pacing."""
        consecutive_failures = 0
        while self._pending and self.running:
            if not self.is_connected():
                consecutive_failures += 1
                if consecutive_failures > 5:
                    self.logger.error(
                        "MQTT not connected — abandoning pending subscriptions"
                    )
                    with self._lock:
                        self._pending.clear()
                    break
                if self._stop_event.wait(min(2 * consecutive_failures, 10)):
                    break
                continue
            consecutive_failures = 0

            with self._lock:
                batch: list[str] = []
                while self._pending and len(batch) < MAX_TOKENS_PER_SUBSCRIBE:
                    batch.append(self._pending.popleft())

            if not batch:
                break

            try:
                self._mqtt.subscribe(batch, qos=0)
                self.logger.debug(f"Subscribed batch of {len(batch)} IIFL topics")
            except Exception as e:
                self.logger.exception(f"IIFL subscribe failed: {e}")
                # Re-queue and back off so we don't tight-loop on broker errors.
                with self._lock:
                    for t in batch:
                        self._pending.appendleft(t)
                if self._stop_event.wait(5):
                    break
                continue

            if self._pending and self._stop_event.wait(self.SUBSCRIPTION_DELAY):
                break

    def _resubscribe_all(self) -> None:
        """Rebuild MQTT-level subscriptions from local state after a reconnect."""
        with self._lock:
            if not self._subscriptions:
                return
            self._pending.clear()
            for key, sub in self._subscriptions.items():
                prefix = self._IDX_TOPIC_PREFIX if sub["is_index"] else self._MW_TOPIC_PREFIX
                self._pending.append(prefix + key)
                if sub.get("oi"):
                    self._pending.append(self._OI_TOPIC_PREFIX + key)

        if not self._sub_thread or not self._sub_thread.is_alive():
            self._sub_thread = threading.Thread(
                target=self._drain_pending, daemon=True, name="IiflSubscribeDrain"
            )
            self._sub_thread.start()

    # ----------------------------------------------------------------- callbacks
    def _on_mqtt_message(self, topic: str, payload: bytes) -> None:
        """
        Route an inbound PUBLISH to the right decoder. We accept three
        prefixes: market feed (mw/v1/), index feed (index/v1/), and open
        interest (oi/v1/). Anything else gets logged and dropped.
        """
        try:
            if topic.startswith(self._MW_TOPIC_PREFIX):
                key = topic[len(self._MW_TOPIC_PREFIX):]
                self._dispatch_feed(key, payload, is_index=False)
            elif topic.startswith(self._IDX_TOPIC_PREFIX):
                key = topic[len(self._IDX_TOPIC_PREFIX):]
                self._dispatch_feed(key, payload, is_index=True)
            elif topic.startswith(self._OI_TOPIC_PREFIX):
                key = topic[len(self._OI_TOPIC_PREFIX):]
                self._dispatch_oi(key, payload)
            else:
                self.logger.debug(f"Unhandled IIFL topic: {topic}")
        except Exception as e:
            self.logger.exception(f"Error handling IIFL message on {topic}: {e}")

    def _dispatch_feed(self, key: str, payload: bytes, is_index: bool) -> None:
        with self._lock:
            sub = self._subscriptions.get(key)
        if sub is None:
            # Late delivery for an instrument we just unsubscribed.
            return

        decoded = _decode_market_feed(payload)
        if decoded is None:
            self.logger.debug(f"Short IIFL market feed payload for {key}: {len(payload)} bytes")
            return

        # Merge cached OI into the tick if the user subscribed to OI on this
        # instrument. This keeps the consumer-facing payload self-contained.
        if sub.get("oi"):
            cached = self._oi_cache.get(key)
            if cached:
                decoded["open_interest"] = cached["open_interest"]
                decoded["oi"] = cached["open_interest"]
                decoded["day_high_oi"] = cached["day_high_oi"]
                decoded["day_low_oi"] = cached["day_low_oi"]
                decoded["previous_oi"] = cached["previous_oi"]

        # Attach routing fields the adapter needs for ZeroMQ topic generation.
        decoded["segment"] = sub["segment"]
        decoded["token"] = sub["token"]
        decoded["mode"] = sub["mode"]
        decoded["is_index"] = is_index

        if self.on_ticks:
            try:
                self.on_ticks([decoded])
            except Exception as e:
                self.logger.exception(f"on_ticks callback raised: {e}")

    def _dispatch_oi(self, key: str, payload: bytes) -> None:
        decoded = _decode_open_interest(payload)
        if decoded is None:
            return
        self._oi_cache[key] = decoded
        # We deliberately do not push an OI-only tick — OI is merged into the
        # next market-feed tick (which is publishing constantly during market
        # hours). This keeps the OpenAlgo proxy's mode set simple.

    def _on_mqtt_disconnect(self, _exc: Exception | None) -> None:
        was_connected = self.connected
        self.connected = False

        if self.on_disconnect:
            try:
                self.on_disconnect()
            except Exception as e:
                self.logger.exception(f"on_disconnect callback raised: {e}")

        # If we shut down deliberately, do nothing further.
        if not self.running or self._stop_event.is_set() or self._fatal_error:
            return

        if was_connected:
            self.logger.warning("IIFL Capital MQTT disconnected — scheduling reconnect")
            self._schedule_reconnect()

    def _on_mqtt_error(self, exc: Exception) -> None:
        self.logger.error(f"IIFL Capital MQTT error: {exc}")
        if self.on_error:
            try:
                self.on_error(exc)
            except Exception:
                pass

    # ----------------------------------------------------------------- reconnect
    def _schedule_reconnect(self) -> None:
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop, daemon=True, name="IiflReconnect"
        )
        self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        while self.running and not self._stop_event.is_set():
            self._reconnect_attempts += 1
            if self._reconnect_attempts > self.RECONNECT_MAX_TRIES:
                self.logger.error("IIFL reconnect attempts exhausted")
                self.running = False
                return

            delay = min(2 * (1.5 ** self._reconnect_attempts), self.RECONNECT_MAX_DELAY)
            self.logger.info(
                f"IIFL reconnect in {delay:.0f}s (attempt {self._reconnect_attempts})"
            )
            if self._stop_event.wait(delay):
                return

            # Re-check liveness *after* the backoff wakes. stop() can flip
            # `running` or set `_fatal_error` between the wait and the
            # connect call; without this guard we would open a new TLS
            # socket the caller is actively trying to tear down — leaking
            # both the FD and the reader/keepalive threads tied to it.
            if (
                not self.running
                or self._stop_event.is_set()
                or self._fatal_error
            ):
                return

            if self._do_connect():
                return
