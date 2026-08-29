#!/usr/bin/env python3
"""
Migration: Retire the legacy /strategy module tables

The legacy /strategy module (blueprints/strategy.py, database/strategy_db.py)
has been removed from OpenAlgo, but its two tables stay behind in openalgo.db
on every installation that upgrades with `git pull`:

- strategies:               one webhook-driven strategy per row
- strategy_symbol_mappings: the instruments each strategy traded, with quantity
                            and product type (FK -> strategies.id)

Nothing else in any OpenAlgo database references either table. The Chartink
module owns a separate pair (chartink_strategies, chartink_symbol_mappings) and
is untouched, as are strategy_portfolio, strategy_order_tags,
strategy_pending_fills and strategy_positions, which belong to unrelated
features and only share the "strategy" name prefix.

EXPORT BEFORE DROP. These rows are user-authored trading configuration: which
symbols a strategy traded, at what quantity, under which product type, plus its
webhook id and its intraday time windows. None of that is reconstructable from
anything else in the database, so both tables are written to a timestamped JSON
file in db/backups/ BEFORE anything is dropped, and the migration aborts
without dropping if that export cannot be written. A failed export followed by
a successful drop is the one outcome that loses the data irrecoverably.

This migration is idempotent - safe to run multiple times. Once the tables are
gone it says so and exits without touching the database.

Usage:
    cd upgrade
    uv run migrate_drop_legacy_strategy.py           # Export, then drop
    uv run migrate_drop_legacy_strategy.py --status  # Report without changing anything
"""

import argparse
import json
import os
import sys
from datetime import date, datetime
from datetime import time as datetime_time
from decimal import Decimal

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add parent directory to path for imports
sys.path.insert(0, PROJECT_ROOT)
# Register the app's SQLite pragmas on this process's engines, so a migration
# waits the same 15s for a write lock the running app does instead of the
# sqlite3 default of 5s (GitHub issue #1726).
import _pragmas  # noqa: F401,E402
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)

STRATEGIES_TABLE = "strategies"
MAPPINGS_TABLE = "strategy_symbol_mappings"

#: Drop order is child first: strategy_symbol_mappings.strategy_id is a real
#: FOREIGN KEY onto strategies(id). SQLite leaves foreign_keys OFF by default so
#: the reverse order happens to succeed there, but PostgreSQL refuses it, and
#: relying on a pragma being off is not a plan.
DROP_ORDER = (MAPPINGS_TABLE, STRATEGIES_TABLE)

#: Read order for the export, parent first, so the JSON reads the way the data
#: is shaped: a strategy, then the symbols underneath it.
EXPORT_ORDER = (STRATEGIES_TABLE, MAPPINGS_TABLE)

EXPORT_PREFIX = "legacy-strategy-export"


def resolve_sqlite_path(db_url):
    """Make a relative sqlite:/// path absolute against the project root.

    The documented invocation is `cd upgrade && uv run
    migrate_drop_legacy_strategy.py`, and DATABASE_URL is relative by default
    ("sqlite:///db/openalgo.db"). Left relative it resolves against the current
    directory, so running from upgrade/ would point at upgrade/db/openalgo.db -
    which SQLAlchemy creates empty on connect. The migration would then report
    success having dropped nothing from a database the app never opens.
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


def export_directory(db_url):
    """Where the JSON export is written.

    Next to the database itself for SQLite (db/backups/, the same place
    rotate_pepper.py puts its backup, and already in .gitignore), and under the
    project root for a server-hosted database that has no local file.
    """
    prefix = "sqlite:///"
    if db_url.startswith(prefix):
        path = db_url[len(prefix) :]
        if path and path != ":memory:":
            return os.path.join(os.path.dirname(os.path.abspath(path)), "backups")
    return os.path.join(PROJECT_ROOT, "db", "backups")


def table_exists(engine, table_name):
    """Check if a table exists in the database.

    The inspector reads sqlite_master on SQLite and pg_catalog on PostgreSQL,
    so one call covers both backends.
    """
    return table_name in inspect(engine).get_table_names()


def row_count(engine, table_name):
    """Number of rows in a table, or 0 when the table is already gone."""
    if not table_exists(engine, table_name):
        return 0
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0


def json_default(value):
    """Serialize the column types the two tables can hand back.

    SQLite returns plain strings for its DATETIME columns; PostgreSQL returns
    real datetime objects, and psycopg can return Decimal. Anything unforeseen
    degrades to its string form rather than failing the export - losing type
    fidelity on one column is recoverable, losing the export is not.
    """
    if isinstance(value, (datetime, date, datetime_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return str(value)


def read_table(engine, table_name):
    """Read a whole table as a list of dicts, ordered by primary key."""
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT * FROM {table_name} ORDER BY id"))
        columns = list(result.keys())
        rows = [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
    return columns, rows


def export_tables(engine, db_url, present):
    """Write every row of both tables to one timestamped JSON file.

    Returns the absolute path on success, or None if the export failed - in
    which case the caller must not drop anything.
    """
    payload = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "source": "OpenAlgo migrate_drop_legacy_strategy.py",
        "note": (
            "Configuration of the retired /strategy module, exported before the "
            "strategies and strategy_symbol_mappings tables were dropped. "
            "strategy_symbol_mappings.strategy_id refers to strategies.id."
        ),
        "tables": {},
    }

    for table_name in EXPORT_ORDER:
        if table_name not in present:
            payload["tables"][table_name] = {"present": False, "row_count": 0, "rows": []}
            continue
        columns, rows = read_table(engine, table_name)
        payload["tables"][table_name] = {
            "present": True,
            "columns": columns,
            "row_count": len(rows),
            "rows": rows,
        }

    directory = export_directory(db_url)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = os.path.abspath(os.path.join(directory, f"{EXPORT_PREFIX}-{timestamp}.json"))
    temp_path = export_path + ".tmp"

    try:
        os.makedirs(directory, exist_ok=True)
        # Write to a temporary name and rename into place, so a half-written
        # file can never be mistaken for a complete export.
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, default=json_default)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, export_path)

        # Read it back before trusting it. The drop that follows is
        # irreversible, so "the write did not raise" is not good enough.
        with open(export_path, encoding="utf-8") as handle:
            verified = json.load(handle)
        for table_name in EXPORT_ORDER:
            written = len(verified["tables"][table_name]["rows"])
            expected = payload["tables"][table_name]["row_count"]
            if written != expected:
                raise ValueError(
                    f"{table_name}: exported {written} row(s) but the table holds {expected}"
                )
    except Exception as e:
        print(f"  [ERROR] Could not write the export: {e}")
        logger.exception("Legacy strategy export failed - aborting without dropping any table")
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        return None

    print(f"  [OK] Exported to {export_path}")
    for table_name in EXPORT_ORDER:
        print(f"       {table_name}: {payload['tables'][table_name]['row_count']} row(s)")
    return export_path


def drop_tables(engine, present):
    """Drop the legacy tables, child before parent."""
    for table_name in DROP_ORDER:
        if table_name not in present:
            print(f"  [SKIP] {table_name} already absent")
            continue
        print(f"  [DROP] Dropping {table_name}...")
        with engine.connect() as conn:
            # No CASCADE: nothing else references these tables, and if some
            # installation proves otherwise the drop should fail loudly rather
            # than quietly take an unrelated object with it.
            conn.execute(text(f"DROP TABLE {table_name}"))
            conn.commit()
        print(f"  [OK] {table_name} dropped")
    return True


def present_tables(engine):
    """Which of the two legacy tables still exist."""
    return [name for name in EXPORT_ORDER if table_exists(engine, name)]


def status(engine):
    """Report what the migration would do without changing anything."""
    print()
    print("Legacy /strategy table removal status")
    print("-" * 46)

    present = present_tables(engine)
    total_rows = 0
    for table_name in EXPORT_ORDER:
        if table_name in present:
            count = row_count(engine, table_name)
            total_rows += count
            print(f"  {table_name:<30} present, {count} row(s)")
        else:
            print(f"  {table_name:<30} absent")

    print("-" * 46)
    if not present:
        print("All changes applied. Both legacy tables are already gone.")
        return True

    if total_rows:
        print(f"Migration needed. Would export {total_rows} row(s), then drop:")
    else:
        print("Migration needed. Both tables are empty, so no export. Would drop:")
    for table_name in DROP_ORDER:
        if table_name in present:
            print(f"  {table_name}")
    return False


def main():
    """Run the migration"""
    parser = argparse.ArgumentParser(description="Retire the legacy /strategy module tables")
    parser.add_argument(
        "--status", action="store_true", help="Report status without changing anything"
    )
    args = parser.parse_args()

    print()
    print("Legacy /strategy Module Table Removal")
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

        present = present_tables(engine)
        if not present:
            print()
            print("  [SKIP] Both legacy tables are already gone - nothing to do")
            print()
            print("[OK] Legacy /strategy table removal already applied!")
            return 0

        total_rows = sum(row_count(engine, name) for name in present)

        print()
        if total_rows:
            print("Exporting legacy strategy configuration...")
            if export_tables(engine, db_url, present) is None:
                print()
                print("[ERROR] Export failed - no table was dropped. Nothing was lost.")
                print("        Fix the export destination and re-run this migration.")
                return 1
        else:
            print("Both legacy tables are empty - no export needed")

        print()
        print("Dropping tables...")
        drop_tables(engine, present)

        print()
        print("[OK] Legacy /strategy table removal completed successfully!")
        return 0

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        logger.exception("Legacy /strategy table removal failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
