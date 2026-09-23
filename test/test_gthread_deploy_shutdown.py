"""The launcher's hooks under a real gunicorn: a stop drains and then cleans up.

Measured before the hooks existed: a gthread worker told to stop waits for
every open connection to finish, up to ``--graceful-timeout``. A Socket.IO
long-poll only finishes at its next ping (25 s) and an idle keep-alive
connection only when ``--keep-alive`` runs out, so with a browser tab open
every stop took the whole window, the arbiter then killed the worker, and
``worker_exit`` (where OpenAlgo's cleanup runs) never ran.

These tests boot gunicorn on a tiny Flask-SocketIO app with the real hooks
file, hold polling clients and an idle keep-alive connection open, send
SIGTERM and time the exit. ``utils.runtime`` and ``utils.shutdown`` are
stand-ins that leave marker files, so the test sees what the hooks called
without starting OpenAlgo. The control case runs the same stop without the
drain and must take the full window, so the fast case cannot pass by luck.

Linux with gunicorn installed only (the production server); skipped elsewhere.
"""

from __future__ import annotations

import http.client
import importlib.util
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "install" / "lib" / "gunicorn_hooks.py"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or importlib.util.find_spec("gunicorn") is None,
    reason="needs gunicorn on Linux (the production server)",
)

GRACEFUL = 8

APP = textwrap.dedent(
    """
    import os, signal, time
    from flask import Flask
    from flask_socketio import SocketIO

    def mark(name):
        with open(os.path.join(os.environ["HOOK_MARKS"], name), "a") as handle:
            handle.write(f"{time.time()}\\n")

    app = Flask(__name__)
    socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

    @app.route("/ping")
    def ping():
        return "ok"

    if os.environ.get("CHAIN_HANDLER"):
        # What utils/ngrok_manager does at import: its own handler, then gunicorn's.
        previous = signal.getsignal(signal.SIGTERM)

        def chained(sig, frame):
            mark("app_handler")
            previous(sig, frame)

        signal.signal(signal.SIGTERM, chained)
    """
)

STUB_RUNTIME = textwrap.dedent(
    """
    import os

    def register_gunicorn_worker(worker):
        path = os.path.join(os.environ["HOOK_MARKS"], "registered")
        with open(path, "w") as handle:
            handle.write(type(worker).__module__)
    """
)

STUB_SHUTDOWN = textwrap.dedent(
    """
    import os, time

    def _mark(name):
        with open(os.path.join(os.environ["HOOK_MARKS"], name), "a") as handle:
            handle.write(f"{time.time()}\\n")

    def begin_drain():
        _mark("drain")

    def shutdown_runtime():
        _mark("shutdown")
    """
)

#: The control: the same hooks without the drain (no post_worker_init).
CONTROL = textwrap.dedent(
    f"""
    import importlib.util
    _spec = importlib.util.spec_from_file_location("hooks", {str(HOOKS)!r})
    _hooks = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_hooks)
    worker_exit = _hooks.worker_exit
    """
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    def __init__(self, tmp_path: Path, worker: str, config: Path, **env):
        self.app_dir = tmp_path / "app"
        self.app_dir.mkdir()
        (self.app_dir / "fixture_app.py").write_text(APP)
        # A stray config gunicorn would auto-load without -c: it must be ignored.
        (self.app_dir / "gunicorn.conf.py").write_text("workers = 3\n")
        stubs = tmp_path / "stubs" / "utils"
        stubs.mkdir(parents=True)
        (stubs / "__init__.py").write_text("")
        (stubs / "runtime.py").write_text(STUB_RUNTIME)
        (stubs / "shutdown.py").write_text(STUB_SHUTDOWN)
        self.marks = tmp_path / "marks"
        self.marks.mkdir()
        self.port = _free_port()
        environ = dict(os.environ)
        environ.pop("GUNICORN_CMD_ARGS", None)
        environ["PYTHONPATH"] = os.pathsep.join([str(tmp_path / "stubs"), str(self.app_dir)])
        environ["HOOK_MARKS"] = str(self.marks)
        environ.update(env)
        args = [sys.executable, "-m", "gunicorn", "-c", str(config), "--worker-class", worker]
        if worker == "gthread":
            args += ["--threads", "4"]
        args += [
            "--workers",
            "1",
            "--bind",
            f"127.0.0.1:{self.port}",
            "--graceful-timeout",
            str(GRACEFUL),
            "--keep-alive",
            "75",
            "--no-control-socket",
            "--log-level",
            "info",
            "fixture_app:app",
        ]
        self.log = tmp_path / "gunicorn.log"
        self.process = subprocess.Popen(
            args,
            cwd=self.app_dir,
            env=environ,
            stdout=self.log.open("w"),
            stderr=subprocess.STDOUT,
        )
        self.base = f"http://127.0.0.1:{self.port}"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
                conn.request("GET", "/ping")
                if conn.getresponse().status == 200:
                    conn.close()
                    break
            except OSError:
                time.sleep(0.2)
        else:
            self.process.kill()
            raise AssertionError("gunicorn did not start:\n" + self.log.read_text())
        # post_worker_init runs just after the app loads; give it a moment.
        deadline = time.monotonic() + 10
        while not (self.marks / "registered").exists() and time.monotonic() < deadline:
            time.sleep(0.1)

    def workers(self) -> int:
        import psutil

        return len(psutil.Process(self.process.pid).children())

    def hold_connections(self) -> list:
        import socketio

        held = []
        for _ in range(3):
            client = socketio.Client(reconnection=False)
            client.connect(self.base, transports=["polling"], wait_timeout=10)
            held.append(client)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("GET", "/ping")
        conn.getresponse().read()
        held.append(conn)  # idle keep-alive connection
        time.sleep(1)  # let each client park its long-poll
        return held

    def stop(self) -> float:
        started = time.monotonic()
        self.process.send_signal(signal.SIGTERM)
        try:
            self.process.wait(timeout=GRACEFUL + 20)
        except subprocess.TimeoutExpired:
            self.process.kill()
            raise AssertionError("gunicorn ignored SIGTERM:\n" + self.log.read_text()) from None
        return time.monotonic() - started

    def marked(self, name: str) -> bool:
        return (self.marks / name).exists()


def _release(held):
    for item in held:
        try:
            (getattr(item, "disconnect", None) or item.close)()
        except Exception:
            pass


def test_the_drain_lets_a_gthread_stop_finish_and_clean_up(tmp_path):
    server = Server(tmp_path, "gthread", HOOKS)
    assert server.workers() == 1, "a stray gunicorn.conf.py was loaded"
    assert (server.marks / "registered").read_text() == "gunicorn.workers.gthread"
    held = server.hold_connections()
    try:
        elapsed = server.stop()
    finally:
        _release(held)
    log = server.log.read_text()
    assert elapsed < GRACEFUL - 3, f"stop took {elapsed:.1f}s\n{log}"
    assert server.marked("drain")
    assert server.marked("shutdown"), log
    assert "Closed 3 browser session" in log


def test_without_the_drain_the_same_stop_waits_out_the_window(tmp_path):
    control = tmp_path / "control_hooks.py"
    control.write_text(CONTROL)
    (tmp_path / "run").mkdir()
    server = Server(tmp_path / "run", "gthread", control)
    held = server.hold_connections()
    try:
        elapsed = server.stop()
    finally:
        _release(held)
    assert elapsed >= GRACEFUL - 1, (
        f"the control stopped in {elapsed:.1f}s: the test proves nothing"
    )


def test_a_handler_the_app_chained_in_front_still_runs_first(tmp_path):
    server = Server(tmp_path, "gthread", HOOKS, CHAIN_HANDLER="1")
    held = server.hold_connections()
    try:
        elapsed = server.stop()
    finally:
        _release(held)
    assert server.marked("app_handler")
    assert server.marked("drain") and server.marked("shutdown")
    assert elapsed < GRACEFUL - 3


@pytest.mark.skipif(importlib.util.find_spec("eventlet") is None, reason="eventlet not installed")
def test_the_eventlet_worker_boots_and_stops_with_the_same_hooks(tmp_path):
    server = Server(tmp_path, "eventlet", HOOKS)
    assert server.workers() == 1
    assert (server.marks / "registered").read_text() == "gunicorn.workers.geventlet"
    elapsed = server.stop()
    log = server.log.read_text()
    assert elapsed < GRACEFUL + 5, log
    assert server.marked("drain")
    assert server.marked("shutdown"), log
    assert "Traceback" not in log
