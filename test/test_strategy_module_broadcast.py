"""The strategy module's push channel.

Three things are worth asserting here and they are not the payload shapes,
though those are checked too because a TypeScript client is written against
them.

The first is the throttle: which frames it is allowed to drop and which it is
not. A dropped delta costs nothing, a dropped fill or terminal costs the
operator the only notice they get.

The second is that a delta carries every open leg. With a throttle in front,
sending only the leg that ticked strands the others at a stale price.

The third is that nothing here can reach the caller. Every caller is on the
risk path, and a broadcast failure must not become an order failure.

The clock is driven rather than slept on, so the throttle's behaviour is
asserted at exact boundaries rather than approached with a sleep.
"""

from __future__ import annotations

import pytest

from services.strategy_module import broadcast, state

STRATEGY_ID = 41
RUN_ID = 7001


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class FakeManager:
    """The shape python-socketio's in-memory manager exposes."""

    def __init__(self) -> None:
        self.rooms: dict[str, dict[str, dict]] = {"/": {}}


class FakeServer:
    def __init__(self) -> None:
        self.manager = FakeManager()


class FakeSocketIO:
    """Runs background tasks inline, so a test sees the emit synchronously."""

    def __init__(self) -> None:
        self.server = FakeServer()
        self.emits: list[tuple[str, dict, dict]] = []
        self.scheduled = 0
        self.raise_on_emit: Exception | None = None
        self.raise_on_schedule: Exception | None = None

    def start_background_task(self, target, *args, **kwargs):
        self.scheduled += 1
        if self.raise_on_schedule is not None:
            raise self.raise_on_schedule
        target(*args, **kwargs)

    def emit(self, event, payload, **kwargs):
        if self.raise_on_emit is not None:
            raise self.raise_on_emit
        self.emits.append((event, payload, kwargs))

    # Test helpers -------------------------------------------------------

    def subscribe(self, strategy_id: int, sid: str = "sid-1") -> None:
        self.server.manager.rooms["/"].setdefault(f"strategy:{strategy_id}", {})[sid] = "eio-1"

    def unsubscribe_all(self) -> None:
        self.server.manager.rooms["/"] = {}

    def events(self) -> list[str]:
        return [event for event, _payload, _kwargs in self.emits]

    def payloads(self, event: str) -> list[dict]:
        return [payload for name, payload, _kwargs in self.emits if name == event]


class Clock:
    """A monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_throttle():
    """No throttle state leaks between tests."""
    broadcast._last_delta_at.clear()
    yield
    broadcast._last_delta_at.clear()


@pytest.fixture
def sio(monkeypatch):
    fake = FakeSocketIO()
    monkeypatch.setattr(broadcast, "socketio", fake)
    fake.subscribe(STRATEGY_ID)
    return fake


@pytest.fixture
def clock(monkeypatch):
    driven = Clock()
    monkeypatch.setattr(broadcast, "_clock", driven)
    return driven


def _legs() -> list[dict]:
    return [
        {
            "leg_id": 1,
            "position": "S",
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "quantity": 75,
            "lots": 1,
            "sl_pts": 20,
            "target_pts": 40,
            "trail": {"x": 10, "y": 5},
        },
        {
            "leg_id": 2,
            "position": "S",
            "symbol": "NIFTY28MAY2624000PE",
            "exchange": "NFO",
            "quantity": 75,
            "lots": 1,
            "sl_pts": 20,
            "target_pts": 40,
            "trail": {"x": 10, "y": 5},
        },
        {
            "leg_id": 3,
            "position": "B",
            "symbol": "NIFTY28MAY2624500CE",
            "exchange": "NFO",
            "quantity": 75,
            "lots": 1,
            "sl_pts": 15,
            "target_pts": 30,
            "trail": {"x": 0, "y": 0},
        },
    ]


@pytest.fixture
def run():
    """A live run: two open legs and one that has been closed."""
    state.init_run_state(RUN_ID, STRATEGY_ID, _legs())
    with state.run_state(RUN_ID) as live:
        for leg_id in ("1", "2"):
            leg = live["legs"][leg_id]
            leg["status"] = "open"
            leg["entry_status"] = "complete"
            leg["entry_avg"] = 100.0
            leg["ltp"] = 90.0
            leg["mtm"] = 750.0
            leg["effective_sl"] = 120.0
            leg["effective_target"] = 60.0
        closed = live["legs"]["3"]
        closed["status"] = "closed"
        closed["entry_avg"] = 50.0
        closed["realized_pnl"] = -300.0
        live["pnl_peak"] = 2000.0
        live["pnl_trough"] = -400.0
        live["lock_armed"] = True
        live["lock_floor"] = 1000.0
    yield RUN_ID
    state.clear_run_state(RUN_ID)


# ---------------------------------------------------------------------------
# Throttle
# ---------------------------------------------------------------------------


def test_a_second_delta_inside_the_window_is_dropped(sio, clock, run):
    assert broadcast.push_delta(run) is True

    clock.advance(broadcast.DELTA_MIN_INTERVAL_SEC / 2)
    assert broadcast.push_delta(run) is False

    assert sio.events() == [broadcast.EVENT_DELTA]


def test_a_delta_after_the_window_is_admitted(sio, clock, run):
    assert broadcast.push_delta(run) is True

    clock.advance(broadcast.DELTA_MIN_INTERVAL_SEC)
    assert broadcast.push_delta(run) is True

    assert sio.events() == [broadcast.EVENT_DELTA, broadcast.EVENT_DELTA]


def test_a_burst_of_ticks_collapses_to_one_frame_per_window(sio, clock, run):
    # A liquid option ticking twenty times inside one window must not become
    # twenty frames the browser cannot paint.
    for _ in range(20):
        broadcast.push_delta(run)
        clock.advance(broadcast.DELTA_MIN_INTERVAL_SEC / 100)

    assert len(sio.payloads(broadcast.EVENT_DELTA)) == 1

    # A full window on, the next tick is painted.
    clock.advance(broadcast.DELTA_MIN_INTERVAL_SEC)
    assert broadcast.push_delta(run) is True
    assert len(sio.payloads(broadcast.EVENT_DELTA)) == 2


def test_a_forced_delta_is_never_dropped(sio, clock, run):
    """The delta after a fill, and the last delta of a run."""
    assert broadcast.push_delta(run) is True
    assert broadcast.push_delta(run) is False
    assert broadcast.push_delta(run, force=True) is True

    assert len(sio.payloads(broadcast.EVENT_DELTA)) == 2


def test_a_forced_delta_stamps_the_window_it_bypassed(sio, clock, run):
    broadcast.push_delta(run, force=True)
    assert broadcast.push_delta(run) is False


def test_a_fill_an_event_and_a_terminal_bypass_the_throttle(sio, clock, run):
    # The window is consumed by a delta, and none of the one-offs behind it may
    # be dropped: each describes something that happened once, and no later
    # frame carries it.
    assert broadcast.push_delta(run) is True

    assert broadcast.push_order_update(STRATEGY_ID, {"id": 5, "run_id": RUN_ID}) is True
    assert (
        broadcast.push_event(STRATEGY_ID, {"id": 9, "run_id": RUN_ID, "kind": "leg_sl_hit"}) is True
    )
    assert (
        broadcast.push_run_update(STRATEGY_ID, {"id": RUN_ID, "strategy_id": STRATEGY_ID}) is True
    )
    assert broadcast.push_terminal(STRATEGY_ID, RUN_ID, "overall_sl", 1234.5) is True

    assert sio.events() == [
        broadcast.EVENT_DELTA,
        broadcast.EVENT_ORDER_UPDATE,
        broadcast.EVENT_EVENT,
        broadcast.EVENT_RUN_UPDATE,
        broadcast.EVENT_TERMINAL,
    ]


def test_a_snapshot_is_not_throttled(sio, clock, run):
    assert broadcast.push_snapshot(run) is True
    assert broadcast.push_snapshot(run) is True
    assert len(sio.payloads(broadcast.EVENT_SNAPSHOT)) == 2


def test_the_throttle_is_per_strategy(sio, clock, run):
    """One strategy's frame rate must not spend another's window."""
    other_run, other_strategy = 7002, 42
    state.init_run_state(other_run, other_strategy, _legs())
    sio.subscribe(other_strategy)
    try:
        assert broadcast.push_delta(run) is True
        assert broadcast.push_delta(other_run) is True
    finally:
        state.clear_run_state(other_run)


def test_an_unwatched_run_does_not_consume_its_own_window(sio, clock, run):
    """Otherwise the first delta after a client joins is dropped for a frame
    that client never saw."""
    sio.unsubscribe_all()
    assert broadcast.push_delta(run) is False

    sio.subscribe(STRATEGY_ID)
    assert broadcast.push_delta(run) is True


# ---------------------------------------------------------------------------
# Payload shapes
# ---------------------------------------------------------------------------


ENVELOPE_KEYS = {"type", "strategy_id", "run_id", "ts", "ts_ms"}

FIGURE_KEYS = {
    "mtm_realized",
    "mtm_unrealized",
    "mtm_total",
    "peak",
    "trough",
    "lock_armed",
    "lock_floor",
    "trail_to_entry_active",
    "tick_source_degraded",
}

LEG_KEYS = {
    "leg_id",
    "symbol",
    "exchange",
    "position",
    "lots",
    "qty",
    "status",
    "entry_status",
    "exit_kind",
    "ltp",
    "entry_avg",
    "mtm",
    "realized_pnl",
    "effective_sl",
    "effective_target",
    "trail_active",
    "favorable_points",
    "tick_source",
}


def test_the_snapshot_payload_carries_the_whole_run(run):
    payload = broadcast.snapshot_payload(run)

    assert set(payload) == ENVELOPE_KEYS | FIGURE_KEYS | {"legs"}
    assert payload["type"] == "snapshot"
    assert payload["strategy_id"] == STRATEGY_ID
    assert payload["run_id"] == RUN_ID

    # Every leg, including the closed one, which the delta stream omits.
    assert [leg["leg_id"] for leg in payload["legs"]] == [1, 2, 3]
    assert set(payload["legs"][0]) == LEG_KEYS

    leg = payload["legs"][0]
    assert leg["symbol"] == "NIFTY28MAY2624000CE"
    assert leg["position"] == "S"
    assert leg["qty"] == 75
    assert leg["ltp"] == 90.0
    assert leg["entry_avg"] == 100.0
    assert leg["effective_sl"] == 120.0
    assert leg["effective_target"] == 60.0
    assert leg["trail_active"] is False
    assert leg["tick_source"] == "ws"

    # Two shorts 10 points in front on 75 lots, less the closed leg's loss.
    assert payload["mtm_unrealized"] == pytest.approx(1500.0)
    assert payload["mtm_realized"] == pytest.approx(-300.0)
    assert payload["mtm_total"] == pytest.approx(1200.0)
    assert payload["peak"] == 2000.0
    assert payload["trough"] == -400.0
    assert payload["lock_armed"] is True
    assert payload["lock_floor"] == 1000.0
    assert payload["trail_to_entry_active"] is False


def test_the_snapshot_payload_is_none_for_a_run_with_no_state():
    assert broadcast.snapshot_payload(999999) is None


def test_a_delta_carries_every_open_leg_not_only_the_one_that_ticked(sio, clock, run):
    broadcast.push_delta(run)
    payload = sio.payloads(broadcast.EVENT_DELTA)[0]

    assert payload["type"] == "delta"
    assert set(payload) == ENVELOPE_KEYS | FIGURE_KEYS | {"legs"}
    # Leg 2 never ticked in this frame and is still present with its own
    # figures. Leg 3 is closed, so it cannot have moved and is left out.
    assert [leg["leg_id"] for leg in payload["legs"]] == [1, 2]
    assert set(payload["legs"][1]) == LEG_KEYS
    assert payload["legs"][1]["symbol"] == "NIFTY28MAY2624000PE"
    assert payload["legs"][1]["ltp"] == 90.0


def test_the_pnl_triplet_is_marked_from_the_legs_not_read_from_the_state(run):
    """A delta after a fill but before the next aggregate pass must not show
    the P&L from before the fill."""
    with state.run_state(run) as live:
        live["pnl_realized"] = 999999.0
        live["pnl_unrealized"] = 999999.0
        live["pnl_total"] = 999999.0

    payload = broadcast.delta_payload(run)

    assert payload["mtm_unrealized"] == pytest.approx(1500.0)
    assert payload["mtm_realized"] == pytest.approx(-300.0)
    assert payload["mtm_total"] == pytest.approx(1200.0)


def test_the_event_payload_wraps_one_row(sio, run):
    row = {
        "id": 12,
        "run_id": RUN_ID,
        "strategy_id": STRATEGY_ID,
        "ts": "2026-08-30T09:20:00+00:00",
        "kind": "leg_sl_hit",
        "severity": "warn",
        "leg_id": 1,
        "message": "Stop hit at 120",
        "payload": {"leg_id": 1},
    }

    assert broadcast.push_event(STRATEGY_ID, row) is True

    payload = sio.payloads(broadcast.EVENT_EVENT)[0]
    assert set(payload) == ENVELOPE_KEYS | {"event"}
    assert payload["type"] == "event"
    assert payload["run_id"] == RUN_ID
    # The row travels verbatim: its own ts stays the explicit UTC string the
    # store emits, so a client is never guessing which timestamp is which.
    assert payload["event"] == row


def test_the_order_update_payload_wraps_one_row(sio, run):
    row = {"id": 3, "run_id": RUN_ID, "leg_id": 1, "kind": "entry", "status": "complete"}

    assert broadcast.push_order_update(STRATEGY_ID, row) is True

    payload = sio.payloads(broadcast.EVENT_ORDER_UPDATE)[0]
    assert set(payload) == ENVELOPE_KEYS | {"order"}
    assert payload["type"] == "order_update"
    assert payload["run_id"] == RUN_ID
    assert payload["order"] == row


def test_the_run_update_payload_wraps_one_row(sio, run):
    row = {"id": RUN_ID, "strategy_id": STRATEGY_ID, "mode": "live", "stop_reason": None}

    assert broadcast.push_run_update(STRATEGY_ID, row) is True

    payload = sio.payloads(broadcast.EVENT_RUN_UPDATE)[0]
    assert set(payload) == ENVELOPE_KEYS | {"run"}
    assert payload["type"] == "run_update"
    # Taken from the row's own id, since a run row names itself.
    assert payload["run_id"] == RUN_ID
    assert payload["run"] == row


def test_the_terminal_payload_carries_the_reason_and_the_final_realized(sio, run):
    assert broadcast.push_terminal(STRATEGY_ID, RUN_ID, "overall_sl", 1234.5) is True

    payload = sio.payloads(broadcast.EVENT_TERMINAL)[0]
    assert set(payload) == ENVELOPE_KEYS | {"stop_reason", "pnl_realized"}
    assert payload["type"] == "terminal"
    assert payload["run_id"] == RUN_ID
    assert payload["stop_reason"] == "overall_sl"
    assert payload["pnl_realized"] == 1234.5


def test_every_message_is_addressed_to_the_strategys_room(sio, clock, run):
    broadcast.push_snapshot(run)
    broadcast.push_delta(run, force=True)
    broadcast.push_event(STRATEGY_ID, {"id": 1, "run_id": RUN_ID})
    broadcast.push_order_update(STRATEGY_ID, {"id": 1, "run_id": RUN_ID})
    broadcast.push_run_update(STRATEGY_ID, {"id": RUN_ID})
    broadcast.push_terminal(STRATEGY_ID, RUN_ID, "manual", 0.0)

    assert len(sio.emits) == 6
    for _event, _payload, kwargs in sio.emits:
        assert kwargs["to"] == f"strategy:{STRATEGY_ID}"
        assert kwargs["namespace"] == "/"


def test_timestamps_are_ist_with_a_matching_epoch_millis(run):
    payload = broadcast.snapshot_payload(run)

    assert payload["ts"].endswith("+05:30")
    assert isinstance(payload["ts_ms"], int)

    from datetime import datetime

    assert datetime.fromisoformat(payload["ts"]).timestamp() * 1000 == pytest.approx(
        payload["ts_ms"], abs=1
    )


def test_a_non_finite_number_never_reaches_the_wire(run):
    """NaN is not JSON, and one of them makes the browser throw on the whole
    frame rather than on the one field."""
    with state.run_state(run) as live:
        live["legs"]["1"]["ltp"] = float("nan")
        live["legs"]["1"]["effective_sl"] = float("inf")

    leg = broadcast.snapshot_payload(run)["legs"][0]

    assert leg["ltp"] is None
    assert leg["effective_sl"] is None


# ---------------------------------------------------------------------------
# Nobody listening
# ---------------------------------------------------------------------------


def test_nothing_is_emitted_when_nobody_is_subscribed(sio, clock, run):
    sio.unsubscribe_all()

    assert broadcast.has_subscribers(STRATEGY_ID) is False
    assert broadcast.push_snapshot(run) is False
    assert broadcast.push_delta(run) is False
    assert broadcast.push_event(STRATEGY_ID, {"id": 1, "run_id": RUN_ID}) is False
    assert broadcast.push_order_update(STRATEGY_ID, {"id": 1, "run_id": RUN_ID}) is False
    assert broadcast.push_run_update(STRATEGY_ID, {"id": RUN_ID}) is False
    assert broadcast.push_terminal(STRATEGY_ID, RUN_ID, "manual", 0.0) is False

    assert sio.emits == []
    assert sio.scheduled == 0


def test_another_strategys_subscriber_does_not_count(sio, clock, run):
    sio.unsubscribe_all()
    sio.subscribe(STRATEGY_ID + 1)

    assert broadcast.has_subscribers(STRATEGY_ID) is False
    assert broadcast.push_delta(run) is False


def test_nobody_is_listening_before_socketio_is_bound_to_the_app(sio):
    sio.server = None
    assert broadcast.has_subscribers(STRATEGY_ID) is False


def test_an_unreadable_manager_fails_open(sio, monkeypatch):
    """A feed that silently goes dead is far worse to diagnose than a few
    payloads built for nobody."""
    monkeypatch.setattr(broadcast, "_subscriber_probe_warned", False)
    sio.server.manager.rooms = "not a dict"

    assert broadcast.has_subscribers(STRATEGY_ID) is True


# ---------------------------------------------------------------------------
# Failure containment
# ---------------------------------------------------------------------------


def test_a_raising_emit_does_not_reach_the_caller(sio, clock, run):
    sio.raise_on_emit = RuntimeError("socket gone")

    # Every kind, since each has its own path to the emit.
    assert broadcast.push_snapshot(run) is True
    assert broadcast.push_delta(run, force=True) is True
    assert broadcast.push_event(STRATEGY_ID, {"id": 1, "run_id": RUN_ID}) is True
    assert broadcast.push_order_update(STRATEGY_ID, {"id": 1, "run_id": RUN_ID}) is True
    assert broadcast.push_run_update(STRATEGY_ID, {"id": RUN_ID}) is True
    assert broadcast.push_terminal(STRATEGY_ID, RUN_ID, "manual", 0.0) is True

    assert sio.emits == []
    assert sio.scheduled == 6


def test_a_failure_to_schedule_the_emit_does_not_reach_the_caller(sio, clock, run):
    sio.raise_on_schedule = RuntimeError("no async mode")

    assert broadcast.push_delta(run, force=True) is False
    assert broadcast.push_terminal(STRATEGY_ID, RUN_ID, "manual", 0.0) is False


def test_a_mark_that_raises_falls_back_to_the_stored_figures(sio, monkeypatch, run):
    """snapshot_payload is reused by a REST route, so a raise inside the mark
    must produce a frame with the stored numbers rather than a 500."""

    def boom(_run):
        raise ValueError("unusable leg")

    monkeypatch.setattr(broadcast, "run_pnl", boom)
    with state.run_state(run) as live:
        live["pnl_realized"] = 11.0
        live["pnl_unrealized"] = 22.0

    payload = broadcast.snapshot_payload(run)

    assert payload["mtm_realized"] == 11.0
    assert payload["mtm_unrealized"] == 22.0
    assert payload["mtm_total"] == 33.0


def test_an_unusable_strategy_id_does_not_reach_the_caller(sio, run):
    assert broadcast.push_event(None, {"id": 1, "run_id": RUN_ID}) is False
    assert broadcast.push_order_update("not-a-number", {"id": 1}) is False


def test_an_empty_row_is_not_broadcast(sio, run):
    assert broadcast.push_event(STRATEGY_ID, {}) is False
    assert broadcast.push_order_update(STRATEGY_ID, {}) is False
    assert broadcast.push_run_update(STRATEGY_ID, {}) is False
    assert sio.emits == []


def test_a_run_with_no_state_is_not_broadcast(sio, clock):
    assert broadcast.push_snapshot(999999) is False
    assert broadcast.push_delta(999999) is False
    assert sio.emits == []


# ---------------------------------------------------------------------------
# Resource surface
# ---------------------------------------------------------------------------


def test_a_terminal_frame_forgets_the_strategys_throttle_entry(sio, clock, run):
    broadcast.push_delta(run)
    assert STRATEGY_ID in broadcast._last_delta_at

    broadcast.push_terminal(STRATEGY_ID, RUN_ID, "manual", 0.0)
    assert STRATEGY_ID not in broadcast._last_delta_at


def test_the_throttle_entry_is_dropped_even_when_the_terminal_emit_fails(sio, clock, run):
    broadcast.push_delta(run)
    sio.raise_on_schedule = RuntimeError("no async mode")

    broadcast.push_terminal(STRATEGY_ID, RUN_ID, "manual", 0.0)

    assert STRATEGY_ID not in broadcast._last_delta_at


def test_forget_strategy_is_safe_for_a_strategy_that_never_streamed():
    broadcast.forget_strategy(123456)


def test_the_throttle_map_does_not_grow_without_bound(monkeypatch, clock):
    """A run that ends without a terminal frame must not leave an entry behind
    for the life of a worker that never restarts."""
    monkeypatch.setattr(broadcast, "MAX_TRACKED_STRATEGIES", 8)

    high_water = 0
    for strategy_id in range(1000):
        broadcast._admit_delta(strategy_id, force=True)
        clock.advance(1.0)
        high_water = max(high_water, len(broadcast._last_delta_at))

    # A thousand strategies through a map that may hold eight.
    assert high_water <= broadcast.MAX_TRACKED_STRATEGIES + 1


def test_an_entry_left_behind_by_a_finished_run_is_swept(monkeypatch, clock):
    monkeypatch.setattr(broadcast, "MAX_TRACKED_STRATEGIES", 8)

    # Eight runs that streamed and then ended without a terminal frame.
    for strategy_id in range(100, 108):
        broadcast._admit_delta(strategy_id, force=True)
    clock.advance(broadcast.THROTTLE_IDLE_SEC + 1)

    # Two live ones arriving later push the map over its ceiling.
    broadcast._admit_delta(200, force=True)
    broadcast._admit_delta(201, force=True)

    assert set(broadcast._last_delta_at) == {200, 201}


def test_the_throttle_map_is_reset_when_nothing_in_it_is_stale(monkeypatch, clock):
    """The pathological case: more live strategies than the ceiling. Clearing
    costs one unthrottled delta each, which is better than growing."""
    monkeypatch.setattr(broadcast, "MAX_TRACKED_STRATEGIES", 8)

    for strategy_id in range(100, 110):
        broadcast._admit_delta(strategy_id, force=True)

    assert list(broadcast._last_delta_at) == [109]


def test_the_map_is_not_swept_while_it_is_under_the_ceiling(sio, clock, run):
    for strategy_id in range(10):
        broadcast._admit_delta(strategy_id, force=True)
    clock.advance(broadcast.THROTTLE_IDLE_SEC + 1)
    broadcast._admit_delta(99, force=True)

    assert len(broadcast._last_delta_at) == 11


# ---------------------------------------------------------------------------
# Room naming
# ---------------------------------------------------------------------------


def test_the_room_name_is_the_one_the_join_handler_must_use():
    assert broadcast.room_for(41) == "strategy:41"
    assert broadcast.NAMESPACE == "/"
