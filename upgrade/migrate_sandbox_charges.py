#!/usr/bin/env python3
"""
Migration: Sandbox brokerage and statutory charges

Sandbox trades are now charged brokerage and statutory charges (STT or CTT,
exchange transaction charges, SEBI fees, stamp duty and GST). This migration
prepares an existing sandbox database for that:

- sandbox_trades gets one column per charge (brokerage, stt, exchange_charges,
  sebi_charges, stamp_duty, gst) and their total, so every fill records what
  it paid and the transaction cost report can list it.

- sandbox_funds gets total_charges (since the last funds reset) and
  today_charges (resets daily). The charges are taken out of the available
  balance as each order fills; these columns keep the running totals.

- sandbox_daily_pnl gets charges, the day's charges beside the day's P&L.

- sandbox_config gets the charges switch and the default brokerage plan, one
  flat amount and one percentage per segment. A value the trader has already
  saved on /sandbox/commissions is never overwritten: only keys that do not
  exist yet are inserted.

Existing rows are left at 0.00, and that is the true figure rather than a
placeholder. No trade made before this release was charged anything and no
balance had a charge taken from it, so there is nothing to backfill: charging
old trades after the fact would change balances and P&L the trader has already
seen. Charges apply from the first fill after the upgrade.

The app adds the same columns at startup, so an installation that simply
restarts is upgraded too; this script is what reaches the installs that
upgrade with `git pull` and migrate_all.py before restarting, and it lets the
change be applied and inspected on its own.

This migration is idempotent - safe to run multiple times.

Usage:
    cd upgrade
    uv run migrate_sandbox_charges.py           # Apply migration
    uv run migrate_sandbox_charges.py --status  # Check status without changing anything
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, PROJECT_ROOT)
# Register the app's SQLite pragmas on this process's engines, so a migration
# waits the same 15s for a write lock the running app does instead of the
# sqlite3 default of 5s (GitHub issue #1726).
import _pragmas  # noqa: F401,E402

# The same set database/sandbox_db.py adds at startup, kept here too so the
# script reads on its own; test/test_migrate_sandbox_charges.py holds the two
# lists, and the models, to each other.
CHARGE_COLUMNS_BY_TABLE = {
    "sandbox_trades": (
        "brokerage",
        "stt",
        "exchange_charges",
        "sebi_charges",
        "stamp_duty",
        "gst",
        "total_charges",
    ),
    "sandbox_funds": ("total_charges", "today_charges"),
    "sandbox_daily_pnl": ("charges",),
}

CONFIG_TABLE = "sandbox_config"


def resolve_sqlite_path(db_url):
    """Make a relative sqlite:/// path absolute against the project root.

    The documented invocation runs from upgrade/, and SANDBOX_DATABASE_URL is
    relative by default ("sqlite:///db/sandbox.db"). Left relative it would
    point at upgrade/db/sandbox.db, which SQLAlchemy creates empty on connect,
    and the migration would report success against a database the app never
    opens.

    Args:
        db_url: The database URL.

    Returns:
        str: The URL with any relative SQLite path made absolute.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return db_url
    path = db_url[len(prefix) :]
    if not path or path == ":memory:" or os.path.isabs(path):
        return db_url
    return prefix + os.path.join(PROJECT_ROOT, path)


def get_database_url():
    """The sandbox database this instance uses.

    Returns:
        str: The SQLAlchemy URL.
    """
    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    return resolve_sqlite_path(os.getenv("SANDBOX_DATABASE_URL", "sqlite:///db/sandbox.db"))


def sqlite_file(db_url):
    """The file a sqlite URL points at, or None for any other backend.

    Args:
        db_url: The database URL.

    Returns:
        str | None: The file path.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return None
    path = db_url[len(prefix) :]
    return path if path and path != ":memory:" else None


def default_settings():
    """The charge settings and their defaults, from the module that applies them.

    One source, so this script cannot seed a default the calculation does not
    use. sandbox/charges.py imports only the standard library.

    Returns:
        list[dict]: Rows with config_key, config_value and description.
    """
    from sandbox.charges import default_config_rows

    return default_config_rows()


def missing_columns(engine):
    """The charge columns each existing table still lacks.

    A table that does not exist is left out: the app creates it, with the
    columns, on its first start.

    Returns:
        dict[str, list[str]]: Table name to the columns to add; empty when
        there is nothing to add.
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing = {}
    for table, columns in CHARGE_COLUMNS_BY_TABLE.items():
        if table not in tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table)}
        lacking = [column for column in columns if column not in present]
        if lacking:
            missing[table] = lacking
    return missing


def missing_settings(engine):
    """The charge settings sandbox_config does not hold yet.

    Returns:
        list[dict]: Rows to insert; empty when all are present or the table
        does not exist (the app seeds it on its first start).
    """
    from sqlalchemy import inspect, text

    if CONFIG_TABLE not in set(inspect(engine).get_table_names()):
        return []
    with engine.connect() as conn:
        present = {row[0] for row in conn.execute(text(f"SELECT config_key FROM {CONFIG_TABLE}"))}
    return [row for row in default_settings() if row["config_key"] not in present]


def add_columns(engine, missing):
    """Add the given columns, one transaction for all of them.

    DEFAULT 0.00 is what an existing row then reads, which is what it paid:
    nothing was charged before this release.

    Args:
        engine: The sandbox database.
        missing: From missing_columns.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        for table, columns in missing.items():
            for column in columns:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} DECIMAL(15, 2) DEFAULT 0.00")
                )


def add_settings(engine, rows):
    """Insert the given settings. A key that already exists is never touched.

    The insert names only keys missing_settings found absent, and the key
    column is unique, so a key saved between the check and the insert makes
    the insert fail rather than be overwritten.

    Args:
        engine: The sandbox database.
        rows: From missing_settings.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        for row in rows:
            # updated_at is NOT NULL and, on a table SQLAlchemy created, has no
            # database default (the application supplies it), so it is given.
            conn.execute(
                text(
                    f"INSERT INTO {CONFIG_TABLE} "
                    "(config_key, config_value, description, updated_at) "
                    "VALUES (:config_key, :config_value, :description, CURRENT_TIMESTAMP)"
                ),
                row,
            )


def main():
    """Entry point.

    Returns:
        int: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(
        description="Add brokerage and statutory charges to the sandbox database"
    )
    parser.add_argument(
        "--status", action="store_true", help="Report what would change without changing it"
    )
    args = parser.parse_args()

    db_url = get_database_url()
    path = sqlite_file(db_url)
    if path is not None and not os.path.exists(path):
        # Connecting would create an empty file; the app creates the tables,
        # with these columns and settings, on its first start.
        print("No sandbox database yet. The app creates it on first start.")
        return 0

    from database.engine_factory import create_db_engine

    engine = create_db_engine(db_url)
    try:
        columns = missing_columns(engine)
        settings = missing_settings(engine)
        column_count = sum(len(names) for names in columns.values())

        if args.status:
            print("Sandbox brokerage and statutory charges")
            print("-" * 62)
            for table in CHARGE_COLUMNS_BY_TABLE:
                lacking = columns.get(table, [])
                state = f"missing {', '.join(lacking)}" if lacking else "up to date"
                print(f"  {table:<20} {state}")
            state = f"{len(settings)} setting(s) to add" if settings else "up to date"
            print(f"  {CONFIG_TABLE:<20} {state}")
            if column_count or settings:
                print(f"Would add {column_count} column(s) and {len(settings)} setting(s).")
            else:
                print("Nothing to change.")
            return 0

        print("=" * 62)
        print("Migration: Sandbox brokerage and statutory charges")
        print("=" * 62)
        if not column_count and not settings:
            print("  [SKIP] The columns and settings are already there")
            return 0

        if column_count:
            add_columns(engine, columns)
            for table, names in columns.items():
                print(f"  [OK] {table}: added {', '.join(names)}")
        if settings:
            add_settings(engine, settings)
            print(f"  [OK] {CONFIG_TABLE}: added {len(settings)} setting(s) at their defaults")

        still_missing = missing_columns(engine)
        if still_missing:
            print(f"  [FAIL] Columns are still missing: {still_missing}")
            return 1
        print("-" * 62)
        print("Migration complete. Charges apply from the next sandbox trade.")
        return 0
    except Exception as exc:
        print(f"  [FAIL] Could not update the sandbox database: {type(exc).__name__}: {exc}")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
