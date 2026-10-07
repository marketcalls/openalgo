"""LockedTTLCache, the smart-order guard and the broker backpressure policy.

The cache's claim is two-part: every mapping operation is safe from many real
threads at once, and a fill that overlapped an invalidation is returned to its
own caller but never cached. The second is the one that matters on the money
path, so it is driven deterministically: the loader blocks on an Event while
the invalidation runs, which is exactly the window a writer's commit lands in.

The smart-order guard and the backpressure helpers must change nothing under
eventlet and the dev server, so each bounded behaviour is tested twice: with
the gthread worker reported active, and without.
"""

from __future__ import annotations

import threading
import time

import pytest

from utils import broker_backpressure as bp
from utils import runtime
from utils.smart_order_guard import (
    SMART_ORDER_LOCK_WAIT_SECONDS,
    PositionBookCache,
    SymbolLocks,
)
from utils.thread_safe_cache import MISSING, LockedTTLCache

THREADS = 16


def _run_all(target, count=THREADS, timeout=60):
    barrier = threading.Barrier(count)
    errors = []

    def runner(index):
        try:
            target(index, barrier)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout)
        assert not thread.is_alive(), "a worker thread hung"
    assert errors == [], errors[:3]


@pytest.fixture
def gthread(monkeypatch):
    """Report the gthread worker as active, for the bounded behaviours."""
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)


@pytest.fixture
def not_gthread(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# --- LockedTTLCache: mapping safety ----------------------------------------


def test_concurrent_mixed_operations_neither_raise_nor_corrupt():
    cache = LockedTTLCache(maxsize=64, ttl=0.01)

    def worker(index, barrier):
        barrier.wait()
        for n in range(2000):
            key = (index * 7 + n) % 97
            cache[key] = n
            cache.get(key)
            key in cache  # noqa: B015 - the read itself is the test
            cache.pop(key)
            if n % 50 == 0:
                list(cache)
                len(cache)
                cache.items()
                cache.expire()

    _run_all(worker)
    assert len(cache) <= 64


def test_iteration_is_a_snapshot_that_mutation_cannot_break():
    cache = LockedTTLCache(maxsize=1000, ttl=60)
    for n in range(500):
        cache[n] = n
    seen = []
    for key in cache:
        seen.append(key)
        cache.pop(key)
        cache[key + 10_000] = key
    assert len(seen) == 500


def test_pop_never_raises_and_get_distinguishes_a_cached_none():
    cache = LockedTTLCache(maxsize=10, ttl=60)
    assert cache.pop("absent") is None
    assert cache.pop("absent", "fallback") == "fallback"
    cache["k"] = None
    assert "k" in cache
    assert cache.get("k", "default") is None
    assert cache.get("missing", MISSING) is MISSING


def test_entries_expire_after_their_ttl():
    clock = FakeClock()
    cache = LockedTTLCache(maxsize=10, ttl=5, timer=clock)
    cache["k"] = "v"
    clock.now += 4.9
    assert cache.get("k") == "v"
    clock.now += 0.2
    assert cache.get("k") is None
    assert "k" not in cache
    assert cache.snapshot() == {}


# --- LockedTTLCache: invalidation-aware fills --------------------------------


def test_a_fill_that_overlapped_an_invalidation_is_returned_but_not_cached():
    """The stale-order-mode race, driven step by step.

    A reader misses and starts loading the old row. A writer commits and
    invalidates. The reader's load finishes. Before the fix it stored the old
    row and every reader after it saw the stale value for the whole TTL.
    """
    cache = LockedTTLCache(maxsize=10, ttl=60)
    loading = threading.Event()
    invalidated = threading.Event()
    result = {}

    def loader():
        loading.set()
        assert invalidated.wait(5)
        return "live"  # read before the writer's commit

    def reader():
        result["value"] = cache.get_or_load("order_mode", loader)

    thread = threading.Thread(target=reader)
    thread.start()
    assert loading.wait(5)
    cache.invalidate("order_mode")  # the writer, after its commit to "semi_auto"
    invalidated.set()
    thread.join(5)

    assert result["value"] == "live", "the reader still gets what it loaded"
    assert "order_mode" not in cache, "the stale load was cached over the invalidation"
    assert cache.get_or_load("order_mode", lambda: "semi_auto") == "semi_auto"
    assert cache.get("order_mode") == "semi_auto"


def test_clear_counts_as_an_invalidation_and_fill_reports_it():
    cache = LockedTTLCache(maxsize=10, ttl=60)
    generation = cache.generation
    cache.clear()
    assert cache.fill("k", "stale", generation) is False
    assert "k" not in cache
    assert cache.fill("k", "fresh", cache.generation) is True
    assert cache["k"] == "fresh"


def test_should_cache_keeps_empty_results_out():
    cache = LockedTTLCache(maxsize=10, ttl=60)
    calls = []

    def loader():
        calls.append(1)
        return []

    assert cache.get_or_load("strikes", loader, should_cache=bool) == []
    assert cache.get_or_load("strikes", loader, should_cache=bool) == []
    assert len(calls) == 2, "an empty result must not be cached"


def test_invalidate_all_and_invalidate_where():
    cache = LockedTTLCache(maxsize=10, ttl=60)
    for key in ("auth-alice", "feed-alice", "auth-bob"):
        cache[key] = key
    assert cache.invalidate_where(lambda key: key.endswith("-alice")) == 2
    assert cache.keys() == ["auth-bob"]
    cache.invalidate()
    assert len(cache) == 0


def test_invalidations_racing_fills_never_leave_a_value_from_before_the_last_one():
    """Many readers loading while a writer bumps a version and invalidates."""
    cache = LockedTTLCache(maxsize=10, ttl=60)
    version = {"value": 0}
    stop = threading.Event()

    def writer():
        while not stop.is_set():
            version["value"] += 1
            cache.invalidate("k")
            time.sleep(0.0005)

    def worker(_index, barrier):
        barrier.wait()
        for _ in range(300):
            cache.get_or_load("k", lambda: version["value"])

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    try:
        _run_all(worker)
    finally:
        stop.set()
        writer_thread.join(5)
    # The writer's last act was an invalidation after its last bump, so any
    # value still cached was loaded after it and must be the final version. A
    # fill that raced an invalidation would leave an older one behind.
    assert cache.get("k", MISSING) in (MISSING, version["value"])


# --- PositionBookCache ------------------------------------------------------


def test_a_position_fetch_that_straddles_an_order_is_not_cached():
    """Two smart orders on one symbol: the second must see the first's fill."""
    book = PositionBookCache(ttl=60)
    fetching = threading.Event()
    placed = threading.Event()
    positions = {"qty": 0}

    def slow_fetch():
        snapshot = dict(positions)
        fetching.set()
        assert placed.wait(5)
        return snapshot

    got = {}
    thread = threading.Thread(target=lambda: got.setdefault("v", book.get("token", slow_fetch)))
    thread.start()
    assert fetching.wait(5)
    positions["qty"] = 50  # the first order fills
    book.invalidate("token")  # and invalidates after placing
    placed.set()
    thread.join(5)

    assert got["v"] == {"qty": 0}
    assert book.get("token", lambda: dict(positions)) == {"qty": 50}


def test_position_book_is_reused_within_its_ttl():
    book = PositionBookCache(ttl=60)
    calls = []
    fetch = lambda: calls.append(1) or {"qty": 1}  # noqa: E731
    book.get("t", fetch)
    book.get("t", fetch)
    assert len(calls) == 1
    book.invalidate("t")
    book.get("t", fetch)
    assert len(calls) == 2


# --- SymbolLocks ----------------------------------------------------------------


def _hold_in_background(locks: SymbolLocks, symbol="SBIN"):
    holding = threading.Event()
    release = threading.Event()

    def holder():
        with locks.hold(symbol, "NSE", "MIS") as acquired:
            assert acquired
            holding.set()
            release.wait(10)

    thread = threading.Thread(target=holder)
    thread.start()
    assert holding.wait(5)
    return thread, release


def test_symbol_lock_waits_without_limit_outside_gthread(not_gthread):
    locks = SymbolLocks(max_wait=0.1)
    assert locks.effective_wait() is None
    thread, release = _hold_in_background(locks)
    threading.Timer(0.4, release.set).start()
    started = time.monotonic()
    with locks.hold("SBIN", "NSE", "MIS") as acquired:
        waited = time.monotonic() - started
        assert acquired is True, "outside gthread the wait is unbounded, as before"
    assert waited >= 0.3
    thread.join(5)
    assert len(locks) == 0


def test_symbol_lock_gives_up_after_the_bound_under_gthread(gthread):
    locks = SymbolLocks(max_wait=0.2)
    assert locks.effective_wait() == 0.2
    thread, release = _hold_in_background(locks)
    started = time.monotonic()
    with locks.hold("SBIN", "NSE", "MIS") as acquired:
        assert acquired is False
    assert time.monotonic() - started < 2
    release.set()
    thread.join(5)
    assert len(locks) == 0


def test_symbol_lock_default_bound_and_busy_tuple(gthread):
    assert SymbolLocks().effective_wait() == SMART_ORDER_LOCK_WAIT_SECONDS
    res, data, orderid = SymbolLocks.busy("SBIN")
    assert res.status == 429 and res.status_code == 429
    assert data["status"] == "error" and "SBIN" in data["message"]
    assert orderid is None


def test_symbol_locks_serialise_one_symbol_and_forget_it_afterwards(not_gthread):
    locks = SymbolLocks()
    inside = []
    overlaps = []
    guard = threading.Lock()

    def worker(index, barrier):
        barrier.wait()
        for n in range(20):
            symbol = "NIFTY" if n % 2 == 0 else f"SYM{index}"
            with locks.hold(symbol, "NFO", "NRML") as acquired:
                assert acquired
                if symbol == "NIFTY":
                    with guard:
                        inside.append(1)
                        if len(inside) > 1:
                            overlaps.append(1)
                    time.sleep(0.0005)
                    with guard:
                        inside.pop()

    _run_all(worker)
    assert overlaps == []
    assert len(locks) == 0


# --- broker backpressure ----------------------------------------------------


def test_no_bound_and_no_refusal_outside_gthread(not_gthread):
    assert bp.max_queue_wait("data") is None
    assert bp.max_queue_wait("order") is None
    bp.check_queue_wait(3600, "order")  # a wait of an hour is still allowed
    assert bp.cap_server_delay(1800, "data") == 1800

    lock = threading.Lock()
    lock.acquire()
    threading.Timer(0.3, lock.release).start()
    assert bp.acquire_bounded(lock, "data") is True


def test_waits_are_bounded_under_gthread(gthread):
    assert bp.max_queue_wait("data") == bp.BROKER_MAX_QUEUE_WAIT_SECONDS
    assert bp.max_queue_wait("order") == bp.BROKER_MAX_ORDER_QUEUE_WAIT_SECONDS
    bp.check_queue_wait(bp.BROKER_MAX_QUEUE_WAIT_SECONDS, "data")
    with pytest.raises(bp.BrokerBusyError) as refused:
        bp.check_queue_wait(bp.BROKER_MAX_QUEUE_WAIT_SECONDS + 1, "data")
    assert refused.value.retry_after == bp.BROKER_MAX_QUEUE_WAIT_SECONDS + 1
    assert str(refused.value) == bp.BROKER_BUSY_MESSAGE
    assert bp.cap_server_delay(2, "order") == 2
    assert bp.cap_server_delay(1800, "order") is None


def test_acquire_bounded_gives_up_under_gthread(gthread, monkeypatch):
    monkeypatch.setitem(bp._CEILINGS, "data", 0.2)
    lock = threading.Lock()
    lock.acquire()
    started = time.monotonic()
    assert bp.acquire_bounded(lock, "data") is False
    assert time.monotonic() - started < 2


def test_the_busy_error_and_response_shapes():
    assert bp.RateLimitBusy is bp.BrokerBusyError
    error = bp.BrokerBusyError("custom sentence", retry_after=3)
    assert str(error) == "custom sentence" and error.retry_after == 3
    res, data, orderid = bp.busy_response()
    assert (res.status, res.status_code) == (429, 429)
    assert data == {"status": "error", "message": bp.BROKER_BUSY_MESSAGE}
    assert orderid is None
    with pytest.raises(ValueError):
        bp.max_queue_wait("positions")
