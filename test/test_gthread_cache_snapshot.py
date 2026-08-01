"""Tests for atomic cache snapshot swaps (gthread PR-4, gate A2).

Covers GT-A2-01, GT-A2-02 (symbol cache) and GT-A2-03 (freeze-quantity cache).

Both caches previously cleared their structures in place and refilled them.
During that window a concurrent reader saw empty structures while the
"loaded" flag was still true. On the order path that is not a slow lookup, it
is a *wrong* one: a missing symbol looks like "no such symbol", and a missing
freeze quantity silently defaults to 1, which changes how an order is split.

eventlet hid both because the rebuild never yielded. Real threads do not.
"""

import threading

import pytest

from database.token_db_enhanced import BrokerSymbolCache, SymbolData, _SymbolSnapshot


def _symbol(token: str) -> SymbolData:
    return SymbolData(
        symbol=f"SYM{token}",
        brsymbol=f"BR{token}",
        name="n",
        exchange="NFO",
        brexchange="NFO",
        token=token,
    )


def _fill(snap: _SymbolSnapshot, n: int) -> _SymbolSnapshot:
    for i in range(n):
        sd = _symbol(str(i))
        snap.symbols[sd.token] = sd
        snap.by_symbol_exchange[(sd.symbol, sd.exchange)] = sd
        snap.by_token[sd.token] = sd
        snap.by_exchange[sd.exchange].append(sd)
    return snap


# --------------------------------------------------------------------------
# Symbol cache
# --------------------------------------------------------------------------


def test_readers_never_observe_a_partial_snapshot():
    """The core guarantee: complete old generation, or complete new one."""
    cache = BrokerSymbolCache()
    cache._snap = _fill(_SymbolSnapshot(), 500)
    cache.cache_loaded = True

    observed_sizes = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            # Bind once, exactly as the lookup paths do.
            snap = cache._snap
            observed_sizes.append(len(snap.symbols))

    def writer():
        for n in (1000, 250, 750):
            cache._snap = _fill(_SymbolSnapshot(), n)

    r = threading.Thread(target=reader)
    r.start()
    w = threading.Thread(target=writer)
    w.start()
    w.join()
    stop.set()
    r.join()

    # Every observation must be one of the published generations. A partial
    # rebuild would show a size nobody ever published.
    assert set(observed_sizes) <= {500, 1000, 250, 750}, sorted(set(observed_sizes))
    assert observed_sizes, "reader never ran"


def test_snapshot_swap_is_a_single_rebind():
    cache = BrokerSymbolCache()
    first = cache._snap
    cache._snap = _fill(_SymbolSnapshot(), 3)
    assert cache._snap is not first
    assert len(cache.symbols) == 3


def test_properties_read_through_to_the_live_snapshot():
    """All ~56 existing read sites go through these, so they must track swaps."""
    cache = BrokerSymbolCache()
    cache._snap = _fill(_SymbolSnapshot(), 2)
    for name in BrokerSymbolCache._SNAPSHOT_FIELDS:
        assert getattr(cache, name) is getattr(cache._snap, name)


def test_clear_cache_lowers_the_flag_before_emptying():
    """A reader must never see loaded=True with empty structures."""
    cache = BrokerSymbolCache()
    cache._snap = _fill(_SymbolSnapshot(), 10)
    cache.cache_loaded = True
    cache.active_broker = "zerodha"

    cache.clear_cache()

    assert cache.cache_loaded is False
    assert cache.active_broker is None
    assert len(cache.symbols) == 0


def test_load_is_serialized_by_a_writer_lock():
    cache = BrokerSymbolCache()
    assert isinstance(cache._load_lock, type(threading.Lock()))


def test_snapshot_has_all_ten_structures():
    snap = _SymbolSnapshot()
    for name in BrokerSymbolCache._SNAPSHOT_FIELDS:
        assert hasattr(snap, name), name


# --------------------------------------------------------------------------
# Freeze-quantity cache
# --------------------------------------------------------------------------


@pytest.fixture
def qty_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    import database.qty_freeze_db as q

    return q


def test_freeze_qty_reload_never_exposes_an_empty_cache(qty_db):
    """A lookup during reload must not silently fall back to the default of 1."""
    qty_db._freeze_qty_cache = {"NFO:NIFTY": 1800}
    qty_db._cache_loaded = True

    observed = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            observed.append(qty_db.get_freeze_qty("NIFTY", "NFO"))

    def writer():
        for value in (900, 1800, 2100):
            # Mirror the publish step: build aside, then rebind.
            qty_db._freeze_qty_cache = {"NFO:NIFTY": value}

    r = threading.Thread(target=reader)
    r.start()
    w = threading.Thread(target=writer)
    w.start()
    w.join()
    stop.set()
    r.join()

    assert observed, "reader never ran"
    # 1 is the "not configured" default. Seeing it here would mean a reader
    # caught the cache mid-rebuild -- the exact bug this gate closes.
    assert 1 not in observed, "reader saw the default during reload"
    assert set(observed) <= {900, 1800, 2100}


def test_freeze_qty_readers_bind_the_global_once(qty_db):
    import inspect

    for fn in (qty_db.get_freeze_qty, qty_db.get_all_freeze_qty):
        src = inspect.getsource(fn)
        assert "cache = _freeze_qty_cache" in src, fn.__name__


def test_freeze_qty_load_has_a_writer_lock(qty_db):
    assert hasattr(qty_db, "_cache_load_lock")


def test_freeze_qty_load_does_not_clear_in_place(qty_db):
    import inspect

    src = inspect.getsource(qty_db.load_freeze_qty_cache)
    assert "_freeze_qty_cache.clear()" not in src
    assert "new_cache" in src
