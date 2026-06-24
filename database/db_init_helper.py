"""
Helper module for database initialization with better logging
"""

import os

from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError


def _ensure_sqlite_dir(engine):
    """Make sure the parent directory of a SQLite database file exists.

    On a fresh install the ``db/`` directory may not exist yet, and the database
    engines (and their background threads) are created/used in parallel. The
    first connection then fails with ``unable to open database file``. Creating
    the directory before the first connect removes that startup race.
    """
    url = engine.url
    if url.get_backend_name() != "sqlite":
        return
    db_path = url.database
    if not db_path or db_path == ":memory:":
        return
    db_dir = os.path.dirname(os.path.abspath(db_path))
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)


def _drop_orphaned_indexes(engine, base, table_names, db_name, logger):
    """Drop indexes declared for tables that do not exist yet.

    A previous interrupted/failed init can leave an index behind without its
    table (e.g. ``idx_user_status``). Because ``create_all``'s ``checkfirst``
    only guards at the table level, the next ``create_all`` then fails forever
    with ``index ... already exists`` and the table (e.g. ``sandbox_funds``) is
    never created. We only target indexes belonging to tables we still need to
    create, so dropping them (IF EXISTS) is safe — a missing table cannot have a
    legitimately-needed index.
    """
    index_names = []
    for tname in table_names:
        table = base.metadata.tables.get(tname)
        if table is None:
            continue
        for idx in table.indexes:
            if idx.name:
                index_names.append(idx.name)

    if not index_names:
        return

    with engine.begin() as conn:
        for name in index_names:
            try:
                conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
            except Exception:
                logger.exception(f"{db_name}: failed to drop orphaned index {name}")

    logger.warning(
        f"{db_name}: dropped {len(index_names)} potentially-orphaned index(es) "
        f"to recover a partially-initialized database"
    )


def init_db_with_logging(base, engine, db_name, logger):
    """
    Initialize database tables with detailed logging

    Args:
        base: SQLAlchemy Base (declarative_base)
        engine: SQLAlchemy engine
        db_name: Name of the database (for logging)
        logger: Logger instance

    Returns:
        tuple: (tables_created, tables_verified)
    """
    # Guarantee the SQLite directory exists before the first connection
    _ensure_sqlite_dir(engine)

    # Get inspector to check existing tables
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    # Get tables defined in this model
    model_tables = set(base.metadata.tables.keys())

    # Find which tables need to be created
    tables_to_create = model_tables - existing_tables
    tables_already_exist = model_tables & existing_tables

    # Create tables (only creates missing ones)
    try:
        base.metadata.create_all(bind=engine)
    except OperationalError as e:
        # Self-heal a database left in a partial state by a previous failed init:
        # an orphaned index makes create_all fail with "... already exists" and
        # leaves tables uncreated on every subsequent startup. Drop the orphaned
        # indexes for the missing tables and retry once.
        if "already exists" not in str(e.orig):
            raise
        logger.warning(
            f"{db_name}: create_all failed with '{e.orig}'; attempting to recover "
            f"a partially-initialized database"
        )
        _drop_orphaned_indexes(engine, base, tables_to_create, db_name, logger)
        base.metadata.create_all(bind=engine)

    # Log appropriately
    if tables_to_create:
        logger.debug(
            f"{db_name}: Created {len(tables_to_create)} new table(s): {', '.join(sorted(tables_to_create))}"
        )

    if tables_already_exist:
        logger.debug(f"{db_name}: Verified {len(tables_already_exist)} existing table(s)")

    if not tables_to_create and tables_already_exist:
        logger.debug(f"{db_name}: Connection verified ({len(tables_already_exist)} table(s) ready)")

    return len(tables_to_create), len(tables_already_exist)
