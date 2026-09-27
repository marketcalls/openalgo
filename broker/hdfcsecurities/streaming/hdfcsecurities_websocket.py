"""HDFC Securities InvestRight market-data WebSocket client.

Uses sync `websocket-client` in a daemon thread (NOT asyncio) so it stays
compatible with gunicorn + eventlet. Implements the same resilience patterns as
the Zerodha/Arrow clients:
  - JSON heartbeat ({"heart_beat": true}) plus a data-stall watchdog
  - automatic reconnection with interruptible exponential backoff
  - bounded auth-refresh on token failure (re-reads a fresh token from the DB
    for the ~3 AM IST daily rollover) instead of dying until a restart
  - resubscribe-on-reconnect
  - daemon threads are never join()ed (eventlet raises Timeout on join)

Protocol (docs: "Market Data - WebSocket"):
  - endpoint  <host>/wsapi/v1/session
  - subscribe / unsubscribe is ONE JSON text frame carrying both arrays:
        {"heart_beat": false,
         "subscribe":   [{"scripId": "NSE_2885", "type": "ALL"}],
         "unSubscribe": [{"scripId": "BSE_1",    "type": "LTP"}]}
    Note the capital S in "unSubscribe" -- the server ignores "unsubscribe".
  - heartbeat is its own frame: {"heart_beat": true}
  - inbound frames are protobuf `GenericDTOList` (see hdfcsecurities_market.proto).
    `packetType` selects which sub-message is populated: mbpData for cash /
    F&O / currency / commodity packets, indexData for NSE_INDEX / BSE_INDEX,
    greekData for the option-greek packets, and HEARTBEAT frames carry
    nothing else. The *_CIRC and *_OI packet types reuse mbpData for a PARTIAL
    refresh (band or open interest only), so they are tagged `kind` "circuit" /
    "oi" and never presented as a full quote.
"""

import json
import ssl
import sys
import threading
import time
from collections import deque
from collections.abc import Callable

import websocket
from google.protobuf.message import DecodeError

from broker.hdfcsecurities.api.baseurl import USER_AGENT, get_ws_url
from broker.hdfcsecurities.streaming import hdfcsecurities_market_pb2 as pb
from broker.hdfcsecurities.streaming.hdfcsecurities_mapping import HDFCSecuritiesCapabilityRegistry
from database.auth_db import get_auth_token
from utils.logging import get_logger

logger = get_logger(__name__)

if "eventlet" in sys.modules:
    import eventlet

    _real_threading = eventlet.patcher.original("threading")
else:
    _real_threading = threading

# packetType values that carry an MBPData payload, resolved from the generated
# enum so a proto update cannot silently desync these lists.
#
# All three groups use `mbpData`, but only the *_ALL group populates it fully.
# The CIRC and OI packets are partial refreshes that leave every other field at
# its proto3 default -- a circuit packet therefore reads as lastTradedPrice 0,
# volume 0, empty book. They must never be handed on as a complete quote, so
# they are tagged separately and the adapter merges them into the last full
# snapshot instead of replacing it.
_QUOTE_PACKET_TYPES = frozenset(
    getattr(pb, name)
    for name in ("NSE_CM_ALL", "NSE_CD_ALL", "NSE_FO_ALL", "BSE_CM", "BSE_FO_ALL", "MCX_PKT")
)
_CIRCUIT_PACKET_TYPES = frozenset((pb.NSE_CM_CIRC, pb.NSE_CD_CIRC, pb.NSE_FO_CIRC))
_OI_PACKET_TYPES = frozenset((pb.NSE_CD_OI, pb.NSE_FO_OI, pb.BSE_FO_OI))

_INDEX_PACKET_TYPES = frozenset((pb.NSE_INDEX, pb.BSE_INDEX))
_GREEK_PACKET_TYPES = frozenset((pb.NSE_FO_GREEK, pb.BSE_FO_GREEK))

# packetType -> OpenAlgo exchange. `instrumentId` is only unique WITHIN an
# exchange: 840 tokens in the live security master appear on more than one
# OpenAlgo exchange (836 NSE/CDS pairs alone, plus BSE_INDEX SENSEX sharing
# token 1 with an NSE scrip). The packet type is the only thing on the wire
# that disambiguates them, so every tick carries the exchange it resolves to
# and the adapter keys its subscription state on (exchange, token).
_PACKET_TYPE_EXCHANGE = {
    pb.NSE_CM_ALL: "NSE",
    pb.NSE_CM_CIRC: "NSE",
    pb.NSE_CD_ALL: "CDS",
    pb.NSE_CD_CIRC: "CDS",
    pb.NSE_CD_OI: "CDS",
    pb.NSE_FO_ALL: "NFO",
    pb.NSE_FO_CIRC: "NFO",
    pb.NSE_FO_OI: "NFO",
    pb.NSE_FO_GREEK: "NFO",
    pb.BSE_CM: "BSE",
    pb.BSE_FO_ALL: "BFO",
    pb.BSE_FO_OI: "BFO",
    pb.BSE_FO_GREEK: "BFO",
    pb.MCX_PKT: "MCX",
    pb.NSE_INDEX: "NSE_INDEX",
    pb.BSE_INDEX: "BSE_INDEX",
}


class HDFCSecuritiesWebSocket:
    """Sync WebSocket client for HDFC Securities's market-data stream."""

    HEARTBEAT_INTERVAL = 10
    DATA_TIMEOUT = 90  # force reconnect after this long without a frame

    MAX_INSTRUMENTS_PER_CONNECTION = HDFCSecuritiesCapabilityRegistry.MAX_INSTRUMENTS_PER_CONNECTION
    MAX_SCRIPS_PER_SUBSCRIBE = 100
    SUBSCRIPTION_DELAY = 0.3
    # Brief window to let a burst of per-symbol subscribe() calls (the proxy
    # subscribes an option chain one symbol at a time) pile up before draining,
    # so they coalesce into as few frames as possible.
    SUBSCRIPTION_COLLECT_DELAY = 0.2

    RECONNECT_BASE_DELAY = 5
    RECONNECT_MAX_DELAY = 60
    RECONNECT_MAX_TRIES = 50

    def __init__(self, access_token, on_ticks=None, user_id=None):
        self.access_token = access_token
        self.on_ticks: Callable | None = on_ticks
        # user_id lets reconnect re-read a fresh token after the daily rollover.
        self.user_id = user_id

        self.ws: websocket.WebSocketApp | None = None
        self.connected = False
        self.running = False
        self.logger = logger
        self.lock = _real_threading.Lock()

        # Subscription state, keyed by scripId ("NSE_2885").
        self.subscribed: dict[str, str] = {}  # scripId -> subscription type SENT
        # scripId -> subscription type WANTED. Written the moment a subscribe
        # is queued and cleared the moment an unsubscribe is issued, so a frame
        # that was queued before an unsubscribe cannot resubscribe the
        # instrument when the drain reaches it.
        self.desired: dict[str, str] = {}
        self.pending_subscriptions: deque = deque()
        self._subscription_thread: threading.Thread | None = None

        # Connection / health.
        self.reconnect_attempts = 0
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

        # Optional external callbacks.
        self.on_connect: Callable | None = None
        self.on_disconnect: Callable | None = None
        self.on_error: Callable | None = None

        self.logger.info("HDFC Securities WebSocket client initialized (sync)")

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
            target=self._run_websocket, daemon=True, name="HDFCSecuritiesWS"
        )
        self._ws_thread.start()
        self.logger.info("HDFC Securities WebSocket client started")
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
            self.logger.debug("HDFC Securities WebSocket client stopped")
        except Exception as e:
            self.logger.error(f"Error stopping WebSocket client: {e}")

    def _refresh_access_token(self):
        """Re-read a fresh token from the DB (bypassing cache).
        Returns True if it changed (worth retrying)."""
        if not self.user_id:
            return False
        try:
            token = get_auth_token(self.user_id, bypass_cache=True)
            if not token:
                self.logger.warning("No fresh auth token on reconnect - keeping existing")
                return False
            with self.lock:
                changed = token != self.access_token
                self.access_token = token
            self.logger.info("Refreshed HDFC Securities access token from DB for reconnect")
            return changed
        except Exception as e:
            self.logger.error(f"Error refreshing access token: {e}")
            return False

    def _run_websocket(self):
        while self.running and not self._stop_event.is_set():
            try:
                self.ws = websocket.WebSocketApp(
                    get_ws_url(self.access_token),
                    header={
                        "Authorization": self.access_token,
                        "User-Agent": USER_AGENT,
                    },
                    on_open=self._on_ws_open,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_ws_close,
                )
                # CERT_REQUIRED: the access token rides in the URL and the
                # headers, so accepting arbitrary certificates would hand it to
                # any MITM.
                self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_REQUIRED})
            except Exception as e:
                self.logger.error(f"WebSocket run_forever error: {e}")

            self.connected = False
            if not self.running or self._stop_event.is_set():
                break

            # Auth/token failure: refresh from the DB and retry a bounded
            # number of times rather than dying until a process restart.
            if self._fatal_error:
                if self._auth_refresh_retries >= self._max_auth_refresh_retries:
                    self.logger.error(
                        f"Stopping HDFC Securities WS - auth failure persisted after "
                        f"{self._max_auth_refresh_retries} refreshes. {self._fatal_error_message}"
                    )
                    self.running = False
                    break
                self._auth_refresh_retries += 1
                if not self._refresh_access_token():
                    self.logger.error(
                        "Stopping HDFC Securities WS - auth failure and DB token unchanged; "
                        "needs re-login."
                    )
                    self.running = False
                    break
                self._fatal_error = False
                self._fatal_error_message = ""
                if self._stop_event.wait(self.RECONNECT_BASE_DELAY):
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
            self._refresh_access_token()

        self.logger.info("HDFC Securities WebSocket thread exited")

    # --- subscription ---------------------------------------------------

    def subscribe_scrips(self, scrip_ids, subscription_type="ALL"):
        if not self.running:
            self.logger.error("WebSocket client not running. Call start() first.")
            return
        scrip_ids = [s for s in scrip_ids if s]
        if not scrip_ids:
            return

        if len(self.subscribed) + len(scrip_ids) > self.MAX_INSTRUMENTS_PER_CONNECTION:
            self.logger.error(
                f"Subscription would exceed HDFC Securities's per-connection limit of "
                f"{self.MAX_INSTRUMENTS_PER_CONNECTION} instruments."
            )
            return

        with self.lock:
            for scrip_id in scrip_ids:
                self.desired[scrip_id] = subscription_type
                self.pending_subscriptions.append((scrip_id, subscription_type))

        if not self._subscription_thread or not self._subscription_thread.is_alive():
            self._subscription_thread = _real_threading.Thread(
                target=self._process_pending_subscriptions, daemon=True
            )
            self._subscription_thread.start()

    def _requeue(self, frames):
        """Put unsent (type, scrip_ids) frames back on the pending queue so a
        connection drop mid-drain never loses a subscription."""
        with self.lock:
            for sub_type, scrip_ids in frames:
                for scrip_id in scrip_ids:
                    self.pending_subscriptions.append((scrip_id, sub_type))

    def _process_pending_subscriptions(self):
        while self.pending_subscriptions and self.running:
            if not self.connected:
                # Wait for the (re)connection rather than dropping the queue --
                # the drain resumes once the feed is back, and stop() ends the
                # wait. Anything queued is also in `desired`, so the reconnect
                # replay covers it even if this loop is torn down first.
                if self._stop_event.wait(1.0):
                    return
                continue

            # Let the burst finish arriving, then drain everything queued and
            # group by subscription type so each type goes out in as few frames
            # as possible regardless of the order it was queued in.
            if self._stop_event.wait(self.SUBSCRIPTION_COLLECT_DELAY):
                return
            with self.lock:
                by_type = {}
                while self.pending_subscriptions:
                    scrip_id, sub_type = self.pending_subscriptions.popleft()
                    by_type.setdefault(sub_type, []).append(scrip_id)

            frames = [
                (sub_type, scrip_ids[start : start + self.MAX_SCRIPS_PER_SUBSCRIBE])
                for sub_type, scrip_ids in by_type.items()
                for start in range(0, len(scrip_ids), self.MAX_SCRIPS_PER_SUBSCRIBE)
            ]

            for index, (sub_type, batch) in enumerate(frames):
                # Space multi-frame sends so a large chain does not flood the
                # server; requeue the remainder if we are told to stop mid-send.
                if index and self._stop_event.wait(self.SUBSCRIPTION_DELAY):
                    self._requeue(frames[index:])
                    return
                if not self._send_subscribe(batch, sub_type):
                    # Send failed (connection likely dropped): requeue this frame
                    # and everything after it, then loop back to wait for reconnect.
                    self._requeue(frames[index:])
                    break

    def _send_subscribe(self, scrip_ids, subscription_type):
        try:
            if not self.connected or not self.ws:
                return False
            with self.lock:
                # Drop anything unsubscribed, or re-queued at another tier,
                # since this frame was built. Without this a mode downgrade
                # followed immediately by a full unsubscribe would leave the
                # instrument live at the broker after OpenAlgo dropped it.
                scrip_ids = [
                    scrip_id
                    for scrip_id in scrip_ids
                    if self.desired.get(scrip_id) == subscription_type
                ]
            if not scrip_ids:
                return True
            message = {
                "heart_beat": False,
                "subscribe": [
                    {"scripId": scrip_id, "type": subscription_type} for scrip_id in scrip_ids
                ],
            }
            self.ws.send(json.dumps(message))
            with self.lock:
                for scrip_id in scrip_ids:
                    self.subscribed[scrip_id] = subscription_type
            self.logger.debug(f"Subscribed {len(scrip_ids)} scrips as {subscription_type}")
            return True
        except Exception as e:
            self.logger.error(f"Subscribe failed: {e}")
            return False

    def unsubscribe(self, scrip_ids):
        try:
            if not self.ws:
                return False
            wanted = {scrip_id for scrip_id in scrip_ids if scrip_id}
            with self.lock:
                # Retract ALL local state before sending, in one step. The
                # frame can fail, and state split across a failure is what
                # resurrects an instrument: leaving it in `subscribed` while
                # `desired` has dropped it means the reconnect replay puts it
                # back. Purge queued frames for the same reason.
                payload = [
                    {
                        "scripId": scrip_id,
                        "type": self.subscribed.get(scrip_id, self.desired.get(scrip_id, "ALL")),
                    }
                    for scrip_id in scrip_ids
                    if scrip_id
                ]
                for scrip_id in wanted:
                    self.desired.pop(scrip_id, None)
                    self.subscribed.pop(scrip_id, None)
                if wanted:
                    self.pending_subscriptions = deque(
                        item for item in self.pending_subscriptions if item[0] not in wanted
                    )
            if not payload:
                return True
            if self.connected:
                # Capital S: the documented key is "unSubscribe".
                self.ws.send(json.dumps({"heart_beat": False, "unSubscribe": payload}))
            return True
        except Exception as e:
            # State is already retracted, so a failed frame cannot resurrect
            # the instrument: the reconnect replay works off `desired`, and a
            # send failure here means the socket is on its way down anyway --
            # the broker drops the whole subscription set with it.
            self.logger.error(f"Error unsubscribing: {e}")
            return False

    def wait_for_connection(self, timeout=15.0):
        return self._connection_ready.wait(timeout=timeout)

    def is_connected(self):
        return self.connected and self.running

    def _resubscribe_all(self):
        """Replay the WANTED subscription set after a reconnect.

        `desired` is the authority, not `subscribed`: replaying what was last
        successfully sent would resurrect an instrument whose unSubscribe frame
        failed, and would miss one whose subscribe frame never got out.
        """
        with self.lock:
            if not self.desired:
                return
            by_type: dict[str, list[str]] = {}
            for scrip_id, sub_type in self.desired.items():
                by_type.setdefault(sub_type, []).append(scrip_id)
        for sub_type, scrip_ids in by_type.items():
            for start in range(0, len(scrip_ids), self.MAX_SCRIPS_PER_SUBSCRIBE):
                batch = scrip_ids[start : start + self.MAX_SCRIPS_PER_SUBSCRIBE]
                try:
                    self.ws.send(
                        json.dumps(
                            {
                                "heart_beat": False,
                                "subscribe": [{"scripId": s, "type": sub_type} for s in batch],
                            }
                        )
                    )
                    with self.lock:
                        # Keep `subscribed` (what was sent) in step with
                        # `desired` (what is wanted) after a replay.
                        for scrip_id in batch:
                            self.subscribed[scrip_id] = sub_type
                    if self._stop_event.wait(self.SUBSCRIPTION_DELAY):
                        return
                except Exception as e:
                    self.logger.error(f"Error re-subscribing batch: {e}")

    # --- callbacks ------------------------------------------------------

    def _on_ws_open(self, ws):
        self.connected = True
        self.reconnect_attempts = 0
        self._auth_refresh_retries = 0
        self.last_message_time = time.time()
        self._connection_ready.set()
        self.logger.info("HDFC Securities WebSocket connected")
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
                ticks = self._parse_frame(message)
                if ticks and self.on_ticks:
                    try:
                        self.on_ticks(ticks)
                    except Exception as e:
                        self.logger.error(f"on_ticks callback error: {e}")
            elif isinstance(message, str):
                # Text frames are acks / errors.
                try:
                    data = json.loads(message)
                    if str(data.get("status", "")).lower() in ("error", "failure"):
                        self.logger.error(f"HDFC Securities WS message: {data}")
                        if self._is_fatal_auth_error(message):
                            self._mark_fatal_error(message)
                    else:
                        self.logger.debug(f"HDFC Securities WS text: {data}")
                except json.JSONDecodeError:
                    self.logger.debug(f"Non-JSON text: {message[:100]}")
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    _AUTH_FAILURE_INDICATORS = (
        "401",
        "403",
        "unauthorized",
        "unauthorised",
        "forbidden",
        "invalid token",
        "token expired",
        "session expired",
        "invalid api_key",
    )

    def _is_fatal_auth_error(self, payload):
        if payload is None:
            return False
        text = str(payload).lower()
        return any(indicator in text for indicator in self._AUTH_FAILURE_INDICATORS)

    def _mark_fatal_error(self, message):
        if self._fatal_error:
            return
        self._fatal_error = True
        self._fatal_error_message = str(message)
        self.logger.error(f"Auth/token failure - will refresh and retry. {message}")

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
            if self._stop_event.wait(self.HEARTBEAT_INTERVAL):
                break
            if not self.running or not self.connected:
                break
            try:
                if self.ws:
                    self.ws.send(json.dumps({"heart_beat": True}))
            except Exception as e:
                self.logger.debug(f"Heartbeat send failed: {e}")
            if (
                self.last_message_time
                and (time.time() - self.last_message_time) > self.DATA_TIMEOUT
            ):
                self.logger.error("Data stall detected - forcing reconnect")
                if self.ws:
                    try:
                        self.ws.close()
                    except Exception:
                        pass
                break

    # --- protobuf parsing -----------------------------------------------

    def _parse_frame(self, payload: bytes) -> list:
        """Decode one binary frame into normalized tick dicts.

        Frames are `GenericDTOList`. Some deployments send a bare `GenericDTO`,
        so that shape is accepted as a fallback -- both are cheap to try and
        the wire formats are unambiguous enough that a wrong guess raises
        rather than producing plausible garbage.
        """
        try:
            envelope = pb.GenericDTOList()
            envelope.ParseFromString(payload)
            packets = list(envelope.genericDTOList)
            if not packets:
                single = pb.GenericDTO()
                single.ParseFromString(payload)
                packets = [single]
        except DecodeError:
            try:
                single = pb.GenericDTO()
                single.ParseFromString(payload)
                packets = [single]
            except DecodeError as e:
                self.logger.error(f"Could not decode HDFC Securities frame ({len(payload)}B): {e}")
                return []

        ticks = []
        for packet in packets:
            tick = self._parse_packet(packet)
            if tick:
                ticks.append(tick)
        return ticks

    def _parse_packet(self, packet) -> dict | None:
        packet_type = packet.packetType
        if packet_type == pb.HEARTBEAT:
            return None

        token = int(packet.instrumentId or 0)
        if not token:
            return None

        # packetTimestamp is in milliseconds when the server sets it.
        timestamp = int(packet.packetTimestamp) or int(time.time() * 1000)
        tick = {
            "token": token,
            "timestamp": timestamp,
            "packet_type": packet_type,
            # None for packet types the map does not cover; the adapter then
            # falls back to a unique-token lookup rather than guessing.
            "exchange": _PACKET_TYPE_EXCHANGE.get(packet_type),
        }

        if packet_type in _INDEX_PACKET_TYPES:
            index = packet.indexData
            tick.update(
                {
                    "kind": "index",
                    "ltp": index.indexValue,
                    "last_price": index.indexValue,
                    "open": index.openingIndex,
                    "high": index.highIndexValue,
                    "low": index.lowIndexValue,
                    "close": index.closingIndex,
                    "volume": 0,
                }
            )
            if index.packetTimeStamp:
                tick["timestamp"] = int(index.packetTimeStamp)
            return tick

        if packet_type in _GREEK_PACKET_TYPES:
            greek = packet.greekData
            tick.update(
                {
                    "kind": "greek",
                    "delta": greek.delta,
                    "gamma": greek.gamma,
                    "vega": greek.vega,
                    "theta": greek.theta,
                    "rho": greek.rho,
                }
            )
            return tick

        if packet_type in _CIRCUIT_PACKET_TYPES:
            # Circuit refresh: only the band moved. Everything else on the
            # message is a proto3 default and must not overwrite live values.
            mbp = packet.mbpData
            tick.update(
                {
                    "kind": "circuit",
                    "lower_limit": mbp.lowerCircuitLimit,
                    "upper_limit": mbp.upperCircuitLimit,
                }
            )
            return tick

        if packet_type in _OI_PACKET_TYPES:
            tick.update({"kind": "oi", "oi": packet.mbpData.oi})
            return tick

        if packet_type in _QUOTE_PACKET_TYPES or packet.HasField("mbpData"):
            mbp = packet.mbpData
            tick.update(
                {
                    "kind": "mbp",
                    "ltp": mbp.lastTradedPrice,
                    "last_price": mbp.lastTradedPrice,
                    "open": mbp.openPrice,
                    "high": mbp.highPrice,
                    "low": mbp.lowPrice,
                    "close": mbp.closingPrice,
                    "volume": mbp.volumeTradedToday,
                    "ltq": mbp.lastTradeQuantity,
                    "average_price": mbp.averageTradePrice,
                    "total_buy_quantity": mbp.totalBuyQuantity,
                    "total_sell_quantity": mbp.totalSellQuantity,
                    "oi": mbp.oi,
                    "lower_limit": mbp.lowerCircuitLimit,
                    "upper_limit": mbp.upperCircuitLimit,
                }
            )
            if mbp.lastTradeTime:
                tick["ltt"] = int(mbp.lastTradeTime)

            buy, sell = [], []
            for level in mbp.marketDepthDTOList.marketDepthDTO:
                entry = {
                    "price": level.price,
                    "quantity": level.quantity,
                    "orders": level.numberOfOrders,
                }
                (buy if level.buyFlag else sell).append(entry)
            if buy or sell:
                tick["depth"] = {"buy": buy[:5], "sell": sell[:5]}
            return tick

        self.logger.debug(f"Ignoring HDFC Securities packet type {packet_type}")
        return None
