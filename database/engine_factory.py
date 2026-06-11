"""Shared SQLAlchemy engine factory.

Centralizes engine creation so every database engine in the project follows the
same connection-pooling policy. This exists to enforce one rule across the whole
codebase, including all broker ``master_contract_db.py`` modules:

    All SQLite engines MUST use NullPool.

With NullPool each operation gets a fresh connection that is closed immediately
after use, so no file descriptors to the SQLite database file accumulate. A real
pool (the SQLAlchemy default QueuePool, or an explicit ``pool_size``/``max_overflow``)
holds connections open per worker thread and leaks descriptors over the lifetime
of the long-running Gunicorn/eventlet process.

StaticPool must NOT be used for SQLite: a single shared connection causes
"bad parameter or other API misuse" and "cannot commit - SQL statements in
progress" errors when concurrent requests corrupt the shared cursor state.

For non-SQLite backends (e.g. PostgreSQL) a normal connection pool is used.

SQLite pragmas (WAL journal mode, synchronous=NORMAL) are applied to every
connection process-wide by the listener in ``database/__init__.py`` — they do
not need to be set here.

See CLAUDE.md "SQLite Connection Pooling (NullPool)" and the reference
implementation in ``database/auth_db.py``.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool


def create_db_engine(database_url=None):
    """Create a SQLAlchemy engine with the project-wide pooling policy.

    Args:
        database_url: SQLAlchemy database URL. Falls back to the ``DATABASE_URL``
            environment variable when not provided.

    Returns:
        A configured SQLAlchemy ``Engine``. SQLite URLs use ``NullPool`` with
        ``check_same_thread=False``; other backends use a QueuePool.
    """
    database_url = database_url or os.getenv("DATABASE_URL")

    if database_url and "sqlite" in database_url:
        # SQLite: NullPool so each checkout creates a fresh connection that is
        # closed immediately. Session cleanup is handled by app.py
        # teardown_appcontext. StaticPool must NOT be used (see module docstring).
        return create_engine(
            database_url,
            poolclass=NullPool,
            connect_args={"check_same_thread": False},
        )

    # Non-SQLite backends (e.g. PostgreSQL): use a real connection pool.
    return create_engine(database_url, pool_size=50, max_overflow=100, pool_timeout=10)
