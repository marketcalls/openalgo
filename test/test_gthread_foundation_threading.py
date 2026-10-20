"""real_threading, LazyInit and KeyedLocks under real, parallel threads.

These are the gthread and dev-server behaviours: nothing is patched, threads
run truly in parallel, and a Barrier lines them up so the race each helper
closes is actually attempted rather than merely possible. The eventlet side of
real_threading (run_on_hub from a real OS thread) is proved under a real hub in
test_eventlet_cross_thread_locks.py, which runs eventlet in a subprocess.
"""

from __future__ import annotations

import threading
import time

import pytest

from utils import real_threading as rt
from utils.keyed_locks import KeyedLocks, LockBusy
from utils.lazy import LazyInit

THREADS = 16


def _run_all(target, count=THREADS, timeout=30):
    """Start ``count`` threads on ``target(index, barrier)`` and join them all."""
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
    assert errors == [], errors


# --- real_threading, unpatched ----------------------------------------------


def test_primitives_are_the_stdlib_ones_when_nothing_is_patched():
    assert rt.Lock is threading.Lock
    assert rt.RLock is threading.RLock
    assert rt.Event is threading.Event
    assert rt.Thread is threading.Thread
    assert rt.sleep is time.sleep
    assert rt.is_monkey_patched() is False
    assert rt.on_hub_thread() is True


def test_wait_for_and_join_use_the_native_wait_and_keep_their_results():
    event = rt.Event()
    threading.Timer(0.05, event.set).start()
    started = time.monotonic()
    assert rt.wait_for(event, 5) is True
    assert time.monotonic() - started < 2
    assert rt.wait_for(rt.Event(), 0.05) is False

    worker = rt.Thread(target=time.sleep, args=(0.05,))
    worker.start()
    assert rt.join(worker, timeout=5) is True
    slow = rt.Thread(target=time.sleep, args=(2,), daemon=True)
    slow.start()
    assert rt.join(slow, timeout=0.05) is False


def test_run_on_hub_calls_inline_when_nothing_is_patched():
    caller = threading.get_ident()
    seen = {}

    def work(a, b=0):
        seen["thread"] = threading.get_ident()
        return a + b

    assert rt.run_on_hub(work, 2, b=3, timeout=1) == 5
    assert seen["thread"] == caller

    with pytest.raises(ValueError, match="boom"):
        rt.run_on_hub(lambda: (_ for _ in ()).throw(ValueError("boom")), timeout=1)


def test_submit_to_hub_calls_inline_and_propagates_when_nothing_is_patched():
    calls = []
    rt.submit_to_hub(calls.append, 1)
    assert calls == [1]

    def boom():
        raise RuntimeError("inline")

    with pytest.raises(RuntimeError, match="inline"):
        rt.submit_to_hub(boom)


def test_start_hub_worker_is_a_no_op_unless_eventlet_patched():
    assert rt.start_hub_worker() is False
    assert rt.hub_worker_running() is False


def test_run_on_hub_requires_an_explicit_timeout():
    with pytest.raises(TypeError):
        rt.run_on_hub(lambda: None)  # type: ignore[call-arg]


# --- LazyInit ---------------------------------------------------------------


def test_lazy_init_builds_once_under_a_simultaneous_first_use():
    built = []

    def factory():
        built.append(1)
        time.sleep(0.05)  # widen the window two builders would share
        return object()

    lazy = LazyInit(factory, name="test")
    results = []

    def worker(_index, barrier):
        barrier.wait()
        results.append(lazy.get())

    _run_all(worker)
    assert len(built) == 1, f"factory ran {len(built)} times"
    assert len({id(value) for value in results}) == 1
    assert lazy.peek() is results[0]


def test_lazy_init_retries_after_a_failing_factory():
    attempts = []

    def factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("first build fails")
        return "ready"

    lazy = LazyInit(factory, name="flaky")
    with pytest.raises(ConnectionError):
        lazy.get()
    assert lazy.peek() is None
    assert lazy.get() == "ready"
    assert len(attempts) == 2


def test_lazy_init_reset_closes_the_old_value_and_rebuilds():
    closed = []
    counter = iter(range(100))
    lazy = LazyInit(lambda: next(counter), name="counter")
    assert lazy.get() == 0
    lazy.reset(close=closed.append)
    assert closed == [0]
    assert lazy.peek() is None
    assert lazy.get() == 1
    lazy.reset()  # no close given: just forgets
    assert lazy.get() == 2
    empty = LazyInit(lambda: 1, name="never-built")
    empty.reset(close=closed.append)
    assert closed == [0], "close must not be called when nothing was built"


# --- KeyedLocks ---------------------------------------------------------------


def test_one_key_is_held_by_one_thread_at_a_time():
    locks = KeyedLocks(name="test")
    inside = []
    overlaps = []
    state_lock = threading.Lock()

    def worker(_index, barrier):
        barrier.wait()
        for _ in range(20):
            with locks.hold("NIFTY"):
                with state_lock:
                    inside.append(1)
                    if len(inside) > 1:
                        overlaps.append(len(inside))
                time.sleep(0.0005)
                with state_lock:
                    inside.pop()

    _run_all(worker)
    assert overlaps == [], "two threads held the same key at once"
    assert len(locks) == 0, "the registry kept a key nobody holds"


def test_different_keys_do_not_wait_on_each_other():
    locks = KeyedLocks(name="test")
    holding = threading.Event()
    release = threading.Event()

    def hold_a():
        with locks.hold("A"):
            holding.set()
            release.wait(5)

    thread = threading.Thread(target=hold_a)
    thread.start()
    assert holding.wait(5)
    started = time.monotonic()
    with locks.hold("B", timeout=1):
        pass
    assert time.monotonic() - started < 0.5
    release.set()
    thread.join(5)
    assert len(locks) == 0


def test_a_timed_out_wait_raises_lock_busy_and_leaves_nothing_behind():
    locks = KeyedLocks(name="smart-order")
    holding = threading.Event()
    release = threading.Event()

    def holder():
        with locks.hold("SBIN"):
            holding.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert holding.wait(5)

    started = time.monotonic()
    with pytest.raises(LockBusy) as busy:
        with locks.hold("SBIN", timeout=0.2):
            pytest.fail("the body must not run without the lock")
    waited = time.monotonic() - started
    assert 0.15 <= waited < 2
    assert busy.value.key == "SBIN" and busy.value.name == "smart-order"
    assert isinstance(busy.value, TimeoutError)
    assert "Try again" in str(busy.value)

    with pytest.raises(LockBusy):
        with locks.hold("SBIN", timeout=0):
            pass

    with locks.try_hold("SBIN", timeout=0) as acquired:
        assert acquired is False

    release.set()
    thread.join(5)
    assert len(locks) == 0


def test_the_registry_is_bounded_by_the_keys_in_use():
    locks = KeyedLocks(name="test")

    def worker(index, barrier):
        barrier.wait()
        for n in range(200):
            with locks.hold(f"SYM{index}-{n}"):
                pass

    _run_all(worker)
    assert len(locks) == 0, f"{len(locks)} keys left in the registry"


def test_a_reentrant_registry_lets_the_holder_take_its_key_again():
    locks = KeyedLocks(reentrant=True, name="positions")
    with locks.hold(("user", "NSE", "SBIN", "MIS")):
        with locks.hold(("user", "NSE", "SBIN", "MIS"), timeout=0):
            assert len(locks) == 1
    assert len(locks) == 0


def test_an_exception_in_the_body_releases_the_key():
    locks = KeyedLocks(name="test")
    with pytest.raises(RuntimeError):
        with locks.hold("X"):
            raise RuntimeError("body failed")
    with locks.hold("X", timeout=0):
        pass
    assert len(locks) == 0
