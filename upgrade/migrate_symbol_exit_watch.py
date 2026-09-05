#!/usr/bin/env python3
"""
Migration: Symbol Exit Watch

Adds the table backing the position calculator's automatic SL / target exit
watches:

- symbol_exit_watch: one row per entry order that was placed with risk legs
  (stoploss / target / trailing_stoploss). The symbol exit monitor squares the
  position off when the market reaches a level, for every trade type, in both
  sandbox (analyze) and live mode.

This is a new table, so there is nothing to backfill and no existing value to
preserve. init_db() in database/symbol_exit_db.py creates it too, but that only
helps an installation whose database is opened after this ships; this script is
what reaches the deployments that upgrade with `git pull`.

This migration is idempotent - safe to run multiple times.

Usage:
    cd upgrade
    uv run migrate_symbol_exit_watch.py           # Apply migration
    uv run migrate_symbol_exit_watch.py --status  # Check status without changing anything
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

TABLE = "symbol_exit_watch"

#: Every index this migration is responsible for. The ORM declares these via
#: ``index=True``, so a fresh init_db() and this migration must agree on names.
INDEXES = {
    "ix_symbol_exit_watch_id": (TABLE, "id"),
    "ix_symbol_exit_watch_status": (TABLE, "status"),
}


def resolve_sqlite_path(db_url):
    """Make a relative sqlite:/// path absolute against the project root.

    The documented invocation is `cd upgrade && uv run migrate_symbol_exit_watch.py`,
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
    return table_name in inspect(engine).get_table_names()


def index_exists(engine, table_name, index_name):
    if not table_exists(engine, table_name):
        return False
    return index_name in {idx["name"] for idx in inspect(engine).get_indexes(table_name)}


def create_table(engine):
    if table_exists(engine, TABLE):
        print(f"  [SKIP] {TABLE} table already exists")
        return True

    print(f"  [CREATE] Creating {TABLE} table...")

    if "sqlite" in str(engine.url):
        sql = """
        CREATE TABLE symbol_exit_watch (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol VARCHAR(60) NOT NULL,
            exchange VARCHAR(10) NOT NULL,
            product VARCHAR(10) NOT NULL,
            side VARCHAR(4) NOT NULL DEFAULT 'BUY',
            mode VARCHAR(10) NOT NULL DEFAULT 'analyze',
            order_id VARCHAR(64) NOT NULL,
            strategy VARCHAR(60) NOT NULL DEFAULT '',
            entry_price FLOAT NOT NULL DEFAULT 0,
            quantity INTEGER NOT NULL DEFAULT 0,
            stop_loss FLOAT,
            target FLOAT,
            trailing_step FLOAT,
            current_stop FLOAT,
            highest_price FLOAT,
            lowest_price FLOAT,
            status VARCHAR(10) NOT NULL DEFAULT 'active',
            exit_reason VARCHAR(20),
            exit_price FLOAT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            executed_at TIMESTAMP,
            CONSTRAINT uq_symbol_exit_watch_order UNIQUE (order_id, mode)
        )
        """
    else:
        sql = """
        CREATE TABLE symbol_exit_watch (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(60) NOT NULL,
            exchange VARCHAR(10) NOT NULL,
            product VARCHAR(10) NOT NULL,
            side VARCHAR(4) NOT NULL DEFAULT 'BUY',
            mode VARCHAR(10) NOT NULL DEFAULT 'analyze',
            order_id VARCHAR(64) NOT NULL,
            strategy VARCHAR(60) NOT NULL DEFAULT '',
            entry_price FLOAT NOT NULL DEFAULT 0,
            quantity INTEGER NOT NULL DEFAULT 0,
            stop_loss FLOAT,
            target FLOAT,
            trailing_step FLOAT,
            current_stop FLOAT,
            highest_price FLOAT,
            lowest_price FLOAT,
            status VARCHAR(10) NOT NULL DEFAULT 'active',
            exit_reason VARCHAR(20),
            exit_price FLOAT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            executed_at TIMESTAMP WITH TIME ZONE,
            CONSTRAINT uq_symbol_exit_watch_order UNIQUE (order_id, mode)
        )
        """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print(f"  [OK] {TABLE} table created")
    return True


def create_indexes(engine):
    for index_name, (table_name, column) in INDEXES.items():
        if not table_exists(engine, table_name):
            continue
        if index_exists(engine, table_name, index_name):
            print(f"  [SKIP] {index_name} already exists")
            continue

        print(f"  [CREATE] Creating {index_name}...")
        with engine.connect() as conn:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column})"))
            conn.commit()
        print(f"  [OK] {index_name} created")
    return True


def status(engine):
    print()
    print("Symbol Exit Watch migration status")
    print("-" * 46)

    applied = True
    present = table_exists(engine, TABLE)
    print(f"  {TABLE:<34} {'present' if present else 'MISSING'}")
    applied = applied and present

    for index_name, (_table_name, _column) in INDEXES.items():
        present = index_exists(engine, TABLE, index_name)
        print(f"  {index_name:<34} {'present' if present else 'MISSING'}")
        applied = applied and present

    if table_exists(engine, TABLE):
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar()
        print(f"  {'existing data':<34} {count} watch(es)")

    print("-" * 46)
    print("All changes applied." if applied else "Migration needed.")
    return applied


def main():
    """Run the migration"""
    parser = argparse.ArgumentParser(description="Symbol exit watch table migration")
    parser.add_argument(
        "--status", action="store_true", help="Report status without changing anything"
    )
    args = parser.parse_args()

    print()
    print("Symbol Exit Watch Migration")
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
        print("Creating table...")
        create_table(engine)

        print()
        print("Creating indexes...")
        create_indexes(engine)

        print()
        print("[OK] Symbol exit watch migration completed successfully!")
        return 0

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
