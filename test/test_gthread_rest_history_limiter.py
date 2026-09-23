"""Broker history requests are spaced about three a second, however they arrive.

``services.history_service`` paces every broker history call (REST, Flow
indicator nodes, the /tools pages, the P&L tracker, the agent) to one per
0.35 s. The old limiter read the time of the last call, slept, and wrote it
back, all unlocked. Callers arriving together computed their sleep from the
same stale value and woke together, and under the gthread worker the read and
the write also interleaved on the no-sleep path, so N concurrent callers all
went straight through: a burst the broker rejects.

The fix books a start slot under a lock and sleeps after releasing it. Under
the gthread worker a caller whose slot is further away than the market-data
queue ceiling is refused at once with the trader-readable busy message (HTTP
429) instead of holding a request thread; under eventlet and the development
server nobody is ever refused.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
import types
from importlib.util import find_spec
from pathlib import Path

import pytest

from services import history_service
from utils import runtime
from utils.broker_backpressure import BROKER_BUSY_MESSAGE, BrokerBusyError

REPO = Path(__file__).resolve().parents[1]
INTERVAL = history_service._MIN_HISTORY_INTERVAL


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    monkeypatch.setattr(history_service, "_next_history_slot", 0.0, raising=False)
    # The limiter this replaced kept its state here; reset it too so the same
    # tests can be pointed at the old code to show they catch the defect.
    monkeypatch.setattr(history_service, "_last_history_call", 0.0, raising=False)
    yield


def test_concurrent_callers_are_spaced_one_interval_apart():
    """The defect: six callers arriving together all went through at once."""
    barrier = threading.Barrier(6)
    returned = []
    lock = threading.Lock()

    def caller():
        barrier.wait()
        history_service._enforce_rate_limit()
        with lock:
            returned.append(time.monotonic())

    threads = [threading.Thread(target=caller) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    returned.sort()
    gaps = [b - a for a, b in zip(returned, returned[1:], strict=False)]
    assert len(gaps) == 5
    assert min(gaps) >= INTERVAL - 0.02, gaps


def test_a_single_caller_waits_as_it_did_before():
    """The non-racing path is unchanged: no wait, one interval, then none."""
    started = time.monotonic()
    history_service._enforce_rate_limit()
    assert time.monotonic() - started < 0.1

    started = time.monotonic()
    history_service._enforce_rate_limit()
    waited = time.monotonic() - started
    assert INTERVAL - 0.05 <= waited <= INTERVAL + 0.2, waited

    time.sleep(INTERVAL + 0.1)
    started = time.monotonic()
    history_service._enforce_rate_limit()
    assert time.monotonic() - started < 0.1


def test_gthread_refuses_a_wait_beyond_the_ceiling_without_booking(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    far = time.monotonic() + 30
    monkeypatch.setattr(history_service, "_next_history_slot", far)

    started = time.monotonic()
    with pytest.raises(BrokerBusyError) as refused:
        history_service._enforce_rate_limit()
    assert time.monotonic() - started < 0.5
    assert str(refused.value) == BROKER_BUSY_MESSAGE
    # A refused caller books nothing, so it delays nobody after it.
    assert history_service._next_history_slot == far


def test_gthread_refusal_reaches_the_caller_as_a_429(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    monkeypatch.setattr(history_service, "_next_history_slot", time.monotonic() + 30)
    called = []
    monkeypatch.setattr(
        history_service, "get_history_with_auth", lambda *a: called.append(a) or (True, {}, 200)
    )

    result = history_service.get_history(
        "NIFTY",
        "NSE_INDEX",
        "1m",
        "2026-09-01",
        "2026-09-22",
        auth_token="token",
        broker="zerodha",
    )

    assert result == (False, {"status": "error", "message": BROKER_BUSY_MESSAGE}, 429)
    assert called == []


def test_without_gthread_a_long_queue_waits_and_is_never_refused(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    monkeypatch.setattr(history_service, "_next_history_slot", time.monotonic() + 30)
    slept = []
    monkeypatch.setattr(history_service.time, "sleep", lambda seconds: slept.append(seconds))

    history_service._enforce_rate_limit()

    assert len(slept) == 1 and 29 < slept[0] <= 30


def test_a_busy_refusal_from_the_broker_is_a_429(monkeypatch):
    """A broker plugin's own limiter raising BrokerBusyError is not a 500."""

    class BrokerData:
        def __init__(self, auth_token):
            pass

        def get_history(self, *args):
            raise BrokerBusyError()

    module = types.SimpleNamespace(BrokerData=BrokerData)
    monkeypatch.setattr(history_service, "validate_symbol_exchange", lambda s, e: (True, None))
    monkeypatch.setattr(history_service, "import_broker_module", lambda name: module)

    result = history_service.get_history_with_auth(
        "token", None, "zerodha", "SBIN", "NSE", "1m", "2026-09-01", "2026-09-22"
    )
    assert result == (False, {"status": "error", "message": BROKER_BUSY_MESSAGE}, 429)


# --- eventlet neutrality -----------------------------------------------------


def _child_env(tmp_path: Path) -> dict:
    env = dict(os.environ)
    db = tmp_path / "db"
    db.mkdir(exist_ok=True)
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{(db / 'openalgo.db').as_posix()}",
            "SANDBOX_DATABASE_URL": f"sqlite:///{(db / 'sandbox.db').as_posix()}",
            "LOGS_DATABASE_URL": f"sqlite:///{(db / 'logs.db').as_posix()}",
            "LATENCY_DATABASE_URL": f"sqlite:///{(db / 'latency.db').as_posix()}",
            "HEALTH_DATABASE_URL": f"sqlite:///{(db / 'health.db').as_posix()}",
            "LOG_DIR": str(tmp_path / "log"),
            "LOG_TO_FILE": "False",
            "API_KEY_PEPPER": "0" * 64,
            "APP_KEY": "test-only-app-key",
            "PYTHONPATH": str(REPO),
        }
    )
    env.pop("OPENALGO_WORKER_CLASS", None)
    env.pop("OPENALGO_EFFECTIVE_THREADS", None)
    return env


@pytest.mark.skipif(find_spec("eventlet") is None, reason="eventlet is not installed (Windows dev)")
def test_under_eventlet_greenlets_are_spaced_and_the_hub_keeps_running(tmp_path):
    """The limiter under a real monkey_patch, as production runs it.

    Greenlets arriving together are spaced one interval apart; the wait is a
    green sleep, so a ticker greenlet keeps running throughout; a real OS thread
    (the agent) takes a turn too without greenlet.error; and a long queue is
    waited out rather than refused, because nothing is refused under eventlet.
    """
    body = """
        import eventlet
        eventlet.monkey_patch()

        import dotenv
        dotenv.load_dotenv = lambda *a, **k: False
        dotenv.main.load_dotenv = dotenv.load_dotenv

        import time
        import eventlet.patcher
        from utils import runtime
        assert runtime.worker_class() == "eventlet"
        assert runtime.gthread_active() is False

        from services import history_service as hs
        interval = hs._MIN_HISTORY_INTERVAL
        real_threading = eventlet.patcher.original("threading")

        ticks = [0]
        stop = [False]

        def ticker():
            while not stop[0]:
                ticks[0] += 1
                eventlet.sleep(0.01)

        returned = []
        def green_caller():
            hs._enforce_rate_limit()
            returned.append(time.monotonic())

        real_done = []
        def real_caller():
            hs._enforce_rate_limit()
            real_done.append(time.monotonic())

        tick = eventlet.spawn(ticker)
        started = time.monotonic()
        greens = [eventlet.spawn(green_caller) for _ in range(5)]
        real = real_threading.Thread(target=real_caller, daemon=True)
        real.start()
        for g in greens:
            g.wait()
        while real.is_alive() and time.monotonic() - started < 10:
            eventlet.sleep(0.02)
        elapsed = time.monotonic() - started

        stamps = sorted(returned + real_done)
        gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
        assert len(real_done) == 1, "the real thread never got its turn"
        assert len(gaps) == 5 and min(gaps) >= interval - 0.03, gaps
        # 6 callers need 5 intervals; the hub ran the ticker all along.
        assert ticks[0] >= int(elapsed / 0.01 * 0.5), (ticks[0], elapsed)

        # A long queue is waited for, never refused, under eventlet.
        hs._next_history_slot = time.monotonic() + 30
        slept = []
        hs.time.sleep = lambda s: slept.append(s)
        hs._enforce_rate_limit()
        assert len(slept) == 1 and slept[0] > 29, slept

        stop[0] = True
        tick.wait()
        print("OK", round(elapsed, 2), ticks[0])
    """
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        cwd=str(REPO),
        env=_child_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr
    assert "Cannot switch to a different thread" not in result.stderr
