"""SQLite pragmas for migration scripts.

Importing this module registers a global SQLAlchemy ``connect`` listener, so
every engine created afterwards in the same process gets the same pragmas the
running application uses. Import it for the side effect, before creating an
engine::

    import _pragmas  # noqa: F401

**Why this exists.** ``database/__init__.py`` registers an identical listener,
which is why the app itself waits 15 seconds for a write lock. Migrations never
got it: ``migrate_all.py`` runs each script with ``subprocess.run``, so every
migration is a *separate process* that imports ``sqlalchemy`` directly and never
imports the ``database`` package. Those engines fell back to the sqlite3 default
of 5 seconds, so a migration gave up three times sooner than the rest of
OpenAlgo under exactly the same contention, and the install failed with
"database is locked" when waiting slightly longer would have succeeded. See
GitHub issue #1726.

This module deliberately does **not** import ``database`` to reuse its listener.
A migration must keep running when the application package cannot be imported --
that is precisely the state a half-finished install is in.

Note that this widens the window a migration will wait for a lock; it does not
create or release one. A lock held by a running OpenAlgo instance, or a ``db/``
folder on OneDrive or a network share where WAL cannot work, still needs fixing
at the source.
"""

import sqlite3

from sqlalchemy import event
from sqlalchemy.engine import Engine

#: Milliseconds a statement waits for a write lock before raising
#: "database is locked". Matches ``database/__init__.py``.
BUSY_TIMEOUT_MS = 15000


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Apply WAL + synchronous=NORMAL + busy_timeout to every SQLite connection."""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        # A pragma failure must never break the connection: if another process
        # holds a legacy-mode lock during first-time conversion, the connection
        # simply continues in the journal mode already on disk.
        for pragma in (
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}",
        ):
            try:
                cursor.execute(pragma)
            except sqlite3.OperationalError:
                pass
    finally:
        cursor.close()
