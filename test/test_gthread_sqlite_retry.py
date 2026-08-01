"""Tests for SQLite snapshot-conflict retry (gthread PR-6, gates A4 and A11).

Covers GT-A4-01 .. GT-A4-08 and GT-A11-01/02.

WAL + busy_timeout=15000 already handles plain SQLITE_BUSY. It cannot handle
SQLITE_BUSY_SNAPSHOT, which SQLite returns *immediately* without calling the
busy handler because waiting cannot help -- the transaction's snapshot is
stale and only a restart fixes it.

The rule is asymmetric and getting it backwards is worse than doing nothing:
retry the snapshot conflict, never re-wait a plain busy.
"""

import os
import sqlite3
import tempfile
import threading

import pytest
from sqlalchemy.exc import OperationalError

from database.sqlite_retry import (
    SQLITE_BUSY,
    SQLITE_BUSY_SNAPSHOT,
    is_plain_busy,
    is_snapshot_conflict,
    retry_on_snapshot_conflict,
)


@pytest.fixture
def wal_db():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("pragma journal_mode=WAL")
    conn.execute("create table t(id integer primary key, n integer)")
    conn.execute("insert into t values (1, 0)")
    conn.close()
    return path


def _induce_snapshot_conflict(path):
    """Produce a real SQLITE_BUSY_SNAPSHOT, not a simulated one."""
    a = sqlite3.connect(path, isolation_level=None, timeout=0.1)
    b = sqlite3.connect(path, isolation_level=None, timeout=0.1)
    try:
        a.execute("begin")
        a.execute("select n from t").fetchone()  # takes a snapshot
        b.execute("begin immediate")
        b.execute("update t set n = n + 1")
        b.execute("commit")  # invalidates a's snapshot
        a.execute("update t set n = 99")  # -> SQLITE_BUSY_SNAPSHOT
    finally:
        try:
            a.close()
        finally:
            b.close()


def test_snapshot_conflict_is_real_and_identifiable(wal_db):
    with pytest.raises(sqlite3.OperationalError) as exc_info:
        _induce_snapshot_conflict(wal_db)

    err = exc_info.value
    assert err.sqlite_errorcode == SQLITE_BUSY_SNAPSHOT
    assert str(err) == "database is locked"  # indistinguishable by message
    assert is_snapshot_conflict(err) is True
    assert is_plain_busy(err) is False


def test_plain_busy_is_not_retried():
    """busy_timeout already waited 15s. Three attempts would park a worker
    thread for 45 seconds -- an outage dressed up as resilience."""
    err = sqlite3.OperationalError("database is locked")
    err.sqlite_errorcode = SQLITE_BUSY

    calls = []

    @retry_on_snapshot_conflict(attempts=3)
    def always_busy():
        calls.append(1)
        raise err

    with pytest.raises(sqlite3.OperationalError):
        always_busy()

    assert len(calls) == 1, "plain SQLITE_BUSY must not be retried"


def test_snapshot_conflict_is_retried_and_can_succeed():
    attempts = []

    @retry_on_snapshot_conflict(attempts=3)
    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            err = sqlite3.OperationalError("database is locked")
            err.sqlite_errorcode = SQLITE_BUSY_SNAPSHOT
            raise err
        return "committed"

    assert flaky() == "committed"
    assert len(attempts) == 3


def test_retry_is_bounded():
    attempts = []

    @retry_on_snapshot_conflict(attempts=3)
    def always_conflicts():
        attempts.append(1)
        err = sqlite3.OperationalError("database is locked")
        err.sqlite_errorcode = SQLITE_BUSY_SNAPSHOT
        raise err

    with pytest.raises(sqlite3.OperationalError):
        always_conflicts()

    assert len(attempts) == 3, "must not retry beyond the configured attempts"


def test_sqlalchemy_wrapped_errors_are_unwrapped():
    """SQLAlchemy wraps the DBAPI error; matching must see through it."""
    orig = sqlite3.OperationalError("database is locked")
    orig.sqlite_errorcode = SQLITE_BUSY_SNAPSHOT
    wrapped = OperationalError("UPDATE t", {}, orig)

    assert is_snapshot_conflict(wrapped) is True

    attempts = []

    @retry_on_snapshot_conflict(attempts=2)
    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise wrapped
        return "ok"

    assert flaky() == "ok"


def test_session_is_released_between_attempts():
    """Without a fresh session the retry re-reads the same stale snapshot and
    fails identically -- the retry would be pure latency."""

    class FakeScopedSession:
        def __init__(self):
            self.removes = 0

        def remove(self):
            self.removes += 1

    session = FakeScopedSession()
    attempts = []

    @retry_on_snapshot_conflict(session_factory=session, attempts=3)
    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            err = sqlite3.OperationalError("database is locked")
            err.sqlite_errorcode = SQLITE_BUSY_SNAPSHOT
            raise err
        return "ok"

    assert flaky() == "ok"
    assert session.removes == 2, "session must be dropped before each retry"


def test_unrelated_errors_propagate_immediately():
    calls = []

    @retry_on_snapshot_conflict(attempts=3)
    def broken():
        calls.append(1)
        raise ValueError("not a database problem")

    with pytest.raises(ValueError):
        broken()
    assert len(calls) == 1


def test_end_to_end_retry_recovers_from_a_real_conflict(wal_db):
    """The whole point, against a real SQLite file rather than a fake error."""
    state = {"conflicted": False}

    @retry_on_snapshot_conflict(attempts=3)
    def increment():
        # Re-reads inside the attempt: replaying a delta computed from a stale
        # read would corrupt the value the retry is meant to protect.
        conn = sqlite3.connect(wal_db, isolation_level=None, timeout=0.5)
        try:
            conn.execute("begin")
            current = conn.execute("select n from t").fetchone()[0]
            if not state["conflicted"]:
                state["conflicted"] = True
                other = sqlite3.connect(wal_db, isolation_level=None, timeout=0.5)
                try:
                    other.execute("begin immediate")
                    other.execute("update t set n = n + 1")
                    other.execute("commit")
                finally:
                    other.close()
            conn.execute("update t set n = ?", (current + 10,))
            conn.execute("commit")
        finally:
            conn.close()
        return current

    increment()

    conn = sqlite3.connect(wal_db)
    final = conn.execute("select n from t").fetchone()[0]
    conn.close()
    # The other writer's +1 must survive: the retry re-read 1 and wrote 11.
    assert final == 11, f"retry replayed a stale value: n={final}"


# --------------------------------------------------------------------------
# GT-A11: DuckDB / Historify
# --------------------------------------------------------------------------


def test_duckdb_connection_is_per_use_and_always_closed():
    """A11-01: historify bypasses engine_factory, so its contract is its own."""
    import inspect

    import database.historify_db as h

    src = inspect.getsource(h.get_connection)
    assert "finally:" in src and "conn.close()" in src, "connection not always closed"
    assert "duckdb.connect(db_path)" in src, "expected a fresh connection per use"


def test_duckdb_survives_concurrent_writers(tmp_path, monkeypatch):
    """A11-01 measured rather than assumed: 16 threads writing at once."""
    import database.historify_db as h

    # HISTORIFY_DB_PATH is resolved from the environment at *import* time, so
    # monkeypatching the env var here would silently do nothing and the test
    # would write into the real db/historify.duckdb. Patch the module
    # attribute that get_db_path() actually reads.
    monkeypatch.setattr(h, "HISTORIFY_DB_PATH", str(tmp_path / "h.duckdb"))
    assert h.get_db_path().startswith(str(tmp_path)), "test would hit the real database"

    h.init_database()

    errors = []
    barrier = threading.Barrier(16)

    def worker(w):
        barrier.wait()
        for i in range(10):
            try:
                with h.get_connection() as conn:
                    conn.execute(
                        "INSERT INTO market_data "
                        "(symbol,exchange,interval,timestamp,open,high,low,close,volume) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        [f"S{w}", "NSE", "1m", i, 1.0, 2.0, 0.5, 1.5, 100],
                    )
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"DuckDB failed under concurrent writers: {errors[:3]}"
