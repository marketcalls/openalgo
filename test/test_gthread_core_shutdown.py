"""The app side of a graceful stop under the gthread worker.

Each open Socket.IO session holds a gthread worker thread. When gunicorn is
told to stop, begin_drain() records the request (it runs in a signal handler,
so it may only assign); the drain watcher started by app.py notices and ends
the sessions while the graceful window is still open, so the stop does not
turn into a kill that skips the teardown. Under eventlet and on the dev
server the watcher does not start.

shutdown_runtime() itself is the foundation's: idempotent across racing
callers, which is asserted here once more because the gunicorn hooks and a
signal can both reach it.
"""

from __future__ import annotations

import threading
import time

import pytest

import utils.shutdown as shutdown
from utils import runtime, stream_registry


@pytest.fixture
def fresh_drain(monkeypatch):
    stream_registry._reset_for_tests()
    monkeypatch.setattr(shutdown, "_drain_watcher_started", False)
    monkeypatch.setattr(shutdown, "DRAIN_WATCH_SECONDS", 0.02)
    yield
    stream_registry._reset_for_tests()


def test_a_drain_closes_the_browser_connections(fresh_drain, monkeypatch):
    closed = threading.Event()
    monkeypatch.setattr(shutdown, "close_socketio_sessions", lambda: closed.set() or 3)
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)

    assert shutdown.start_drain_watcher() is True
    assert shutdown.start_drain_watcher() is True  # idempotent
    time.sleep(0.1)
    assert not closed.is_set()

    shutdown.begin_drain()
    assert closed.wait(5), "the sessions were not closed when the drain began"


def test_eventlet_and_the_dev_server_start_no_watcher(fresh_drain, monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    assert shutdown.start_drain_watcher() is False
    assert shutdown._drain_watcher_started is False


def test_closing_sessions_asks_engineio_to_disconnect_everyone(monkeypatch):
    from extensions import socketio

    calls = []

    class FakeEio:
        sockets = {"a": object(), "b": object()}

        def disconnect(self, sid=None):
            calls.append(sid)

    monkeypatch.setattr(socketio, "server", type("S", (), {"eio": FakeEio()})(), raising=False)
    assert shutdown.close_socketio_sessions() == 2
    assert calls == [None]


def test_racing_shutdown_callers_run_the_teardown_once(monkeypatch):
    ran = []
    monkeypatch.setattr(shutdown, "_shutdown_done", False)
    for name in (
        "_stop_health_collector",
        "_stop_flow_scheduler",
        "_stop_historify_scheduler",
        "_stop_chartink_scheduler",
        "_stop_python_strategy_scheduler",
        "_stop_squareoff_scheduler",
        "_stop_strategy_module",
        "_stop_websocket_proxy",
        "_remove_all_scoped_sessions",
    ):
        monkeypatch.setattr(shutdown, name, lambda name=name: ran.append(name))
    monkeypatch.setattr(shutdown, "_hooks", [])
    barrier = threading.Barrier(4)

    def caller():
        barrier.wait()
        shutdown.shutdown_runtime()

    threads = [threading.Thread(target=caller) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert len(ran) == len(set(ran)) == 9
    stream_registry._reset_for_tests()
