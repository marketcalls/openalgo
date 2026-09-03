#!/usr/bin/env python3
"""
Migration: Agent module (/agent)

Adds the six tables backing the LLM agent, all prefixed ``ag_``:

- ag_provider_model   one row per model the operator has enabled
- ag_secret           Fernet ciphertext for a provider or per-model API key
- ag_setting          key/value agent settings, so a new setting needs no migration
- ag_conversation     what the chat and chart surfaces list
- ag_message          what those surfaces render
- ag_audit            append-only record of every mutating tool call

All six are new, so there is nothing to backfill and no existing value to
preserve. This script adds tables and touches nothing else: no other feature's
table is read, altered or dropped by it.

Why this exists at all, given init_db() already creates them. Roughly 290k live
deployments upgrade with `cd upgrade && uv run migrate_all.py`, and a schema
change that lives only in init_db() never reaches them: create_all skips a
database whose tables are already there, and a seeding function typically only
runs against an empty table. This script is the path that reaches an existing
installation.

The DDL is read from the ORM metadata in database/agent_db.py rather than
written out by hand. Six tables with a dozen indexes between them is a lot of
surface for a transcription error, and a hand-written CREATE TABLE that drifts
from the model produces the worst kind of bug: the app starts, the query
compiles, and one column silently holds the wrong thing.

Three arrival orders, all of which this survives:

1. Fresh install. The tables do not exist and this creates them.
2. App started first. init_db() has already created them through create_all,
   so this finds them present and reports nothing to do. It does not fail and
   it does not recreate anything.
3. Run twice. Identical to the second case.

A later change that adds a column to an ``ag_`` table needs its own block here,
because create_all(checkfirst=True) skips a table it finds present and so would
never reach a new column on it. That block must guard the update on the old
value rather than clobbering something an operator customised, and backfill from
the row's own data rather than a uniform default.

This migration is idempotent - safe to run multiple times.

Usage:
    cd upgrade
    uv run migrate_agent.py           # Apply migration
    uv run migrate_agent.py --status  # Check status without changing anything
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add parent directory to path for imports
sys.path.insert(0, PROJECT_ROOT)
# Register the app's SQLite pragmas on this process's engines, so a migration
# waits the same 15s for a write lock the running app does instead of the
# sqlite3 default of 5s (GitHub issue #1726).
import _pragmas  # noqa: F401,E402
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

#: Table names in dependency order: ag_conversation before ag_message, which
#: carries a foreign key to it. create_all sorts this itself, but --status reads
#: better in this order and a human comparing the two lists should not have to.
TABLES = (
    "ag_provider_model",
    "ag_secret",
    "ag_setting",
    "ag_conversation",
    "ag_message",
    "ag_audit",
)


def resolve_sqlite_path(db_url):
    """Make a relative sqlite:/// path absolute against the project root.

    The documented invocation is `cd upgrade && uv run migrate_agent.py`, and
    DATABASE_URL is relative by default ("sqlite:///db/openalgo.db"). Left
    relative it resolves against the current directory, so running from upgrade/
    would point at upgrade/db/openalgo.db - which SQLAlchemy creates empty on
    connect. The migration would then report success having created its tables
    in a database the app never opens.

    Args:
        db_url: The DATABASE_URL as configured.

    Returns:
        The same URL with any relative sqlite path made absolute. A non-sqlite
        URL is returned unchanged.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return db_url
    path = db_url[len(prefix) :]
    if os.path.isabs(path):
        return db_url
    return prefix + os.path.join(PROJECT_ROOT, path).replace("\\", "/")


def get_database_url():
    """Read DATABASE_URL from the environment, with the project default.

    Returns:
        The resolved database URL.
    """
    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    return resolve_sqlite_path(os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db"))


def sqlite_file(db_url):
    """The filesystem path a sqlite URL points at, or None for other backends.

    Args:
        db_url: A resolved database URL.

    Returns:
        The absolute path, or None when the URL is not sqlite.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return None
    return db_url[len(prefix) :]


def load_metadata():
    """The agent ORM metadata, which is the source of the DDL.

    Imported here rather than at module scope so --status never touches it. The
    module builds its own engine and scoped session on import, and neither is
    wanted on a path that promises to change nothing.

    Returns:
        The SQLAlchemy MetaData carrying the six ``ag_`` tables.
    """
    from database.agent_db import Base

    return Base.metadata


def missing_tables(engine):
    """Which of our tables are not in the database yet.

    Args:
        engine: An engine bound to the target database.

    Returns:
        The absent table names, in TABLES order.
    """
    present = set(inspect(engine).get_table_names())
    return [table for table in TABLES if table not in present]


def status(engine, db_url):
    """Report what would change, without changing anything.

    Reads nothing when the sqlite file does not exist yet: connecting would
    create it, and an empty database file is exactly the kind of side effect
    --status must not have.

    Args:
        engine: An engine bound to the target database.
        db_url: The resolved database URL, used to find the sqlite file.

    Returns:
        True when the schema is already up to date, False when work is pending.
    """
    print("\nAgent module table status")
    print("-" * 46)

    path = sqlite_file(db_url)
    if path is not None and not os.path.exists(path):
        for table in TABLES:
            print(f"  {table:<22} MISSING")
        print("-" * 46)
        print("Database file does not exist yet. Not created: --status changes nothing.")
        print(f"Migration needed. Would create {len(TABLES)} table(s).")
        return False

    inspector = inspect(engine)
    present = set(inspector.get_table_names())
    for table in TABLES:
        if table in present:
            count = len(inspector.get_indexes(table))
            print(f"  {table:<22} present, {count} index(es)")
        else:
            print(f"  {table:<22} MISSING")
    print("-" * 46)

    absent = [table for table in TABLES if table not in present]
    if not absent:
        print("Up to date. Nothing to do.")
        return True

    print(f"Migration needed. Would create {len(absent)} table(s):")
    for table in absent:
        print(f"  {table}")
    return False


def apply(engine):
    """Create whatever is missing. An existing table keeps its rows.

    Args:
        engine: An engine bound to the target database.

    Returns:
        True on success, False when a table that should exist still does not.
    """
    absent = missing_tables(engine)
    if not absent:
        print("  All agent tables already present. Nothing to do.")
        return True

    metadata = load_metadata()
    # checkfirst=True is what makes this safe to re-run: a table that already
    # exists is skipped rather than raising, so a partially applied migration
    # (interrupted midway, or half created by an app that started first)
    # completes cleanly on the next run.
    try:
        metadata.create_all(bind=engine, checkfirst=True)
    except Exception as exc:
        print(f"  [FAIL] Could not create the agent tables: {exc}")
        return False

    still_missing = missing_tables(engine)
    if still_missing:
        print(f"  [FAIL] These tables were not created: {', '.join(still_missing)}")
        return False

    for table in absent:
        print(f"  [OK] Created {table}")
    return True


def main():
    """Entry point.

    Returns:
        0 on success, 1 when the migration could not be applied.
    """
    parser = argparse.ArgumentParser(description="Agent module schema migration")
    parser.add_argument(
        "--status",
        action="store_true",
        help="Report what would change without changing anything",
    )
    args = parser.parse_args()

    db_url = get_database_url()
    shown = db_url if not db_url.startswith("sqlite") else "sqlite://..."
    print("\nAgent Module Migration")
    print("-" * 46)
    print(f"Database: {shown}")

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        if args.status:
            status(engine, db_url)
            return 0

        print("\nApplying migration...")
        ok = apply(engine)
        print("-" * 46)
        if ok:
            print("Migration complete.")
            return 0
        print("Migration failed. See the messages above.")
        return 1
    finally:
        # A migration is a short-lived process, but disposing is what keeps the
        # SQLite file unlocked for the app that may be waiting on it.
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
