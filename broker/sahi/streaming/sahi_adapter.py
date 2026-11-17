"""
Sahi market-data adapter for the OpenAlgo WebSocket proxy.

Multi-mode design: the Sahi stream holds ONE mode per instrument_id, while an
OpenAlgo client may hold LTP, QUOTE and DEPTH on the same symbol at once. The
adapter keeps, per instrument_id, the set of OpenAlgo modes requested and the
mode currently asked of Sahi (the highest requested). A higher tick serves
every lower topic (DepthTick -> DEPTH, QUOTE, LTP), so one broker
subscription fans out to all requested topics. Dropping the highest mode
downgrades the broker subscription with ModeChange; dropping the last mode
sends Unsubscribe.

Batching: subscribe() and unsubscribe() only change the adapter's state and
mark the instrument as changed. A short timer (BATCH_DELAY, the 0.5 s window
the angel, dhan and zerodha adapters use) then compares, for every changed
instrument, the mode Sahi holds with the mode wanted, and sends the
difference as grouped frames: Unsubscribe first, then one ModeChange and one
Subscribe per mode, each of at most 500 ids. An option chain that subscribes
200 symbols one call at a time costs a handful of frames instead of 200, and
a subscribe undone inside the window sends nothing.

The diff, the frames that express it and the full resubscribe on
(re)connect all run under one lock, so the server always ends up with the
state the adapter holds. The tick path never takes the lock.
"""

import time
from typing import Any

from database.auth_db import get_auth_token
from database.token_db import get_token
from utils import runtime as _runtime
from utils.logging import get_logger
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

from . import sahi_proto as pb
from .sahi_mapping import (
    DEPTH_LEVELS,
    OA_TO_SAHI_MODE,
    SahiCapabilityRegistry,
    SahiExchangeMapper,
    build_payloads,
)
from .sahi_websocket import SahiWebSocket

_real_threading = _runtime.original("threading")

# Ids per Subscribe/ModeChange/Unsubscribe frame (the connection cap is 1000).
_RESUBSCRIBE_CHUNK = 500

# Seconds subscription changes are collected before one grouped flush.
BATCH_DELAY = 0.5


def _chunks(ids: list[int]):
    for i in range(0, len(ids), _RESUBSCRIBE_CHUNK):
        yield ids[i : i + _RESUBSCRIBE_CHUNK]


class _Sub:
    """Subscription state for one instrument_id. ``modes`` is replaced, never
    mutated, so the tick thread can read it without the lock."""

    __slots__ = ("symbol", "exchange", "modes")

    def __init__(self, symbol: str, exchange: str):
        self.symbol = symbol
        self.exchange = exchange
        self.modes: frozenset[int] = frozenset()

    def wanted(self) -> int:
        """The Sahi mode to hold: the highest OpenAlgo mode requested."""
        return OA_TO_SAHI_MODE[max(self.modes)] if self.modes else 0


class SahiWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Sahi implementation of the OpenAlgo market-data adapter."""

    def __init__(self):
        super().__init__()
        self.logger = get_logger("sahi_websocket")
        self.broker_name = "sahi"
        self.user_id = None
        self.ws_client: SahiWebSocket | None = None
        self.running = False
        self.connected = False
        self.lock = _real_threading.Lock()
        self._subs: dict[int, _Sub] = {}  # instrument_id -> _Sub
        self._keys: dict[tuple[str, str], int] = {}  # (symbol, exchange) -> instrument_id
        # instrument_id -> Sahi mode the server holds on this connection.
        self._server: dict[int, int] = {}
        # Instruments whose wanted mode may differ from _server; flushed by the timer.
        self._dirty: set[int] = set()
        self._batch_timer = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, str] | None = None
    ) -> dict[str, Any]:
        try:
            if broker_name != self.broker_name:
                return {"status": "error", "message": f"Invalid broker name: {broker_name}"}
            self.user_id = user_id

            access_token = (auth_data or {}).get("auth_token")
            if not access_token:
                # bypass_cache: the proxy may run in its own process with a stale cache.
                access_token = get_auth_token(user_id, bypass_cache=True)
            if not access_token:
                return {"status": "error", "message": "Authentication token not found"}

            self.ws_client = SahiWebSocket(
                access_token=access_token,
                user_id=user_id,
                on_message=self._on_message,
                on_open=self._on_open,
                on_close=self._on_close,
            )
            self.logger.info(f"Sahi adapter initialized for user {user_id}")
            return {"status": "success", "message": "Adapter initialized successfully"}
        except Exception as e:
            self.logger.exception(f"Error initializing Sahi adapter: {e}")
            return {"status": "error", "message": str(e)}

    def connect(self) -> dict[str, Any]:
        if not self.ws_client:
            return {"status": "error", "message": "WebSocket client not initialized"}
        try:
            if self.running and self.ws_client.is_connected():
                return {"status": "success", "message": "Already connected"}
            self.ws_client.start()
            self.running = True
            if self.ws_client.wait_for_connection(timeout=15.0):
                self.connected = True
                return {"status": "success", "message": "Connected successfully"}
            if self.ws_client.fatal_error:
                self.running = False
                return {"status": "error", "message": self.ws_client.fatal_error}
            self.logger.warning("Sahi stream not connected yet; retrying in the background")
            return {"status": "success", "message": "Client started, connection in progress"}
        except Exception as e:
            self.logger.exception(f"Error connecting Sahi stream: {e}")
            return {"status": "error", "message": str(e)}

    def disconnect(self) -> dict[str, Any]:
        try:
            with self.lock:
                if self.ws_client:
                    self.ws_client.stop()
                    self.ws_client = None
                self.running = False
                self.connected = False
                # The timer thread must not fire after the socket is gone.
                self._cancel_batch_timer()
                self._subs.clear()
                self._keys.clear()
                self._server.clear()
                self._dirty.clear()
            self.cleanup_zmq()
            self.logger.info("Sahi stream disconnected")
            return {
                "status": "success",
                "message": "Disconnected successfully and resources cleaned up",
            }
        except Exception as e:
            self.logger.exception(f"Error disconnecting Sahi stream: {e}")
            try:
                self.cleanup_zmq()
            except Exception:
                self.logger.exception("Error cleaning up ZMQ during disconnect")
            return {"status": "error", "message": str(e)}

    def __del__(self):
        try:
            if self.ws_client:
                self.ws_client.stop()
        except Exception:
            pass
        try:
            self.cleanup_zmq()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def _send(self, frame: bytes) -> None:
        """Send if connected; otherwise the next on_open resubscribes from state."""
        client = self.ws_client
        if client is not None:
            client.send(frame)

    def subscribe(
        self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5
    ) -> dict[str, Any]:
        if mode not in OA_TO_SAHI_MODE:
            return self._create_error_response("INVALID_MODE", f"Invalid mode {mode}")
        if not SahiExchangeMapper.is_supported(exchange):
            return self._create_error_response(
                "UNSUPPORTED_EXCHANGE", f"Exchange {exchange} is not streamed by Sahi"
            )
        if not self.ws_client or not self.running:
            return {"status": "error", "message": "WebSocket not connected. Call connect() first."}

        try:
            token = get_token(symbol, exchange)
            if not token:
                return {"status": "error", "message": f"Token not found for {symbol} on {exchange}"}
            try:
                instrument_id = int(token)
            except (TypeError, ValueError):
                return {"status": "error", "message": f"Invalid token format for {symbol}"}

            with self.lock:
                sub = self._subs.get(instrument_id)
                if sub is None:
                    if len(self._subs) >= SahiCapabilityRegistry.MAX_INSTRUMENTS_PER_CONNECTION:
                        return self._create_error_response(
                            "MAX_SYMBOLS_REACHED",
                            "Sahi allows 1000 instruments per connection",
                        )
                    sub = _Sub(symbol, exchange)
                    self._subs[instrument_id] = sub
                    self._keys[(symbol, exchange)] = instrument_id
                sub.modes = sub.modes | {mode}
                self._mark_dirty(instrument_id)

            self.logger.info(f"Subscribed to {exchange}:{symbol} (mode {mode})")
            response = {
                "status": "success",
                "message": f"Subscribed to {symbol}",
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode,
            }
            if mode == 3:
                response["requested_depth"] = depth_level
                response["actual_depth"] = DEPTH_LEVELS
                response["is_fallback"] = depth_level != DEPTH_LEVELS
            return response
        except Exception as e:
            self.logger.exception(f"Error subscribing to {exchange}:{symbol}: {e}")
            return {"status": "error", "message": str(e)}

    def unsubscribe(self, symbol: str, exchange: str, mode: int | None = 2) -> dict[str, Any]:
        """Remove one mode (or every mode when mode is None) for a symbol."""
        try:
            with self.lock:
                instrument_id = self._keys.get((symbol, exchange))
                sub = self._subs.get(instrument_id) if instrument_id is not None else None
                if sub is None or (mode is not None and mode not in sub.modes):
                    return {"status": "error", "message": f"Not subscribed to {symbol}"}

                sub.modes = frozenset() if mode is None else sub.modes - {mode}
                if not sub.modes:
                    del self._subs[instrument_id]
                    del self._keys[(symbol, exchange)]
                self._mark_dirty(instrument_id)

            self.logger.info(
                f"Unsubscribed from {exchange}:{symbol}"
                f"{f' (mode {mode})' if mode is not None else ''}"
            )
            return {"status": "success", "message": f"Unsubscribed from {symbol}"}
        except Exception as e:
            self.logger.exception(f"Error unsubscribing from {exchange}:{symbol}: {e}")
            return {"status": "error", "message": str(e)}

    def unsubscribe_all(self) -> dict[str, Any]:
        try:
            with self.lock:
                ids = list(self._subs)
                self._subs.clear()
                self._keys.clear()
                # Everything the server holds goes now, in one pass, rather
                # than after the batch window.
                self._dirty.update(self._server)
                self._cancel_batch_timer()
                self._flush_locked()
            return {"status": "success", "message": f"Unsubscribed from {len(ids)} instruments"}
        except Exception as e:
            self.logger.exception(f"Error unsubscribing all: {e}")
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------
    # Batched flush
    # ------------------------------------------------------------------

    def _mark_dirty(self, instrument_id: int) -> None:
        """Queue one instrument for the next flush. Caller holds the lock.

        The first change of a window starts the timer and later ones do not
        restart it, so a steady stream of subscribes is still flushed every
        BATCH_DELAY seconds.
        """
        self._dirty.add(instrument_id)
        if self._batch_timer is None:
            timer = _real_threading.Timer(BATCH_DELAY, self._flush_pending)
            timer.daemon = True
            self._batch_timer = timer
            timer.start()

    def _cancel_batch_timer(self) -> None:
        """Caller holds the lock."""
        if self._batch_timer is not None:
            self._batch_timer.cancel()
            self._batch_timer = None

    def _flush_pending(self) -> None:
        """Timer callback: send the queued changes as grouped frames."""
        try:
            with self.lock:
                self._batch_timer = None
                self._flush_locked()
        except Exception:
            self.logger.exception("Error sending batched Sahi subscriptions")

    def _flush_locked(self) -> None:
        """Bring the server to the wanted mode of every changed instrument.

        Caller holds the lock. Unsubscribes go first, so the 1000-instrument
        connection cap is freed before new ids are added. While disconnected
        the sends fail quietly and on_open resends the whole state.
        """
        if not self._dirty:
            return
        dirty, self._dirty = self._dirty, set()
        removes: list[int] = []
        changes: dict[int, list[int]] = {}
        adds: dict[int, list[int]] = {}
        for instrument_id in dirty:
            sub = self._subs.get(instrument_id)
            wanted = sub.wanted() if sub is not None else 0
            held = self._server.get(instrument_id, 0)
            if wanted == held:
                continue  # undone inside the window, or already held
            if wanted == 0:
                removes.append(instrument_id)
                del self._server[instrument_id]
            elif held == 0:
                adds.setdefault(wanted, []).append(instrument_id)
                self._server[instrument_id] = wanted
            else:
                changes.setdefault(wanted, []).append(instrument_id)
                self._server[instrument_id] = wanted

        frames = [pb.encode_unsubscribe(ids) for ids in _chunks(sorted(removes))]
        for sahi_mode, ids in sorted(changes.items()):
            frames.extend(pb.encode_mode_change(sahi_mode, c) for c in _chunks(sorted(ids)))
        for sahi_mode, ids in sorted(adds.items()):
            frames.extend(pb.encode_subscribe(sahi_mode, c) for c in _chunks(sorted(ids)))
        for frame in frames:
            self._send(frame)
        if frames:
            self.logger.debug(
                f"Sahi batch: {len(removes)} unsubscribed, "
                f"{sum(map(len, changes.values()))} mode changes, "
                f"{sum(map(len, adds.values()))} subscribed, in {len(frames)} frame(s)"
            )

    def get_subscriptions(self) -> dict[str, Any]:
        with self.lock:
            subs = [
                f"{s.exchange}:{s.symbol}:{m}" for s in self._subs.values() for m in sorted(s.modes)
            ]
        return {"status": "success", "subscriptions": subs, "count": len(subs)}

    def is_connected(self) -> bool:
        return bool(self.ws_client and self.ws_client.is_connected())

    # ------------------------------------------------------------------
    # Connection callbacks (run on the SahiMarketWS thread)
    # ------------------------------------------------------------------

    def _on_open(self, client: SahiWebSocket) -> None:
        """Resend every Subscribe: Sahi subscription state is connection-local."""
        self.connected = True
        with self.lock:
            # The new connection holds nothing: send the whole wanted state,
            # which also settles every change still waiting for the timer.
            self._server.clear()
            self._dirty.clear()
            by_mode: dict[int, list[int]] = {}
            for instrument_id, sub in self._subs.items():
                wanted = sub.wanted()
                if wanted:
                    by_mode.setdefault(wanted, []).append(instrument_id)
                    self._server[instrument_id] = wanted
            for sahi_mode, ids in sorted(by_mode.items()):
                for chunk in _chunks(ids):
                    client.send(pb.encode_subscribe(sahi_mode, chunk))
            total = len(self._subs)
        if total:
            self.logger.info(f"Resubscribed {total} Sahi instruments after connect")

    def _on_close(self, code: int | None, reason: str) -> None:
        self.connected = False
        with self.lock:
            # Subscriptions are connection-local: the next connection holds nothing.
            self._server.clear()
        self.logger.warning(f"Sahi stream closed (code={code}, reason={reason})")

    # ------------------------------------------------------------------
    # Tick path (no lock)
    # ------------------------------------------------------------------

    def _on_message(self, data: bytes) -> None:
        try:
            kind, payload = pb.decode_server_message(data)
        except pb.ProtoDecodeError as e:
            self.logger.warning(f"Dropped malformed Sahi frame ({len(data)} bytes): {e}")
            return
        if kind is None:
            return
        if kind == pb.KIND_ERROR:
            self.logger.warning(
                f"Sahi stream error {payload.get('code')}: {payload.get('message')}"
            )
            return
        if kind == pb.KIND_ACK:
            self.logger.debug(
                f"Sahi ack action={payload['action']} ids={len(payload['instrument_ids'])}"
            )
            return
        self._handle_tick(kind, payload)

    def _handle_tick(self, kind: str, tick: dict) -> None:
        sub = self._subs.get(tick["instrument_id"])
        if sub is None:
            return  # late tick for an instrument just unsubscribed
        now_ms = int(time.time() * 1000)
        for topic, payload in build_payloads(
            kind, tick, sub.symbol, sub.exchange, sub.modes, now_ms
        ):
            self.publish_market_data(topic, payload)
