"""The admin runtime report names the real web server and says what to do.

Before this change the report inferred the server from eventlet's patching
alone, so a gthread production server described itself as ``flask-dev``, and
it had no view of the thread budget or of a switch that was asked for in
.env but not applied. Every figure here is read, never imported: the report
must not put eventlet into ``sys.modules`` on a server that does not use it.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class _Cfg:
    def __init__(self, threads, workers=1, graceful_timeout=30, worker_class_str="gthread"):
        self.threads = threads
        self.workers = workers
        self.graceful_timeout = graceful_timeout
        self.worker_class_str = worker_class_str


def _worker_type(module: str):
    """A stand-in class whose module is the gunicorn worker module named."""
    return type("FakeWorker", (), {"__module__": module})


@pytest.fixture
def report(monkeypatch, tmp_path):
    """blueprints.admin with a clean runtime registration and a private .env."""
    from blueprints import admin
    from utils import runtime

    monkeypatch.setattr(runtime, "_registered", None)
    monkeypatch.setattr(runtime, "_worker_ref", None)
    for key in (
        "OPENALGO_WORKER_CLASS",
        "OPENALGO_LAUNCHER_VERSION",
        "OPENALGO_REQUESTED_WORKER_CLASS",
        "OPENALGO_EFFECTIVE_WORKER_CLASS",
        "OPENALGO_EFFECTIVE_THREADS",
        "APP_MODE",
    ):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("APP_KEY = 'x'\n", encoding="utf-8")
    monkeypatch.setattr(admin, "_resolve_env_path", lambda: env_file)
    return admin, runtime, env_file


def _register(runtime, module, cfg, **attrs):
    worker = _worker_type(module)()
    worker.cfg = cfg
    for name, value in attrs.items():
        setattr(worker, name, value)
    runtime.register_gunicorn_worker(worker)
    return worker


def test_the_report_never_imports_eventlet(tmp_path):
    """A stub eventlet sits first on sys.path; building the report must not load it."""
    stub = tmp_path / "stub" / "eventlet"
    stub.mkdir(parents=True)
    (stub / "__init__.py").write_text("raise ImportError('the report imported eventlet')\n")
    (stub / "patcher.py").write_text("raise ImportError('the report imported eventlet.patcher')\n")
    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(tmp_path / "stub")!r})
        sys.path.insert(1, {str(ROOT)!r})
        import blueprints.admin as admin
        info = admin._runtime_info()
        assert "eventlet" not in sys.modules
        assert "eventlet.patcher" not in sys.modules
        assert info["worker_class"] == "dev", info
        assert info["wsgi_hint"] == "flask-dev", info
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=180
    )
    assert "OK" in result.stdout, result.stdout[-2000:] + result.stderr[-4000:]


def test_the_dev_server_reports_what_it_did_before(report):
    admin, _runtime, _env = report
    info = admin._runtime_info()
    assert info["eventlet_active"] is False
    assert info["wsgi_hint"] == "flask-dev"
    assert info["worker_class"] == "dev"
    assert info["configured_threads"] is None
    assert info["started_by_launcher"] is None
    assert info["notes"] == []


def test_a_gthread_worker_reports_its_budget_and_launcher(report, monkeypatch):
    admin, runtime, env_file = report
    env_file.write_text("OPENALGO_WORKER_CLASS = 'gthread'\n", encoding="utf-8")
    monkeypatch.setenv("OPENALGO_LAUNCHER_VERSION", "1")
    monkeypatch.setenv("OPENALGO_REQUESTED_WORKER_CLASS", "gthread")
    monkeypatch.setenv("OPENALGO_EFFECTIVE_WORKER_CLASS", "gthread")
    monkeypatch.setenv("OPENALGO_EFFECTIVE_THREADS", "4")
    release = threading.Event()
    pool = ThreadPoolExecutor(max_workers=4)
    try:
        for _ in range(2):
            pool.submit(release.wait, 10)
        worker = _register(
            runtime, "gunicorn.workers.gthread", _Cfg(threads=4), tpool=pool, nr_conns=3
        )
        info = admin._runtime_info()
    finally:
        release.set()
        pool.shutdown(wait=True)
    assert worker is not None
    assert info["worker_class"] == "gthread"
    assert info["wsgi_hint"] == "gunicorn-gthread"
    assert info["configured_threads"] == 4
    assert info["configured_workers"] == 1
    assert info["graceful_timeout"] == 30
    assert info["launcher"]["version"] == "1"
    assert info["started_by_launcher"] is True
    assert info["thread_pool"]["spawned"] == 2
    assert info["thread_pool"]["open_connections"] == 3
    assert info["notes"] == []


def test_waiting_requests_are_explained(report, monkeypatch):
    admin, runtime, env_file = report
    env_file.write_text("OPENALGO_WORKER_CLASS = 'gthread'\n", encoding="utf-8")
    monkeypatch.setenv("OPENALGO_LAUNCHER_VERSION", "1")
    release = threading.Event()
    running = threading.Event()
    pool = ThreadPoolExecutor(max_workers=1)

    def hold():
        running.set()
        release.wait(10)

    try:
        pool.submit(hold)
        assert running.wait(5)
        pool.submit(release.wait, 10)  # queued: nothing free to run it
        # Kept referenced: the registry holds the worker weakly, as gunicorn's is.
        worker = _register(
            runtime, "gunicorn.workers.gthread", _Cfg(threads=1), tpool=pool, nr_conns=2
        )
        info = admin._runtime_info()
        del worker
    finally:
        release.set()
        pool.shutdown(wait=True)
    assert info["thread_pool"]["waiting"] == 1
    assert any("request slot is busy" in note for note in info["notes"]), info["notes"]
    assert any("OPENALGO_WORKER_CLASS = 'eventlet'" in note for note in info["notes"])


def test_a_switch_asked_for_but_not_applied_is_explained(report):
    admin, runtime, env_file = report
    env_file.write_text("OPENALGO_WORKER_CLASS = 'gthread'\n", encoding="utf-8")
    _register(runtime, "gunicorn.workers.geventlet", _Cfg(threads=1, worker_class_str="eventlet"))
    info = admin._runtime_info()
    assert info["worker_class"] == "eventlet"
    assert info["requested_worker_class"] == "gthread"
    assert info["started_by_launcher"] is False
    assert any("switch-worker.sh" in note for note in info["notes"]), info["notes"]


def test_a_change_made_after_start_is_pending(report, monkeypatch):
    admin, runtime, env_file = report
    monkeypatch.setenv("OPENALGO_LAUNCHER_VERSION", "1")
    monkeypatch.setenv("OPENALGO_REQUESTED_WORKER_CLASS", "gthread")
    monkeypatch.setenv("OPENALGO_EFFECTIVE_WORKER_CLASS", "gthread")
    env_file.write_text("OPENALGO_WORKER_CLASS = 'eventlet'\n", encoding="utf-8")
    _register(runtime, "gunicorn.workers.gthread", _Cfg(threads=64))
    info = admin._runtime_info()
    assert any("Restart OpenAlgo after 23:30 IST" in note for note in info["notes"]), info["notes"]


def test_the_default_eventlet_server_gets_no_notes(report):
    admin, runtime, _env = report
    _register(runtime, "gunicorn.workers.geventlet", _Cfg(threads=1, worker_class_str="eventlet"))
    info = admin._runtime_info()
    assert info["worker_class"] == "eventlet"
    assert info["wsgi_hint"] == "gunicorn-eventlet"
    assert info["configured_threads"] is None
    assert info["notes"] == []


def test_the_rendered_report_lists_the_web_server(report, monkeypatch):
    admin, runtime, env_file = report
    env_file.write_text("OPENALGO_WORKER_CLASS = 'gthread'\n", encoding="utf-8")
    _register(runtime, "gunicorn.workers.geventlet", _Cfg(threads=1, worker_class_str="eventlet"))
    payload = {"runtime": admin._runtime_info()}
    text = admin._render_report(payload, None, None, "md")
    assert "**Web server:** eventlet" in text
    assert "**Web server in .env:** gthread" in text
    assert "**Started by launcher:** False" in text
    assert "Note: Your .env asks for the gthread web server" in text


def test_the_report_carries_the_proxy_status_when_the_proxy_runs_here(report, monkeypatch):
    """The card's "Market data proxy status" row read a field the server never
    sent, so a proxy that had died (subscribe works, no ticks) never showed."""
    import types

    admin, _runtime, _env = report
    fake = types.ModuleType("websocket_proxy.app_integration")
    fake.proxy_status = lambda: {
        "mode": "subprocess",
        "pid": 4242,
        "alive": False,
        "restarts": 2,
        "last_exit_code": 1,
        "last_restart_at": 1_700_000_000.0,
    }
    monkeypatch.setitem(sys.modules, "websocket_proxy.app_integration", fake)

    info = admin._runtime_info()

    assert info["websocket_proxy"] == {
        "mode": "subprocess",
        "pid": 4242,
        "alive": False,
        "restarts": 2,
        "last_exit_code": 1,
        "last_restart_at": 1_700_000_000.0,
    }
    text = admin._render_report({"runtime": info}, None, None, "md")
    assert "**Market data proxy running:** False" in text
    assert "**Market data proxy restarts:** 2" in text


def test_the_report_has_no_proxy_status_when_the_proxy_is_elsewhere(report, monkeypatch):
    admin, _runtime, _env = report
    monkeypatch.delitem(sys.modules, "websocket_proxy.app_integration", raising=False)

    info = admin._runtime_info()

    assert "websocket_proxy" in info
    assert info["websocket_proxy"] is None
