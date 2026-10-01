"""One connection pool per user and broker, and a stale wrapper cannot evict a new one.

On the development server the websocket proxy runs as a thread beside request
threads, and logins tear pools down from those. The registry's check-then-
insert could build two pools (two broker feeds) for one user, a stale
wrapper's disconnect removed whatever pool now sat under its key, and stats
iterated the live dict. In production the proxy is a child process whose own
loop is the only writer, which is why this is low severity.
"""

from __future__ import annotations

import threading
import time

import pytest

import websocket_proxy.broker_factory as broker_factory


class SlowPool:
    built = 0
    lock = threading.Lock()

    def __init__(self, **kwargs):
        with SlowPool.lock:
            SlowPool.built += 1
        self.kwargs = kwargs
        self.disconnected = False
        time.sleep(0.02)

    def disconnect(self):
        self.disconnected = True

    def get_stats(self):
        return {"ok": True}


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(broker_factory, "ConnectionPool", SlowPool)
    monkeypatch.setattr(broker_factory, "_POOLED_ADAPTERS", {})
    SlowPool.built = 0
    return broker_factory._POOLED_ADAPTERS


def test_simultaneous_first_connects_share_one_pool(registry):
    barrier = threading.Barrier(16)
    pools = []

    def first_connect():
        wrapper = broker_factory._PooledAdapterWrapper(object, "fakebroker")
        barrier.wait()
        pools.append(wrapper._ensure_pool("u1"))

    threads = [threading.Thread(target=first_connect) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert len({id(pool) for pool in pools}) == 1
    assert registry["fakebroker_u1"] is pools[0]


def test_a_stale_wrapper_does_not_evict_the_newer_pool(registry):
    stale = broker_factory._PooledAdapterWrapper(object, "fakebroker")
    old_pool = stale._ensure_pool("u1")

    # A login replaces the pool under the same key.
    assert broker_factory.cleanup_pools_for_user("u1") == 1
    fresh = broker_factory._PooledAdapterWrapper(object, "fakebroker")
    new_pool = fresh._ensure_pool("u1")
    assert new_pool is not old_pool

    stale.disconnect()

    assert old_pool.disconnected is True
    assert registry["fakebroker_u1"] is new_pool  # before the fix: evicted


def test_stats_and_cleanup_work_on_a_snapshot(registry):
    for user in ("u1", "u2", "u3"):
        broker_factory._PooledAdapterWrapper(object, "fakebroker")._ensure_pool(user)

    stats = broker_factory.get_pool_stats("fakebroker")
    assert set(stats) == {"fakebroker_u1", "fakebroker_u2", "fakebroker_u3"}
    health = broker_factory.get_resource_health()
    assert health["active_pools"]["count"] == 3

    broker_factory.cleanup_all_pools()
    assert registry == {}
