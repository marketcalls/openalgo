"""Realtime broadcaster — pumps engine snapshots to the UI via Socket.IO.

Why a separate module from rms_engine: tick-rate UI updates would saturate
the event-bus thread pool (10 workers, but 500-2000 ticks/sec). Plan §5.3.1
splits the flow:

  Market tick (CRITICAL priority) → rms_engine
                                    ├─ updates registry state
                                    ├─ evaluates rules
                                    └─ persists changes
  Same tick   (LOW priority)      → realtime_broadcaster
                                    ├─ checks per-run debounce (200ms)
                                    ├─ snapshots engine state
                                    └─ socketio.emit room-scoped

Subscriber priority means the engine ALWAYS processes the tick first; the
broadcaster sees the post-evaluation state. Per-run debounce caps emission
rate at ~5Hz so even a chatty NIFTY-options strategy with 4 legs and 100
ticks/sec only emits 5 times per second per browser tab.

Health watcher: a separate background thread polls market_data_service's
is_trade_management_safe and emits strategy_health when the state flips
(safe → unsafe or vice versa). Browser banner reflects this so the user
knows when the engine pauses RMS evaluations.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from utils.logging import get_logger

logger = get_logger(__name__)


# Default debounce — 200ms means at most 5 frames/sec per active run per
# browser. Configurable via env if anyone wants smoother updates.
_DEBOUNCE_SEC = 0.20


# Health-watcher poll interval. The market_data_service updates its safety
# flag synchronously on tick reception, so 1Hz polling is fine.
_HEALTH_POLL_SEC = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strategy_room(strategy_id: int) -> str:
    return f"strategy_{int(strategy_id or 0)}"


def _ts_pair() -> tuple[int, str]:
    """(epoch_ms, IST display string) — see plan §6 timestamp policy."""
    from utils.ist_time import fmt_orderbook, now_utc, to_epoch_ms
    now = now_utc()
    return to_epoch_ms(now), fmt_orderbook(now)


# ---------------------------------------------------------------------------
# Broadcaster
# ---------------------------------------------------------------------------


class _RealtimeBroadcaster:
    """Singleton — see module docstring for design rationale."""

    def __init__(self):
        self._lock = threading.Lock()
        self._last_emit_ts: dict[int, float] = {}   # run_id -> monotonic time
        self._tick_subscriber_id: Optional[int] = None
        self._health_thread: Optional[threading.Thread] = None
        self._health_running = False
        self._last_safe_flag: Optional[bool] = None

    # ----- Tick subscription -----------------------------------------------

    def start(self) -> None:
        """Wire up the tick subscription + start the health watcher.

        Idempotent — safe to call on every app start. Lazy-imports the
        market_data_service so app boot doesn't force-load it.
        """
        from services.market_data_service import get_market_data_service, SubscriberPriority

        if self._tick_subscriber_id is not None:
            return

        mds = get_market_data_service()
        self._tick_subscriber_id = mds.subscribe_with_priority(
            priority=SubscriberPriority.LOW,
            event_type="all",        # we filter by symbol in _on_tick anyway
            callback=self._on_tick,
            filter_symbols=None,     # see all ticks; engine maintains the
                                     # symbol→run map we'll consult per tick
            name="strategy_v2_realtime_broadcaster",
        )
        logger.info(
            "realtime_broadcaster: subscribed (priority=LOW, debounce=%ss)",
            _DEBOUNCE_SEC,
        )

        # Health watcher — separate thread polls is_trade_management_safe.
        self._health_running = True
        self._health_thread = threading.Thread(
            target=self._health_loop,
            name="strategy_v2_health_watcher",
            daemon=True,
        )
        self._health_thread.start()

    def stop(self) -> None:
        """Tear down (test cleanup)."""
        self._health_running = False
        if self._tick_subscriber_id is not None:
            try:
                from services.market_data_service import get_market_data_service
                get_market_data_service().unsubscribe_priority(self._tick_subscriber_id)
            except Exception:
                logger.exception("realtime_broadcaster: unsubscribe failed")
            self._tick_subscriber_id = None
        with self._lock:
            self._last_emit_ts.clear()

    # ----- Tick callback ---------------------------------------------------

    def _on_tick(self, data: dict) -> None:
        """Fired on every tick. Identifies affected runs from the engine's
        symbol→runs index, debounces per-run, snapshots + emits.
        """
        try:
            symbol = data.get("symbol")
            exchange = data.get("exchange")
            if not symbol or not exchange:
                return

            from services.strategy.rms_engine import get_engine
            engine = get_engine()
            affected = engine.runs_for_symbol(exchange, symbol)
            if not affected:
                return

            now = time.monotonic()
            for run_id in affected:
                with self._lock:
                    last = self._last_emit_ts.get(run_id, 0.0)
                    if (now - last) < _DEBOUNCE_SEC:
                        continue
                    self._last_emit_ts[run_id] = now

                snap = engine.snapshot_run(run_id)
                if snap is None:
                    continue
                self._emit(snap)

        except Exception:
            # NEVER let exceptions propagate into market_data_service —
            # it would unsubscribe us. Mirror rms_engine pattern.
            logger.exception("realtime_broadcaster: tick callback failed")

    def _emit(self, snap: dict) -> None:
        """Emit room-scoped Socket.IO payloads from a snapshot.

        Two events:
          strategy_pnl_tick   — run-level aggregate (MTM, peak, drawdown)
          strategy_leg_update — per-leg LTP, SL distance, target distance, etc.
        """
        from extensions import socketio

        ts_utc, ts_ist = _ts_pair()
        strategy_id = snap.get("strategy_id", 0)
        run_id = snap.get("run_id", 0)
        room = _strategy_room(strategy_id)

        # Run-level aggregate
        socketio.emit(
            "strategy_pnl_tick",
            {
                "strategy_id": strategy_id,
                "run_id": run_id,
                "agg_mtm": snap.get("agg_mtm", 0.0),
                "peak_mtm": snap.get("peak_mtm", 0.0),
                "drawdown": snap.get("drawdown", 0.0),
                "profit_locked": snap.get("profit_locked", False),
                "leg_mtms": [
                    {"leg_id": leg.get("leg_id"), "mtm": leg.get("mtm", 0.0)}
                    for leg in snap.get("legs", [])
                ],
                "ts_utc": ts_utc,
                "ts_ist": ts_ist,
            },
            room=room,
        )

        # Per-leg detail (one event per leg keeps payload sizes predictable)
        for leg in snap.get("legs", []):
            socketio.emit(
                "strategy_leg_update",
                {
                    "strategy_id": strategy_id,
                    "run_id": run_id,
                    "leg_id": leg.get("leg_id"),
                    "symbol": leg.get("symbol"),
                    "exchange": leg.get("exchange"),
                    "ltp": leg.get("ltp"),
                    "mtm": leg.get("mtm", 0.0),
                    "current_sl_price": leg.get("current_sl_price"),
                    "sl_distance_pts": leg.get("sl_distance_pts"),
                    "target_distance_pts": leg.get("target_distance_pts"),
                    "next_trail_at_pts": leg.get("next_trail_at_pts"),
                    "trail_advances_count": leg.get("trail_advances_count", 0),
                    "trail_to_entry_armed": leg.get("trail_to_entry_armed", False),
                    "ts_utc": ts_utc,
                    "ts_ist": ts_ist,
                },
                room=room,
            )

    # ----- Health watcher --------------------------------------------------

    def _health_loop(self) -> None:
        """Background polling — when is_trade_management_safe transitions,
        emit a strategy_health event so the UI banner reflects state."""
        while self._health_running:
            try:
                time.sleep(_HEALTH_POLL_SEC)
                from services.market_data_service import get_market_data_service
                mds = get_market_data_service()
                safe, reason = mds.is_trade_management_safe()
                if self._last_safe_flag is None or safe != self._last_safe_flag:
                    self._last_safe_flag = safe
                    self._emit_health(safe, reason)
            except Exception:
                logger.exception("realtime_broadcaster: health loop iteration failed")

    def _emit_health(self, feed_safe: bool, reason: str) -> None:
        """Broadcast strategy_health to ALL strategy rooms — every browser
        tab on a strategy detail page shows the banner.

        This is a global emit (no room) since the user only has one feed.
        Frontend can filter / display per its own logic.
        """
        from extensions import socketio

        ts_utc, ts_ist = _ts_pair()
        socketio.emit(
            "strategy_health",
            {
                "feed_safe": feed_safe,
                # Keep order_channel_safe true for now — Phase 5 doesn't
                # ship the broker order-update channel; existing
                # OrderPlaced/Cancelled events handle that path.
                "order_channel_safe": True,
                "reason": reason,
                "ts_utc": ts_utc,
                "ts_ist": ts_ist,
            },
        )
        logger.info(
            "realtime_broadcaster: emitted strategy_health feed_safe=%s reason=%s",
            feed_safe, reason,
        )


# Module-level singleton
_broadcaster = _RealtimeBroadcaster()


def start_broadcaster() -> None:
    _broadcaster.start()


def stop_broadcaster() -> None:
    _broadcaster.stop()


def get_broadcaster() -> _RealtimeBroadcaster:
    """Test helper."""
    return _broadcaster
