"""
Tests for services.order_position_poller_service.OrderPositionPoller.

Exercises the diff engine and fast/normal state machine in isolation -
fetch_orders/fetch_trades/fetch_positions and the clock are injected so
no real broker call, thread, or wall-clock sleep is involved.
"""

import threading
import time

import pytest

from services.order_position_poller_service import (
    MODE_FAST,
    MODE_NORMAL,
    OrderPositionPoller,
    get_poller,
    register_poller,
    trigger_fast_mode,
    unregister_poller,
)


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_poller(orders=None, trades=None, positions=None, clock=None, **kwargs):
    orders = orders if orders is not None else []
    trades = trades if trades is not None else []
    positions = positions if positions is not None else []

    return OrderPositionPoller(
        broker="zerodha",
        user_id="user1",
        fetch_orders=lambda: orders,
        fetch_trades=lambda: trades,
        fetch_positions=lambda: positions,
        clock=clock or FakeClock(),
        **kwargs,
    )


ORDER_OPEN = {
    "orderid": "1",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 10,
    "price": 825.5,
    "product": "MIS",
    "pricetype": "LIMIT",
    "order_status": "open",
    "timestamp": "t1",
}

ORDER_COMPLETE = {**ORDER_OPEN, "order_status": "complete"}

TRADE_1 = {
    "orderid": "1",
    "symbol": "SBIN",
    "exchange": "NSE",
    "product": "MIS",
    "action": "BUY",
    "quantity": 10,
    "average_price": 825.5,
    "trade_value": 8255.0,
    "timestamp": "t1",
}

POSITION_1 = {
    "symbol": "SBIN",
    "exchange": "NSE",
    "product": "MIS",
    "quantity": 10,
    "average_price": 825.5,
    "ltp": 826.0,
    "pnl": 5.0,
}


class TestInitialState:
    def test_starts_in_normal_mode(self):
        poller = make_poller()
        assert poller.mode == MODE_NORMAL

    def test_generation_starts_at_zero(self):
        poller = make_poller()
        assert poller.generation == 0


class TestOrderDiffing:
    def test_emits_order_update_for_new_order(self):
        poller = make_poller(orders=[ORDER_OPEN])

        events = poller.poll_once()

        assert len(events) == 1
        assert events[0]["event_type"] == "order_update"
        assert events[0]["orderid"] == "1"
        assert events[0]["status"] == "open"

    def test_does_not_reemit_unchanged_order_on_next_poll(self):
        poller = make_poller(orders=[ORDER_OPEN])
        poller.poll_once()

        events = poller.poll_once()

        assert events == []

    def test_emits_order_update_when_status_changes(self):
        seen_orders = [ORDER_OPEN]
        poller = OrderPositionPoller(
            broker="zerodha",
            user_id="user1",
            fetch_orders=lambda: seen_orders,
            fetch_trades=lambda: [],
            fetch_positions=lambda: [],
            clock=FakeClock(),
        )
        poller.poll_once()

        seen_orders[0] = ORDER_COMPLETE
        events = poller.poll_once()

        assert len(events) == 1
        assert events[0]["status"] == "complete"


class TestTradeDiffing:
    def test_emits_trade_update_for_new_fill(self):
        poller = make_poller(trades=[TRADE_1])

        events = poller.poll_once()

        assert len(events) == 1
        assert events[0]["event_type"] == "trade_update"
        assert events[0]["fill_quantity"] == 10

    def test_does_not_reemit_same_fill_on_next_poll(self):
        poller = make_poller(trades=[TRADE_1])
        poller.poll_once()

        events = poller.poll_once()

        assert events == []

    def test_partial_then_full_fill_are_distinct_events(self):
        trades = [TRADE_1]
        poller = OrderPositionPoller(
            broker="zerodha",
            user_id="user1",
            fetch_orders=lambda: [],
            fetch_trades=lambda: trades,
            fetch_positions=lambda: [],
            clock=FakeClock(),
        )
        poller.poll_once()

        second_fill = {**TRADE_1, "quantity": 5, "average_price": 826.0, "timestamp": "t2"}
        trades.append(second_fill)
        events = poller.poll_once()

        assert len(events) == 1
        assert events[0]["fill_quantity"] == 5


class TestPositionDiffing:
    def test_emits_position_update_for_new_position(self):
        poller = make_poller(positions=[POSITION_1])

        events = poller.poll_once()

        assert len(events) == 1
        assert events[0]["event_type"] == "position_update"
        assert events[0]["net_quantity"] == 10

    def test_does_not_reemit_unchanged_position(self):
        poller = make_poller(positions=[POSITION_1])
        poller.poll_once()

        events = poller.poll_once()

        assert events == []

    def test_emits_position_update_when_pnl_changes(self):
        positions = [POSITION_1]
        poller = OrderPositionPoller(
            broker="zerodha",
            user_id="user1",
            fetch_orders=lambda: [],
            fetch_trades=lambda: [],
            fetch_positions=lambda: positions,
            clock=FakeClock(),
        )
        poller.poll_once()

        positions[0] = {**POSITION_1, "ltp": 830.0, "pnl": 45.0}
        events = poller.poll_once()

        assert len(events) == 1
        assert events[0]["pnl"] == 45.0


class TestCanonicalOrderingAndBookkeeping:
    def test_orders_before_trades_before_positions_in_same_cycle(self):
        poller = make_poller(orders=[ORDER_OPEN], trades=[TRADE_1], positions=[POSITION_1])

        events = poller.poll_once()

        assert [e["event_type"] for e in events] == [
            "order_update",
            "trade_update",
            "position_update",
        ]
        assert [e["sequence"] for e in events] == [0, 1, 2]

    def test_all_events_in_a_cycle_share_the_same_generation(self):
        poller = make_poller(orders=[ORDER_OPEN], trades=[TRADE_1], positions=[POSITION_1])

        events = poller.poll_once()

        assert {e["generation"] for e in events} == {1}

    def test_generation_increments_every_cycle_even_with_no_changes(self):
        poller = make_poller()

        poller.poll_once()
        poller.poll_once()

        assert poller.generation == 2

    def test_get_last_snapshot_reflects_latest_state(self):
        poller = make_poller(orders=[ORDER_OPEN], trades=[TRADE_1], positions=[POSITION_1])
        poller.poll_once()

        snapshot = poller.get_last_snapshot()

        assert snapshot["generation"] == 1
        assert snapshot["orders"] == [ORDER_OPEN]
        assert snapshot["trades"] == [TRADE_1]
        assert snapshot["positions"] == [POSITION_1]


class TestFastModeStateMachine:
    def test_enter_fast_mode_switches_mode(self):
        poller = make_poller()

        poller.enter_fast_mode()

        assert poller.mode == MODE_FAST

    def test_fast_mode_uses_fast_poll_intervals(self):
        poller = make_poller(order_poll_normal_ms=750, order_poll_fast_ms=250)

        poller.enter_fast_mode()

        assert poller.order_poll_interval_ms == 250

    def test_normal_mode_uses_normal_poll_intervals(self):
        poller = make_poller(order_poll_normal_ms=750, order_poll_fast_ms=250)

        assert poller.order_poll_interval_ms == 750

    def test_fast_mode_exits_to_normal_once_no_non_terminal_orders_remain(self):
        orders = [ORDER_OPEN]
        poller = OrderPositionPoller(
            broker="zerodha",
            user_id="user1",
            fetch_orders=lambda: orders,
            fetch_trades=lambda: [],
            fetch_positions=lambda: [],
            clock=FakeClock(),
        )
        poller.enter_fast_mode()
        poller.poll_once()
        assert poller.mode == MODE_FAST

        orders[0] = ORDER_COMPLETE
        poller.poll_once()

        assert poller.mode == MODE_NORMAL

    def test_fast_mode_stays_active_while_order_is_open(self):
        orders = [ORDER_OPEN]
        poller = OrderPositionPoller(
            broker="zerodha",
            user_id="user1",
            fetch_orders=lambda: orders,
            fetch_trades=lambda: [],
            fetch_positions=lambda: [],
            clock=FakeClock(),
        )
        poller.enter_fast_mode()

        poller.poll_once()

        assert poller.mode == MODE_FAST

    def test_fast_mode_times_out_even_if_order_still_open(self):
        orders = [ORDER_OPEN]
        clock = FakeClock()
        poller = OrderPositionPoller(
            broker="zerodha",
            user_id="user1",
            fetch_orders=lambda: orders,
            fetch_trades=lambda: [],
            fetch_positions=lambda: [],
            clock=clock,
            fast_mode_timeout_sec=30,
        )
        poller.enter_fast_mode()
        poller.poll_once()
        assert poller.mode == MODE_FAST

        clock.advance(31)
        poller.poll_once()

        assert poller.mode == MODE_NORMAL

    def test_entering_fast_mode_again_resets_timeout_clock(self):
        orders = [ORDER_OPEN]
        clock = FakeClock()
        poller = OrderPositionPoller(
            broker="zerodha",
            user_id="user1",
            fetch_orders=lambda: orders,
            fetch_trades=lambda: [],
            fetch_positions=lambda: [],
            clock=clock,
            fast_mode_timeout_sec=30,
        )
        poller.enter_fast_mode()
        clock.advance(20)
        poller.enter_fast_mode()  # e.g. a modify/cancel call comes in
        clock.advance(20)  # total 40s since first entry, only 20s since reset

        poller.poll_once()

        assert poller.mode == MODE_FAST


class TestLifecycle:
    def test_start_invokes_on_events_and_stop_cleanly_reaps_the_thread(self):
        orders = [ORDER_OPEN]
        poller = OrderPositionPoller(
            broker="zerodha",
            user_id="user1",
            fetch_orders=lambda: orders,
            fetch_trades=lambda: [],
            fetch_positions=lambda: [],
            order_poll_normal_ms=10,
            position_poll_ms=10,
        )
        received = threading.Event()
        events_seen = []

        def on_events(events):
            events_seen.extend(events)
            received.set()

        poller.start(on_events)
        try:
            assert received.wait(timeout=2), "on_events was never called"
        finally:
            poller.stop()

        assert events_seen[0]["event_type"] == "order_update"
        assert poller._thread is None
        # give the OS a moment to reflect the join; thread must not be alive
        time.sleep(0.05)


class TestPollerRegistry:
    def teardown_method(self):
        # registry is module-level global state; keep tests isolated
        unregister_poller("zerodha", "user1")
        unregister_poller("dhan", "user2")

    def test_register_then_get_returns_the_same_instance(self):
        poller = make_poller()

        register_poller(poller)

        assert get_poller("zerodha", "user1") is poller

    def test_get_returns_none_when_nothing_registered(self):
        assert get_poller("dhan", "user2") is None

    def test_unregister_removes_and_returns_the_poller(self):
        poller = make_poller()
        register_poller(poller)

        removed = unregister_poller("zerodha", "user1")

        assert removed is poller
        assert get_poller("zerodha", "user1") is None

    def test_unregister_missing_session_returns_none(self):
        assert unregister_poller("dhan", "user2") is None

    def test_trigger_fast_mode_enters_fast_mode_on_registered_poller(self):
        poller = make_poller()
        register_poller(poller)

        trigger_fast_mode("zerodha", "user1")

        assert poller.mode == MODE_FAST

    def test_trigger_fast_mode_is_a_noop_when_no_poller_registered(self):
        # e.g. analyze/sandbox mode, or before the poller has started -
        # must not raise
        trigger_fast_mode("dhan", "user2")
