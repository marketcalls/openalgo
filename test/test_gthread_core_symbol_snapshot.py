"""The symbol and freeze-quantity caches publish whole generations.

Both used to clear their dicts and refill them in place. Under eventlet the
rebuild never yielded, so no reader saw it half done. Under the gthread
worker a reader iterating the symbol indexes during a reload could raise
"dictionary changed size during iteration" or get the part of an expiry list
loaded so far, which the option chain presents as complete; and a freeze
quantity read in the gap came back 0, "no limit known", so an order above the
freeze quantity went out unsplit and the exchange rejected it.

Now each load builds a new generation aside and publishes it in one
assignment. These tests drive a writer reloading between two different
universes while readers loop, and require every answer to be all of one
universe or all of the other.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import database.qty_freeze_db as qf
import database.symbol as symbol_module
import database.token_db_enhanced as tde

ROWS_PER_EXPIRY = 5000
EXPIRIES_A = ("30-DEC-27", "27-JAN-28")
EXPIRIES_B = ("24-FEB-28", "30-MAR-28")


def _rows(expiries, underlyings=("NIFTY", "BANKNIFTY")):
    rows = []
    n = 0
    for expiry in expiries:
        day, month, year = expiry.split("-")
        for underlying in underlyings:
            for i in range(ROWS_PER_EXPIRY // len(underlyings)):
                n += 1
                strike = 10000 + i * 50
                side = "CE" if i % 2 else "PE"
                rows.append(
                    SimpleNamespace(
                        symbol=f"{underlying}{day}{month}{year}{strike}{side}",
                        brsymbol=f"BR{n}",
                        name=underlying,
                        exchange="NFO",
                        brexchange="NFO",
                        token=f"{expiry}-{n}",
                        expiry=expiry,
                        strike=float(strike),
                        lotsize=50,
                        instrumenttype="OPTIDX",
                        tick_size=0.05,
                    )
                )
    return rows


class FakeSymTokenQuery:
    def __init__(self, universes):
        self.universes = universes
        self.turn = 0
        self.calls = 0

    def all(self):
        self.calls += 1
        rows = self.universes[self.turn % len(self.universes)]
        self.turn += 1
        return rows


@pytest.fixture
def fresh_cache(monkeypatch):
    cache = tde.BrokerSymbolCache()
    monkeypatch.setattr(tde, "_cache_instance", cache)
    # fno_search_symbols adds a freeze quantity to every row.
    monkeypatch.setattr(qf, "_cache_loaded", True)
    monkeypatch.setattr(qf, "_freeze_qty_cache", {"NFO:NIFTY": 1800})
    return cache


def test_readers_never_see_a_half_built_universe(fresh_cache, monkeypatch):
    query = FakeSymTokenQuery([_rows(EXPIRIES_A), _rows(EXPIRIES_B)])
    monkeypatch.setattr(symbol_module.SymToken, "query", query)
    assert fresh_cache.load_all_symbols("zerodha") is True

    full_a = sorted(EXPIRIES_A, key=lambda e: time.strptime(e, "%d-%b-%y"))
    full_b = sorted(EXPIRIES_B, key=lambda e: time.strptime(e, "%d-%b-%y"))
    stop = threading.Event()
    errors = []
    partial = []

    def reader():
        try:
            while not stop.is_set():
                expiries = tde.get_distinct_expiries_cached("NFO", "NIFTY")
                if expiries not in (full_a, full_b):
                    partial.append(expiries)
                underlyings = tde.get_distinct_underlyings_cached("NFO")
                if underlyings not in ([], ["BANKNIFTY", "NIFTY"]):
                    partial.append(underlyings)
                tde.search_symbols("NIFTY 10050", "NFO", limit=20)
                tde.fno_search_symbols(underlying="NIFTY", exchange="NFO", limit=20)
                tde.get_distinct_expiries_cached()
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    def writer():
        try:
            for _ in range(20):
                fresh_cache.load_all_symbols("zerodha")
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    readers = [threading.Thread(target=reader) for _ in range(6)]
    for thread in readers:
        thread.start()
    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    writer_thread.join(120)
    stop.set()
    for thread in readers:
        thread.join(30)

    assert errors == [], errors[:3]
    # Before the fix: partial expiry lists, and sometimes a RuntimeError.
    assert partial == [], partial[:3]


def test_a_reader_during_a_reload_gets_the_whole_previous_universe(fresh_cache, monkeypatch):
    """Pause a reload half way through and read: the answer is the old universe.

    Before the fix the reload had already cleared the indexes, so the reader
    either saw them half refilled or, with the loaded flag down, went to the
    database, which during a master contract download is itself half written.
    """
    query = FakeSymTokenQuery([_rows(EXPIRIES_A), _rows(EXPIRIES_B)])
    monkeypatch.setattr(symbol_module.SymToken, "query", query)
    assert fresh_cache.load_all_symbols("zerodha") is True

    def no_database(*_args, **_kwargs):
        raise AssertionError("a reader fell back to the database during a reload")

    monkeypatch.setattr(symbol_module, "get_distinct_expiries", no_database)
    monkeypatch.setattr(symbol_module, "get_distinct_underlyings", no_database)

    real_symbol_data = tde.SymbolData
    paused = threading.Event()
    resume = threading.Event()
    writer_ident = []
    built = []

    def pausing_symbol_data(*args, **kwargs):
        if threading.get_ident() in writer_ident:
            built.append(1)
            if len(built) == ROWS_PER_EXPIRY:
                paused.set()
                assert resume.wait(30), "the test never resumed the reload"
        return real_symbol_data(*args, **kwargs)

    monkeypatch.setattr(tde, "SymbolData", pausing_symbol_data)

    def reload():
        writer_ident.append(threading.get_ident())
        fresh_cache.load_all_symbols("zerodha")

    writer = threading.Thread(target=reload)
    writer.start()
    try:
        assert paused.wait(30), "the reload never reached the middle"
        full_a = sorted(EXPIRIES_A, key=lambda e: time.strptime(e, "%d-%b-%y"))
        assert tde.get_distinct_expiries_cached("NFO", "NIFTY") == full_a
        assert tde.get_distinct_underlyings_cached("NFO") == ["BANKNIFTY", "NIFTY"]
        assert len(tde.fno_search_symbols(underlying="NIFTY", exchange="NFO")) == (
            ROWS_PER_EXPIRY // 2 * len(EXPIRIES_A)
        )
    finally:
        resume.set()
        writer.join(60)

    full_b = sorted(EXPIRIES_B, key=lambda e: time.strptime(e, "%d-%b-%y"))
    assert tde.get_distinct_expiries_cached("NFO", "NIFTY") == full_b


def test_two_loads_at_once_run_one_after_the_other(fresh_cache, monkeypatch):
    inside = []
    overlap = []

    class SlowQuery:
        def all(self):
            inside.append(1)
            if len(inside) > 1:
                overlap.append(1)
            time.sleep(0.05)
            inside.pop()
            return _rows(EXPIRIES_A[:1])

    monkeypatch.setattr(symbol_module.SymToken, "query", SlowQuery())
    barrier = threading.Barrier(4)

    def load():
        barrier.wait()
        fresh_cache.load_all_symbols("zerodha")

    threads = [threading.Thread(target=load) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert overlap == []
    assert fresh_cache.cache_loaded is True
    assert fresh_cache.stats.total_symbols == ROWS_PER_EXPIRY


def test_the_quiet_path_is_unchanged(fresh_cache, monkeypatch):
    monkeypatch.setattr(symbol_module.SymToken, "query", FakeSymTokenQuery([_rows(EXPIRIES_A)]))
    assert tde.get_cache() is fresh_cache
    assert fresh_cache.cache_loaded is False
    assert fresh_cache.load_all_symbols("zerodha") is True
    assert fresh_cache.cache_loaded is True
    assert fresh_cache.active_broker == "zerodha"
    assert fresh_cache.is_cache_valid() is True

    row = _rows(EXPIRIES_A)[0]
    assert tde.get_token(row.symbol, "NFO") == row.token
    assert tde.get_br_symbol(row.symbol, "NFO") == row.brsymbol
    assert tde.get_symbol(row.token, "NFO") == row.symbol
    assert tde.get_oa_symbol(row.brsymbol, "NFO") == row.symbol
    assert tde.get_symbol_info(row.symbol, "NFO").lotsize == 50
    assert tde.get_tokens_bulk([(row.symbol, "NFO")]) == [row.token]

    info = fresh_cache.get_cache_info()
    assert info["cache_loaded"] is True and info["next_reset"] is not None

    # A clear empties the cache and keeps the session timing, as before.
    fresh_cache.clear_cache()
    assert fresh_cache.cache_loaded is False
    assert fresh_cache.symbols == {}
    assert fresh_cache.get_cache_info()["next_reset"] == info["next_reset"]

    # A load that finds nothing leaves the cache empty, as before.
    monkeypatch.setattr(symbol_module.SymToken, "query", FakeSymTokenQuery([[]]))
    assert fresh_cache.load_all_symbols("zerodha") is False
    assert fresh_cache.cache_loaded is False


def _reads_of_snap(node) -> int:
    return sum(
        1
        for sub in ast.walk(node)
        if isinstance(sub, ast.Attribute)
        and sub.attr == "_snap"
        and isinstance(sub.value, ast.Name)
        and sub.value.id == "self"
        and isinstance(sub.ctx, ast.Load)
    )


def test_no_cache_method_reads_the_snapshot_twice():
    source = textwrap.dedent(inspect.getsource(tde.BrokerSymbolCache))
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and _reads_of_snap(node) > 1:
            offenders.append(node.name)
    assert offenders == [], f"bind self._snap once per call: {offenders}"


def test_the_singleton_exists_before_anyone_asks():
    source = Path(tde.__file__).read_text(encoding="utf-8")
    assert "_cache_instance: BrokerSymbolCache = BrokerSymbolCache()" in source
    assert isinstance(tde.get_cache(), tde.BrokerSymbolCache)


# --- freeze quantities (core-11) ---------------------------------------------


class FakeFreezeQuery:
    def __init__(self, rows, delay=0.0):
        self.rows = rows
        self.delay = delay
        self.calls = 0

    def all(self):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return list(self.rows)


def _freeze_rows():
    rows = [SimpleNamespace(exchange="NFO", symbol="NIFTY", freeze_qty=1800)]
    rows += [
        SimpleNamespace(exchange="NFO", symbol=f"STOCK{i}", freeze_qty=100 + i) for i in range(200)
    ]
    return rows


def test_a_freeze_quantity_read_during_a_reload_is_never_zero(monkeypatch):
    monkeypatch.setattr(qf.QtyFreeze, "query", FakeFreezeQuery(_freeze_rows(), delay=0.001))
    monkeypatch.setattr(qf, "_freeze_qty_cache", {})
    monkeypatch.setattr(qf, "_cache_loaded", False)
    qf.load_freeze_qty_cache()

    stop = threading.Event()
    zeros = []

    def reader():
        while not stop.is_set():
            if qf.get_freeze_qty("NIFTY", "NFO") == 0:
                zeros.append(1)

    readers = [threading.Thread(target=reader) for _ in range(6)]
    for thread in readers:
        thread.start()
    for _ in range(50):
        qf.load_freeze_qty_cache()
    stop.set()
    for thread in readers:
        thread.join(30)

    # Before the fix a read landing between clear() and the refill answered
    # 0, and the order was not split at the freeze quantity.
    assert zeros == []


def test_cold_readers_load_the_freeze_table_once(monkeypatch):
    query = FakeFreezeQuery(_freeze_rows(), delay=0.05)
    monkeypatch.setattr(qf.QtyFreeze, "query", query)
    monkeypatch.setattr(qf, "_freeze_qty_cache", {})
    monkeypatch.setattr(qf, "_cache_loaded", False)
    barrier = threading.Barrier(8)
    answers = []

    def cold_reader():
        barrier.wait()
        answers.append(qf.get_freeze_qty("NIFTY", "NFO"))

    threads = [threading.Thread(target=cold_reader) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert query.calls == 1
    assert answers == [1800] * 8


def test_a_failed_freeze_load_leaves_the_cache_empty_as_before(monkeypatch):
    class Broken:
        def all(self):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(qf, "_freeze_qty_cache", {"NFO:NIFTY": 1800})
    monkeypatch.setattr(qf, "_cache_loaded", True)
    monkeypatch.setattr(qf.QtyFreeze, "query", Broken())
    assert qf.load_freeze_qty_cache() is False
    assert qf.get_freeze_qty("NIFTY", "NFO") == 0
