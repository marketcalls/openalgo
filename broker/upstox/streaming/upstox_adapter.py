# broker/upstox/streaming/upstox_adapter.py
"""
Upstox V3 WebSocket adapter implementation (synchronous).

Uses sync websocket-client (same as Angel/Dhan) to avoid asyncio event loop
conflicts with eventlet in gunicorn+eventlet deployments.
"""

import json
import threading
from typing import Any

from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

from .upstox_client import UpstoxWebSocketClient


class UpstoxWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    Upstox V3 WebSocket adapter implementation.

    Features:
    - Uses synchronous websocket-client (no asyncio event loop needed)
    - Processes protobuf messages decoded to dict format
    - Manages subscriptions and market data publishing
    - Compatible with eventlet/gunicorn deployments
    """

    # NOTE: there is deliberately no THREAD_JOIN_TIMEOUT here. Nothing in this
    # package joins a thread — join() under eventlet becomes a green wait that
    # raises Timeout (see UpstoxWebSocketClient.disconnect) — so a constant
    # advertising a join bound the code does not implement was only misleading.
    #
    # NOTE on Upstox V3 connection limits:
    #   Standard tier: 2 connections per user
    #   Plus tier:     5 connections per user
    # The pool size is driven by the MAX_WEBSOCKET_CONNECTIONS environment
    # variable in .env — set it to 2 if you are on Standard, or up to 5 on Plus.
    # Its generic default of 3 is ONE TOO MANY for a Standard account: the pool
    # happily builds a 3rd adapter, Upstox refuses it, and nothing about that is
    # obvious from this side (connect() returns success because the handshake runs
    # in a background thread), so UpstoxWebSocketClient names the cause explicitly
    # once a socket has failed to open several times in a row.
    #
    # The per-mode KEY caps from the same table live in UpstoxWebSocketClient
    # (MODE_KEY_LIMITS / MODE_COMBINED_LIMITS) and are enforced there, because
    # every subscribe — batched, replayed or direct — passes through its
    # subscribe(). See upstox-api-docs/21a-websocket-market-data-v3.md.

    def __init__(self):
        super().__init__()
        self.logger = get_logger("upstox_websocket")
        self.ws_client: UpstoxWebSocketClient | None = None
        self.user_id: str | None = None
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.market_status: dict[str, Any] = {}
        self.connected = False
        self.running = False
        self.lock = threading.Lock()

        # Batch subscription queue (mirrors Zerodha pattern).
        # Coalesces multiple subscribe() calls into one or two WS messages
        # (one per Upstox mode: ltpc / full) and naturally bridges the cold-
        # start race between connect() returning and _on_connect firing.
        self.subscription_queue: list[dict[str, Any]] = []
        self.batch_timer: threading.Timer | None = None
        self.batch_delay = 0.5  # seconds — long enough to absorb the WS handshake

        # Bumped by every teardown and by the handshake replay. A Timer stamps
        # the value it was armed with and refuses to act on a mismatch, which is
        # the only way to stop one that fired before cancel() could reach it.
        self._batch_generation = 0

        # Per-instrument merged snapshot, keyed by instrument key. Upstox V3
        # ticks are incremental: a packet carries only what changed (ltpc,
        # marketLevel, marketOHLC, atp, vtt, tbq/tsq, oi), and MessageToDict
        # drops proto3 defaults. Every tick is merged here and each payload is
        # built from the merged values, so a field the tick did not carry keeps
        # its last value and a field never sent is left out.
        self._snapshots: dict[str, dict[str, Any]] = {}

        # One-shot flag so a deeper-than-5 depth request reports its downgrade once
        # rather than on every symbol (see _get_upstox_mode for why it downgrades).
        self._depth_downgrade_warned = False

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Initialize the adapter with authentication data"""
        try:
            self.user_id = user_id
            auth_token = self._get_auth_token(auth_data, user_id)
            if not auth_token:
                return self._create_error_response("AUTH_ERROR", "No authentication token found")

            # initialize() is unconditional and callers do re-run it on an
            # existing adapter (websocket_proxy/server.py re-initializes one that
            # reported an error). Dropping the reference to a client whose
            # _run_websocket loop is alive would orphan its socket and its thread
            # permanently — the same unrecoverable leak connect() guards against,
            # through a different door — so stop the old one before replacing it.
            self._release_ws_client()

            # Pass user_id so the client can re-read a fresh bearer token from
            # the database on reconnect (tokens roll over daily at ~3 AM IST).
            self.ws_client = UpstoxWebSocketClient(auth_token, user_id=user_id)
            self._wire_callbacks()

            self.logger.debug("UpstoxWebSocketClient initialized successfully")
            return self._create_success_response("Initialized Upstox WebSocket adapter")

        except Exception as e:
            self.logger.error(f"Initialization error: {e}")
            return self._create_error_response("INIT_ERROR", str(e))

    def connect(self) -> dict[str, Any]:
        """Establish WebSocket connection"""
        try:
            if self.connected:
                return self._create_success_response("Already connected")

            if not self.ws_client:
                return self._create_error_response(
                    "NOT_INITIALIZED", "WebSocket client not initialized"
                )

            # `self.connected` goes False the moment the socket drops and the
            # client's backoff holds it there for up to 30s — the same window
            # subscribe() documents below. Without this second test a caller
            # landing in it starts a SECOND _run_websocket loop, which overwrites
            # the client's `ws` slot and orphans the first socket and thread
            # beyond any reach. The client refuses re-entry too; this keeps the
            # adapter's own flags honest and reports the truth to the caller.
            if self.ws_client.running:
                self.running = True
                return self._create_success_response("Connect already in progress")

            # A previous disconnect() released the ZMQ publisher (see
            # _ensure_zmq_publisher for why it has to). Restore it before the
            # feed starts, otherwise this connect reports success, opens a real
            # socket and burns an Upstox connection slot while every tick is
            # dropped into a closed publisher.
            self._ensure_zmq_publisher()
            self._wire_callbacks()

            success = self.ws_client.connect()

            if success:
                self.connected = True
                self.running = True
                self.logger.info("Connected to Upstox WebSocket")
                return self._create_success_response("Connected to Upstox WebSocket")
            else:
                return self._create_error_response(
                    "CONNECTION_FAILED", "Failed to connect to Upstox WebSocket"
                )

        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            return self._create_error_response("CONNECTION_ERROR", str(e))

    def subscribe(
        self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 0
    ) -> dict[str, Any]:
        """Subscribe to market data"""
        if mode not in [1, 2, 3]:
            return self._create_error_response(
                "INVALID_MODE", f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)"
            )

        if not self.ws_client:
            return self._create_error_response(
                "NOT_INITIALIZED", "WebSocket client not initialized"
            )

        # `self.connected` goes False the moment the socket drops, and the client's
        # backoff can hold it there for up to 30s. Rejecting during that window
        # would fail a subscribe that the existing replay machinery is already able
        # to honour: the subscription is recorded, and _on_connect re-issues
        # everything in self.subscriptions on the next handshake. So accept while
        # the client is still running (connected or reconnecting) and only refuse
        # once it has actually been stopped.
        if not (self.connected or self.ws_client.running):
            return self._create_error_response("NOT_CONNECTED", "WebSocket is not connected")

        if mode == 3 and depth_level > 5 and not self._depth_downgrade_warned:
            self._depth_downgrade_warned = True
            self.logger.warning(
                f"Depth {depth_level} requested; Upstox is served as 5-level `full` depth. "
                f"Upstox's 30-level feed (`full_d30`) is Plus-only and capped at 50 keys "
                f"per connection — see _get_upstox_mode."
            )

        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
            )

        instrument_key = self._create_instrument_key(token_info)
        correlation_id = f"{symbol}_{exchange}_{mode}"

        with self.lock:
            if correlation_id in self.subscriptions:
                self.logger.debug(f"Already subscribed to {symbol} on {exchange} with mode {mode}")
                return self._create_success_response(
                    f"Already subscribed to {symbol} on {exchange}"
                )

        subscription_info = {
            "symbol": symbol,
            "exchange": exchange,
            "mode": mode,
            "depth_level": depth_level,
            "token": token_info["token"],
            "instrument_key": instrument_key,
        }

        with self.lock:
            self.subscriptions[correlation_id] = subscription_info
            self.subscription_queue.append(subscription_info)
            self.logger.debug(f"Queued subscription: {correlation_id} -> {subscription_info}")

        # Defer the actual WS send by `batch_delay` seconds so multiple
        # subscribes coalesce into a single grouped-by-mode message. The
        # delay also bridges the cold-start race between connect() returning
        # and _on_connect firing — by the time the timer expires, the
        # handshake has typically completed. If it hasn't, _process_batch_
        # subscriptions defers; _on_connect will replay from self.subscriptions.
        self._start_batch_timer()

        return self._create_success_response(
            f"Subscription queued for {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
        )

    def _start_batch_timer(self) -> None:
        """Arm (or rearm) the batched-subscribe timer."""
        with self.lock:
            if self.batch_timer is not None:
                self.batch_timer.cancel()
            timer = threading.Timer(
                self.batch_delay,
                self._process_batch_subscriptions,
                args=(self._batch_generation,),
            )
            timer.daemon = True
            self.batch_timer = timer
            timer.start()

    def _process_batch_subscriptions(self, generation: int | None = None) -> None:
        """Drain the subscription queue and send one bulk-subscribe per mode.

        Upstox V3's `instrumentKeys` field accepts an array, so N symbols of
        the same mode collapse to a single message. Modes 2 and 3 both map
        to Upstox's `full` feed, so they coalesce into the same message.

        `generation` is the value `self._batch_generation` held when this timer
        was armed; every teardown bumps it. cancel() cannot stop a Timer that
        has already passed its cancel point, so the stamp is what keeps such a
        timer from acting against a torn-down adapter. It is None when the body
        is invoked directly rather than by a Timer, which always proceeds.
        """
        # Snapshot under lock — release before the WS send to avoid blocking
        # subsequent subscribe() calls during network I/O.
        with self.lock:
            # Clear the handle only if it is OURS. Clearing it unconditionally
            # let a timer that had passed its cancel point discard the handle to
            # whatever _start_batch_timer armed in the meantime, leaving that
            # newer timer invisible to every cancel path. A Timer IS its own
            # thread, so identity against current_thread() is the whole test.
            if self.batch_timer is threading.current_thread():
                self.batch_timer = None

            if generation is not None and generation != self._batch_generation:
                # Teardown (or a handshake replay) happened between this timer
                # firing and it reaching the lock. Whatever it was going to send
                # has already been dealt with by whoever bumped the generation.
                return

            queue = self.subscription_queue[:]
            self.subscription_queue.clear()

        if not queue:
            return

        # If the WS handshake hasn't completed, do nothing — _on_connect will
        # replay every recorded subscription from self.subscriptions (which
        # already includes everything we just dequeued).
        if not (self.ws_client and getattr(self.ws_client, "_connected", False)):
            # INFO, not DEBUG: if the socket never opens (the classic case being a
            # connection over the Upstox per-user limit), this line is the only
            # trace that a "successfully queued" subscription was never sent.
            self.logger.info(
                f"Batch deferred: WS not connected yet. {len(queue)} subscription(s) "
                f"will be sent from _on_connect."
            )
            return

        # Group instrument keys by Upstox mode string ("ltpc" or "full"). Upstox
        # holds one mode per key, so each key is sent at the highest mode any
        # live subscription needs: an ltpc subscribe never downgrades a key a
        # quote or depth subscriber holds in full.
        with self.lock:
            keys_by_mode = self._group_keys_by_mode(sub["instrument_key"] for sub in queue)

        for mode_str, instrument_keys in keys_by_mode.items():
            try:
                self.logger.info(
                    f"Batch subscribing {len(instrument_keys)} instrument(s) in {mode_str} mode"
                )
                self.ws_client.subscribe(instrument_keys, mode_str)
            except Exception as e:
                self.logger.error(f"Batch subscribe failed for mode {mode_str}: {e}")

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict[str, Any]:
        """Unsubscribe from market data"""
        try:
            if not self.ws_client:
                return self._create_error_response(
                    "NOT_INITIALIZED", "WebSocket client not initialized"
                )

            token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
            if not token_info:
                return self._create_error_response(
                    "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
                )

            instrument_key = self._create_instrument_key(token_info)
            correlation_id = f"{symbol}_{exchange}_{mode}"

            with self.lock:
                if correlation_id not in self.subscriptions:
                    self.logger.debug(f"Not subscribed to {symbol} on {exchange} with mode {mode}")
                    return self._create_success_response(
                        f"Not subscribed to {symbol} on {exchange}"
                    )

            # Another mode of the same instrument may still be subscribed. Upstox
            # unsubscribes a key for every mode at once, so the key stays on the
            # feed while any subscription needs it, re-sent at the highest mode
            # still needed when the one leaving was the only one needing `full`.
            with self.lock:
                before = self._needed_upstox_mode(instrument_key)
                sub_info = self.subscriptions.pop(correlation_id, None)
                after = self._needed_upstox_mode(instrument_key)

            if after is not None:
                if after != before and not self.ws_client.subscribe([instrument_key], after):
                    # The key is still held in the old mode: keep this
                    # subscription recorded so the state matches the feed and
                    # a retry can try the change again.
                    with self.lock:
                        if sub_info is not None:
                            self.subscriptions.setdefault(correlation_id, sub_info)
                    return self._create_error_response(
                        "UNSUBSCRIBE_FAILED",
                        f"Failed to change {symbol} on {exchange} to {after} mode",
                    )
                self.logger.info(
                    f"Unsubscribed {symbol} on {exchange} mode {mode}; "
                    f"{instrument_key} stays subscribed in {after} mode"
                )
                return self._create_success_response(f"Unsubscribed from {symbol} on {exchange}")

            success = self.ws_client.unsubscribe([instrument_key])

            if success:
                with self.lock:
                    self._snapshots.pop(instrument_key, None)
                self.logger.info(f"Unsubscribed from {symbol} on {exchange}")
                return self._create_success_response(f"Unsubscribed from {symbol} on {exchange}")
            else:
                # Keep the subscription recorded so a retry can unsubscribe again.
                with self.lock:
                    if sub_info is not None:
                        self.subscriptions.setdefault(correlation_id, sub_info)
                return self._create_error_response(
                    "UNSUBSCRIBE_FAILED", f"Failed to unsubscribe from {symbol} on {exchange}"
                )

        except Exception as e:
            self.logger.error(f"Unsubscribe error: {e}")
            return self._create_error_response("UNSUBSCRIBE_ERROR", str(e))

    def get_market_status(self) -> dict[str, Any]:
        """Return the last `marketInfo` snapshot as Upstox sent it.

        Shape: {"segmentStatus": {...}, "casMarketStatus": {...},
        "preOpenSessionStatus": {...}} — each map keyed by segment, and each
        only present once Upstox has sent it at least once.
        """
        return dict(self.market_status)

    def get_cas_phase(self, segment: str) -> str | None:
        """Current Closing Auction Session phase for a segment (e.g. "NSE_EQ").

        One of CTS_CLOSE (~15:15, continuous trading ends), CAS_LM_START (~15:20,
        auction opens to limit + market orders), CAS_M_STOP (~15:25, limit only),
        CAS_STOP (15:28-15:30, randomised end of order entry), or None when no
        CAS update has been received for that segment.
        """
        return self._phase_from_map("casMarketStatus", segment)

    def get_pre_open_phase(self, segment: str) -> str | None:
        """Current pre-open session phase for a segment, or None if unknown."""
        return self._phase_from_map("preOpenSessionStatus", segment)

    def _phase_from_map(self, map_name: str, segment: str) -> str | None:
        """Read StatusInfo.status out of one of the marketInfo status maps."""
        info = (self.market_status.get(map_name) or {}).get(segment)
        return info.get("status") if isinstance(info, dict) else None

    def disconnect(self) -> None:
        """Stop streaming and release every OS resource this adapter owns.

        The adapter stays REUSABLE: `ws_client` is kept and connect() will bring
        the feed and the ZMQ publisher back. Only cleanup() drops the client.

        This is the teardown path, not a half-measure. `.cleanup()` has no caller
        anywhere in the repository outside each broker's own destructor, and the
        destructor cannot run while the socket thread is alive because that
        thread reaches back to the adapter through the client's callbacks — so
        anything left for cleanup() to release would simply never be released.
        Everything that costs a descriptor is therefore released here.
        """
        try:
            self.running = False
            self.connected = False

            # Cancel any pending batch-subscribe timer so it doesn't fire
            # against a half-torn-down adapter, and bump the generation so one
            # that already slipped past its cancel point refuses to act.
            with self.lock:
                self._batch_generation += 1
                if self.batch_timer is not None:
                    self.batch_timer.cancel()
                    self.batch_timer = None

            if self.ws_client:
                try:
                    self.ws_client.disconnect()
                except Exception as e:
                    self.logger.warning(f"Error disconnecting WebSocket client: {e}")

            with self.lock:
                self.subscriptions.clear()
                self.subscription_queue.clear()
                self._snapshots.clear()

            self.cleanup_zmq()
            self.logger.info("Disconnected from Upstox WebSocket")

        except Exception as e:
            self.logger.error(f"Disconnect error: {e}")
        finally:
            self.running = False
            self.connected = False

    def cleanup(self) -> None:
        """Full teardown: stop streaming, then drop the client itself.

        A strict superset of disconnect(). The client reference is the only
        thing left for it to release, and a disconnected client holds no socket
        and no thread — which is what makes it safe that no caller invokes this.
        """
        try:
            self.disconnect()
        finally:
            self._release_ws_client()
            # Idempotent; only does anything if disconnect() failed before
            # reaching it.
            try:
                self.cleanup_zmq()
            except Exception as zmq_err:
                self.logger.error(f"Error cleaning up ZMQ during final cleanup attempt: {zmq_err}")
            self.logger.info("Upstox adapter cleaned up completely")

    # NOTE: no __del__ here on purpose. The base class already releases ZMQ from
    # its destructor, and an Upstox-specific one only added a garbage-collection-
    # time ws_client.disconnect() on an arbitrary thread — measured unreachable
    # in exactly the case it existed for (the socket thread holds a reference to
    # the adapter through the callbacks, so the adapter cannot be collected while
    # that thread lives). Teardown is deterministic: disconnect().

    # Private helper methods
    def _wire_callbacks(self) -> None:
        """Point the client's callbacks at this adapter."""
        if not self.ws_client:
            return
        self.ws_client.callbacks = {
            "on_connect": self._on_connect,
            "on_message": self._on_market_data,
            "on_error": self._on_error,
            "on_close": self._on_close,
        }

    def _release_ws_client(self) -> None:
        """Stop the current client, sever its callbacks and drop the reference.

        Severing matters as much as stopping: the callbacks are the edges that
        keep a replaced client able to write `connected = False` into an adapter
        that has since built a new one, and they are the reference cycle
        (adapter -> client -> bound method -> adapter) that keeps a dropped
        adapter alive until a gc pass.
        """
        client = self.ws_client
        if client is None:
            return
        self.ws_client = None
        try:
            client.disconnect()
        except Exception as e:
            self.logger.warning(f"Error stopping previous WebSocket client: {e}")
        finally:
            client.callbacks = dict.fromkeys(client.callbacks, None)

    def _ensure_zmq_publisher(self) -> None:
        """Re-create the ZMQ PUB socket if a previous disconnect() released it.

        disconnect() has to release it: nothing outside this package ever calls
        cleanup(), so leaving the release to cleanup()/__del__ would swap a
        dropped-tick bug for a ZMQ leak. Making the release reversible is the
        other half. Without this, a reconnected adapter returns success, opens a
        real socket, starts a real thread and holds one of the 2-or-5 Upstox
        per-user connection slots while every tick lands in a closed publisher
        and is logged away as "No ZMQ socket available for publishing".
        """
        if not getattr(self, "_zmq_cleaned_up", False):
            return

        # A pooled adapter publishes through the shared publisher, which
        # cleanup_zmq() deliberately leaves open — it only gave back the
        # instance count — so there is no socket to rebuild, just bookkeeping.
        if not getattr(self, "_uses_shared_zmq", False):
            self._initialize_shared_context()
            self.socket = self._create_socket()
            self.zmq_port = self._connect_to_zmq_bus()

        # Symmetric with the decrement cleanup_zmq() performed; without it the
        # count drifts down and a later cleanup could term() the shared context
        # out from under this socket.
        with self._context_lock:
            BaseBrokerWebSocketAdapter._instance_count += 1
        self._zmq_cleaned_up = False
        self.logger.info("ZMQ publisher re-established for adapter reuse")

    def _get_auth_token(self, auth_data: dict[str, Any] | None, user_id: str) -> str | None:
        """Get authentication token from auth_data or database"""
        if auth_data and "auth_token" in auth_data:
            return auth_data["auth_token"]
        return get_auth_token(user_id, bypass_cache=True)

    def _create_instrument_key(self, token_info: dict[str, Any]) -> str:
        """Create instrument key from token info"""
        token = token_info["token"]
        brexchange = token_info["brexchange"]
        if "|" in token:
            token = token.split("|")[-1]
        return f"{brexchange}|{token}"

    def _get_upstox_mode(self, mode: int, depth_level: int) -> str:
        """Convert internal mode to Upstox mode string.

        `depth_level` is deliberately NOT mapped onto Upstox's `full_d30`, and this
        is the mapping to get right before touching any cap:

        - OpenAlgo mode 3 (depth) maps to `full`, whose cap is 2000 keys. Capping
          depth subscriptions at `full_d30`'s 50 keys because "depth means d30"
          would throttle every depth feed to 1/40th of what Upstox allows.
        - `full_d30` is Plus-only, so emitting it for a Standard account would turn
          a working 5-level depth feed into a rejected subscription.
        - `_merge_feed` keeps 5 levels regardless, so `full_d30` would
          buy 30 levels of bandwidth and throw 25 of them away.

        A request for more than 5 levels is therefore served as 5 (reported once by
        subscribe()). If full_d30 is ever wired up, the client's MODE_KEY_LIMITS
        already carries its 50-key cap and enforcement follows automatically.
        """
        mode_map = {1: "ltpc", 2: "full", 3: "full"}
        return mode_map.get(mode, "ltpc")

    def _needed_upstox_mode(self, instrument_key: str) -> str | None:
        """Highest Upstox mode any live subscription needs for this key (caller holds lock)."""
        needed = None
        for sub in self.subscriptions.values():
            if sub.get("instrument_key") != instrument_key:
                continue
            mode_str = self._get_upstox_mode(sub["mode"], sub.get("depth_level", 0))
            if mode_str == "full":
                return "full"
            needed = mode_str
        return needed

    def _group_keys_by_mode(self, instrument_keys) -> dict[str, list[str]]:
        """Group keys by the Upstox mode each needs, de-duplicated (caller holds lock)."""
        keys_by_mode: dict[str, list[str]] = {}
        seen: set = set()
        for key in instrument_keys:
            if key in seen:
                continue
            seen.add(key)
            mode_str = self._needed_upstox_mode(key)
            if mode_str is not None:
                keys_by_mode.setdefault(mode_str, []).append(key)
        return keys_by_mode

    def _create_topic(self, exchange: str, symbol: str, mode: int) -> str:
        """Create ZMQ topic for publishing"""
        mode_map = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}
        mode_str = mode_map.get(mode, "QUOTE")
        return f"{exchange}_{symbol}_{mode_str}"

    # WebSocket event handlers (called synchronously by upstox_client)
    def _on_connect(self):
        """Callback when WebSocket connection is opened.

        Handles both the initial cold start (subscriptions queued before the
        handshake completed) and reconnects (subscriptions need re-issuing).
        Sends one bulk message per Upstox mode regardless of how many
        symbols are involved.
        """
        self.logger.info("Upstox WebSocket connection opened")
        self.connected = True

        # Drain the pending queue (subscribes that arrived before handshake)
        # and merge with the persistent record; on reconnect, queue is empty
        # but self.subscriptions still has every active subscription.
        with self.lock:
            self._batch_generation += 1
            if self.batch_timer is not None:
                self.batch_timer.cancel()
                self.batch_timer = None
            self.subscription_queue.clear()
            all_subs = list(self.subscriptions.values())

        if not all_subs or not self.ws_client:
            return

        with self.lock:
            keys_by_mode = self._group_keys_by_mode(sub["instrument_key"] for sub in all_subs)

        for mode_str, instrument_keys in keys_by_mode.items():
            try:
                self.logger.info(
                    f"Replaying {len(instrument_keys)} subscription(s) in {mode_str} mode "
                    f"after WS handshake"
                )
                self.ws_client.subscribe(instrument_keys, mode_str)
            except Exception as e:
                self.logger.error(f"Replay subscribe failed for mode {mode_str}: {e}")

    def _on_error(self, error: str):
        """Handle WebSocket errors"""
        self.logger.error(f"WebSocket error: {error}")
        self.connected = False

    def _on_close(self):
        """Handle WebSocket closure"""
        self.logger.info("WebSocket connection closed")
        self.connected = False

    def _on_market_data(self, data: dict[str, Any]):
        """Handle market data messages"""
        try:
            if data.get("type") == "market_info":
                self._handle_market_info(data)
                return

            feeds = data.get("feeds", {})
            if not feeds:
                self.logger.debug(f"No feeds in market data: {list(data.keys())}")
                return

            self.logger.debug(f"Processing {len(feeds)} feed(s): {list(feeds.keys())}")

            current_ts = data.get("currentTs", 0)

            for feed_key, feed_data in feeds.items():
                self._process_feed(feed_key, feed_data, current_ts)

        except Exception as e:
            self.logger.error(f"Market data handler error: {e}")

    def _handle_market_info(self, data: dict[str, Any]):
        """Handle market info messages.

        `marketInfo` carries three maps keyed by segment ("NSE_EQ", "NSE_FO", ...):
        `segmentStatus` (the MarketStatus enum), plus `casMarketStatus` and
        `preOpenSessionStatus` (StatusInfo: status + updatedTime), both added by
        Upstox on 2026-09-04. Upstox sends only the map that changed, so a CAS
        phase transition arrives with `casMarketStatus` alone — merge per map
        instead of replacing wholesale, otherwise the segmentStatus already
        learned is dropped the first time a CAS update lands.
        """
        market_info = data.get("marketInfo")
        if not market_info:
            return

        previous = {
            key: dict(self.market_status.get(key) or {})
            for key in ("casMarketStatus", "preOpenSessionStatus")
        }

        for key, incoming in market_info.items():
            existing = self.market_status.get(key)
            if isinstance(incoming, dict) and isinstance(existing, dict):
                merged = dict(existing)
                merged.update(incoming)
                self.market_status[key] = merged
            else:
                self.market_status[key] = incoming

        if "segmentStatus" in market_info:
            self.logger.debug(f"Market status update: {self.market_status['segmentStatus']}")

        # The CAS phases (CTS_CLOSE -> CAS_LM_START -> CAS_M_STOP -> CAS_STOP) are
        # NOT part of the MarketStatus enum — they only ever arrive through these
        # StatusInfo maps, which is why the maps exist. Log a genuine transition at
        # INFO (a handful per session, and repeats of an unchanged phase stay
        # silent) so the current auction phase is visible without a debug build.
        for key in ("casMarketStatus", "preOpenSessionStatus"):
            for segment, info in (market_info.get(key) or {}).items():
                if not isinstance(info, dict):
                    continue
                status = info.get("status")
                if status and status != (previous[key].get(segment) or {}).get("status"):
                    self.logger.info(f"{key} {segment}: {status}")

    def _process_feed(self, feed_key: str, feed_data: dict[str, Any], current_ts: int):
        """Process individual feed data"""
        try:
            matching_subscriptions = []
            with self.lock:
                for correlation_id, sub_info in self.subscriptions.items():
                    if sub_info.get("instrument_key") == feed_key:
                        matching_subscriptions.append((correlation_id, sub_info))
                    elif "|" in feed_key:
                        token = feed_key.split("|")[-1]
                        if sub_info.get("token") == token or sub_info.get("token") == feed_key:
                            matching_subscriptions.append((correlation_id, sub_info))

            if not matching_subscriptions:
                self.logger.warning(f"No subscription found for feed key: {feed_key}")
                return

            # Merge the tick once per instrument, then build each subscriber's
            # payload from the merged snapshot.
            instrument_key = matching_subscriptions[0][1].get("instrument_key", feed_key)
            snapshot = self._merge_feed(instrument_key, feed_data)

            for _correlation_id, sub_info in matching_subscriptions:
                symbol = sub_info["symbol"]
                exchange = sub_info["exchange"]
                mode = sub_info["mode"]

                topic = self._create_topic(exchange, symbol, mode)
                market_data = self._build_payload(feed_data, snapshot, sub_info, current_ts)

                if market_data:
                    self.logger.debug(
                        f"Publishing {symbol}.{exchange} mode={mode} topic={topic} "
                        f"ltp={market_data.get('ltp', 'N/A')}"
                    )
                    self.publish_market_data(topic, market_data)

        except Exception as e:
            self.logger.error(f"Error processing feed for {feed_key}: {e}")

    @staticmethod
    def _full_feed_body(feed_data: dict[str, Any]) -> dict[str, Any]:
        """The MarketFullFeed or IndexFullFeed dict of a tick, or {}."""
        full_feed = feed_data.get("fullFeed") or {}
        return full_feed.get("marketFF") or full_feed.get("indexFF") or {}

    def _merge_feed(self, instrument_key: str, feed_data: dict[str, Any]) -> dict[str, Any]:
        """Merge one tick into the instrument's snapshot and return a copy of it."""
        updates: dict[str, Any] = {}

        ltpc = self._extract_tick_ltpc(feed_data)
        if "ltp" in ltpc:
            updates["ltp"] = float(ltpc["ltp"])
        if "ltq" in ltpc:
            updates["ltq"] = int(ltpc["ltq"])
        if "ltt" in ltpc:
            updates["ltt"] = int(ltpc["ltt"])
        if "cp" in ltpc:
            # LTPC.cp is the previous day's close (21a-websocket-market-data-v3.md).
            updates["cp"] = float(ltpc["cp"])

        ff = self._full_feed_body(feed_data)
        # Only the day candle carries the session's OHLC. The other entries
        # (e.g. I1) are intraday candles and must never stand in for it.
        for candle in (ff.get("marketOHLC") or {}).get("ohlc") or []:
            if candle.get("interval") != "1d":
                continue
            for key in ("open", "high", "low"):
                if key in candle:
                    updates[key] = float(candle[key])
            if "vol" in candle:
                updates["day_candle_volume"] = int(candle["vol"])
            break

        if "vtt" in ff:
            updates["vtt"] = int(ff["vtt"])
        if "atp" in ff:
            updates["average_price"] = float(ff["atp"])
        if "tbq" in ff:
            updates["total_buy_quantity"] = int(float(ff["tbq"]))
        if "tsq" in ff:
            updates["total_sell_quantity"] = int(float(ff["tsq"]))
        if "oi" in ff:
            updates["oi"] = float(ff["oi"])

        market_level = ff.get("marketLevel")
        if isinstance(market_level, dict) and "bidAskQuote" in market_level:
            buy_levels = []
            sell_levels = []
            for level in market_level.get("bidAskQuote") or []:
                bid_price = float(level.get("bidP", 0))
                if bid_price > 0:
                    buy_levels.append(
                        {"price": bid_price, "quantity": int(float(level.get("bidQ", 0)))}
                    )
                ask_price = float(level.get("askP", 0))
                if ask_price > 0:
                    sell_levels.append(
                        {"price": ask_price, "quantity": int(float(level.get("askQ", 0)))}
                    )
            updates["buy"] = sorted(buy_levels, key=lambda x: x["price"], reverse=True)[:5]
            updates["sell"] = sorted(sell_levels, key=lambda x: x["price"])[:5]

        with self.lock:
            snapshot = self._snapshots.setdefault(instrument_key, {})
            snapshot.update(updates)
            return dict(snapshot)

    @staticmethod
    def _quote_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
        """Quote fields under OpenAlgo's names; only those Upstox has sent."""
        out: dict[str, Any] = {}
        if "ltp" in snapshot:
            out["ltp"] = snapshot["ltp"]
        for key in ("open", "high", "low"):
            if key in snapshot:
                out[key] = snapshot[key]
        if "cp" in snapshot:
            out["close"] = snapshot["cp"]
        if "ltq" in snapshot:
            out["last_trade_quantity"] = snapshot["ltq"]
            out["last_quantity"] = snapshot["ltq"]
        if "vtt" in snapshot:
            out["volume"] = snapshot["vtt"]
        elif "day_candle_volume" in snapshot:
            out["volume"] = snapshot["day_candle_volume"]
        for key in ("average_price", "total_buy_quantity", "total_sell_quantity", "oi"):
            if key in snapshot:
                out[key] = snapshot[key]
        if "ltt" in snapshot:
            out["ltt"] = snapshot["ltt"]
            out["last_trade_time"] = snapshot["ltt"]
        return out

    def _build_payload(
        self,
        feed_data: dict[str, Any],
        snapshot: dict[str, Any],
        sub_info: dict[str, Any],
        current_ts: Any,
    ) -> dict[str, Any]:
        """Build the payload for one subscription from the merged snapshot."""
        if not snapshot:
            return {}
        mode = sub_info["mode"]
        result: dict[str, Any] = {
            "symbol": sub_info["symbol"],
            "exchange": sub_info["exchange"],
            "token": sub_info["token"],
        }

        if mode == 1:
            for key in ("ltp", "ltq", "ltt", "cp"):
                if key in snapshot:
                    result[key] = snapshot[key]
            # The indicative equilibrium price is valid only for the tick that
            # carried it, so it comes from this tick and is never cached.
            iep = self._read_optional_double(self._extract_tick_ltpc(feed_data).get("iep"))
            if iep is not None:
                result["indicative_equilibrium_price"] = iep
            return result

        if mode not in (2, 3):
            return {}

        result.update(self._quote_fields(snapshot))
        if current_ts:
            result["timestamp"] = int(current_ts)
        # Additive CAS/pre-open extras, from this tick only.
        ff = self._full_feed_body(feed_data)
        if ff:
            result.update(self._extract_cas_fields(ff))

        if mode == 3:
            depth: dict[str, Any] = {
                "buy": list(snapshot.get("buy", [])),
                "sell": list(snapshot.get("sell", [])),
            }
            if current_ts:
                depth["timestamp"] = int(current_ts)
            result["depth"] = depth
        return result

    def _extract_tick_ltpc(self, feed_data: dict[str, Any]) -> dict[str, Any]:
        """Pull LTPC from a Feed protobuf-as-dict regardless of which oneof
        branch it was sent under (`Feed.ltpc` for mode=ltpc, or
        `Feed.fullFeed.{marketFF|indexFF}.ltpc` for mode=full).
        """
        if "ltpc" in feed_data and isinstance(feed_data["ltpc"], dict):
            return feed_data["ltpc"]
        full_feed = feed_data.get("fullFeed") or {}
        ff = full_feed.get("marketFF") or full_feed.get("indexFF") or {}
        ltpc = ff.get("ltpc") or {}
        return ltpc if isinstance(ltpc, dict) else {}

    @staticmethod
    def _read_optional_double(value: Any) -> float | None:
        """Read a possibly-absent double out of a protobuf-as-dict.

        Returns None when the field was not on the wire, so callers can omit the
        key rather than publish a misleading 0.0.

        `LTPC.iep` is a `google.protobuf.DoubleValue` **wrapper**, i.e. it has
        explicit presence. `MessageToDict` walks `ListFields()`, which yields a
        message field only when `HasField()` is true, and flattens a wrapper to
        its bare `.value` — so key-presence here is exactly `HasField('iep')`
        and `value` is exactly `.value` (an explicit 0.0 IS emitted, which is the
        point of the wrapper). The dict form {"value": <double>} is accepted too
        so a differently-configured json_format cannot silently drop the field.
        """
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get("value")
            if value is None:
                return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _extract_cas_fields(self, ff: dict[str, Any]) -> dict[str, Any]:
        """Extract the Closing Auction Session / pre-open extras from a
        MarketFullFeed-as-dict (added by Upstox on 2026-09-04).

        Every one of these is additive and only populated while a pre-open or
        closing auction is actually running. Outside an auction window Upstox
        leaves them at their proto3 defaults and `MessageToDict` (default
        options) omits defaulted scalars entirely, so this returns an empty dict
        and the published payload is exactly what subscribers already receive.

        Absent fields are deliberately NOT defaulted to 0/0.0/False: during an
        auction a real zero is meaningful, so a synthetic one would be
        indistinguishable from "no auction running".
        """
        cas: dict[str, Any] = {}

        # iep arrives either on the full feed (MarketFullFeed.iep, a plain
        # double) or on the nested LTPC (a presence-tracked DoubleValue wrapper).
        iep = self._read_optional_double(ff.get("iep"))
        if iep is None:
            iep = self._read_optional_double((ff.get("ltpc") or {}).get("iep"))
        if iep is not None:
            cas["indicative_equilibrium_price"] = iep

        if "rp" in ff:
            cas["reference_price"] = float(ff["rp"])
        if "ieq" in ff:
            cas["indicative_equilibrium_quantity"] = int(ff["ieq"])
        # iiqTotal is a SIGNED net imbalance — negative means more sell than buy
        # quantity is left unmatched at the IEP. json_format renders int64 as a
        # string, and int() on "-4200" keeps the sign: never abs() or cast this
        # unsigned, the direction of the imbalance is the whole signal.
        if "iiqTotal" in ff:
            cas["indicative_imbalance_quantity_total"] = int(ff["iiqTotal"])
        if "iiqM" in ff:
            cas["indicative_imbalance_quantity_market"] = int(ff["iiqM"])
        if "casEligible" in ff:
            cas["cas_eligible"] = bool(ff["casEligible"])

        return cas
