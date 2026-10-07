"""An OI Profile request cannot hold a gthread worker thread for minutes.

The page used to fetch daily history one contract at a time, inside the
request, for every option with open interest in a 20-strike chain (up to 82
contracts), with a 1 s then 2 s backoff on every broker refusal. Normally 30 to
40 seconds; while the broker refused requests it was several minutes. Under
eventlet that cost a greenlet. Under the gthread worker it holds one of a fixed
pool of request threads.

The default "vs previous session" change no longer fetches inside the request at
all: its anchors come from NSE's bhavcopy or a background worker, and the answer
says `oi_change_pending` while they fill. What still reads broker history in the
request is a drag-selected window, one call per contract, and under gthread that
path stops at the time budget and says how many contracts it covers. A contract
not reached is left without a change rather than given one of zero. Under
eventlet and the development server there is no budget.

The option chain, the futures lookup, NSE and every broker history call are
stubbed.
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
WINDOW = (1_760_000_000, 1_760_003_600)


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
    monkeypatch.setattr(ois, "_nse_previous_session_oi", lambda exchange: None)
    monkeypatch.setattr(ois, "_nse_cached_book", lambda exchange: None)
    ois._profile_cache.clear()
    ois._prev_oi_cache.clear()
    yield monkeypatch
    # Drain the anchor worker while the stubs are still in place.
    ois._anchor_executor.submit(lambda: None).result(timeout=60)
    ois._profile_cache.clear()
    ois._prev_oi_cache.clear()


def _history(delay: float, status: int = 200):
    """Bars either side of the window: OI 600 entering it, 1000/2000 at its end."""

    def get_history(**kwargs):
        time.sleep(delay)
        if status != 200:
            return False, {"status": "error", "message": "busy"}, status
        oi_end = 1000 if kwargs["symbol"].endswith("CE") else 2000
        return (
            True,
            {
                "data": [
                    {"timestamp": WINDOW[0] - 60, "oi": 600},
                    {"timestamp": WINDOW[1], "oi": oi_end},
                ]
            },
            200,
        )

    return get_history


def _no_pauses(monkeypatch):
    """Skip the batch pauses and backoffs for tests that are not about time."""
    fake_time = types.SimpleNamespace(monotonic=time.monotonic, sleep=lambda s: None)
    monkeypatch.setattr(ois, "time", fake_time)


def _profile(window=None):
    start, end = window or (None, None)
    return ois.get_oi_profile_data(
        "NIFTY", "NSE_INDEX", "28OCT25", "5m", 3, "key", window_start=start, window_end=end
    )


def _run_with_watchdog(fn, limit: float):
    box = {}

    def target():
        box["result"] = fn()

    thread = threading.Thread(target=target, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(limit)
    return thread.is_alive(), time.monotonic() - started, box.get("result")


def test_under_gthread_the_default_change_never_waits_on_history(stubs):
    """The defect, in the default view: the request no longer fetches at all."""
    stubs.setattr(runtime, "gthread_active", lambda: True)
    stubs.setattr(ois, "get_history", _history(0.5, status=429))

    still_running, elapsed, result = _run_with_watchdog(_profile, limit=8)

    assert not still_running, "the OI Profile request was still fetching after 8 s"
    assert elapsed < 2, elapsed
    ok, body, status = result
    assert (ok, status) == (True, 200)
    assert body["oi_change_pending"] is True

    # The anchors were handed to the background worker, which is now working
    # through the same refusal storm. Let it finish at once so the fixture's
    # drain does not wait out 82 contracts of backoff.
    stubs.setattr(ois, "_history_rows", lambda *a, **k: None)
    _no_pauses(stubs)


def test_under_gthread_a_windowed_refusal_storm_is_cut_at_the_budget(stubs):
    stubs.setattr(runtime, "gthread_active", lambda: True)
    stubs.setattr(ois, "GTHREAD_OI_CHANGE_BUDGET_SECONDS", 1.0)
    stubs.setattr(ois, "get_history", _history(0.05, status=429))

    still_running, elapsed, result = _run_with_watchdog(lambda: _profile(WINDOW), limit=8)

    assert not still_running, "the windowed request was still fetching after 8 s"
    assert elapsed < 4, elapsed
    ok, body, status = result
    assert (ok, status) == (True, 200)
    assert body["oi_change_requested"] == 82
    assert body["oi_change_loaded"] < 82
    assert "Refresh in a minute" in body["message"]


def test_under_gthread_the_note_counts_what_was_loaded(stubs):
    stubs.setattr(runtime, "gthread_active", lambda: True)
    stubs.setattr(ois, "GTHREAD_OI_CHANGE_BUDGET_SECONDS", 0.5)
    stubs.setattr(ois, "get_history", _history(0.05))

    ok, body, status = _profile(WINDOW)

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


def test_under_gthread_a_normal_windowed_fetch_is_complete(stubs):
    stubs.setattr(runtime, "gthread_active", lambda: True)
    _no_pauses(stubs)
    stubs.setattr(ois, "get_history", _history(0.0))

    ok, body, status = _profile(WINDOW)

    assert (ok, status) == (True, 200)
    assert "message" not in body and "oi_change_loaded" not in body
    assert all(
        row["ce_oi_change"] == 400 and row["pe_oi_change"] == 1400 for row in body["oi_chain"]
    )


def test_without_gthread_there_is_no_budget(stubs):
    stubs.setattr(runtime, "gthread_active", lambda: False)
    stubs.setattr(ois, "GTHREAD_OI_CHANGE_BUDGET_SECONDS", 0.0)
    _no_pauses(stubs)
    stubs.setattr(ois, "get_history", _history(0.0))

    ok, body, status = _profile(WINDOW)

    assert (ok, status) == (True, 200)
    assert "message" not in body
    assert all(row["ce_oi_change"] == 400 for row in body["oi_chain"])
    assert ois._oi_change_deadline() is None


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
        def get_history(**kwargs):
            return False, {"status": "error"}, 429
        ois.get_history = get_history
        real_sleep = ois.time.sleep
        ois.time.sleep = slept.append
        try:
            result = ois._fetch_windowed_oi_changes(
                [{"symbol": "A", "oi": 5}], "NFO", "1m", 1760000000, 1760003600, "key"
            )
        finally:
            ois.time.sleep = real_sleep
        assert result == {}, result
        assert not result.cut
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
