"""Tests for thread-safe TTL caches (gthread PR-5b, gate A3).

Covers GT-A3-01 .. GT-A3-12.

cachetools states its cache classes are not thread-safe and shared access must
be synchronized. Nothing did: 12 modules held 26 TTLCache instances with no
lock. A TTLCache is not a plain dict -- it keeps an internal linked list for
expiry ordering, and concurrent mutation can corrupt it.
"""

import importlib
import sys
import threading

import pytest
from cachetools import TTLCache

from utils.thread_safe_cache import LockedTTLCache

CACHE_MODULES = [
    "database.auth_db",
    "database.settings_db",
    "database.user_db",
    "database.traffic_db",
    "database.flow_db",
    "database.strategy_db",
    "database.market_calendar_db",
    "database.leverage_db",
    "database.latency_db",
    "database.telegram_db",
    "database.whatsapp_db",
    "utils.trading_calendar",
]


def test_every_module_cache_is_locked():
    """No bare TTLCache may survive in the twelve audited modules."""
    unlocked = []
    locked = 0
    for name in CACHE_MODULES:
        mod = importlib.import_module(name)
        for attr, value in vars(mod).items():
            if isinstance(value, TTLCache):
                if isinstance(value, LockedTTLCache):
                    locked += 1
                else:
                    unlocked.append(f"{name}.{attr}")
    assert unlocked == [], f"unlocked caches remain: {unlocked}"
    assert locked == 26, f"expected 26 locked caches, found {locked}"


def test_concurrent_mutation_does_not_corrupt_the_cache():
    """The hazard cachetools warns about, driven hard."""
    cache = LockedTTLCache(maxsize=256, ttl=60)
    errors = []
    barrier = threading.Barrier(8)

    def churn(worker):
        barrier.wait()
        try:
            for i in range(400):
                key = f"k{(worker * 400 + i) % 300}"
                cache[key] = i
                cache.get(key)
                if i % 7 == 0:
                    cache.pop(key, None)
                if i % 23 == 0:
                    len(cache)
        except Exception as exc:  # pragma: no cover - the failure we guard against
            errors.append(exc)

    threads = [threading.Thread(target=churn, args=(w,)) for w in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"cache raised under concurrency: {errors[:3]}"
    assert len(cache) <= 256


def _churn(cache, workers=12, iterations=3000):
    """Drive expiry AND eviction hard -- that is where the internal linked
    list is rewritten, and where an unlocked cache actually breaks."""
    errors = []
    barrier = threading.Barrier(workers)

    def worker(w):
        barrier.wait()
        try:
            for i in range(iterations):
                key = f"k{(w * iterations + i) % 64}"
                cache[key] = i
                cache.get(key)
                if i % 3 == 0:
                    cache.pop(key, None)
                if i % 5 == 0:
                    len(cache)
                if i % 11 == 0:
                    list(cache)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def test_unlocked_cache_really_does_break(monkeypatch):
    """The control. Without this, the test below proves nothing.

    A plain load does NOT reproduce the fault -- CPython's GIL hides it. It
    needs expiry plus eviction plus a tight switch interval, which is exactly
    why this class of bug never surfaced under eventlet.
    """
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        errors = _churn(TTLCache(maxsize=32, ttl=0.001))
    finally:
        sys.setswitchinterval(old)
    assert errors, "expected an unlocked TTLCache to fail under expiry pressure"


def test_locked_cache_survives_the_same_load():
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        errors = _churn(LockedTTLCache(maxsize=32, ttl=0.001))
    finally:
        sys.setswitchinterval(old)
    assert errors == [], f"locked cache failed: {errors[:3]}"


def test_get_is_atomic_where_contains_then_getitem_is_not():
    """`if k in c: c[k]` is two operations; only get() is one."""
    cache = LockedTTLCache(maxsize=8, ttl=60)
    cache["a"] = 1
    assert cache.get("a") == 1
    assert cache.get("missing") is None
    assert cache.get("missing", "fallback") == "fallback"


def test_lock_is_public_and_reentrant():
    """Callers need it for genuinely multi-step sequences."""
    cache = LockedTTLCache(maxsize=8, ttl=60)
    assert hasattr(cache, "lock")
    with cache.lock:
        # Reentrant: operations take the same lock internally.
        cache["x"] = 1
        assert cache["x"] == 1


def test_pop_and_setdefault_are_atomic():
    cache = LockedTTLCache(maxsize=8, ttl=60)
    cache["a"] = 1
    assert cache.pop("a") == 1
    assert cache.pop("a", "default") == "default"
    assert cache.setdefault("b", 2) == 2
    assert cache.setdefault("b", 99) == 2


def test_iteration_takes_a_snapshot():
    """Iterating must not hold the lock across the caller's loop body."""
    cache = LockedTTLCache(maxsize=64, ttl=60)
    for i in range(10):
        cache[f"k{i}"] = i
    keys = []
    for key in cache:
        keys.append(key)
        cache[f"new{key}"] = 1  # mutating during iteration must not explode
    assert len(keys) == 10


def test_ttl_behaviour_is_preserved():
    """Locking must not change expiry semantics."""
    cache = LockedTTLCache(maxsize=8, ttl=0.05)
    cache["a"] = 1
    assert cache.get("a") == 1
    threading.Event().wait(0.1)
    assert cache.get("a") is None


def test_maxsize_eviction_is_preserved():
    cache = LockedTTLCache(maxsize=3, ttl=60)
    for i in range(5):
        cache[f"k{i}"] = i
    assert len(cache) == 3


@pytest.mark.parametrize(
    "snippet",
    [
        "auth_cache.get(cache_key)",
        "feed_token_cache.get(cache_key)",
        "verified_api_key_cache.get(cache_key)",
        "broker_cache.get(provided_api_key)",
        "auth_cache.pop(cache_key, None)",
    ],
)
def test_auth_db_order_path_uses_atomic_reads(snippet):
    """auth_db is on the live order path: tokens, broker choice, order mode."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "database" / "auth_db.py").read_text()
    assert snippet in src, f"expected atomic access: {snippet}"
