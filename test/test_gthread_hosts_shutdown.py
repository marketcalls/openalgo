"""Strategy and OpenScript cleanup runs before the gthread worker is killed (hosts-08).

Both hosts stopped their child processes only from atexit. The gthread worker
never gets there while a request thread is still streaming: interpreter
finalisation joins the request pool first, an open /python stream or Socket.IO
connection never finishes, and the worker is killed at the end of its graceful
window. Neither cleanup ran, and the strategies kept trading with nothing
supervising them. Nor was anything stopping a scheduled start already in flight
from launching a child behind the cleanup.

Each host now registers an early utils.shutdown hook that, under gthread only,
refuses new starts, stops what is running side by side within a budget, and
kills what is left. Under eventlet and on the development server the hook does
nothing and atexit stops them exactly as before.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from flask import Flask

import utils.session
from blueprints import python_strategy as ps
from services import openscript_runner_service as service
from utils import shutdown as shutdown_mod
from utils import stream_registry


class FakeScheduler:
    def __init__(self):
        self.running = True
        self.shutdowns = []

    def shutdown(self, wait=True):
        self.shutdowns.append(wait)
        self.running = False


class FakeChild:
    """A child process that is alive until something stops it."""

    def __init__(self, pid):
        self.pid = pid
        self.alive = True

    def poll(self):
        return None if self.alive else 0


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setattr(ps, "_SHUTTING_DOWN", threading.Event())
    scheduler = FakeScheduler()
    monkeypatch.setattr(ps, "SCHEDULER", scheduler)
    saved = dict(ps.RUNNING_STRATEGIES)
    ps.RUNNING_STRATEGIES.clear()
    yield scheduler
    ps.RUNNING_STRATEGIES.clear()
    ps.RUNNING_STRATEGIES.update(saved)


def test_begin_shutdown_stops_everything_and_refuses_new_starts(host, monkeypatch):
    scheduler = host
    children = {f"s{i}": FakeChild(3_000_000 + i) for i in range(3)}
    for sid, child in children.items():
        ps.RUNNING_STRATEGIES[sid] = {"process": child, "pid": child.pid}

    stopped = []
    lock = threading.Lock()

    def fake_stop(strategy_id):
        time.sleep(0.3)  # each stop takes a while; together they must overlap
        with lock:
            stopped.append(strategy_id)
        children[strategy_id].alive = False
        with ps.PROCESS_LOCK:
            ps.RUNNING_STRATEGIES.pop(strategy_id, None)
        return True, "Strategy stopped"

    killed_pids = []
    monkeypatch.setattr(ps, "stop_strategy_process", fake_stop)
    monkeypatch.setattr(ps, "_kill_process_tree", lambda pid: killed_pids.append(pid) or True)

    started = time.monotonic()
    killed = ps.begin_shutdown(budget_s=5)
    took = time.monotonic() - started

    assert sorted(stopped) == sorted(children)
    assert killed == [] and killed_pids == []
    assert took < 0.9, f"the stops ran one after another ({took:.2f}s)"
    assert scheduler.shutdowns == [False]
    assert ps.start_strategy_process("s0") == (False, ps.SHUTTING_DOWN_MESSAGE)


def test_a_strategy_that_outlives_the_budget_is_killed(host, monkeypatch):
    child = FakeChild(3_100_000)
    ps.RUNNING_STRATEGIES["stuck"] = {"process": child, "pid": child.pid}

    def hanging_stop(strategy_id):
        time.sleep(2)
        return False, "Failed to stop"

    killed_pids = []
    monkeypatch.setattr(ps, "stop_strategy_process", hanging_stop)
    monkeypatch.setattr(ps, "_kill_process_tree", lambda pid: killed_pids.append(pid) or True)

    started = time.monotonic()
    killed = ps.begin_shutdown(budget_s=0.3)

    assert time.monotonic() - started < 1.5
    assert killed == ["stuck"]
    assert killed_pids == [child.pid]


def test_begin_shutdown_ends_a_live_status_stream(host, monkeypatch):
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: True)
    monkeypatch.setattr(ps, "_SSE_POLL_SECONDS", 0.2)
    monkeypatch.setattr(ps.runtime, "gthread_active", lambda: True)
    stream_registry._reset_for_tests()
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(ps.python_strategy_bp)
    stream = app.test_client().get("/python/api/events", buffered=False)
    assert stream.status_code == 200

    def drain():
        return list(stream.response)

    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(drain)
        time.sleep(0.3)
        assert not task.done()
        ps.begin_shutdown(budget_s=1)
        chunks = task.result(timeout=6)

    assert chunks, "the stream never sent its first event"
    stream.close()
    stream_registry._reset_for_tests()


def test_the_hook_acts_only_under_gthread(host, monkeypatch):
    calls = []
    monkeypatch.setattr(ps, "begin_shutdown", lambda *a, **k: calls.append("python"))
    monkeypatch.setattr(service, "begin_shutdown", lambda *a, **k: calls.append("openscript"))

    monkeypatch.setattr(ps.runtime, "gthread_active", lambda: False)
    ps._shutdown_hook()
    service._shutdown_hook()
    assert calls == [], "eventlet and the development server are left to atexit"

    monkeypatch.setattr(ps.runtime, "gthread_active", lambda: True)
    ps._shutdown_hook()
    service._shutdown_hook()
    assert calls == ["python", "openscript"]


def test_both_hooks_are_registered_early():
    early = {hook.name for hook in shutdown_mod._hooks if hook.early}
    assert {"python_strategy", "openscript_runs"} <= early
    # A test elsewhere may reload a module and register its hook again; a
    # repeat finds nothing left to stop, so each name is counted once.
    budgets = {
        hook.name: hook.budget_s
        for hook in shutdown_mod._hooks
        if hook.name in ("python_strategy", "openscript_runs")
    }
    assert sum(budgets.values()) <= shutdown_mod.SHUTDOWN_BUDGET_S


@pytest.fixture
def runs(monkeypatch):
    monkeypatch.setattr(service, "_SHUTTING_DOWN", threading.Event())
    children = {f"openscript_r{i}": FakeChild(3_200_000 + i) for i in range(2)}
    monkeypatch.setattr(
        service,
        "RUNNING_RUNS",
        {run_id: {"process": child, "pid": child.pid} for run_id, child in children.items()},
    )
    monkeypatch.setattr(service, "STOPPING_RUNS", set())
    monkeypatch.setattr(service, "STARTING_RUNS", set())
    return children


def test_openscript_begin_shutdown_pauses_every_run_and_refuses_starts(runs, monkeypatch):
    asked = []

    def fake_stop(run_id, forget=True, close=False):
        time.sleep(0.3)
        asked.append((run_id, forget, close))
        runs[run_id].alive = False
        return True, "paused"

    monkeypatch.setattr(service, "stop_run", fake_stop)

    started = time.monotonic()
    killed = service.begin_shutdown(budget_s=5)

    assert killed == []
    assert time.monotonic() - started < 0.9, "the runs were stopped one after another"
    # Paused, never closed, and not forgotten: the worker going down is not the
    # trader deciding to stop, so the record that brings them back is kept.
    assert sorted(asked) == sorted((run_id, False, False) for run_id in runs)

    ok, message = service.start_run("x.oscript", symbol="SBIN", exchange="NSE", interval="1m")
    assert (ok, message) == (False, service.SHUTTING_DOWN_MESSAGE)
