#!/usr/bin/env python3
"""
Migration: Broker Keys and session sign-out

Adds three tables to the main database:

- broker_keys: the API keys a trader saves in OpenAlgo (Broker Configuration),
  one set per broker, every key and secret encrypted. The trader logs in to
  one broker at a time. The .env file still comes first: a broker it sets keys
  for always uses them.
- session_revocations: when a user last ended every session (a logout, a
  password change or a reset), so a copy of the session cookie on another
  device stops working at that moment, and when a sign-in that never reached
  a broker login was logged out (pre_broker_revoked_at), which ends every such
  sign-in. An install that created the table before that column existed gets
  it added, empty: no logout of that kind has been recorded yet.
- broker_login_states: broker logins started from the broker login page and
  not yet completed, kept as SHA-256 digests with a ten-minute expiry, so the
  broker's answer is accepted only for a login started here.

All are new tables, so there is nothing to backfill and no existing value to
preserve; the added column starts empty for the same reason. The app creates them at startup too; this script is what reaches the
installs that upgrade with `git pull` and migrate_all.py before restarting.

This migration is idempotent - safe to run multiple times.

Usage:
    cd upgrade
    uv run migrate_broker_keys.py           # Apply migration
    uv run migrate_broker_keys.py --status  # Check status without changing anything
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

TABLES = ("broker_keys", "session_revocations", "broker_login_states")


def resolve_sqlite_path(db_url):
    """Make a relative sqlite:/// path absolute against the project root.

    The documented invocation runs from upgrade/, and DATABASE_URL is relative
    by default ("sqlite:///db/openalgo.db"). Left relative it would point at
    upgrade/db/openalgo.db, which SQLAlchemy creates empty on connect, and the
    migration would report success against a database the app never opens.

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
    """The database this instance uses.

    Returns:
        str: The SQLAlchemy URL.
    """
    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    return resolve_sqlite_path(os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db"))


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


def model_tables():
    """The tables as the app defines them, so the schema has one source.

    Returns:
        list: SQLAlchemy Table objects, in TABLES order.
    """
    from database.auth_db import SessionRevocation
    from database.broker_keys_db import BrokerKey, BrokerLoginState

    return [BrokerKey.__table__, SessionRevocation.__table__, BrokerLoginState.__table__]


def missing_tables(engine):
    """The tables of TABLES not in the database yet.

    Returns:
        list[str]: Table names.
    """
    from sqlalchemy import inspect

    present = set(inspect(engine).get_table_names())
    return [name for name in TABLES if name not in present]


def missing_columns(engine):
    """Columns added to these tables after they were first created, not there yet.

    Returns:
        list[str]: "table.column" names.
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)
    if "session_revocations" not in inspector.get_table_names():
        return []
    present = {column["name"] for column in inspector.get_columns("session_revocations")}
    return [
        f"session_revocations.{name}"
        for name in ("pre_broker_revoked_at",)
        if name not in present
    ]


def main():
    """Entry point.

    Returns:
        int: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(
        description="Add the broker keys, session sign-out and broker login tables"
    )
    parser.add_argument(
        "--status", action="store_true", help="Report what would change without changing it"
    )
    args = parser.parse_args()

    db_url = get_database_url()
    path = sqlite_file(db_url)
    if path is not None and not os.path.exists(path):
        # Connecting would create an empty file; the app creates the tables on
        # its first start.
        print("No database yet. The app creates these tables on first start.")
        return 0

    # The database modules build their engines from DATABASE_URL at import.
    os.environ["DATABASE_URL"] = db_url
    from database.engine_factory import create_db_engine

    engine = create_db_engine(db_url)
    try:
        missing = missing_tables(engine)
        columns = missing_columns(engine)
        if args.status:
            print("Broker keys, session sign-out and broker login tables")
            print("-" * 62)
            for name in TABLES:
                print(f"  {name:<22} {'missing' if name in missing else 'present'}")
            for name in columns:
                print(f"  {name:<40} missing")
            if missing or columns:
                print(f"Would create {len(missing)} table(s) and add {len(columns)} column(s).")
            else:
                print("Nothing to change.")
            return 0

        print("=" * 62)
        print("Migration: Broker keys, session sign-out and broker login")
        print("=" * 62)
        if not missing:
            print("  [SKIP] All tables already exist")
        for table in model_tables():
            if table.name in missing:
                table.create(engine, checkfirst=True)
                print(f"  [OK] Created {table.name}")
        still_missing = missing_tables(engine)
        if still_missing:
            print(f"  [FAIL] Could not create: {', '.join(still_missing)}")
            return 1
        from database.auth_db import ensure_session_revocation_columns

        if not columns:
            print("  [SKIP] All columns already exist")
        for name in ensure_session_revocation_columns(engine):
            print(f"  [OK] Added session_revocations.{name}")
        still_missing = missing_columns(engine)
        if still_missing:
            print(f"  [FAIL] Could not add: {', '.join(still_missing)}")
            return 1
        print("-" * 62)
        print("Migration complete.")
        return 0
    except Exception as exc:
        print(f"  [FAIL] Could not create the tables: {type(exc).__name__}: {exc}")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
