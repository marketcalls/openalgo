"""The strategy order-update stash under truly parallel threads.

A broker's fill can arrive before the strategy has written the broker order id
onto its order row: the sandbox fills a MARKET order inside the dispatch call,
and a live broker's push can beat its own REST acknowledgement. The update is
then held in ``order_events._pending_updates`` and replayed by ``replay_for``
the moment the row is recorded.

Under eventlet the update worker and the engine were greenlets that could not
interleave inside that handshake. Under the gthread worker they run in
parallel, which breaks it two ways, each pinned here:

* the stash was a plain cachetools ``TTLCache``, which is not safe for
  concurrent set and pop;
* the worker could miss the row, the engine could record it and replay
  nothing, and only then the worker stashed the frame, which nobody would ever
  replay: a lost entry fill, which leaves a leg with no stop.
"""

import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from database import strategy_module_db as store
from services.strategy_module import order_events, state
from utils.thread_safe_cache import LockedTTLCache

USER = "gthread_order_events_user"


@pytest.fixture(autouse=True)
def clean_slate():
    store.db_session.remove()
    store.init_db()

    def purge():
        for row in store.list_strategies(USER):
            for run in store.list_runs(row["id"]):
                state.clear_run_state(run["id"])
            store.set_strategy_status(row["id"], "stopped", None)
            store.delete_strategy(row["id"], USER)
        store.clear_strategy_module_cache()

    purge()
    yield
    purge()


@pytest.fixture
def unacknowledged_order():
    """A run with one entry row the broker has not acknowledged yet."""
    created, error = store.create_strategy(
        USER,
        {
            "name": "gthread order events",
            "underlying": "NIFTY",
            "underlying_exchange": "NSE_INDEX",
            "universe_tab": "weekly_monthly",
            "legs": [{"id": 1, "segment": "options", "position": "S", "lots": 1}],
        },
    )
    assert error is None, error
    run = store.create_run(created["id"], "sandbox", "zerodha")
    row = store.record_order(
        run.id,
        leg_id=1,
        kind="entry",
        order={
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 75,
            "status": "pending",
        },
    )
    assert row is not None
    return SimpleNamespace(strategy_id=created["id"], run_id=run.id, order_id=row.id)


def _fill(orderid):
    return SimpleNamespace(
        orderid=orderid,
        order_status="complete",
        average_price=142.5,
        filled_quantity=75,
        rejection_reason="",
    )


def test_the_stash_is_a_locked_cache():
    """Deterministic half of the check: a plain TTLCache cannot be shared."""
    assert isinstance(order_events._pending_updates, LockedTTLCache)


def test_the_stash_survives_concurrent_stash_and_replay(monkeypatch):
    """Eight threads stash and replay distinct ids as fast as they can."""
    applied = []
    applied_lock = threading.Lock()

    def record(order_id, _event):
        with applied_lock:
            applied.append(order_id)

    monkeypatch.setattr(order_events, "_apply_update", record)
    errors = []
    start = threading.Barrier(8)

    def worker(n):
        try:
            start.wait()
            for i in range(400):
                key = f"T{n}-{i}"
                order_events._pending_updates[key] = [_fill(key)]
                order_events.replay_for(key)
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(repr(exc))

    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
    finally:
        sys.setswitchinterval(previous)

    assert errors == []
    assert len(applied) == 8 * 400
    assert len(set(applied)) == 8 * 400


def _race(unacknowledged_order, broker_order_id, *, replay_before_stash):
    """Run the update worker and the recording thread against each other.

    The worker's first lookup misses the row. With ``replay_before_stash`` the
    recording thread then writes the broker id and calls replay_for before the
    worker stashes the frame: the interleaving that used to lose the fill.
    Without it the worker stashes first and replay_for must apply it.
    """
    real_lookup = store.get_order_by_broker_id
    worker_missed = threading.Event()
    recorded = threading.Event()
    # The worker's Thread object, not its ident: a finished thread's ident is
    # reused, and the recorder can start after the worker has already ended.
    worker_thread_ref: list[threading.Thread] = []
    worker_lookups = []

    def lookup(order_id):
        if not worker_thread_ref or threading.current_thread() is not worker_thread_ref[0]:
            return real_lookup(order_id)
        worker_lookups.append(order_id)
        if len(worker_lookups) == 1:
            # The first look: the row carries no broker id yet.
            worker_missed.set()
            if replay_before_stash:
                assert recorded.wait(10), "the recording thread never ran"
            return None
        # The second look, which only the fixed worker makes, and only when a
        # replay ran between its first look and its stash.
        if not replay_before_stash:
            assert recorded.wait(10), "the recording thread never ran"
        return real_lookup(order_id)

    def worker():
        worker_thread_ref.append(threading.current_thread())
        order_events._apply_update(broker_order_id, _fill(broker_order_id))

    def recorder():
        assert worker_missed.wait(10), "the worker never looked the row up"
        if not replay_before_stash:
            # Replay only once the frame is stashed.
            deadline = time.monotonic() + 5
            while order_events._pending_updates.get(broker_order_id) is None:
                assert time.monotonic() < deadline, "the worker never stashed"
                time.sleep(0.005)
        try:
            assert store.update_order(
                unacknowledged_order.order_id, status="open", broker_order_id=broker_order_id
            )
            order_events.replay_for(broker_order_id)
        finally:
            store.db_session.remove()
            recorded.set()

    with (
        patch.object(store, "get_order_by_broker_id", side_effect=lookup),
        patch("services.strategy_module.engine.apply_fill") as apply_fill,
    ):
        worker_thread = threading.Thread(target=worker)
        recorder_thread = threading.Thread(target=recorder)
        worker_thread.start()
        recorder_thread.start()
        worker_thread.join(20)
        recorder_thread.join(20)
        assert not worker_thread.is_alive() and not recorder_thread.is_alive()
    order_events._pending_updates.pop(broker_order_id, None)
    return apply_fill


def test_a_fill_that_misses_its_row_is_applied_when_replay_ran_first(unacknowledged_order):
    """The interleaving that lost the fill: replay ran before the stash."""
    apply_fill = _race(unacknowledged_order, "BRK-GT-RACE-1", replay_before_stash=True)

    assert apply_fill.call_count == 1, (
        "the fill was stashed after its replay and never applied: the leg keeps "
        "entry_status 'open' and no stop or target is ever evaluated"
    )
    args, kwargs = apply_fill.call_args
    assert args[:3] == (unacknowledged_order.run_id, 1, 142.5)
    assert kwargs["order_row_id"] == unacknowledged_order.order_id


def test_a_fill_stashed_before_its_replay_is_applied_once(unacknowledged_order):
    """The other interleaving: the frame is stashed first and replay_for takes
    it, so it is applied exactly once."""
    apply_fill = _race(unacknowledged_order, "BRK-GT-RACE-2", replay_before_stash=False)

    assert apply_fill.call_count == 1


def test_somebody_elses_order_is_held_for_one_lookup(unacknowledged_order):
    """Almost every update belongs to another surface. With no replay running
    it costs one lookup, as before, and is held rather than applied."""
    real_lookup = store.get_order_by_broker_id
    with (
        patch.object(store, "get_order_by_broker_id", side_effect=real_lookup) as lookup,
        patch("services.strategy_module.engine.apply_fill") as apply_fill,
    ):
        order_events._apply_update("NOT-OURS-1", _fill("NOT-OURS-1"))
    try:
        assert lookup.call_count == 1
        assert apply_fill.call_count == 0
        assert order_events._pending_updates.get("NOT-OURS-1") is not None
    finally:
        order_events._pending_updates.pop("NOT-OURS-1", None)


def test_the_strategy_subscriber_rides_the_critical_lane(monkeypatch):
    """A fill the strategy never hears about is a leg with no stop, so the
    subscriber must not share the best-effort lane's cap with alert senders."""
    calls = []
    monkeypatch.setattr(order_events, "_started", False)
    monkeypatch.setattr(order_events.bus, "subscribe", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(order_events.atexit, "register", lambda fn: fn)

    assert order_events.start() is True
    ((args, kwargs),) = calls
    assert args[0] == "order.update"
    assert kwargs.get("critical") is True


def test_the_flow_order_update_monitor_rides_the_critical_lane(monkeypatch):
    import services.flow_order_update_monitor_service as monitor_module

    calls = []
    monkeypatch.setattr(monitor_module.FlowOrderUpdateMonitor, "_instance", None)
    monkeypatch.setattr(monitor_module.bus, "subscribe", lambda *a, **k: calls.append((a, k)))

    monitor_module.FlowOrderUpdateMonitor()

    ((args, kwargs),) = calls
    assert args[0] == "order.update"
    assert kwargs.get("critical") is True
