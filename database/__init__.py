"""Database package initialization.

Registers a process-wide SQLAlchemy connect listener so EVERY SQLite
connection — regardless of which module created the engine — runs with:

    PRAGMA journal_mode=WAL      (persistent, stored in the db file)
    PRAGMA synchronous=NORMAL    (per-connection)
    PRAGMA busy_timeout=15000    (per-connection)

Why: in the default rollback-journal mode every commit is a full fsync and
writers block readers, which is the root cause of the "database is locked"
errors documented in CLAUDE.md. WAL allows concurrent readers during writes
and, with synchronous=NORMAL, commits no longer fsync on every transaction
(WAL is still fsynced on checkpoint, so worst-case loss on power failure is
the last few transactions — never corruption).

busy_timeout is set because there is no other place that sets it: Python's
sqlite3 defaults to 5 seconds, and every engine in the project uses NullPool,
so each operation opens a fresh connection that must acquire the write lock on
its own. openalgo.db is shared by every feature module (auth, symtoken,
telegram, whatsapp, apilog, settings, strategies) AND by two processes, the
gunicorn worker and the out-of-process websocket proxy, so a write can
legitimately queue behind several seconds of contention. It does NOT help with
a WAL snapshot conflict (SQLITE_BUSY_SNAPSHOT), which is reported with the same
message but returns immediately; only re-running the transaction fixes that one.

**The wait itself must not happen inside SQLite.** ``busy_timeout`` is served by
C code that sleeps without releasing control to eventlet, so under
gunicorn+eventlet a waiting greenlet freezes the entire worker for the whole
timeout. That is not merely slow, it is a deadlock: the greenlet holding the
write lock cannot be scheduled to commit while the waiter is blocking the hub,
so the wait can only ever end in "database is locked". Measured, a holder that
needed the lock for 0.5s produced a 16s failure.

So the in-SQLite wait is short (``BUSY_TIMEOUT_MS``) and the real waiting is
done here in Python, retrying the statement with a sleep between attempts. That
sleep is eventlet's, so the hub keeps running and the holder commits at once:
the same 0.5s holder now yields a 0.47s success. The total budget is unchanged,
so a write that legitimately has to queue still gets its 15 seconds, it just
stops taking the rest of the application down with it. Retrying one statement
is what ``busy_timeout`` does internally anyway, so this changes when the app
waits, not what it waits for.

On the dev server, where nothing is monkey-patched, ``time.sleep`` is an
ordinary sleep and the behaviour is the same as before.

Registered here (the package __init__) because every database module is
imported as ``database.<module>``, so this listener is guaranteed to be in
place before any engine in the project creates its first connection. The
listener is a no-op for non-SQLite backends (PostgreSQL pools, DuckDB).

Note: WAL requires a local filesystem (it uses shared memory); do not place
the db/ directory on NFS/SMB mounts.
"""

import sqlite3
import sqlite3.dbapi2
import time

from sqlalchemy import event
from sqlalchemy.engine import Engine

#: How long SQLite itself waits for the write lock before handing control back.
#: Short on purpose: this wait is uninterruptible C code, so it is also the
#: longest the eventlet hub can be frozen by one attempt.
BUSY_TIMEOUT_MS = 100

#: Total time a blocked statement keeps trying, matching the 15s this module
#: used to pass to busy_timeout. Only the waiting method changed.
LOCK_RETRY_BUDGET_S = 15.0

#: Gap between attempts. Under eventlet this is a yield, which is the entire
#: point: it lets the lock holder run and commit.
LOCK_RETRY_POLL_S = 0.05


def _is_locked(exc: sqlite3.OperationalError) -> bool:
    """True for the transient write-lock errors, not for real failures."""
    message = str(exc).lower()
    return "database is locked" in message or "database is busy" in message


def _retrying(call, *args):
    """Run a DBAPI call, waiting out a busy write lock without blocking the hub.

    The success path costs one try block and nothing else. Anything that is not
    a lock error is re-raised untouched, as is a lock error that outlives the
    budget, so a genuine problem still surfaces exactly as it does today.
    """
    try:
        return call(*args)
    except sqlite3.OperationalError as exc:
        if not _is_locked(exc):
            raise
    deadline = time.monotonic() + LOCK_RETRY_BUDGET_S
    while True:
        time.sleep(LOCK_RETRY_POLL_S)
        try:
            return call(*args)
        except sqlite3.OperationalError as exc:
            if not _is_locked(exc) or time.monotonic() >= deadline:
                raise


class _CooperativeCursor(sqlite3.Cursor):
    """A cursor whose statements wait for the write lock in Python."""

    def execute(self, sql, parameters=(), /):
        return _retrying(super().execute, sql, parameters)

    def executemany(self, sql, parameters, /):
        return _retrying(super().executemany, sql, parameters)


class _CooperativeConnection(sqlite3.Connection):
    """Hands out cooperative cursors and commits the same way.

    COMMIT takes the write lock too, and in WAL mode it is the statement most
    likely to find it held, so it needs the same treatment as the writes.
    """

    def cursor(self, factory=_CooperativeCursor):
        return super().cursor(factory)

    def execute(self, sql, parameters=(), /):
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql, parameters, /):
        return self.cursor().executemany(sql, parameters)

    def commit(self):
        return _retrying(super().commit)


def _install_connection_factory():
    """Default every sqlite3 connection in this process to the cooperative one.

    Done by wrapping ``sqlite3.connect`` rather than by passing ``connect_args``
    per engine, for the same reason the pragma listener is registered here: some
    modules build their engine with ``create_engine`` directly instead of going
    through ``database.engine_factory``, and a connection that misses this is
    exactly the one that will freeze the worker. A caller that passes its own
    ``factory`` still wins.

    ``sqlalchemy``'s pysqlite dialect imports ``sqlite3.dbapi2``, which holds a
    separate reference to the same function, so both names are wrapped.
    """
    original = sqlite3.dbapi2.connect
    if getattr(original, "_openalgo_cooperative", False):
        return

    def connect(*args, **kwargs):
        kwargs.setdefault("factory", _CooperativeConnection)
        return original(*args, **kwargs)

    connect._openalgo_cooperative = True
    sqlite3.dbapi2.connect = connect
    sqlite3.connect = connect


_install_connection_factory()


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Apply WAL + synchronous=NORMAL + busy_timeout to every SQLite connection."""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        # A pragma failure must never break the connection: if another
        # process holds a legacy-mode lock during first-time conversion the
        # connection simply continues in the journal mode already on disk.
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        except sqlite3.OperationalError:
            pass
    finally:
        cursor.close()
