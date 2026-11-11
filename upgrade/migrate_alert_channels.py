#!/usr/bin/env python3
"""
Migration: Alert channels

Adds one table to the main database:

- alert_channels: the settings of each alert channel a trader has changed on
  the /alerts page. Whether the channel is on, which event groups it receives,
  and for Slack and Discord the webhook URL, encrypted.

It is a new table, so there is nothing to backfill and no existing value to
preserve. A channel with no row keeps its defaults: Telegram and WhatsApp stay
on with every event group, exactly as they alerted before this table existed,
and Slack and Discord stay off until a webhook is saved. No seed rows are
written, so an install that never opens /alerts is unchanged.

The app creates the table at startup too; this script is what reaches the
installs that upgrade with `git pull` and migrate_all.py before restarting.

This migration is idempotent - safe to run multiple times.

Usage:
    cd upgrade
    uv run migrate_alert_channels.py           # Apply migration
    uv run migrate_alert_channels.py --status  # Check status without changing anything
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

TABLE = "alert_channels"


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


def table_missing(engine):
    """Whether the table is not in the database yet.

    Returns:
        bool: True when it has to be created.
    """
    from sqlalchemy import inspect

    return TABLE not in set(inspect(engine).get_table_names())


def main():
    """Entry point.

    Returns:
        int: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(description="Add the alert channels table")
    parser.add_argument(
        "--status", action="store_true", help="Report what would change without changing it"
    )
    args = parser.parse_args()

    db_url = get_database_url()
    path = sqlite_file(db_url)
    if path is not None and not os.path.exists(path):
        # Connecting would create an empty file; the app creates the table on
        # its first start.
        print("No database yet. The app creates this table on first start.")
        return 0

    # The database modules build their engines from DATABASE_URL at import.
    os.environ["DATABASE_URL"] = db_url
    from database.engine_factory import create_db_engine

    engine = create_db_engine(db_url)
    try:
        missing = table_missing(engine)
        if args.status:
            print("Alert channels table")
            print("-" * 62)
            print(f"  {TABLE:<24} {'missing' if missing else 'present'}")
            print("Would create 1 table." if missing else "Nothing to change.")
            return 0

        print("=" * 62)
        print("Migration: Alert channels")
        print("=" * 62)
        if not missing:
            print("  [SKIP] The table already exists")
            return 0
        # The schema has one source: the model the app itself uses.
        from database.alert_channels_db import AlertChannelRow

        AlertChannelRow.__table__.create(engine, checkfirst=True)
        if table_missing(engine):
            print(f"  [FAIL] Could not create {TABLE}")
            return 1
        print(f"  [OK] Created {TABLE}")
        print("-" * 62)
        print("Migration complete.")
        return 0
    except Exception as exc:
        print(f"  [FAIL] Could not create the table: {type(exc).__name__}: {exc}")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
