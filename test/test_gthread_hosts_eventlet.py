"""The strategy hosts behave exactly as before under the eventlet worker.

Everything in the hosts partition that a trader could notice is gated on the
gthread worker: the resource limit bootstrap, the live stream cap and lifetime,
the early shutdown hooks and Chartink's in-process orders. The race fixes
(locks, claims, single flight, snapshots) apply everywhere, and under eventlet
they must be green primitives that never block the hub.

Each case runs in a subprocess, because ``eventlet.monkey_patch()`` is global
and cannot be undone. See test_eventlet_cross_thread_locks.py for the pattern.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip(
    "eventlet",
    reason="eventlet is installed by the production installer, not by pyproject",
)

ROOT = Path(__file__).resolve().parent.parent

PREAMBLE = """
import eventlet
eventlet.monkey_patch()

import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
dotenv.main.load_dotenv = dotenv.load_dotenv

import json, os, tempfile, threading, time
from pathlib import Path
"""


def run(body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", PREAMBLE + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(ROOT),
    )


def test_the_hosts_take_their_eventlet_paths():
    result = run(
        """
        from blueprints import python_strategy as ps
        from blueprints import chartink
        from services import openscript_runner_service as svc
        from utils import runtime, stream_registry

        assert runtime.worker_class() == "eventlet"
        assert not runtime.gthread_active()

        # The launch is unchanged: preexec_fn on POSIX, no bootstrap.
        args = ps.create_subprocess_args()
        assert ("preexec_fn" in args) == (os.name != "nt"), args
        assert not ps._limits_applied_after_exec()

        # No cap on live status streams.
        assert stream_registry.enforced_limit(ps.PYTHON_STRATEGY_SSE_MAX) is None

        # The early shutdown hooks leave the stopping to atexit.
        called = []
        ps.begin_shutdown = lambda *a, **k: called.append("python")
        svc.begin_shutdown = lambda *a, **k: called.append("openscript")
        ps._shutdown_hook()
        svc._shutdown_hook()
        assert called == [], called

        # Chartink posts its orders to the API as before.
        posted = []
        chartink.requests.post = lambda url, json=None, timeout=None: (
            posted.append(url) or type("R", (), {"ok": True, "text": "ok"})()
        )
        ok, _ = chartink._place("placeorder", {"symbol": "SBIN"})
        assert ok and posted == [chartink.BASE_URL + "/api/v1/placeorder"], posted

        # The race fixes use green primitives: a manual stop is still honoured
        # through the reentrant PROCESS_LOCK.
        ps.STRATEGY_CONFIGS["m"] = {"manually_stopped": True}
        assert ps._start_unless_stopped_by_trader("m") == (False, ps.MANUAL_STOP_REFUSAL)
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stdout + result.stderr


def test_concurrent_saves_across_greenlets_keep_the_hub_alive():
    result = run(
        """
        from blueprints import python_strategy as ps

        directory = Path(tempfile.mkdtemp())
        ps.CONFIG_FILE = directory / "strategy_configs.json"
        ps.STRATEGY_CONFIGS.clear()

        ticks = []

        def ticker():
            while True:
                ticks.append(1)
                eventlet.sleep(0.01)

        beat = eventlet.spawn(ticker)

        def saver(i):
            for n in range(20):
                with ps.PROCESS_LOCK:
                    ps.STRATEGY_CONFIGS[f"s{i}_{n}"] = {"name": "x"}
                assert ps.save_configs() is True
                eventlet.sleep(0)

        started = time.monotonic()
        workers = [eventlet.spawn(saver, i) for i in range(10)]
        for worker in workers:
            worker.wait()
        took = time.monotonic() - started
        stored = json.loads(ps.CONFIG_FILE.read_text(encoding="utf-8"))
        eventlet.sleep(0.1)
        beat.kill()

        assert len(stored) == 200, len(stored)
        assert not [p for p in directory.iterdir() if p.name.endswith(".tmp")]
        assert len(ticks) >= 5, f"the hub stalled: {len(ticks)} ticks in {took:.2f}s"
        print("OK", took)
        """
    )
    assert "OK" in result.stdout, result.stdout + result.stderr


def test_a_live_status_stream_ends_on_shutdown_under_eventlet():
    result = run(
        """
        from flask import Flask

        import utils.session
        from blueprints import python_strategy as ps

        utils.session.is_session_valid = lambda: True
        ps._SSE_POLL_SECONDS = 0.1
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(ps.python_strategy_bp)
        streams = [app.test_client().get("/python/api/events", buffered=False) for _ in range(12)]
        assert all(s.status_code == 200 for s in streams), "a stream was capped under eventlet"

        chunks = []

        def drain(stream):
            for chunk in stream.response:
                chunks.append(chunk)

        readers = [eventlet.spawn(drain, s) for s in streams]
        eventlet.sleep(0.3)
        ps._SHUTTING_DOWN.set()
        with eventlet.Timeout(3):
            for reader in readers:
                reader.wait()
        for s in streams:
            s.close()
        assert len(chunks) >= 12
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stdout + result.stderr
