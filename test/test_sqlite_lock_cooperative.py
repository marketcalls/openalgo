"""Waiting for the SQLite write lock must not freeze the worker.

``PRAGMA busy_timeout`` is served inside SQLite by C code that sleeps without
handing control back to eventlet. Under gunicorn+eventlet a greenlet waiting
that way freezes the entire worker, and because the greenlet holding the write
lock then cannot be scheduled to commit, the wait can only ever end in
"database is locked". A holder that needs the lock for half a second produces a
fifteen second failure, and every other request on the worker is stopped for
the duration.

So the in-SQLite wait is short and the real waiting happens in Python, with a
sleep between attempts that eventlet turns into a yield.

`test_a_blocked_write_still_gives_up_eventually` is the one that keeps this
honest: the budget has to stay real, or this file would pass just as well with
the retry loop spinning forever.

Each case runs in a subprocess, because ``eventlet.monkey_patch()`` is global
and cannot be undone.
"""

import subprocess
import sys
import textwrap

import pytest

pytest.importorskip(
    "eventlet",
    reason="eventlet is installed by the production installer, not by pyproject",
)

PREAMBLE = '''
import eventlet
eventlet.monkey_patch()

import os, sqlite3, sys, tempfile, time

sys.path.insert(0, os.getcwd())
import database          # installs the cooperative connection factory
from database import BUSY_TIMEOUT_MS, LOCK_RETRY_BUDGET_S

DB = os.path.join(tempfile.mkdtemp(), "t.db")
_s = sqlite3.connect(DB)
_s.execute("PRAGMA journal_mode=WAL")
_s.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
_s.commit()
_s.close()

ticks = []

def _beat():
    while True:
        ticks.append(1)
        eventlet.sleep(0.02)

def connect():
    c = sqlite3.connect(DB)
    c.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return c

def hold_then_commit(seconds):
    """Take the write lock, yield once, commit. What any handler does."""
    c = connect()
    c.execute("BEGIN IMMEDIATE")
    c.execute("INSERT INTO t (v) VALUES ('holder')")
    eventlet.sleep(seconds)
    c.commit()
    c.close()

def write_while_locked(hold_s):
    """Returns (outcome, seconds, hub_ticks) for a write made while locked."""
    del ticks[:]
    beat = eventlet.spawn(_beat)
    holder = eventlet.spawn(hold_then_commit, hold_s)
    eventlet.sleep(0.1)
    before, t0 = len(ticks), time.monotonic()
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO t (v) VALUES ('waiter')")
        c.commit()
        outcome = "ok"
    except sqlite3.OperationalError as exc:
        outcome = str(exc)
    finally:
        c.close()
    took, during = time.monotonic() - t0, len(ticks) - before
    holder.wait()
    beat.kill()
    return outcome, took, during
'''


def run(body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", PREAMBLE + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_the_in_sqlite_wait_is_short():
    """The C-level wait is the one that cannot be interrupted, so it bounds how
    long a single attempt can freeze the hub."""
    result = run(
        """
        assert BUSY_TIMEOUT_MS <= 500, (
            f"busy_timeout is {BUSY_TIMEOUT_MS}ms; that is how long one attempt "
            f"can freeze every other request on the worker"
        )
        assert LOCK_RETRY_BUDGET_S >= 10, (
            "the total budget shrank; a write that legitimately has to queue "
            "will now fail where it used to succeed"
        )
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


def test_a_write_blocked_by_a_yielding_holder_succeeds_and_keeps_the_hub_alive():
    result = run(
        """
        HOLD = 0.5
        outcome, took, ticks_during = write_while_locked(HOLD)

        assert outcome == "ok", f"blocked write failed: {outcome}"
        assert took < HOLD + 0.5, (
            f"took {took:.2f}s for a lock held {HOLD}s; it is not picking the "
            f"lock up promptly after the holder commits"
        )
        assert ticks_during > 5, (
            f"only {ticks_during} hub ticks while waiting: the worker was "
            f"frozen, which is the defect this guards"
        )
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


def test_a_blocked_write_still_gives_up_eventually():
    """The budget must stay finite, or a stuck holder hangs the caller forever
    instead of surfacing an error."""
    result = run(
        """
        import database

        database.LOCK_RETRY_BUDGET_S = 0.5
        outcome, took, _ = write_while_locked(30.0)

        assert "locked" in outcome.lower(), f"expected a lock error, got {outcome}"
        assert took < 5, f"gave up only after {took:.2f}s"
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


def test_an_error_that_is_not_a_lock_is_raised_at_once():
    """Retrying a genuine failure would turn a fast error into a slow one."""
    result = run(
        """
        c = connect()
        t0 = time.monotonic()
        try:
            c.execute("SELECT * FROM no_such_table")
            raise AssertionError("expected an error")
        except sqlite3.OperationalError as exc:
            assert "no such table" in str(exc), exc
        took = time.monotonic() - t0
        assert took < 0.5, f"a non-lock error took {took:.2f}s; it was retried"
        c.close()
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr
