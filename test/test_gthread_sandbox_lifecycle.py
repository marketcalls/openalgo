"""Tests for sandbox lifecycle and scheduler defaults (gthread PR-8, A9/A13).

Covers GT-A9-01 (lock held across a join), GT-A9-12 (T+1 settlement race) and
GT-A13-01/04/06 (schedulers inheriting a 1-second misfire grace).
"""

import importlib.util
import inspect
import sys
import threading
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# `test/sandbox/` is itself a package, and pytest puts the test directory on
# sys.path, so a plain `import sandbox.holdings_manager` resolves to the test
# package and fails. Load the real modules by file path instead.
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent


def _load(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, REPO / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


execution_thread = _load("_gt_execution_thread", "sandbox/execution_thread.py")
holdings_manager = _load("_gt_holdings_manager", "sandbox/holdings_manager.py")
HoldingsManager = holdings_manager.HoldingsManager


# --------------------------------------------------------------------------
# GT-A9-01: lock held across a join
# --------------------------------------------------------------------------


def test_watcher_is_stopped_before_the_engine_lock_is_taken():
    """The defect: stop_execution_engine held _thread_lock and then joined the
    auto-upgrade watcher, which needs that same lock. The join could never
    succeed, so it burned its full 5s timeout and then cleared the thread
    reference while the thread was still alive."""
    et = execution_thread

    src = inspect.getsource(et.stop_execution_engine)
    stop_at = src.index("_stop_websocket_upgrade_watcher()")
    lock_at = src.index("with _thread_lock:")
    assert stop_at < lock_at, "watcher must be stopped before _thread_lock is taken"


def test_a_watcher_that_will_not_stop_is_not_reported_as_stopped():
    """Clearing the reference on a timed-out join is how an orphan keeps
    mutating engine state while being treated as gone."""
    et = execution_thread

    src = inspect.getsource(et._stop_websocket_upgrade_watcher)
    assert "is_alive()" in src
    assert "return" in src, "must bail out rather than null a live reference"


def test_watcher_rechecks_the_stop_event_after_acquiring_the_lock():
    et = execution_thread

    src = inspect.getsource(et)
    idx = src.index("def _start_websocket_upgrade_watcher")
    body = src[idx : idx + 2000]
    lock_at = body.index("with _thread_lock:")
    assert "_auto_upgrade_stop_event.is_set()" in body[lock_at:], (
        "must re-check the stop event after waiting for the lock"
    )


def test_lock_across_join_really_does_deadlock_until_timeout():
    """The control, modelled directly: a joiner holding the lock its target
    needs cannot finish before the timeout."""
    lock = threading.Lock()
    stop = threading.Event()
    reached = threading.Event()

    def watcher():
        while not stop.is_set():
            time.sleep(0.01)
            with lock:  # needs the lock the stopper holds
                reached.set()

    thread = threading.Thread(target=watcher, daemon=True)
    thread.start()
    time.sleep(0.05)

    # Bad shape: hold the lock, then join.
    started = time.monotonic()
    with lock:
        stop.set()
        thread.join(timeout=0.5)
        timed_out_while_holding = thread.is_alive()
    elapsed = time.monotonic() - started

    assert timed_out_while_holding, "expected the join to time out"
    assert elapsed >= 0.5, f"join returned early ({elapsed:.2f}s)"
    thread.join(timeout=2)


def test_correct_shape_joins_promptly():
    """Signal and join outside the lock: the target exits at once."""
    lock = threading.Lock()
    stop = threading.Event()

    def watcher():
        while not stop.is_set():
            time.sleep(0.01)
            with lock:
                pass

    thread = threading.Thread(target=watcher, daemon=True)
    thread.start()
    time.sleep(0.05)

    started = time.monotonic()
    stop.set()
    thread.join(timeout=2)  # lock NOT held
    elapsed = time.monotonic() - started

    assert not thread.is_alive()
    assert elapsed < 0.5, f"join took {elapsed:.2f}s"


# --------------------------------------------------------------------------
# GT-A9-12: T+1 settlement
# --------------------------------------------------------------------------


def test_settlement_is_serialized_across_instances():
    """Callers build a fresh manager per run, so a per-instance lock would
    guard nothing. Two overlapping runs would each read the same holding, each
    compute from the same starting quantity, and each transfer margin."""
    a = HoldingsManager("user-a")
    b = HoldingsManager("user-b")
    assert a._settlement_lock is b._settlement_lock, "lock must be class-level"

    src = inspect.getsource(HoldingsManager.process_t1_settlement)
    assert "_settlement_lock" in src


def test_settlement_lock_actually_excludes():
    overlaps = []
    active = []
    guard = threading.Lock()

    def fake_settlement(_self):
        with guard:
            active.append(1)
            if len(active) > 1:
                overlaps.append(1)
        time.sleep(0.01)
        with guard:
            active.pop()

    original = HoldingsManager._process_t1_settlement_locked
    HoldingsManager._process_t1_settlement_locked = fake_settlement
    try:
        threads = [
            threading.Thread(
                target=lambda n=i: HoldingsManager(f"u{n}").process_t1_settlement()
            )
            for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        HoldingsManager._process_t1_settlement_locked = original

    assert overlaps == [], "settlement ran concurrently"


# --------------------------------------------------------------------------
# GT-A13: scheduler misfire grace
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,marker",
    [
        ("sandbox/squareoff_thread.py", "misfire_grace_time"),
        ("blueprints/python_strategy.py", "misfire_grace_time"),
        ("blueprints/chartink.py", "misfire_grace_time"),
    ],
)
def test_every_scheduler_sets_an_explicit_misfire_grace(path, marker):
    """APScheduler defaults misfire_grace_time to 1 second. A loaded worker can
    miss that window, and a missed job is skipped silently -- not deferred."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / path).read_text(encoding="utf-8")
    idx = src.index("BackgroundScheduler(")
    block = src[idx : idx + 700]
    assert marker in block, f"{path} inherits the 1s default misfire grace"


def test_apscheduler_default_grace_is_one_second():
    """Documents the premise, so this test fails if the library changes it."""
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(daemon=True)
    assert scheduler._job_defaults["misfire_grace_time"] == 1
    # These two are already safe by default -- rev 4 wrongly claimed otherwise.
    assert scheduler._job_defaults["coalesce"] is True
    assert scheduler._job_defaults["max_instances"] == 1


def test_all_six_schedulers_are_accounted_for():
    """Six BackgroundScheduler instances exist; none may be left unreviewed."""
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    expected = {
        "blueprints/python_strategy.py",
        "blueprints/chartink.py",
        "blueprints/strategy.py",
        "services/flow_scheduler_service.py",
        "services/historify_scheduler_service.py",
        "sandbox/squareoff_thread.py",
    }
    found = set()
    for sub in ("blueprints", "services", "sandbox"):
        for path in (repo / sub).rglob("*.py"):
            if "BackgroundScheduler(" in path.read_text(encoding="utf-8"):
                found.add(path.relative_to(repo).as_posix())
    assert found == expected, f"scheduler inventory drifted: {found ^ expected}"
