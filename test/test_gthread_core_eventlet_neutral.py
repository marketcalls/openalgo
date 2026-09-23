"""Under the eventlet worker the core changes behave exactly as before.

Every refusal, bound and supervisor added for the gthread worker is gated on
utils.runtime.gthread_active(), and the race fixes must not change what a
greenlet sees when nothing races. This runs a real eventlet hub in a
subprocess (monkey_patch() is global and cannot be undone) with gunicorn's
eventlet worker module stubbed in, and checks the eventlet-side answers:

* the proxy is a child process, unsupervised, with no drain watcher, and
  its SIGTERM handler is installed as it always was;
* the health thresholds, the httpx timeout and the ngrok handlers (a no-op
  under gunicorn, overridden by the proxy's handler as before) are
  unchanged;
* a mode change queued behind another waits its turn instead of being
  refused, and the hub keeps running while it waits;
* the locked caches work from many greenlets at once.
"""

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

REPO = Path(__file__).resolve().parents[1]

PREAMBLE = """
import eventlet
eventlet.monkey_patch()

import sys, types, time
for name in ("gunicorn", "gunicorn.workers", "gunicorn.workers.base", "gunicorn.workers.geventlet"):
    sys.modules.setdefault(name, types.ModuleType(name))
"""


def run(body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", PREAMBLE + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(REPO),
        env=dict(os.environ),
    )


def test_the_eventlet_worker_keeps_todays_topology_and_limits():
    result = run(
        """
        from utils import runtime
        assert runtime.worker_class() == "eventlet", runtime.worker_class()
        assert runtime.gthread_active() is False

        import websocket_proxy.app_integration as ai
        assert ai.resolve_proxy_mode() == "subprocess"
        assert ai._supervised() is False

        from utils.shutdown import start_drain_watcher
        assert start_drain_watcher() is False

        import utils.health_monitor as hm
        assert hm._thread_thresholds() == (hm.THREAD_WARNING_THRESHOLD, hm.THREAD_CRITICAL_THRESHOLD)

        import httpx
        import utils.httpx_client as hc
        assert hc.get_httpx_client().timeout == httpx.Timeout(120.0)

        import signal
        before = signal.getsignal(signal.SIGTERM)
        import utils.ngrok_manager as ng
        ng.setup_ngrok_handlers()
        assert signal.getsignal(signal.SIGTERM) is before

        # The proxy integration still installs its SIGTERM handler under
        # eventlet, exactly as before, and starts no supervisor.
        class Child:
            pid = 1

            def poll(self):
                return None

        import atexit
        atexit.register = lambda fn: None
        ai._launch_child = lambda: Child()
        ai.start_websocket_server("subprocess")
        assert signal.getsignal(signal.SIGTERM) is ai.signal_handler
        assert ai._supervisor_thread is None

        import blueprints.master_contract_status as mcs
        assert mcs.gthread_active() is False
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr[-3000:]


def test_a_queued_mode_change_waits_without_freezing_the_hub():
    result = run(
        """
        import services.analyzer_service as asvc

        ticks = []

        def ticker():
            for _ in range(20):
                ticks.append(time.monotonic())
                eventlet.sleep(0.02)

        def holder():
            with asvc.mode_transition():
                eventlet.sleep(0.3)

        h = eventlet.spawn(holder)
        eventlet.sleep(0.01)
        t = eventlet.spawn(ticker)
        started = time.monotonic()
        with asvc.mode_transition(timeout=0.05):
            waited = time.monotonic() - started
        h.wait()
        t.wait()
        # Waited for the holder rather than being refused after 0.05 s, and
        # other greenlets kept running meanwhile.
        assert waited >= 0.2, waited
        assert len(ticks) >= 10, len(ticks)
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr[-3000:]


def test_the_locked_caches_serve_many_greenlets():
    result = run(
        """
        import database.auth_db as auth_db
        from utils.thread_safe_cache import LockedTTLCache

        errors = []

        def reader(n):
            try:
                for i in range(300):
                    auth_db.auth_cache.get(f"auth-u{i % 7}")
                    gen = auth_db.auth_cache.generation
                    auth_db.auth_cache.fill(f"auth-u{i % 7}", ("t", "b"), gen)
                    if i % 50 == 0:
                        eventlet.sleep(0)
            except Exception as exc:
                errors.append(exc)

        def writer():
            try:
                for i in range(300):
                    auth_db.invalidate_user_auth_cache(f"u{i % 7}")
                    if i % 30 == 0:
                        auth_db.auth_cache.clear()
                        eventlet.sleep(0)
            except Exception as exc:
                errors.append(exc)

        pool = [eventlet.spawn(reader, n) for n in range(8)] + [eventlet.spawn(writer)]
        for g in pool:
            g.wait()
        assert errors == [], errors[:3]
        assert isinstance(auth_db.auth_cache, LockedTTLCache)
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr[-3000:]
