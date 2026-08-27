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
telegram, whatsapp, apilog, settings, strategies) AND by two processes — the
gunicorn worker and the out-of-process websocket proxy — so at startup a write
can legitimately queue behind several seconds of contention. 15 seconds is well
under the gunicorn 300s worker timeout and turns a spurious "database is
locked" into a slightly slower commit. It does NOT help with a WAL snapshot
conflict (SQLITE_BUSY_SNAPSHOT), which is reported with the same message but
returns immediately; only re-running the transaction fixes that one.

Registered here (the package __init__) because every database module is
imported as ``database.<module>``, so this listener is guaranteed to be in
place before any engine in the project creates its first connection. The
listener is a no-op for non-SQLite backends (PostgreSQL pools, DuckDB).

Note: WAL requires a local filesystem (it uses shared memory); do not place
the db/ directory on NFS/SMB mounts.
"""

import sqlite3

from sqlalchemy import event
from sqlalchemy.engine import Engine


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
            cursor.execute("PRAGMA busy_timeout=15000")
        except sqlite3.OperationalError:
            pass
    finally:
        cursor.close()
