#!/usr/bin/env python3
"""Set the 2026 Diwali Muhurat session to the timings the exchanges published.

Muhurat trading is held on Sunday 8 November 2026. NSE, BSE and MCX published
the session on 19 October 2026 (MCX circular MCX/TRD/590/2026):

    Segment                        Pre-open        Trading
    Equity (NSE, BSE)              14:05 - 14:15   14:20 - 15:30
    Equity derivatives (NFO, BFO)  14:05 - 14:15   14:20 - 15:40
    Commodities (MCX, NCO)         14:05 - 14:20   14:20 - 15:30
    Currency (CDS, BCD)            -               14:20 - 15:30

Until then the 2026 calendar OpenAlgo shipped carried a guess of 18:00 to 19:15
(MCX to 00:15 the next morning) and no NCO row. A new install is seeded with
the published session. An existing install keeps the row it was seeded with,
because the seed loads only into an empty table, so this migration moves each
exchange that still holds the guess and adds the NCO row. An exchange an admin
set or removed on the Holidays page is left alone and reported, and nothing
happens when 8 November 2026 is no longer stored as a special session.

The app makes the same change at startup (database.market_calendar_db.
migrate_muhurat_2026), so restarting OpenAlgo alone is enough; this script is
for installs upgraded with migrate_all.py and for checking with --status.

Idempotent, and safe to re-run.

Usage:
    cd upgrade
    uv run migrate_muhurat_2026.py
    uv run migrate_muhurat_2026.py --status
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

PENDING = ("update", "insert")


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


def calendar_stored(calendar):
    """Whether the holiday tables exist yet.

    Args:
        calendar: The database.market_calendar_db module.

    Returns:
        bool: False on an install the app has not started since the calendar
        was added; the app creates and seeds the tables with the published
        session on its next start.
    """
    from sqlalchemy import inspect

    return calendar.Holiday.__tablename__ in set(inspect(calendar.engine).get_table_names())


def describe(calendar, step):
    """One report line for a planned step.

    Args:
        calendar: The database.market_calendar_db module.
        step: An (exchange, action) tuple from plan_muhurat_2026().

    Returns:
        str: The line.
    """
    exchange, action = step
    start, end = (_clock(ms) for ms in calendar.MUHURAT_2026_SESSION[exchange])
    window = f"{start} - {end}"
    if action == "update":
        return f"  {exchange:<4} -> {window}"
    if action == "insert":
        return f"  {exchange:<4} -> {window} (row added)"
    if action == "current":
        return f"  {exchange:<4}    {window}, already set"
    return f"  {exchange:<4}    set by an admin, left alone (published session is {window})"


def _clock(epoch_ms):
    """An epoch-millisecond instant as an IST wall-clock time."""
    from datetime import datetime, timedelta, timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.fromtimestamp(epoch_ms / 1000, ist).strftime("%H:%M")


def report(calendar, steps):
    """Print the plan, one line per exchange.

    Args:
        calendar: The database.market_calendar_db module.
        steps: The plan, or None when there is nothing stored to change.
    """
    if steps is None:
        print("  8 November 2026 is not stored as a special session; nothing to change.")
        return
    for step in steps:
        print(describe(calendar, step))


def main():
    """Entry point.

    Returns:
        int: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(
        description="Set the 2026 Diwali Muhurat session to the published timings"
    )
    parser.add_argument(
        "--status", action="store_true", help="Report what would change without changing it"
    )
    args = parser.parse_args()

    db_url = get_database_url()
    path = sqlite_file(db_url)
    if path is not None and not os.path.exists(path):
        # Connecting would create an empty file; the app seeds a new one.
        print("No database yet. The app seeds the published Muhurat session on first start.")
        return 0

    # database.market_calendar_db builds its engine from DATABASE_URL at import.
    os.environ["DATABASE_URL"] = db_url
    from database import market_calendar_db as calendar

    try:
        if not calendar_stored(calendar):
            print("No market calendar stored yet. The app seeds the published")
            print("Muhurat session when it next starts.")
            return 0

        if args.status:
            print("Diwali Muhurat 2026 (Sunday 8 November) status")
            print("-" * 62)
            steps = calendar.plan_muhurat_2026()
            report(calendar, steps)
            pending = sum(1 for _exchange, action in steps or () if action in PENDING)
            print(f"Would change {pending} exchange(s)." if pending else "Nothing to change.")
            return 0

        print("=" * 62)
        print("Migration: Diwali Muhurat 2026 published timings")
        print("=" * 62)
        before = calendar.plan_muhurat_2026()
        calendar.migrate_muhurat_2026()
        after = calendar.plan_muhurat_2026()
        report(calendar, before)
        if any(action in PENDING for _exchange, action in after or ()):
            print("  [FAIL] The session was not updated. See log/errors.jsonl.")
            print("-" * 62)
            print("Migration failed. See the messages above.")
            return 1
        changed = sum(1 for _exchange, action in before or () if action in PENDING)
        if changed:
            print(f"  [OK] Updated {changed} exchange(s). Restart OpenAlgo to apply them.")
        else:
            print("  [OK] Nothing to change.")
        print("-" * 62)
        print("Migration complete.")
        return 0
    except Exception as exc:
        print(f"  [FAIL] Could not update the Muhurat session: {type(exc).__name__}: {exc}")
        return 1
    finally:
        calendar.db_session.remove()
        calendar.engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
