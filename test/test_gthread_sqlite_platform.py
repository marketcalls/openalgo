"""SQLite behaviour under real threads, on whatever platform CI is running.

Covers GT-A4-08. CLAUDE.md records that SQLite locking is stricter on Windows,
and the A4 retry bounds had only ever been exercised on one developer machine.
The retry budget is 3 attempts inside a 2-second ceiling; if a platform needs
longer than that to clear contention, the bound is wrong there and a worker
thread gets parked instead of erroring cleanly.

This runs everywhere. It is meaningful on Linux and macOS, and it is the point
on Windows -- the dev-startup CI job covers all three.
"""

import platform
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from database.sqlite_retry import (
    SQLITE_BUSY_SNAPSHOT,
    DEFAULT_ATTEMPTS,
    DEFAULT_MAX_SECONDS,
    is_snapshot_conflict,
    retry_on_snapshot_conflict,
)


@pytest.fixture
def wal_db(tmp_path: Path) -> str:
    path = str(tmp_path / "platform.db")
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("pragma journal_mode=WAL")
        conn.execute("pragma synchronous=NORMAL")
        conn.execute("create table t(id integer primary key, n integer)")
        conn.execute("insert into t values (1, 0)")
    finally:
        conn.close()
    return path


def test_wal_is_available_on_this_platform(wal_db):
    """WAL needs a local filesystem with shared memory. If it silently fell
    back to rollback journal, readers would block writers and the whole
    contention model in the plan would be wrong here."""
    conn = sqlite3.connect(wal_db)
    try:
        mode = conn.execute("pragma journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal", f"{platform.system()} did not honour WAL: {mode}"


def test_busy_timeout_is_applied_by_the_project_listener():
    """The 15s busy_timeout is what makes plain contention survivable without
    a retry. It is set by a connect listener, so it must reach every engine."""
    from sqlalchemy import text

    from database.engine_factory import create_db_engine

    engine = create_db_engine("sqlite:///:memory:")
    try:
        with engine.connect() as conn:
            assert conn.execute(text("pragma busy_timeout")).scalar() == 15000
            assert conn.execute(text("pragma journal_mode")).scalar().lower() in ("wal", "memory")
    finally:
        engine.dispose()


def test_snapshot_conflict_is_reproducible_here(wal_db):
    """The retry only helps if this platform actually raises 517 rather than
    blocking. If it blocks instead, busy_timeout handles it and the retry is
    never reached -- worth knowing per platform."""
    a = sqlite3.connect(wal_db, isolation_level=None, timeout=0.1)
    b = sqlite3.connect(wal_db, isolation_level=None, timeout=0.1)
    try:
        a.execute("begin")
        a.execute("select n from t").fetchone()
        b.execute("begin immediate")
        b.execute("update t set n = n + 1")
        b.execute("commit")

        with pytest.raises(sqlite3.OperationalError) as exc_info:
            a.execute("update t set n = 99")
    finally:
        a.close()
        b.close()

    assert exc_info.value.sqlite_errorcode == SQLITE_BUSY_SNAPSHOT
    assert is_snapshot_conflict(exc_info.value)


def test_retry_budget_is_enough_on_this_platform(wal_db):
    """The real question: does a conflicting write recover inside the budget?

    A retry that exhausts its attempts parks a worker thread and then fails
    anyway, which is the outcome the bound exists to avoid.
    """
    attempts = []
    conflict_once = {"done": False}

    @retry_on_snapshot_conflict(attempts=DEFAULT_ATTEMPTS, max_seconds=DEFAULT_MAX_SECONDS)
    def increment():
        attempts.append(1)
        conn = sqlite3.connect(wal_db, isolation_level=None, timeout=0.5)
        try:
            conn.execute("begin")
            current = conn.execute("select n from t").fetchone()[0]
            if not conflict_once["done"]:
                conflict_once["done"] = True
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

    started = time.monotonic()
    increment()
    elapsed = time.monotonic() - started

    assert len(attempts) <= DEFAULT_ATTEMPTS, f"{platform.system()} needed {len(attempts)} attempts"
    assert elapsed < DEFAULT_MAX_SECONDS + 1.0, (
        f"{platform.system()} took {elapsed:.2f}s, near the {DEFAULT_MAX_SECONDS}s ceiling"
    )

    conn = sqlite3.connect(wal_db)
    try:
        final = conn.execute("select n from t").fetchone()[0]
    finally:
        conn.close()
    # The other writer's +1 must survive: the retry re-read 1 and wrote 11.
    assert final == 11, f"retry replayed a stale value on {platform.system()}: n={final}"


def test_concurrent_writers_do_not_exceed_the_budget(wal_db):
    """Eight threads writing at once, which is what a gthread worker does."""
    errors = []
    barrier = threading.Barrier(8)

    @retry_on_snapshot_conflict(attempts=DEFAULT_ATTEMPTS, max_seconds=DEFAULT_MAX_SECONDS)
    def bump():
        conn = sqlite3.connect(wal_db, isolation_level=None, timeout=5.0)
        try:
            conn.execute("begin immediate")
            current = conn.execute("select n from t").fetchone()[0]
            conn.execute("update t set n = ?", (current + 1,))
            conn.execute("commit")
        finally:
            conn.close()

    def worker(_b=barrier):
        _b.wait()
        for _ in range(5):
            try:
                bump()
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"{platform.system()} writers failed: {errors[:3]}"

    conn = sqlite3.connect(wal_db)
    try:
        final = conn.execute("select n from t").fetchone()[0]
    finally:
        conn.close()
    # BEGIN IMMEDIATE serializes writers, so every increment must land.
    assert final == 40, f"lost updates on {platform.system()}: expected 40, got {final}"
