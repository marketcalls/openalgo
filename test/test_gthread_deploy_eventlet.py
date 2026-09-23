"""Under the eventlet worker, the deploy changes behave exactly as before.

eventlet stays the default web server, so the admin runtime report, the .env
lock and the launcher's hooks are exercised here under a real
``eventlet.monkey_patch()``, in a subprocess because patching is global and
cannot be undone (the same approach as test_eventlet_cross_thread_locks.py).
Each case also checks that the hub kept running: a ticker greenlet must make
progress while the code under test runs, because a greenlet that blocks the
hub is the failure the dev server can never show.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip(
    "eventlet",
    reason="eventlet is installed by the production installer, not by pyproject",
)

ROOT = Path(__file__).resolve().parents[1]

PREAMBLE = """
import eventlet
eventlet.monkey_patch()

import os, sys, threading, time
sys.path.insert(0, {root!r})

ticks = [0]


def _ticker():
    while True:
        ticks[0] += 1
        eventlet.sleep(0.01)


eventlet.spawn(_ticker)


def hub_alive(before, minimum=5):
    eventlet.sleep(0.1)
    return ticks[0] - before >= minimum
"""


def run(body: str, tmp_path: Path) -> subprocess.CompletedProcess:
    code = PREAMBLE.format(root=str(ROOT)) + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=ROOT,
        env={
            **os.environ,
            "HOOK_TMP": str(tmp_path),
            "LOG_DIR": str(tmp_path / "log"),
        },
    )


def test_the_child_really_runs_under_eventlet(tmp_path):
    """The control, so the rest of this file cannot pass on an unpatched interpreter."""
    result = run(
        """
        import eventlet.patcher
        from utils import runtime
        assert eventlet.patcher.is_monkey_patched("thread")
        assert runtime.is_monkey_patched() and runtime.worker_class() == "eventlet"
        assert type(threading.Lock()).__module__ != "_thread", "threading.Lock is still real"
        print("OK")
        """,
        tmp_path,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr[-3000:]


def test_the_runtime_report_is_what_it_was(tmp_path):
    result = run(
        """
        import blueprints.admin as admin
        before = ticks[0]
        started = time.monotonic()
        info = admin._runtime_info()
        elapsed = time.monotonic() - started
        assert info["eventlet_active"] is True, info
        assert info["wsgi_hint"] == "gunicorn-eventlet", info
        assert info["worker_class"] == "eventlet", info
        assert info["configured_threads"] is None and info["thread_pool"] is None, info
        assert info["notes"] == [], info
        assert elapsed < 5, elapsed
        assert hub_alive(before)
        print("OK")
        """,
        tmp_path,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr[-3000:]


def test_two_admin_saves_that_yield_mid_write_both_land(tmp_path):
    """The .env lock is green under eventlet and serialises two greenlets."""
    result = run(
        """
        from pathlib import Path
        import blueprints.admin as admin

        class Yielding(type(Path())):
            def read_text(self, *args, **kwargs):
                text = super().read_text(*args, **kwargs)
                eventlet.sleep(0.2)  # the other save gets the hub here
                return text

        def save_both(env_file):
            target = Yielding(env_file)
            pool = eventlet.GreenPool()
            pool.spawn(admin._set_env_value, target, "MCP_OAUTH_REQUIRE_APPROVAL", "True")
            pool.spawn(admin._set_env_value, target, "MCP_OAUTH_WRITE_SCOPE_ENABLED", "True")
            pool.waitall()
            return env_file.read_text()

        env_file = Path(os.environ["HOOK_TMP"]) / ".env"
        env_file.write_text("APP_KEY = 'x'\\n")
        before = ticks[0]
        text = save_both(env_file)
        assert "MCP_OAUTH_REQUIRE_APPROVAL = 'True'" in text, text
        assert "MCP_OAUTH_WRITE_SCOPE_ENABLED = 'True'" in text, text
        assert hub_alive(before)

        # The control: without the lock the same yield loses one key.
        class NoLock:
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False

        admin.ENV_WRITE_LOCK = NoLock()
        env_file.write_text("APP_KEY = 'x'\\n")
        text = save_both(env_file)
        both = "REQUIRE_APPROVAL = 'True'" in text and "WRITE_SCOPE_ENABLED = 'True'" in text
        assert not both, "the yield did not interleave the saves; the test proves nothing"
        print("OK")
        """,
        tmp_path,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr[-3000:]


def test_the_hooks_under_eventlet_register_and_add_only_the_drain_flag(tmp_path):
    result = run(
        """
        import importlib.util, signal
        spec = importlib.util.spec_from_file_location(
            "hooks", os.path.join(sys.path[0], "install", "lib", "gunicorn_hooks.py"))
        hooks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hooks)

        from utils import runtime, stream_registry

        warnings = []

        class Log:
            def info(self, message): pass
            def warning(self, message): warnings.append(message)

        class Cfg:
            threads = 1
            workers = 1
            graceful_timeout = 30
            worker_class_str = "eventlet"

        Worker = type("EventletWorker", (), {"__module__": "gunicorn.workers.geventlet"})
        worker = Worker()
        worker.cfg, worker.log = Cfg(), Log()

        calls = []
        signal.signal(signal.SIGTERM, lambda sig, frame: calls.append("gunicorn"))
        threads_before = threading.active_count()
        before = ticks[0]
        hooks.post_worker_init(worker)
        assert runtime.registered_worker()["worker_class"] == "eventlet"
        assert runtime.configured_threads() is None
        os.kill(os.getpid(), signal.SIGTERM)
        eventlet.sleep(0.2)
        assert calls == ["gunicorn"], calls
        assert stream_registry.should_stop()
        assert threading.active_count() == threads_before, "the drain started a thread"
        assert hub_alive(before)
        assert warnings == [], warnings
        print("OK")
        """,
        tmp_path,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr[-3000:]
