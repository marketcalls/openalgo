"""Bounded registries, sleep-outside-lock, and the last money-path race.

Covers GT-B2-06 (pnltracker limiter), GT-A9-06 (expired-position settlement),
GT-A12-02 (strike cache), GT-A12-03/GT-F-01 (workflow locks) and GT-A12-13
(hdfcsky chart cache).
"""

import importlib
import importlib.util
import inspect
import sys
import threading
import time
from pathlib import Path

from cachetools import TTLCache

from utils.thread_safe_cache import LockedTTLCache

REPO = Path(__file__).resolve().parent.parent


def _load_real_sandbox(name):
    saved = {k: v for k, v in sys.modules.items() if k == "sandbox" or k.startswith("sandbox.")}
    for key in list(saved):
        del sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        "sandbox",
        REPO / "sandbox" / "__init__.py",
        submodule_search_locations=[str(REPO / "sandbox")],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules["sandbox"] = package
    spec.loader.exec_module(package)
    try:
        return importlib.import_module(f"sandbox.{name}")
    finally:
        for key in [k for k in sys.modules if k == "sandbox" or k.startswith("sandbox.")]:
            del sys.modules[key]
        sys.modules.update(saved)


# --------------------------------------------------------------------------
# GT-B2-06: the limiter must not sleep while holding its lock
# --------------------------------------------------------------------------


def test_rate_limiter_sleeps_outside_its_lock():
    """Sleeping inside the lock serializes callers twice: each waits for the
    lock, then waits again for its own interval. N callers take N x interval
    instead of finishing together, and under gthread each waiter holds a worker
    thread throughout."""
    import blueprints.pnltracker as pnl

    src = inspect.getsource(pnl.RateLimiter.wait)
    inside_lock = src[src.index("with self.lock") : src.index("if sleep_for > 0")]
    # Match an actual sleep CALL, not the `sleep_for` variable that computes
    # how long to wait once the lock has been released.
    assert ".sleep(" not in inside_lock, "the limiter still sleeps while holding its lock"
    # And the call must exist after the lock block.
    assert ".sleep(" in src[src.index("if sleep_for > 0") :], "the limiter no longer waits at all"


def test_reserved_slots_mean_callers_finish_together():
    """Behavioural: with the slot reserved under the lock and the sleep outside,
    N callers finish after roughly the LAST reserved slot, not N intervals."""
    import blueprints.pnltracker as pnl

    limiter = pnl.RateLimiter(calls_per_second=50)  # 20ms interval
    started = time.monotonic()
    barrier = threading.Barrier(5)

    def call(_b=barrier):
        _b.wait()
        limiter.wait()

    threads = [threading.Thread(target=call) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - started

    # Serial-inside-lock would be ~5 x 20ms plus lock handoff. Reserved slots
    # overlap their sleeps, so the total stays close to the last slot.
    assert elapsed < 0.25, f"callers serialized on the lock ({elapsed:.3f}s)"


# --------------------------------------------------------------------------
# GT-A9-06: expired-position settlement
# --------------------------------------------------------------------------


def test_expired_position_settlement_is_serialized():
    """Settlement runs as a side effect of get_open_positions -- every
    positions page load and API call. It reads a quantity, releases margin and
    credits P&L, then zeroes the quantity. Two concurrent reads both saw a
    non-zero quantity and both settled: margin released twice."""
    position_manager = _load_real_sandbox("position_manager")
    cls = position_manager.PositionManager

    assert hasattr(cls, "_settle_lock")
    assert "_settle_lock" in inspect.getsource(cls._check_and_close_expired_positions)


def test_settlement_lock_is_class_level():
    position_manager = _load_real_sandbox("position_manager")
    src = (REPO / "sandbox" / "position_manager.py").read_text(encoding="utf-8")
    assert "_settle_lock = threading.RLock()" in src
    assert position_manager.PositionManager._settle_lock is not None


def test_only_the_settlement_is_serialized_not_the_whole_read():
    """Ordinary position fetches must not queue behind each other."""
    position_manager = _load_real_sandbox("position_manager")
    src = inspect.getsource(position_manager.PositionManager.get_open_positions)
    assert "_settle_lock" not in src, "the whole read path is serialized"


# --------------------------------------------------------------------------
# GT-A12-02 / GT-A12-13: unbounded caches
# --------------------------------------------------------------------------


def test_strike_cache_is_bounded_and_locked():
    """Keyed by (symbol, exchange, expiry, type), so the key space grows with
    every distinct instrument queried -- and only one broker ever invalidates
    it, so nothing reclaimed the memory."""
    import services.option_symbol_service as oss

    assert isinstance(oss._STRIKES_CACHE, LockedTTLCache)
    assert oss._STRIKES_CACHE.maxsize == 4096


def test_hdfcsky_chart_cache_is_bounded_and_locked():
    """The only class-level attribute in the codebase mutated at runtime
    without a guard, and shared by every instance."""
    from broker.hdfcsky.api.data import BrokerData

    assert isinstance(BrokerData._CHART_SYMBOL_CACHE, LockedTTLCache)


def test_bounded_caches_actually_evict():
    cache = LockedTTLCache(maxsize=8, ttl=3600)
    for i in range(50):
        cache[f"k{i}"] = i
    assert len(cache) == 8, "cache is not bounded"
    assert isinstance(cache, TTLCache)


# --------------------------------------------------------------------------
# GT-A12-03 / GT-F-01: workflow lock registry
# --------------------------------------------------------------------------


def test_workflow_locks_can_be_released():
    """Creation was guarded but entries were never removed: one Lock per
    distinct workflow id, forever, in a worker that never restarts."""
    import services.flow_executor_service as fes

    assert hasattr(fes, "release_workflow_lock")

    lock = fes.get_workflow_lock(987654)
    assert 987654 in fes._workflow_locks
    assert fes.release_workflow_lock(987654) is True
    assert 987654 not in fes._workflow_locks
    assert fes.release_workflow_lock(987654) is False
    assert lock is not None


def test_a_held_workflow_lock_is_not_removed():
    """Removing a lock mid-run would strand the runner without its mutex."""
    import services.flow_executor_service as fes

    lock = fes.get_workflow_lock(987655)
    lock.acquire()
    try:
        assert fes.release_workflow_lock(987655) is False, "removed a lock that was held"
        assert 987655 in fes._workflow_locks
    finally:
        lock.release()
    assert fes.release_workflow_lock(987655) is True
