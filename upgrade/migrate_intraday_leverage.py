#!/usr/bin/env python3
"""
Migration: Intraday Leverage Table

Creates the intraday_leverage table storing per-symbol intraday leverage
multipliers for NSE stocks. Seeds 1579 rows from broker margin data.

init_db() in the main database module does not cover this table, so this
script is what reaches deployments that upgrade with `git pull`.

This migration is idempotent - safe to run multiple times.

Usage:
    cd upgrade
    uv run migrate_intraday_leverage.py           # Apply migration
    uv run migrate_intraday_leverage.py --status  # Check status without changing anything
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

TABLE_NAME = "intraday_leverage"


def resolve_sqlite_path(db_url):
    """Make a relative sqlite:/// path absolute against the project root.

    The documented invocation is `cd upgrade && uv run migrate_intraday_leverage.py`,
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


def get_row_count(engine, table_name):
    """Get the row count of a table"""
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()


def create_table(engine):
    """Create the intraday_leverage table."""
    if table_exists(engine, TABLE_NAME):
        print(f"  [SKIP] {TABLE_NAME} table already exists")
        return True

    print(f"  [CREATE] Creating {TABLE_NAME} table...")

    sql = text("""
        CREATE TABLE IF NOT EXISTS intraday_leverage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            exchange TEXT NOT NULL DEFAULT 'NSE',
            multiplier REAL NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, exchange)
        )
    """)

    with engine.connect() as conn:
        conn.execute(sql)
        conn.commit()

    print(f"  [OK] {TABLE_NAME} table created")
    return True


def seed_data(engine):
    """Seed the table with NSE stock leverage multipliers."""
    count = get_row_count(engine, TABLE_NAME)
    if count > 0:
        print(f"  [SKIP] {TABLE_NAME} already has {count} rows")
        return True

    print("  [SEED] Inserting NSE leverage multipliers...")

    from database.intraday_leverage_data import _LEVERAGE_DATA

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO intraday_leverage (symbol, exchange, multiplier) "
                "VALUES (:symbol, 'NSE', :multiplier) ON CONFLICT (symbol, exchange) DO NOTHING"
            ),
            [
                {"symbol": symbol, "multiplier": multiplier}
                for symbol, multiplier in _LEVERAGE_DATA.items()
            ],
        )

    count = get_row_count(engine, TABLE_NAME)
    print(f"  [OK] Seeded {count} rows into {TABLE_NAME}")
    return True


def status(engine):
    """Report what exists without changing anything."""
    print()
    print("Intraday Leverage Migration Status")
    print("-" * 46)

    present = table_exists(engine, TABLE_NAME)
    print(f"  {TABLE_NAME:<34} {'present' if present else 'MISSING'}")

    if present:
        count = get_row_count(engine, TABLE_NAME)
        print(f"  {'row count':<34} {count}")

    print("-" * 46)
    if present:
        count = get_row_count(engine, TABLE_NAME)
        print(f"All changes applied. ({count} rows)")
    else:
        print("Migration needed.")
    return present


def main():
    """Run the migration"""
    parser = argparse.ArgumentParser(description="Intraday leverage table migration")
    parser.add_argument(
        "--status", action="store_true", help="Report status without changing anything"
    )
    args = parser.parse_args()

    print()
    print("Intraday Leverage Migration")
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
        print("Seeding data...")
        seed_data(engine)

        print()
        print("[OK] Intraday leverage migration completed successfully!")
        return 0

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
