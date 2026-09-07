#!/usr/bin/env python3
"""
Migration: Charting Terminal Watchlists

Adds the tables backing the watchlist panel on /trading:
- watchlists:      one named list per row, ordered in the picker
- watchlist_items: the instruments inside a list, ordered

Both are new tables, so there is nothing to backfill and no existing value to
preserve. init_db() in database/watchlist_db.py creates them too, but that only
helps an installation whose database is opened after this ships; this script is
what reaches the deployments that upgrade with `git pull`.

This migration is idempotent - safe to run multiple times.

Usage:
    cd upgrade
    uv run migrate_watchlist.py           # Apply migration
    uv run migrate_watchlist.py --status  # Check status without changing anything
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
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

WATCHLISTS_TABLE = "watchlists"
ITEMS_TABLE = "watchlist_items"

#: Every index this migration is responsible for, as {name: (table, columns)}.
#: Reordering and the ownership filter both read these, and the item lookup
#: joins back to the parent on every read.
INDEXES = {
    "ix_watchlists_user_id": (WATCHLISTS_TABLE, "user_id"),
    "ix_watchlist_items_watchlist_id": (ITEMS_TABLE, "watchlist_id"),
}


def resolve_sqlite_path(db_url):
    """Make a relative sqlite:/// path absolute against the project root.

    The documented invocation is `cd upgrade && uv run migrate_watchlist.py`,
    and DATABASE_URL is relative by default ("sqlite:///db/openalgo.db"). Left
    relative it resolves against the current directory, so running from
    upgrade/ would point at upgrade/db/openalgo.db - which SQLAlchemy creates
    empty on connect. The migration would then report success having created
    its tables in a database the app never opens.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return db_url
    path = db_url[len(prefix) :]
    if not path or path == ":memory:" or os.path.isabs(path):
        return db_url
    return prefix + os.path.join(PROJECT_ROOT, path)


def get_database_url():
    """Get database URL from environment"""
    from dotenv import load_dotenv

    load_dotenv()
    return resolve_sqlite_path(os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db"))


def table_exists(engine, table_name):
    """Check if a table exists in the database"""
    return table_name in inspect(engine).get_table_names()


def index_exists(engine, table_name, index_name):
    """Check if an index is present on a table that exists."""
    if not table_exists(engine, table_name):
        return False
    return index_name in {idx["name"] for idx in inspect(engine).get_indexes(table_name)}


def create_watchlists_table(engine):
    """Create the watchlists table."""
    if table_exists(engine, WATCHLISTS_TABLE):
        print(f"  [SKIP] {WATCHLISTS_TABLE} table already exists")
        return True

    print(f"  [CREATE] Creating {WATCHLISTS_TABLE} table...")

    if "sqlite" in str(engine.url):
        sql = """
        CREATE TABLE watchlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id VARCHAR(80) NOT NULL,
            name VARCHAR(64) NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_watchlist_user_name UNIQUE (user_id, name)
        )
        """
    else:
        sql = """
        CREATE TABLE watchlists (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(80) NOT NULL,
            name VARCHAR(64) NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_watchlist_user_name UNIQUE (user_id, name)
        )
        """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print(f"  [OK] {WATCHLISTS_TABLE} table created")
    return True


def create_items_table(engine):
    """Create the watchlist_items table."""
    if table_exists(engine, ITEMS_TABLE):
        print(f"  [SKIP] {ITEMS_TABLE} table already exists")
        return True

    print(f"  [CREATE] Creating {ITEMS_TABLE} table...")

    if "sqlite" in str(engine.url):
        sql = """
        CREATE TABLE watchlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
            symbol VARCHAR(64) NOT NULL,
            exchange VARCHAR(16) NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_watchlist_item UNIQUE (watchlist_id, symbol, exchange)
        )
        """
    else:
        sql = """
        CREATE TABLE watchlist_items (
            id SERIAL PRIMARY KEY,
            watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
            symbol VARCHAR(64) NOT NULL,
            exchange VARCHAR(16) NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_watchlist_item UNIQUE (watchlist_id, symbol, exchange)
        )
        """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print(f"  [OK] {ITEMS_TABLE} table created")
    return True


def create_indexes(engine):
    """Create the lookup indexes, skipping any that already exist."""
    for index_name, (table_name, column) in INDEXES.items():
        if not table_exists(engine, table_name):
            continue
        if index_exists(engine, table_name, index_name):
            print(f"  [SKIP] {index_name} already exists")
            continue

        print(f"  [CREATE] Creating {index_name}...")
        with engine.connect() as conn:
            conn.execute(text(f"CREATE INDEX {index_name} ON {table_name} ({column})"))
            conn.commit()
        print(f"  [OK] {index_name} created")
    return True


def status(engine):
    """Report what exists without changing anything."""
    print()
    print("Watchlist migration status")
    print("-" * 46)

    applied = True
    for table in (WATCHLISTS_TABLE, ITEMS_TABLE):
        present = table_exists(engine, table)
        print(f"  {table:<34} {'present' if present else 'MISSING'}")
        applied = applied and present

    for index_name, (table_name, _column) in INDEXES.items():
        present = index_exists(engine, table_name, index_name)
        print(f"  {index_name:<34} {'present' if present else 'MISSING'}")
        applied = applied and present

    if table_exists(engine, WATCHLISTS_TABLE):
        with engine.connect() as conn:
            lists = conn.execute(text(f"SELECT COUNT(*) FROM {WATCHLISTS_TABLE}")).scalar()
            items = (
                conn.execute(text(f"SELECT COUNT(*) FROM {ITEMS_TABLE}")).scalar()
                if table_exists(engine, ITEMS_TABLE)
                else 0
            )
        print(f"  {'existing data':<34} {lists} list(s), {items} instrument(s)")

    print("-" * 46)
    print("All changes applied." if applied else "Migration needed.")
    return applied


def main():
    """Run the migration"""
    parser = argparse.ArgumentParser(description="Charting terminal watchlist tables migration")
    parser.add_argument(
        "--status", action="store_true", help="Report status without changing anything"
    )
    args = parser.parse_args()

    print()
    print("Charting Terminal Watchlist Migration")
    print("-" * 46)

    try:
        db_url = get_database_url()
        print(f"Database: {db_url.split('://')[0]}://...")

        if "sqlite" in db_url:
            engine = create_engine(db_url, poolclass=NullPool)
        else:
            engine = create_engine(db_url)

        if args.status:
            return 0 if status(engine) else 1

        print()
        print("Creating tables...")
        create_watchlists_table(engine)
        create_items_table(engine)

        print()
        print("Creating indexes...")
        create_indexes(engine)

        print()
        print("[OK] Watchlist migration completed successfully!")
        return 0

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
