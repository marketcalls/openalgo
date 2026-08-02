"""The pooled broker-adapter registry under real threads (GT-A15-08).

``websocket_proxy/broker_factory._POOLED_ADAPTERS`` maps ``{broker}_{user_id}``
to a live ``ConnectionPool``. It had no lock at all.

Two shapes were reachable:

1. **Check-then-create.** ``_ensure_pool()`` did::

       if pool_key in _POOLED_ADAPTERS:      # both threads miss
           ...
       else:
           _POOLED_ADAPTERS[pool_key] = ConnectionPool(...)

   Two callers could each build a pool; the second registration overwrites the
   first, and the orphaned pool keeps its broker sockets open with no reference
   left to disconnect it. That is a descriptor leak in a process that never
   restarts, not merely a wasted object.

2. **Live iteration.** ``get_pool_stats()`` and ``get_resource_health()``
   iterated the dict directly. Both are reachable from
   ``utils/health_monitor.py``, which runs on a background daemon thread, so a
   pool appearing or disappearing mid-loop raises RuntimeError.

Under Gunicorn the proxy runs out of process, so the worker's copy stays empty
and the iteration is incidentally safe. In ``thread`` mode -- ``uv run app.py``
on Windows and macOS -- the proxy shares the process, the dict is populated,
and this is a live race **today**, independent of the gthread migration.
"""

import ast
import inspect
import threading

import pytest

import websocket_proxy.broker_factory as bf


@pytest.fixture(autouse=True)
def clean_registry():
    saved = dict(bf._POOLED_ADAPTERS)
    bf._POOLED_ADAPTERS.clear()
    yield
    bf._POOLED_ADAPTERS.clear()
    bf._POOLED_ADAPTERS.update(saved)


class _FakePool:
    """Stands in for ConnectionPool: records whether it was ever disconnected."""

    def __init__(self, *a, **kw):
        self.disconnected = False

    def get_stats(self):
        return {"ok": True}

    def disconnect(self):
        self.disconnected = True


def test_registry_has_a_lock():
    assert isinstance(bf._POOL_LOCK, type(threading.RLock())), (
        "_POOLED_ADAPTERS must be guarded by a reentrant lock"
    )


def test_concurrent_ensure_pool_creates_exactly_one_pool(monkeypatch):
    """The important one: a second pool would hold broker sockets that nothing
    ever disconnects."""
    created = []

    def _factory(*a, **kw):
        pool = _FakePool()
        created.append(pool)
        return pool

    monkeypatch.setattr(bf, "ConnectionPool", _factory)

    adapters = [
        bf._PooledAdapterWrapper(adapter_class=object, broker_name="testbroker")
        for _ in range(8)
    ]
    barrier = threading.Barrier(len(adapters))
    errors = []

    def race(adapter):
        try:
            barrier.wait(timeout=10)
            adapter._ensure_pool("user1")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=race, args=(a,)) for a in adapters]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == [], errors
    assert len(created) == 1, (
        f"{len(created)} pools created for one key; the extras hold broker "
        "sockets that nothing will ever disconnect"
    )
    assert len(bf._POOLED_ADAPTERS) == 1
    # Every adapter must share the single registered pool.
    registered = bf._POOLED_ADAPTERS["testbroker_user1"]
    assert all(a._pool is registered for a in adapters)


def test_stats_readers_survive_concurrent_registry_churn():
    """get_pool_stats runs from the health-monitor daemon thread."""
    stop = threading.Event()
    errors = []

    def churn():
        i = 0
        while not stop.is_set():
            bf._POOLED_ADAPTERS[f"b_{i}"] = _FakePool()
            bf._POOLED_ADAPTERS.pop(f"b_{i}", None)
            i += 1

    def reader(fn):
        while not stop.is_set():
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{fn.__name__}: {type(exc).__name__}: {exc}")
                return

    threads = [threading.Thread(target=churn)]
    for fn in (bf.get_pool_stats, bf.get_resource_health):
        threads += [threading.Thread(target=reader, args=(fn,)) for _ in range(2)]

    for t in threads:
        t.start()
    stop.wait(2.0)
    stop.set()
    for t in threads:
        t.join(timeout=5)

    assert errors == [], f"stats readers raised during churn: {errors[:3]}"


def test_cleanup_disconnects_every_pool_exactly_once():
    pools = {f"b_{i}": _FakePool() for i in range(5)}
    bf._POOLED_ADAPTERS.update(pools)

    bf.cleanup_all_pools()

    assert bf._POOLED_ADAPTERS == {}
    assert all(p.disconnected for p in pools.values()), (
        "a pool was dropped from the registry without being disconnected"
    )


def test_no_reader_iterates_the_live_registry():
    """Structural guard for functions that do not exist yet."""
    tree = ast.parse(inspect.getsource(bf))

    locked = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With) and "_POOL_LOCK" in ast.dump(node):
            for sub in ast.walk(node):
                if hasattr(sub, "lineno"):
                    locked.add(sub.lineno)

    offenders = []
    for node in ast.walk(tree):
        iters = []
        if isinstance(node, ast.For):
            iters.append((node.lineno, node.iter))
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            iters += [(node.lineno, g.iter) for g in node.generators]
        for lineno, it in iters:
            base = it.func.value if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) else it
            if isinstance(base, ast.Name) and base.id == "_POOLED_ADAPTERS" and lineno not in locked:
                offenders.append(f"line {lineno}")
    assert offenders == [], (
        f"these iterate the live pool registry outside the lock: {offenders}; "
        "snapshot under _POOL_LOCK first"
    )


def test_pool_stats_is_not_computed_while_holding_the_lock():
    """get_stats() can be slow. Holding the lock across it would let a
    diagnostics page stall a broker connect."""
    src = inspect.getsource(bf.get_pool_stats)
    fn = ast.parse(src).body[0]

    locked = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.With) and "_POOL_LOCK" in ast.dump(node):
            for sub in ast.walk(node):
                if hasattr(sub, "lineno"):
                    locked.add(sub.lineno)

    inside = [
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "get_stats"
        and n.lineno in locked
    ]
    assert inside == [], f"get_stats() called while holding _POOL_LOCK: {inside}"
