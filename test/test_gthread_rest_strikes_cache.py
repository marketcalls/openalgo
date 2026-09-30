"""The option strikes cache never serves a stale "no strikes" answer.

``services.option_symbol_service.get_available_strikes`` backs options orders,
the option chain, the strategy module's symbol resolver, the /tools pages and
the agent. Its cache used to be a plain dict, and three defects lived in it:

* An empty query result was stored with no expiry. A master contract download
  deletes the old SymToken rows and inserts the new ones in separate commits,
  and under the gthread worker a lookup on another thread can run between the
  two. It then cached ``[]``, and every later options order on that underlying
  was refused with "No strikes found ... update master contract" for the life
  of the process, even after the download finished.
* ``key in cache`` followed by ``cache[key]`` raised KeyError when a clear ran
  in between, and the handler turned that into the same ``[]``.
* The key space had no bound.

Under eventlet none of this could interleave, because neither the download's
delete and insert nor the cache check ever yielded. The fixed cache is a
``LockedTTLCache``: one atomic read, no empty entries, a size bound and a TTL.

No database is touched: ``db_session`` is replaced with a stub whose query
chain returns whatever the test says.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from importlib.util import find_spec
from pathlib import Path

import pytest

from services import option_symbol_service as oss
from utils.thread_safe_cache import LockedTTLCache

REPO = Path(__file__).resolve().parents[1]


class _Row:
    def __init__(self, strike):
        self.strike = strike


class _FakeQuery:
    def __init__(self, source):
        self._source = source

    def filter(self, *args, **kwargs):
        return self

    def distinct(self):
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return self._source()


class _FakeSession:
    """Stands in for ``database.symbol.db_session``; counts the queries run."""

    def __init__(self, source):
        self._source = source
        self._lock = threading.Lock()
        self.calls = 0

    def query(self, *args, **kwargs):
        with self._lock:
            self.calls += 1
        return _FakeQuery(self._source)


def _rows(*strikes):
    return [_Row(s) for s in strikes]


@pytest.fixture(autouse=True)
def _fresh_cache():
    oss.clear_strikes_cache()
    yield
    oss.clear_strikes_cache()


def _lookup(expiry="28OCT25"):
    return oss.get_available_strikes("NIFTY", expiry, "CE", "NFO")


def test_an_empty_result_is_not_cached(monkeypatch):
    """The defect: [] read mid-download was served for the rest of the day."""
    answers = [[], _rows(24000.0, 24050.0, 24100.0)]
    session = _FakeSession(lambda: answers.pop(0) if len(answers) > 1 else answers[0])
    monkeypatch.setattr(oss, "db_session", session)

    assert _lookup() == []
    assert _lookup() == [24000.0, 24050.0, 24100.0]
    assert session.calls == 2


def test_a_non_empty_result_is_cached(monkeypatch):
    session = _FakeSession(lambda: _rows(100.0, 200.0))
    monkeypatch.setattr(oss, "db_session", session)

    assert _lookup() == [100.0, 200.0]
    assert _lookup() == [100.0, 200.0]
    assert session.calls == 1
    stats = oss.get_strikes_cache_stats()
    assert (stats["hits"], stats["misses"], stats["total_queries"]) == (1, 1, 2)
    assert stats["cached_entries"] == 1


def test_a_lookup_racing_a_clear_never_reports_no_strikes(monkeypatch):
    """A clear between the membership test and the read must not surface as [].

    With the GIL, CPython rarely switches threads between the two bytecodes the
    old ``in`` then ``[]`` pair compiled to, so this pins the fixed behaviour
    rather than reliably reproducing the old failure; the deterministic proofs
    of the defects are the empty-result and overlapping-clear tests.
    """
    session = _FakeSession(lambda: _rows(100.0, 200.0, 300.0))
    monkeypatch.setattr(oss, "db_session", session)
    assert _lookup() == [100.0, 200.0, 300.0]

    stop = threading.Event()
    empties = []
    errors = []
    lookups = [0]
    count_lock = threading.Lock()

    def reader():
        try:
            while not stop.is_set():
                result = _lookup()
                with count_lock:
                    lookups[0] += 1
                if not result:
                    empties.append(result)
        except Exception as exc:  # pragma: no cover - a failure path
            errors.append(exc)

    def clearer():
        while not stop.is_set():
            oss.clear_strikes_cache()

    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=reader) for _ in range(8)]
        threads.append(threading.Thread(target=clearer))
        for thread in threads:
            thread.start()
        time.sleep(1.5)
        stop.set()
        for thread in threads:
            thread.join(10)
    finally:
        sys.setswitchinterval(previous)

    assert not errors
    assert lookups[0] > 100
    assert empties == []


def test_a_load_overlapping_a_clear_is_not_stored(monkeypatch):
    """Rows read before a master contract reload must not outlive the reload."""
    calls = []

    def source():
        calls.append(1)
        if len(calls) == 1:
            # A master contract load finishes while this query is running.
            oss.clear_strikes_cache()
            return _rows(100.0)
        return _rows(100.0, 150.0)

    monkeypatch.setattr(oss, "db_session", _FakeSession(source))

    assert _lookup() == [100.0]
    assert _lookup() == [100.0, 150.0]
    assert len(calls) == 2


def test_the_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(oss, "db_session", _FakeSession(lambda: _rows(1.0, 2.0)))
    for index in range(oss.STRIKES_CACHE_MAXSIZE + 904):
        oss.get_available_strikes(f"SYM{index}", "28OCT25", "CE", "NFO")
    assert oss.get_strikes_cache_stats()["cached_entries"] <= oss.STRIKES_CACHE_MAXSIZE


def test_an_entry_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(
        oss, "_STRIKES_CACHE", LockedTTLCache(maxsize=16, ttl=60, timer=lambda: now[0])
    )
    session = _FakeSession(lambda: _rows(1.0, 2.0))
    monkeypatch.setattr(oss, "db_session", session)

    _lookup()
    _lookup()
    assert session.calls == 1
    now[0] += 61
    _lookup()
    assert session.calls == 2


def test_each_caller_gets_its_own_list(monkeypatch):
    monkeypatch.setattr(oss, "db_session", _FakeSession(lambda: _rows(1.0, 2.0, 3.0)))

    first = _lookup()
    first.append(999.0)
    first.remove(1.0)
    assert _lookup() == [1.0, 2.0, 3.0]


def test_statistics_add_up_under_concurrent_lookups(monkeypatch):
    monkeypatch.setattr(oss, "db_session", _FakeSession(lambda: _rows(1.0, 2.0)))
    barrier = threading.Barrier(8)
    per_thread = 250

    def worker(index):
        barrier.wait()
        for n in range(per_thread):
            oss.get_available_strikes(f"U{(index + n) % 5}", "28OCT25", "PE", "NFO")

    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
    finally:
        sys.setswitchinterval(previous)

    stats = oss.get_strikes_cache_stats()
    assert stats["total_queries"] == 8 * per_thread
    assert stats["hits"] + stats["misses"] == stats["total_queries"]


def test_clear_resets_the_statistics_in_place(monkeypatch):
    monkeypatch.setattr(oss, "db_session", _FakeSession(lambda: _rows(1.0)))
    stats_dict = oss._CACHE_STATS
    _lookup()
    oss.clear_strikes_cache()
    assert oss._CACHE_STATS is stats_dict
    assert oss.get_strikes_cache_stats()["total_queries"] == 0
    assert oss.get_strikes_cache_stats()["cached_entries"] == 0


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
def test_greenlets_and_a_real_thread_share_the_cache_under_eventlet(tmp_path):
    """The agent's real OS thread and request greenlets use one cache.

    Under a real monkey_patch the cache lock and the statistics lock must be
    real ones: the real thread finishes its lookups, nothing raises
    greenlet.error, and a ticker greenlet keeps running throughout (the hub is
    never blocked for longer than a dictionary operation).
    """
    body = """
        import eventlet
        eventlet.monkey_patch()

        import dotenv
        dotenv.load_dotenv = lambda *a, **k: False
        dotenv.main.load_dotenv = dotenv.load_dotenv

        import time
        import eventlet.patcher
        from utils import runtime
        assert runtime.worker_class() == "eventlet"

        from services import option_symbol_service as oss

        class Row:
            def __init__(self, strike):
                self.strike = strike

        class Q:
            def filter(self, *a, **k): return self
            def distinct(self): return self
            def order_by(self, *a): return self
            def all(self): return [Row(1.0), Row(2.0)]

        class S:
            def query(self, *a, **k): return Q()

        oss.db_session = S()
        real_threading = eventlet.patcher.original("threading")

        ticks = [0]
        stop = [False]

        def ticker():
            while not stop[0]:
                ticks[0] += 1
                eventlet.sleep(0.01)

        def green_reader(i):
            for n in range(300):
                assert oss.get_available_strikes(f"G{n % 7}", "28OCT25", "CE", "NFO")
                if n % 5 == 0:
                    oss.clear_strikes_cache()
                eventlet.sleep(0)

        done = []
        def real_reader():
            for n in range(300):
                assert oss.get_available_strikes(f"G{n % 7}", "28OCT25", "CE", "NFO")
            done.append(True)

        tick = eventlet.spawn(ticker)
        greens = [eventlet.spawn(green_reader, i) for i in range(4)]
        real = real_threading.Thread(target=real_reader, daemon=True)
        started = time.monotonic()
        real.start()
        for g in greens:
            g.wait()
        while real.is_alive() and time.monotonic() - started < 10:
            eventlet.sleep(0.02)
        stop[0] = True
        tick.wait()
        assert done == [True], "the real thread never finished its lookups"
        assert ticks[0] > 5, ticks[0]
        print("OK", round(time.monotonic() - started, 2))
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
    assert "Cannot switch to a different thread" not in result.stderr
