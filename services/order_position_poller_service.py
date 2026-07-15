"""
Broker-agnostic order/trade/position poller.

One instance is pooled per {broker}_{user_id} broker session (mirroring
websocket_proxy/broker_factory.py's market-data adapter pooling) and
serves every browser tab/device sharing that session. It diffs each
poll cycle's orderbook/tradebook/positions against the previous
snapshot and returns only what changed, normalized and stamped with a
per-cycle generation and canonical in-cycle sequence
(orders -> trades -> positions).

Polling cadence adapts between MODE_NORMAL and MODE_FAST: order
placement/modification/cancellation should call enter_fast_mode()
directly (see services/order_router_service.py) rather than relying on
this class to discover activity by polling faster speculatively - the
broker REST rate-limit budget is shared with actual trading calls, so
fast mode is a temporary state, not a standing one.

Fetch functions and the clock are injected so the diff engine and state
machine are fully unit-testable without a live broker connection, a
thread, or a wall-clock sleep - see test/test_order_position_poller_service.py.
"""

import threading
import time
from collections.abc import Callable
from typing import Any

from services.order_event_normalizer import (
    build_trade_id,
    normalize_order_event,
    normalize_position_event,
    normalize_trade_event,
)
from utils.logging import get_logger

logger = get_logger(__name__)

MODE_NORMAL = "normal"
MODE_FAST = "fast"

DEFAULT_ORDER_POLL_NORMAL_MS = 750
DEFAULT_ORDER_POLL_FAST_MS = 250
DEFAULT_TRADE_POLL_NORMAL_MS = 750
DEFAULT_TRADE_POLL_FAST_MS = 250
DEFAULT_POSITION_POLL_MS = 1000
DEFAULT_FAST_MODE_TIMEOUT_SEC = 30

# Order statuses that mean the poller should keep watching closely.
_NON_TERMINAL_ORDER_STATUSES = {"open", "trigger pending", "partially filled", "pending"}


def _order_key(order: dict[str, Any]) -> str:
    return str(order.get("orderid", ""))


def _position_key(position: dict[str, Any]) -> tuple[str, str, str]:
    return (position.get("symbol", ""), position.get("exchange", ""), position.get("product", ""))


class OrderPositionPoller:
    def __init__(
        self,
        broker: str,
        user_id: str,
        fetch_orders: Callable[[], list[dict[str, Any]]],
        fetch_trades: Callable[[], list[dict[str, Any]]],
        fetch_positions: Callable[[], list[dict[str, Any]]],
        order_poll_normal_ms: int = DEFAULT_ORDER_POLL_NORMAL_MS,
        order_poll_fast_ms: int = DEFAULT_ORDER_POLL_FAST_MS,
        trade_poll_normal_ms: int = DEFAULT_TRADE_POLL_NORMAL_MS,
        trade_poll_fast_ms: int = DEFAULT_TRADE_POLL_FAST_MS,
        position_poll_ms: int = DEFAULT_POSITION_POLL_MS,
        fast_mode_timeout_sec: int = DEFAULT_FAST_MODE_TIMEOUT_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.broker = broker
        self.user_id = user_id
        self._fetch_orders = fetch_orders
        self._fetch_trades = fetch_trades
        self._fetch_positions = fetch_positions

        self.order_poll_normal_ms = order_poll_normal_ms
        self.order_poll_fast_ms = order_poll_fast_ms
        self.trade_poll_normal_ms = trade_poll_normal_ms
        self.trade_poll_fast_ms = trade_poll_fast_ms
        self.position_poll_ms = position_poll_ms
        self.fast_mode_timeout_sec = fast_mode_timeout_sec
        self._clock = clock

        self.mode = MODE_NORMAL
        self._fast_mode_entered_at: float | None = None

        self._last_orders: dict[str, dict[str, Any]] = {}
        self._last_trades: dict[str, dict[str, Any]] = {}
        self._last_positions: dict[tuple[str, str, str], dict[str, Any]] = {}

        self.generation = 0

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ---- state machine -----------------------------------------------

    def enter_fast_mode(self) -> None:
        """Called by order_router_service right after a place/modify/
        cancel call, so the poller never has to guess that something
        changed."""
        self.mode = MODE_FAST
        self._fast_mode_entered_at = self._clock()

    def _maybe_exit_fast_mode(self, orders_snapshot: dict[str, dict[str, Any]]) -> None:
        if self.mode != MODE_FAST:
            return

        has_non_terminal_order = any(
            order.get("order_status", "").lower() in _NON_TERMINAL_ORDER_STATUSES
            for order in orders_snapshot.values()
        )
        timed_out = (
            self._fast_mode_entered_at is not None
            and (self._clock() - self._fast_mode_entered_at) >= self.fast_mode_timeout_sec
        )

        if not has_non_terminal_order or timed_out:
            self.mode = MODE_NORMAL
            self._fast_mode_entered_at = None

    @property
    def order_poll_interval_ms(self) -> int:
        return self.order_poll_fast_ms if self.mode == MODE_FAST else self.order_poll_normal_ms

    @property
    def trade_poll_interval_ms(self) -> int:
        return self.trade_poll_fast_ms if self.mode == MODE_FAST else self.trade_poll_normal_ms

    # ---- diff engine ----------------------------------------------------

    def poll_once(self) -> list[dict[str, Any]]:
        """Run one poll cycle: fetch, diff against the last snapshot,
        normalize, and return only what changed - in canonical order
        (orders, then trades, then positions). Advances self.generation
        and updates the snapshots regardless of whether anything
        changed."""
        self.generation += 1
        sequence = 0
        events: list[dict[str, Any]] = []

        current_orders = {_order_key(order): order for order in self._fetch_orders()}
        for key, order in current_orders.items():
            if self._last_orders.get(key) != order:
                events.append(normalize_order_event(order, self.generation, sequence))
                sequence += 1

        current_trades = {build_trade_id(trade): trade for trade in self._fetch_trades()}
        for key, trade in current_trades.items():
            if key not in self._last_trades:
                events.append(normalize_trade_event(trade, self.generation, sequence))
                sequence += 1

        current_positions = {_position_key(pos): pos for pos in self._fetch_positions()}
        for key, position in current_positions.items():
            if self._last_positions.get(key) != position:
                events.append(normalize_position_event(position, self.generation, sequence))
                sequence += 1

        self._last_orders = current_orders
        self._last_trades = current_trades
        self._last_positions = current_positions

        self._maybe_exit_fast_mode(current_orders)

        return events

    def get_last_snapshot(self) -> dict[str, Any]:
        """Full current state, used to bring a newly subscribed or
        reconnected client up to date before it starts receiving
        deltas."""
        return {
            "generation": self.generation,
            "orders": list(self._last_orders.values()),
            "trades": list(self._last_trades.values()),
            "positions": list(self._last_positions.values()),
        }

    # ---- lifecycle -------------------------------------------------------

    def start(self, on_events: Callable[[list[dict[str, Any]]], None]) -> None:
        """Start the background poll loop. on_events is called with
        whatever poll_once() returns after every cycle (including empty
        lists) so the caller can decide how to publish them - this class
        has no knowledge of ZeroMQ or WebSockets."""
        if self._thread is not None:
            return

        self._stop_event.clear()

        def _loop() -> None:
            while not self._stop_event.is_set():
                try:
                    events = self.poll_once()
                    if events:
                        on_events(events)
                except Exception:
                    logger.exception(
                        f"Error polling orders/positions for {self.broker}_{self.user_id}"
                    )
                interval_ms = min(self.order_poll_interval_ms, self.position_poll_ms)
                self._stop_event.wait(interval_ms / 1000)

        self._thread = threading.Thread(
            target=_loop, name=f"order-poller-{self.broker}-{self.user_id}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None


# ---- module-level registry --------------------------------------------
#
# One poller per {broker}_{user_id} broker session, mirroring
# websocket_proxy/broker_factory.py's _POOLED_ADAPTERS - every browser
# tab/device belonging to the same user shares the same poller instead of
# each starting its own. order_router_service / the order-event
# subscribers look the poller up by (broker, user_id) to call
# enter_fast_mode() without needing a direct reference to it.

_POLLER_REGISTRY: dict[tuple[str, str], OrderPositionPoller] = {}
_REGISTRY_LOCK = threading.Lock()


def register_poller(poller: OrderPositionPoller) -> None:
    with _REGISTRY_LOCK:
        _POLLER_REGISTRY[(poller.broker, poller.user_id)] = poller


def unregister_poller(broker: str, user_id: str) -> OrderPositionPoller | None:
    with _REGISTRY_LOCK:
        return _POLLER_REGISTRY.pop((broker, user_id), None)


def get_poller(broker: str, user_id: str) -> OrderPositionPoller | None:
    with _REGISTRY_LOCK:
        return _POLLER_REGISTRY.get((broker, user_id))


def trigger_fast_mode(broker: str, user_id: str) -> None:
    """No-op if no poller is registered for this session (e.g. analyze/
    sandbox mode, or the poller hasn't started yet) - callers should not
    have to check existence themselves."""
    poller = get_poller(broker, user_id)
    if poller is not None:
        poller.enter_fast_mode()
