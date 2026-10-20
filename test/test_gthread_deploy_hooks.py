"""The launcher's gunicorn hooks, one piece at a time, with stand-in workers.

``install/lib/gunicorn_hooks.py`` is executed by gunicorn in the arbiter
before the worker class is loaded (and loading the eventlet worker patches
the process), so it must import nothing at module scope. Its hooks must never
fail a worker, must call whatever SIGTERM handler is already in place first
and unchanged, and must run ``shutdown_runtime`` once the app has loaded.
The same hooks under a real gunicorn are in test_gthread_deploy_shutdown.py.
"""

from __future__ import annotations

import ast
import importlib.util
import signal
import threading
import time
from collections import deque
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "install" / "lib" / "gunicorn_hooks.py"

#: gunicorn setting names a config file could set by accident.
GUNICORN_SETTINGS = {
    "bind",
    "workers",
    "worker_class",
    "threads",
    "timeout",
    "graceful_timeout",
    "keepalive",
    "preload_app",
    "max_requests",
    "reload",
    "daemon",
    "raw_env",
    "worker_connections",
    "control_socket",
}


def _load():
    spec = importlib.util.spec_from_file_location("gunicorn_hooks_under_test", HOOKS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hooks = _load()


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, message):
        self.lines.append(("info", message))

    def warning(self, message):
        self.lines.append(("warning", message))


class _Cfg:
    threads = 4
    workers = 1
    graceful_timeout = 30
    worker_class_str = "gthread"


class _MethodQueue:
    def __init__(self):
        self.deferred = []

    def defer(self, callback, *args):
        self.deferred.append((callback, args))


def _worker(module="gunicorn.workers.gthread", **attrs):
    worker = type("Worker", (), {"__module__": module})()
    worker.cfg = _Cfg()
    worker.log = _Log()
    for name, value in attrs.items():
        setattr(worker, name, value)
    return worker


@pytest.fixture
def signals(monkeypatch):
    """Stand-ins for signal.getsignal and signal.signal, so pytest's own handler is untouched."""
    state = {"current": None, "installed": None}
    monkeypatch.setattr(signal, "getsignal", lambda sig: state["current"])

    def fake_signal(sig, handler):
        state["installed"] = handler
        return state["current"]

    monkeypatch.setattr(signal, "signal", fake_signal)
    if hasattr(signal, "siginterrupt"):
        monkeypatch.setattr(signal, "siginterrupt", lambda *args: None)
    return state


@pytest.fixture
def clean_runtime(monkeypatch):
    from utils import runtime

    monkeypatch.setattr(runtime, "_registered", None)
    monkeypatch.setattr(runtime, "_worker_ref", None)
    return runtime


def test_the_file_imports_nothing_and_sets_no_gunicorn_setting():
    tree = ast.parse(HOOKS.read_text(encoding="utf-8"))
    for node in tree.body:
        assert not isinstance(node, (ast.Import, ast.ImportFrom)), ast.dump(node)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {t.id for t in targets if isinstance(t, ast.Name)}
            assert not names & GUNICORN_SETTINGS, names
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert {"post_worker_init", "worker_exit", "worker_int"} <= defined


def test_post_worker_init_records_the_worker(signals, clean_runtime):
    worker = _worker()
    hooks.post_worker_init(worker)
    info = clean_runtime.registered_worker()
    assert info["worker_class"] == "gthread"
    assert info["threads"] == 4 and info["workers"] == 1 and info["graceful_timeout"] == 30


def test_a_bare_worker_raises_nothing(signals, clean_runtime):
    hooks.post_worker_init(object())
    hooks.worker_exit(None, object())
    hooks.worker_int(object())


def test_the_existing_handler_runs_first_then_the_drain(signals, clean_runtime, monkeypatch):
    from utils import shutdown

    calls = []
    signals["current"] = lambda sig, frame: calls.append("existing")
    monkeypatch.setattr(shutdown, "begin_drain", lambda: calls.append("begin_drain"))
    queue = _MethodQueue()
    worker = _worker(method_queue=queue)
    hooks.post_worker_init(worker)
    handler = signals["installed"]
    assert callable(handler)
    handler(signal.SIGTERM, None)
    assert calls == ["existing", "begin_drain"]
    assert [callback for callback, _args in queue.deferred] == [hooks._drain_connections]


def test_an_existing_handler_that_exits_still_exits(signals, clean_runtime, monkeypatch):
    from utils import shutdown

    calls = []

    def exits(sig, frame):
        raise SystemExit(0)

    signals["current"] = exits
    monkeypatch.setattr(shutdown, "begin_drain", lambda: calls.append("begin_drain"))
    worker = _worker(method_queue=_MethodQueue())
    hooks.post_worker_init(worker)
    with pytest.raises(SystemExit):
        signals["installed"](signal.SIGTERM, None)
    assert calls == []


def test_no_python_handler_means_nothing_is_wrapped(signals, clean_runtime):
    signals["current"] = signal.SIG_DFL
    hooks.post_worker_init(_worker())
    assert signals["installed"] is None


def test_the_eventlet_worker_gets_only_the_drain_flag(signals, clean_runtime, monkeypatch):
    """No method queue: the handler runs, the flag is set, nothing is scheduled."""
    from utils import shutdown

    calls = []
    signals["current"] = lambda sig, frame: calls.append("existing")
    monkeypatch.setattr(shutdown, "begin_drain", lambda: calls.append("begin_drain"))
    worker = _worker(module="gunicorn.workers.geventlet")
    hooks.post_worker_init(worker)
    signals["installed"](signal.SIGTERM, None)
    assert calls == ["existing", "begin_drain"]
    assert clean_runtime.registered_worker()["worker_class"] == "eventlet"


class _Conn:
    def __init__(self):
        self.timeout = 10**9


class _Session:
    def __init__(self, closed):
        self.closed = closed

    def close(self, wait=True, abort=False, reason=None):
        assert wait is False
        self.closed.append(self)


class _App:
    def __init__(self, sessions):
        server = type("S", (), {})()
        server.eio = type("E", (), {"sockets": {str(i): s for i, s in enumerate(sessions)}})()
        self.extensions = {"socketio": type("SIO", (), {"server": server})()}


def test_drain_expires_idle_connections_and_closes_browser_sessions():
    closed = []
    sessions = [_Session(closed) for _ in range(3)]
    keepalive = deque([_Conn(), _Conn()])
    pending = deque([_Conn()])
    worker = _worker(keepalived_conns=keepalive, pending_conns=pending, wsgi=_App(sessions))
    hooks._drain_connections(worker)
    assert [conn.timeout for conn in (*keepalive, *pending)] == [0, 0, 0]
    deadline = time.monotonic() + 5
    while len(closed) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sorted(map(id, closed)) == sorted(map(id, sessions))
    assert any("Closed 3 browser session" in message for _level, message in worker.log.lines)


def test_drain_tolerates_a_worker_without_those_attributes():
    hooks._drain_connections(_worker())
    hooks._drain_connections(_worker(wsgi=object()))


def test_sessions_are_closed_off_the_main_loop():
    """The disconnect handlers are app code: they must not run on gunicorn's loop."""
    seen = []

    class _Recorder(_Session):
        def close(self, wait=True, abort=False, reason=None):
            seen.append(threading.current_thread().name)

    worker = _worker(wsgi=_App([_Recorder([])]))
    hooks._drain_connections(worker)
    deadline = time.monotonic() + 5
    while not seen and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen == ["openalgo-drain-socketio"]


def test_shutdown_runs_only_once_the_app_has_loaded(monkeypatch):
    from utils import shutdown

    calls = []
    monkeypatch.setattr(shutdown, "shutdown_runtime", lambda: calls.append("shutdown"))
    hooks.worker_exit(None, _worker())
    hooks.worker_int(_worker())
    assert calls == []
    hooks.worker_exit(None, _worker(wsgi=object()))
    hooks.worker_int(_worker(wsgi=object()))
    assert calls == ["shutdown", "shutdown"]


def test_a_failing_shutdown_is_logged_not_raised(monkeypatch):
    from utils import shutdown

    def boom():
        raise RuntimeError("scheduler would not stop")

    monkeypatch.setattr(shutdown, "shutdown_runtime", boom)
    worker = _worker(wsgi=object())
    hooks.worker_exit(None, worker)
    assert any("did not complete" in message for _level, message in worker.log.lines)
