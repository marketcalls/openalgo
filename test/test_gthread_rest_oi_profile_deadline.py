"""An OI Profile request cannot hold a gthread worker thread for minutes.

The OI Profile page fetches daily history one contract at a time for every
option with open interest in a 20-strike chain (up to 82 contracts), paced by
the history limiter, with a pause between batches and a 1 s then 2 s backoff
on every broker refusal. Normally that is 30 to 40 seconds; while the broker
refuses requests it was several minutes, and reloading the page started
another. Under eventlet that cost a greenlet. Under the gthread worker it holds
one of a fixed pool of request threads.

Under gthread the previous-day OI fetch now stops at a time budget and the page
says how many contracts it covers; a contract not reached is left without an
OI change rather than given a previous OI of zero. Under eventlet and the
development server there is no budget and the response is exactly as before.

The option chain, the futures lookup and every broker history call are stubbed.
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

from services import oi_profile_service as ois
from utils import runtime

REPO = Path(__file__).resolve().parents[1]
STRIKES = [24000 + 50 * i for i in range(41)]  # 82 contracts with open interest
OLD_RESPONSE_KEYS = {
    "status",
    "underlying",
    "spot_price",
    "atm_strike",
    "lot_size",
    "expiry_date",
    "futures_symbol",
    "interval",
    "candles",
    "oi_chain",
}


def _chain(**kwargs):
    rows = []
    for strike in STRIKES:
        rows.append(
            {
                "strike": strike,
                "ce": {"symbol": f"NIFTY28OCT25{strike}CE", "oi": 1000, "lotsize": 75},
                "pe": {"symbol": f"NIFTY28OCT25{strike}PE", "oi": 2000, "lotsize": 75},
            }
        )
    return (
        True,
        {"chain": rows, "atm_strike": 25000, "underlying_ltp": 25010.0, "underlying": "NIFTY"},
        200,
    )


@pytest.fixture
def stubs(monkeypatch):
    monkeypatch.setattr(ois, "get_option_chain", _chain)
    monkeypatch.setattr(ois, "_find_futures_symbol", lambda *a: None)
    return monkeypatch


def _history(delay: float, status: int = 200, prev_oi: float = 600.0):
    def get_history(**kwargs):
        time.sleep(delay)
        if status != 200:
            return False, {"status": "error", "message": "busy"}, status
        return True, {"data": [{"oi": prev_oi}, {"oi": 0}]}, 200

    return get_history


def _no_pauses(monkeypatch):
    """Skip the batch pauses and backoffs for tests that are not about time."""
    fake_time = types.SimpleNamespace(monotonic=time.monotonic, sleep=lambda s: None)
    monkeypatch.setattr(ois, "time", fake_time)


def _profile():
    return ois.get_oi_profile_data("NIFTY", "NSE_INDEX", "28OCT25", "5m", 3, "key")


def _run_with_watchdog(fn, limit: float):
    box = {}

    def target():
        box["result"] = fn()

    thread = threading.Thread(target=target, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(limit)
    return thread.is_alive(), time.monotonic() - started, box.get("result")


def test_under_gthread_a_refusal_storm_is_cut_at_the_budget(stubs):
    """The defect: 82 contracts refused with backoff held the thread for minutes."""
    stubs.setattr(runtime, "gthread_active", lambda: True)
    stubs.setattr(ois, "GTHREAD_OI_CHANGE_BUDGET_SECONDS", 1.0, raising=False)
    stubs.setattr(ois, "get_history", _history(0.05, status=429))

    still_running, elapsed, result = _run_with_watchdog(_profile, limit=8)

    assert not still_running, "the OI Profile request was still fetching after 8 s"
    assert elapsed < 4, elapsed
    ok, body, status = result
    assert (ok, status) == (True, 200)
    assert body["oi_change_requested"] == 82
    assert body["oi_change_loaded"] < 82
    assert "Refresh in a minute" in body["message"]


def test_under_gthread_the_note_counts_what_was_loaded(stubs):
    stubs.setattr(runtime, "gthread_active", lambda: True)
    stubs.setattr(ois, "GTHREAD_OI_CHANGE_BUDGET_SECONDS", 0.5, raising=False)
    stubs.setattr(ois, "get_history", _history(0.05))

    ok, body, status = _profile()

    loaded = body["oi_change_loaded"]
    assert 0 < loaded < 82
    assert body["message"] == ois._oi_change_note(loaded, 82)
    changed = [
        row for row in body["oi_chain"] if row["ce_oi_change"] != 0 or row["pe_oi_change"] != 0
    ]
    # A contract not reached shows no change, not its whole OI as a change.
    assert sum((row["ce_oi_change"] != 0) + (row["pe_oi_change"] != 0) for row in changed) == loaded
    for row in changed:
        assert row["ce_oi_change"] in (0, 1000 - 600)
        assert row["pe_oi_change"] in (0, 2000 - 600)


def test_under_gthread_a_normal_fetch_is_complete_and_unchanged(stubs):
    stubs.setattr(runtime, "gthread_active", lambda: True)
    _no_pauses(stubs)
    stubs.setattr(ois, "get_history", _history(0.0))

    ok, body, status = _profile()

    assert (ok, status) == (True, 200)
    assert set(body) == OLD_RESPONSE_KEYS
    assert all(
        row["ce_oi_change"] == 400 and row["pe_oi_change"] == 1400 for row in body["oi_chain"]
    )


def test_without_gthread_there_is_no_budget(stubs):
    stubs.setattr(runtime, "gthread_active", lambda: False)
    stubs.setattr(ois, "GTHREAD_OI_CHANGE_BUDGET_SECONDS", 0.0, raising=False)
    _no_pauses(stubs)
    stubs.setattr(ois, "get_history", _history(0.0))

    ok, body, status = _profile()

    assert (ok, status) == (True, 200)
    assert set(body) == OLD_RESPONSE_KEYS
    assert all(row["ce_oi_change"] == 400 for row in body["oi_chain"])
    assert getattr(ois, "_oi_change_deadline", lambda: None)() is None


def test_without_gthread_refusals_are_retried_as_before(stubs):
    """Unchanged: two retries with backoff, then a previous OI of zero."""
    stubs.setattr(runtime, "gthread_active", lambda: False)
    slept = []
    fake_time = types.SimpleNamespace(monotonic=time.monotonic, sleep=slept.append)
    stubs.setattr(ois, "time", fake_time)
    calls = []

    def get_history(**kwargs):
        calls.append(kwargs["symbol"])
        return False, {"status": "error"}, 429

    stubs.setattr(ois, "get_history", get_history)

    result = ois._fetch_daily_oi_changes(
        [{"symbol": "A", "oi": 5}, {"symbol": "B", "oi": 5}], "NFO", "key"
    )

    assert result == {"A": 0.0, "B": 0.0}
    assert calls == ["A", "A", "A", "B", "B", "B"]
    assert slept == [1.0, 2.0, 1.0, 2.0]


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
def test_under_eventlet_there_is_no_budget(tmp_path):
    body = """
        import eventlet
        eventlet.monkey_patch()

        import dotenv
        dotenv.load_dotenv = lambda *a, **k: False
        dotenv.main.load_dotenv = dotenv.load_dotenv

        from utils import runtime
        from services import oi_profile_service as ois

        assert runtime.worker_class() == "eventlet"
        assert ois._oi_change_deadline() is None

        slept = []
        calls = []
        def get_history(**kwargs):
            calls.append(kwargs["symbol"])
            return False, {"status": "error"}, 429
        ois.get_history = get_history
        real_sleep = ois.time.sleep
        ois.time.sleep = slept.append
        try:
            result = ois._fetch_daily_oi_changes([{"symbol": "A", "oi": 5}], "NFO", "key")
        finally:
            ois.time.sleep = real_sleep
        assert result == {"A": 0.0}, result
        assert slept == [1.0, 2.0], slept
        print("OK")
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
