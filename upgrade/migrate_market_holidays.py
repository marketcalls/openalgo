#!/usr/bin/env python3
"""Move an install off the first 2026 market holiday calendar.

The first calendar OpenAlgo shipped (December 2025) had 2026 wrong in places,
corrected in March 2026 against the NSE and MCX circulars:

- Holi: 2026-03-10 -> 2026-03-03
- Ram Navami: 2026-04-02 -> 2026-03-26
- Mahavir Jayanti: 2026-04-06 -> 2026-03-31
- Bakri Id: 2026-05-27 -> 2026-05-28
- Muharram: 2026-06-25 -> 2026-06-26
- Dussehra: added 2026-10-20
- Diwali Balipratipada: 2026-10-21 -> 2026-11-10
- Diwali Muhurat: 2026-10-20 -> 2026-11-08
- Guru Nanak Dev: 2026-11-08 -> 2026-11-24
- Added: 2026-01-15 (Municipal Corporation Election), 2026-09-14 (Ganesh Chaturthi)
- Removed: entries that are not exchange holidays (settlement holidays,
  Id-Ul-Fitr, Holi Dhuleti, Milad-un-Nabi, Independence Day on a Saturday)
- MCX evening sessions stamped with 2025's dates moved to 2026's

This script used to delete every holiday and reseed the calendar from code,
on every upgrade. Each run took every holiday an admin had added or edited on
the Holidays page. It now changes only rows still exactly as the first
calendar shipped them, and adds a corrected entry only where its date is free.
An install already on the corrected calendar, or one its admin has curated, is
not touched, so a holiday an admin added stays and one an admin deleted stays
deleted. The app makes the same correction at startup
(database.market_calendar_db.correct_2026_calendar).

Idempotent, and safe to re-run.

Usage:
    cd upgrade
    uv run migrate_market_holidays.py
    uv run migrate_market_holidays.py --status
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


def report(steps):
    """Print the plan, one line per change.

    Args:
        steps: The plan from plan_2026_calendar_correction(), or None.
    """
    if steps is None:
        print("  No holidays stored yet. The app seeds the corrected calendar.")
        return
    if not steps:
        print("  The calendar is not the first 2026 release; nothing to change.")
        return
    for action, day, description in steps:
        sign = "-" if action == "remove" else "+"
        print(f"  {sign} {day}  {description}")


def main():
    """Entry point.

    Returns:
        int: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(
        description="Move an install off the first 2026 market holiday calendar"
    )
    parser.add_argument(
        "--status", action="store_true", help="Report what would change without changing it"
    )
    args = parser.parse_args()

    db_url = get_database_url()
    path = sqlite_file(db_url)
    if path is not None and not os.path.exists(path):
        # Connecting would create an empty file; the app seeds a new one.
        print("No database yet. The app seeds the corrected calendar on first start.")
        return 0

    # database.market_calendar_db builds its engine from DATABASE_URL at import.
    os.environ["DATABASE_URL"] = db_url
    from sqlalchemy import inspect

    from database import market_calendar_db as calendar

    try:
        tables = set(inspect(calendar.engine).get_table_names())
        if calendar.Holiday.__tablename__ not in tables:
            print("No market calendar stored yet. The app seeds the corrected")
            print("calendar when it next starts.")
            return 0

        if args.status:
            print("2026 market holiday calendar status")
            print("-" * 62)
            steps = calendar.plan_2026_calendar_correction()
            report(steps)
            pending = len(steps or ())
            print(f"Would change {pending} holiday(s)." if pending else "Nothing to change.")
            return 0

        print("=" * 62)
        print("Migration: 2026 market holiday calendar")
        print("=" * 62)
        before = calendar.plan_2026_calendar_correction()
        calendar.correct_2026_calendar()
        after = calendar.plan_2026_calendar_correction()
        report(before)
        if after:
            print("  [FAIL] The calendar was not corrected. See log/errors.jsonl.")
            print("-" * 62)
            print("Migration failed. See the messages above.")
            return 1
        if before:
            print(f"  [OK] Changed {len(before)} holiday(s). Restart OpenAlgo to apply them.")
        else:
            print("  [OK] Nothing to change.")
        print("-" * 62)
        print("Migration complete.")
        return 0
    except Exception as exc:
        print(f"  [FAIL] Could not correct the calendar: {type(exc).__name__}: {exc}")
        return 1
    finally:
        calendar.db_session.remove()
        calendar.engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
