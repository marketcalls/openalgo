"""Where the websocket proxy runs, how it is kept running, and who owns SIGTERM.

The topology used to follow whether eventlet was active, so the gthread worker
would have run the whole proxy (asyncio loop, broker adapters, the ZeroMQ
bind) inside the trading worker. It is now decided by resolve_proxy_mode(),
whose answer under eventlet is unchanged: gunicorn gives a child process,
Docker gives external, the dev server gives a thread.

Under the gthread worker only, the child is supervised and exits by itself
when orphaned. And under gunicorn nothing replaces gunicorn's graceful SIGTERM
with a handler that calls os._exit(0), which used to kill in-flight requests,
an order already sent to the broker among them.
"""

from __future__ import annotations

import ast
import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

import utils.ngrok_manager as ngrok_manager
import websocket_proxy.app_integration as ai
import websocket_proxy.server as proxy_server
from utils import runtime

REPO = Path(__file__).resolve().parents[1]


_real_exists = os.path.exists


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv(ai.PROXY_MODE_ENV, raising=False)
    monkeypatch.delenv("APP_MODE", raising=False)
    monkeypatch.setattr(
        ai.os.path, "exists", lambda path: False if path == "/.dockerenv" else _real_exists(path)
    )
    monkeypatch.setattr(runtime, "_registered", None)
    monkeypatch.delitem(sys.modules, "gunicorn.workers.base", raising=False)


def _pretend_gunicorn(monkeypatch):
    monkeypatch.setitem(sys.modules, "gunicorn.workers.base", types.ModuleType("gunicorn.workers.base"))


# --- resolve_proxy_mode --------------------------------------------------------


def test_the_dev_server_runs_the_proxy_in_a_thread(clean_env):
    assert ai.resolve_proxy_mode() == "thread"


def test_any_gunicorn_worker_runs_the_proxy_as_a_child(clean_env, monkeypatch):
    _pretend_gunicorn(monkeypatch)
    # With or without eventlet patching: before the fix a gthread worker got
    # "thread", which put the proxy inside the trading worker.
    monkeypatch.setattr(runtime, "is_monkey_patched", lambda module="thread": False)
    assert ai.resolve_proxy_mode() == "subprocess"
    monkeypatch.setattr(runtime, "is_monkey_patched", lambda module="thread": True)
    assert ai.resolve_proxy_mode() == "subprocess"


def test_docker_leaves_the_proxy_to_start_sh(clean_env, monkeypatch):
    _pretend_gunicorn(monkeypatch)
    monkeypatch.setenv("APP_MODE", "standalone")
    assert ai.resolve_proxy_mode() == "external"
    monkeypatch.delenv("APP_MODE")
    monkeypatch.setattr(ai.os.path, "exists", lambda path: path == "/.dockerenv")
    assert ai.os.path.exists("/.dockerenv") is True
    assert ai.resolve_proxy_mode() == "external"


def test_the_launcher_override_wins_and_nonsense_is_ignored(clean_env, monkeypatch):
    _pretend_gunicorn(monkeypatch)
    monkeypatch.setenv(ai.PROXY_MODE_ENV, "external")
    assert ai.resolve_proxy_mode() == "external"
    monkeypatch.setenv(ai.PROXY_MODE_ENV, "'Thread'")
    assert ai.resolve_proxy_mode() == "thread"
    monkeypatch.setenv(ai.PROXY_MODE_ENV, "sideways")
    assert ai.resolve_proxy_mode() == "subprocess"


def test_app_py_no_longer_decides_the_topology_itself():
    source = (REPO / "app.py").read_text(encoding="utf-8")
    assert "/.dockerenv" not in source
    assert "start_websocket_proxy(app)" in source


# --- signals (core-05) -----------------------------------------------------------


class RecordingSignalModule:
    """Stands in for the signal module inside the two modules under test only.

    Patching signal.signal itself would also catch pytest's own handlers.
    """

    SIGINT = signal.SIGINT
    SIGTERM = getattr(signal, "SIGTERM", 15)
    SIG_DFL = signal.SIG_DFL

    def __init__(self):
        self.calls = []

    def signal(self, signum, handler):
        self.calls.append(signum)

    def getsignal(self, signum):
        return signal.SIG_DFL


@pytest.fixture
def recorded_signals(monkeypatch):
    fake = RecordingSignalModule()
    monkeypatch.setattr(ai, "signal", fake)
    monkeypatch.setattr(ngrok_manager, "signal", fake)
    return fake.calls


class FakeProc:
    def __init__(self, pid=4242):
        self.pid = pid
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.returncode = -9


@pytest.fixture
def proxy_state(monkeypatch):
    from utils import stream_registry

    stream_registry._reset_for_tests()
    for name, value in (
        ("_websocket_subprocess", None),
        ("_supervisor_thread", None),
        ("_stopping", False),
        ("_restarts", 0),
        ("_last_exit_code", None),
        ("_last_restart_at", None),
        ("_resolved_mode", None),
    ):
        monkeypatch.setattr(ai, name, value)
    yield ai
    ai._stopping = True
    thread = ai._supervisor_thread
    if thread is not None:
        thread.join(5)


def test_under_gunicorn_no_handler_replaces_the_graceful_stop(
    clean_env, monkeypatch, recorded_signals, proxy_state
):
    _pretend_gunicorn(monkeypatch)
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    monkeypatch.setattr(ai, "_launch_child", lambda: FakeProc())
    monkeypatch.setattr(ngrok_manager, "_ngrok_initialized", False)

    ai.start_websocket_server("subprocess")
    ngrok_manager.setup_ngrok_handlers()
    ai._install_dev_signal_handlers()

    # Before the fix both modules installed SIGINT and SIGTERM handlers here,
    # the proxy's ending in os._exit(0).
    assert recorded_signals == []


def test_the_dev_server_keeps_its_ctrl_c_handlers(clean_env, monkeypatch, recorded_signals):
    monkeypatch.setattr(ngrok_manager, "_ngrok_initialized", False)
    monkeypatch.setattr(ngrok_manager.atexit, "register", lambda fn: None)
    ngrok_manager.setup_ngrok_handlers()
    ai._install_dev_signal_handlers()
    assert signal.SIGINT in recorded_signals


# --- supervision (gthread only) ----------------------------------------------------


QUICK_EXIT = [sys.executable, "-c", "import sys; sys.exit(3)"]


def _speed_up(monkeypatch):
    monkeypatch.setattr(ai, "SPAWN_COMMAND", QUICK_EXIT)
    monkeypatch.setattr(ai, "SUPERVISOR_POLL_SECONDS", 0.05)
    monkeypatch.setattr(ai, "RESTART_BACKOFF_SECONDS", (0.05,))
    monkeypatch.setattr(ai, "SLOW_RETRY_SECONDS", 0.05)
    monkeypatch.setattr(ai, "_ports_free", lambda: True)
    monkeypatch.setattr(ai.atexit, "register", lambda fn: None)


def test_gthread_restarts_a_child_that_exits_until_shutdown(monkeypatch, proxy_state):
    _speed_up(monkeypatch)
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)

    ai._spawn_websocket_subprocess()
    deadline = time.monotonic() + 30
    while ai.proxy_status()["restarts"] < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    status = ai.proxy_status()
    assert status["restarts"] >= 2
    assert status["last_exit_code"] == 3

    ai._terminate_websocket_subprocess()
    ai._supervisor_thread.join(5)
    assert not ai._supervisor_thread.is_alive()
    settled = ai.proxy_status()["restarts"]
    time.sleep(0.3)
    assert ai.proxy_status()["restarts"] == settled


def test_a_restart_that_cannot_launch_is_tried_again(monkeypatch, proxy_state):
    _speed_up(monkeypatch)
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    crashed = FakeProc(pid=1)
    crashed.returncode = 1
    healthy = FakeProc(pid=2)
    launches = [crashed, None, None, healthy]

    def launch():
        return launches.pop(0) if launches else healthy

    monkeypatch.setattr(ai, "_launch_child", launch)
    ai._spawn_websocket_subprocess()
    deadline = time.monotonic() + 30
    while ai._websocket_subprocess is not healthy and time.monotonic() < deadline:
        time.sleep(0.05)

    # Two launches failed outright; the supervisor kept trying until one ran.
    assert ai._websocket_subprocess is healthy
    assert ai.proxy_status()["restarts"] == 3
    ai._terminate_websocket_subprocess()


def test_eventlet_and_the_dev_server_do_not_supervise(monkeypatch, proxy_state):
    _speed_up(monkeypatch)
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)

    ai._spawn_websocket_subprocess()
    time.sleep(0.5)
    assert ai._supervisor_thread is None
    assert ai.proxy_status()["restarts"] == 0


def test_the_child_is_told_its_parent_only_under_gthread(monkeypatch, proxy_state):
    seen = []

    def fake_popen(cmd, **kwargs):
        seen.append(kwargs.get("env"))
        return FakeProc()

    monkeypatch.setattr(ai.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    ai._launch_child()
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    ai._launch_child()

    assert seen[0] is None  # inherits the environment, exactly as before
    assert seen[1][ai.PARENT_PID_ENV] == str(os.getpid())


def test_terminate_stops_a_child_without_a_green_wait(monkeypatch, proxy_state):
    proc = FakeProc()
    monkeypatch.setattr(ai, "_websocket_subprocess", proc)
    ai._terminate_websocket_subprocess()
    assert proc.terminated is True
    assert ai._websocket_subprocess is None
    assert ai._stopping is True


# --- orphan exit -------------------------------------------------------------------


def test_the_orphan_watch_stops_the_proxy_when_its_parent_is_gone(monkeypatch):
    monkeypatch.setattr(proxy_server, "ORPHAN_CHECK_SECONDS", 0.02)
    proxy = types.SimpleNamespace(running=True)

    async def run():
        task = asyncio.create_task(proxy_server._exit_when_orphaned(proxy, os.getppid() + 12345))
        for _ in range(100):
            await asyncio.sleep(0.02)
            if not proxy.running:
                break
        task.cancel()

    asyncio.run(run())
    assert proxy.running is False


def test_the_orphan_watch_leaves_a_child_with_a_live_parent_alone(monkeypatch):
    monkeypatch.setattr(proxy_server, "ORPHAN_CHECK_SECONDS", 0.02)
    proxy = types.SimpleNamespace(running=True)

    async def run():
        task = asyncio.create_task(proxy_server._exit_when_orphaned(proxy, os.getppid()))
        await asyncio.sleep(0.2)
        task.cancel()

    asyncio.run(run())
    assert proxy.running is True


def test_no_parent_pid_means_no_watch(monkeypatch):
    monkeypatch.delenv(proxy_server.PARENT_PID_ENV, raising=False)
    assert proxy_server._expected_parent_pid() is None


@pytest.mark.skipif(os.name != "posix", reason="orphan re-parenting is POSIX behaviour")
def test_a_real_orphaned_proxy_exits_by_itself(tmp_path):
    import socket

    def free_port():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    pid_file = tmp_path / "child.pid"
    launcher = (
        "import os, subprocess, sys\n"
        "env = dict(os.environ)\n"
        f"env['{proxy_server.PARENT_PID_ENV}'] = str(os.getpid())\n"
        "child = subprocess.Popen([sys.executable, '-m', 'websocket_proxy.server'], env=env)\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "import time; time.sleep(4)\n"
        "os._exit(0)\n"
    )
    env = dict(os.environ)
    env["WEBSOCKET_PORT"] = str(free_port())
    env["ZMQ_PORT"] = str(free_port())
    parent = subprocess.Popen([sys.executable, "-c", launcher], cwd=str(REPO), env=env)
    parent.wait(30)
    child_pid = int(pid_file.read_text())

    deadline = time.monotonic() + 15
    alive = True
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            alive = False
            break
        time.sleep(0.2)
    if alive:
        os.kill(child_pid, signal.SIGKILL)
    assert alive is False, "the orphaned proxy kept running and would hold its ports"


# --- messaging-04, the app.py half ---------------------------------------------------


def test_the_telegram_auto_start_has_one_entry_point():
    source = (REPO / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    body = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_init_databases_and_schedulers":
            body = ast.get_source_segment(source, node)
    assert body is not None
    start = body.index("Auto-start Telegram bot")
    block = body[start:]
    assert "initialize_bot_sync" in block
    assert "new_event_loop" not in block
    assert "use_sync_initialization" not in block
    assert "sys.modules" not in block


def test_supervisor_thread_is_a_plain_thread():
    # Green under eventlet (never used there), real under gthread.
    assert ai.threading is threading
