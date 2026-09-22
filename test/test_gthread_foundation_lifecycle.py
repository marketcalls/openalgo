"""Stream accounting, the shutdown entry points and the shared thread pools.

Under the gthread worker a long-lived response holds a worker thread for its
whole life and a graceful stop has a hard end, so three things have to be
exactly right: a stream's slot is returned however it ends, a stop reaches
every stream without a lock in the signal path, and teardown runs once however
many callers race to start it, within a bounded time.
"""

from __future__ import annotations

import threading
import time

import pytest

from utils import runtime, shared_executors, stream_registry
from utils import shutdown as shutdown_mod

THREADS = 32

_STEP_NAMES = (
    "_stop_health_collector",
    "_stop_flow_scheduler",
    "_stop_historify_scheduler",
    "_stop_chartink_scheduler",
    "_stop_python_strategy_scheduler",
    "_stop_squareoff_scheduler",
    "_stop_strategy_module",
    "_stop_websocket_proxy",
    "_remove_all_scoped_sessions",
)


def _run_all(target, count=THREADS, timeout=60):
    barrier = threading.Barrier(count)
    errors = []

    def runner(index):
        try:
            target(index, barrier)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout)
        assert not thread.is_alive(), "a worker thread hung"
    assert errors == [], errors[:3]


@pytest.fixture(autouse=True)
def _clean_registry():
    stream_registry._reset_for_tests()
    yield
    stream_registry._reset_for_tests()


# --- stream_registry --------------------------------------------------------


def test_concurrent_streams_return_every_slot_and_record_the_peak():
    def worker(_index, barrier):
        barrier.wait()
        ticket = stream_registry.admit("python_strategy_sse")
        assert ticket is not None
        barrier.wait()  # every stream open at once
        ticket.release()

    _run_all(worker)
    counts = stream_registry.snapshot()["python_strategy_sse"]
    assert counts == {"open": 0, "peak": THREADS}


def test_a_limit_refuses_the_stream_over_it_and_admits_after_a_release():
    first = stream_registry.admit("mcp_sse", limit=2)
    second = stream_registry.admit("mcp_sse", limit=2)
    assert first is not None and second is not None
    assert stream_registry.admit("mcp_sse", limit=2) is None
    first.release()
    third = stream_registry.admit("mcp_sse", limit=2)
    assert third is not None
    assert stream_registry.snapshot()["mcp_sse"]["open"] == 2


def test_releasing_twice_counts_once():
    """call_on_close and the generator's finally both release the same ticket."""
    ticket = stream_registry.admit("agent_sse")
    other = stream_registry.admit("agent_sse")
    ticket.release()
    ticket.release()
    assert ticket.released is True
    assert stream_registry.snapshot()["agent_sse"]["open"] == 1
    other.release()


def test_track_stream_releases_when_the_stream_raises():
    with pytest.raises(ConnectionResetError):
        with stream_registry.track_stream("sse"):
            assert stream_registry.open_streams() == 1
            raise ConnectionResetError("client went away")
    assert stream_registry.open_streams() == 0


def test_kinds_beyond_the_cap_fold_into_one_bucket():
    tickets = [stream_registry.admit(f"kind-{n}") for n in range(stream_registry.MAX_KINDS + 8)]
    snap = stream_registry.snapshot()
    assert len(snap) == stream_registry.MAX_KINDS + 1
    assert snap["_other"]["open"] == 8
    for ticket in tickets:
        ticket.release()
    assert stream_registry.open_streams() == 0


def test_limits_are_enforced_only_under_gthread(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    assert stream_registry.enforced_limit(4) is None
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    assert stream_registry.enforced_limit(4) == 4


def test_a_drain_request_is_seen_by_should_stop_and_wakes_wait_stop():
    assert stream_registry.should_stop() is False
    assert stream_registry.wait_stop(0.05) is False
    threading.Timer(0.1, stream_registry.request_drain).start()
    started = time.monotonic()
    assert stream_registry.wait_stop(10, poll=0.02) is True
    assert time.monotonic() - started < 2
    assert stream_registry.should_stop() is True


def test_the_stop_event_is_seen_by_should_stop():
    stream_registry.STOP.set()
    assert stream_registry.should_stop() is True


def test_thread_budget_has_no_pool_outside_gthread(monkeypatch):
    monkeypatch.setattr(runtime, "configured_threads", lambda: None)
    budget = stream_registry.thread_budget()
    assert budget["threads"] is None and budget["headroom"] is None
    assert budget["streams"] == 0


def test_thread_budget_under_gthread_counts_streams_and_warns_once(monkeypatch):
    monkeypatch.setattr(runtime, "configured_threads", lambda: 10)
    monkeypatch.setattr(stream_registry, "socketio_connection_count", lambda: 1)
    tickets = [stream_registry.admit("sse") for _ in range(4)]
    budget = stream_registry.thread_budget()
    assert budget == {"threads": 10, "streams": 4, "socketio": 1, "headroom": 5}
    for ticket in tickets:
        ticket.release()
    assert stream_registry._headroom_warned is True


# --- shutdown ---------------------------------------------------------------


@pytest.fixture
def quiet_shutdown(monkeypatch):
    """Each test starts clear, with the built-in steps replaced by recorders."""
    calls = []
    monkeypatch.setattr(shutdown_mod, "_shutdown_done", False)
    monkeypatch.setattr(shutdown_mod, "_hooks", [])
    for name in _STEP_NAMES:
        monkeypatch.setattr(shutdown_mod, name, lambda n=name: calls.append(n))
    yield calls
    shutdown_mod._shutdown_done = False


def test_begin_drain_only_flags_the_streams():
    shutdown_mod.begin_drain()
    shutdown_mod.begin_drain()
    assert stream_registry.should_stop() is True
    assert not stream_registry.STOP.is_set(), "begin_drain must not take the Event's lock"


def test_racing_callers_run_the_teardown_exactly_once(quiet_shutdown):
    """A worker_exit hook, a worker_int hook and a signal, all at once."""

    def worker(_index, barrier):
        barrier.wait()
        shutdown_mod.shutdown_runtime()

    _run_all(worker, count=4)
    assert quiet_shutdown == list(_STEP_NAMES)
    assert stream_registry.STOP.is_set()


def test_hooks_run_early_and_late_around_the_built_in_steps(quiet_shutdown):
    shutdown_mod.register_shutdown_hook(
        lambda: quiet_shutdown.append("strategies"), name="strategies", early=True
    )
    shutdown_mod.register_shutdown_hook(lambda: quiet_shutdown.append("pools"), name="pools")
    shutdown_mod.shutdown_runtime()
    assert quiet_shutdown[0] == "strategies"
    assert quiet_shutdown[-2:] == ["pools", "_remove_all_scoped_sessions"]
    assert quiet_shutdown[1:-2] == list(_STEP_NAMES[:-1])


def test_a_hook_that_hangs_costs_its_budget_and_no_more(quiet_shutdown):
    release = threading.Event()
    shutdown_mod.register_shutdown_hook(
        lambda: release.wait(30), name="stuck", budget_s=0.3, early=True
    )
    started = time.monotonic()
    shutdown_mod.shutdown_runtime()
    elapsed = time.monotonic() - started
    release.set()
    assert elapsed < 5, f"a stuck hook held teardown for {elapsed:.1f}s"
    assert quiet_shutdown == list(_STEP_NAMES), "later steps still ran"


def test_a_failing_hook_does_not_stop_the_teardown(quiet_shutdown):
    def boom():
        raise RuntimeError("hook failed")

    shutdown_mod.register_shutdown_hook(boom, name="boom", early=True)
    shutdown_mod.shutdown_runtime()
    assert quiet_shutdown == list(_STEP_NAMES)


def test_hooks_share_one_overall_budget(quiet_shutdown, monkeypatch):
    monkeypatch.setattr(shutdown_mod, "SHUTDOWN_BUDGET_S", 0.4)
    ran = []
    release = threading.Event()
    shutdown_mod.register_shutdown_hook(
        lambda: release.wait(30), name="slow", budget_s=10, early=True
    )
    shutdown_mod.register_shutdown_hook(lambda: ran.append("late"), name="skipped", early=True)
    started = time.monotonic()
    shutdown_mod.shutdown_runtime()
    release.set()
    assert time.monotonic() - started < 5
    assert ran == [], "a hook past the overall budget must be skipped"


# --- shared executors ---------------------------------------------------------


@pytest.fixture
def clean_executors(monkeypatch):
    monkeypatch.setattr(shared_executors, "_executors", {})
    monkeypatch.setattr(shared_executors, "_hooks_registered", True)  # no atexit in tests
    yield
    shared_executors.shutdown_all()


def test_one_pool_per_name_under_a_simultaneous_first_use(clean_executors):
    pools = []

    def worker(_index, barrier):
        barrier.wait()
        pools.append(shared_executors.get_executor("quotes", 4))

    _run_all(worker, count=16)
    assert len({id(pool) for pool in pools}) == 1
    assert shared_executors.get_executor("quotes", 99)._max_workers == 4


def test_pool_stats_and_shutdown(clean_executors):
    pool = shared_executors.get_executor("history", 2)
    assert pool.submit(lambda: 7).result(5) == 7
    stats = shared_executors.executor_stats()["history"]
    assert stats["max_workers"] == 2 and stats["threads"] >= 1 and stats["queued"] == 0
    shared_executors.shutdown_all()
    assert shared_executors.executor_stats() == {}
    with pytest.raises(RuntimeError):
        pool.submit(lambda: 1)
    fresh = shared_executors.get_executor("history", 2)
    assert fresh is not pool


def test_the_first_pool_registers_the_teardown_once(monkeypatch):
    monkeypatch.setattr(shared_executors, "_executors", {})
    monkeypatch.setattr(shared_executors, "_hooks_registered", False)
    registered = []
    monkeypatch.setattr(shared_executors.atexit, "register", lambda fn: registered.append(fn))
    monkeypatch.setattr(shutdown_mod, "_hooks", [])
    try:
        shared_executors.get_executor("a", 1)
        shared_executors.get_executor("b", 1)
        assert registered == [shared_executors.shutdown_all]
        assert [hook.name for hook in shutdown_mod._hooks] == ["shared-executors"]
    finally:
        shared_executors.shutdown_all()
