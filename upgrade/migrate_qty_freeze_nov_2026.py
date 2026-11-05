#!/usr/bin/env python3
"""Set the NSE index freeze limits to the values in force from 2 November 2026.

NSE circular NSE/FAOP/77189 (30 October 2026) returns the index futures and
options freeze limits to its computation methodology, which NSE/FAOP/76693 had
set aside from 5 October 2026. Every limit comes down:

    Index        5 Oct 2026   2 Nov 2026   Largest order at October's lot sizes
    NIFTY             3,510        1,800   27 x 65 = 1,755
    BANKNIFTY         1,440          900   30 x 30
    FINNIFTY          3,240        1,800   30 x 60
    MIDCPNIFTY        5,760        2,800   23 x 120 = 2,760
    NIFTYNXT50        1,125          600   24 x 25
    NIFTYFPI         53,900        8,500   7 x 1,100 = 7,700

The table stores NSE's figure as published, not a whole number of lots: the
order paths round down to whole lots themselves.

A fresh install picks these up from data/qtyfreeze.csv, but the startup hook
only seeds an empty table, so an existing install would keep the October limits
forever, and the exchange rejects every order above the new ones. This
migration updates the NFO rows in place.

It only changes a row that still holds a value OpenAlgo shipped or NSE
published before this revision: the October limits above, and the values NSE
published from November 2025 to September 2026, which were NIFTY 1,800;
BANKNIFTY 600 or 900 (900 from 1 April to 30 June 2026); FINNIFTY 1,200 or
1,800 (1,200, the seed OpenAlgo shipped until October); MIDCPNIFTY 2,800;
NIFTYNXT50 600; NIFTYFPI 8,500. Most of those equal the new limits, so a row
still holding one is already current. A row an admin set to anything else on
the Freeze Quantities page is left alone and reported. A missing NIFTYFPI row is
added, because no release before October seeded one; a missing row for the
other five was deleted by an admin, so it stays deleted.

**It replaces migrate_qty_freeze_oct_2026.py rather than running after it.**
migrate_all.py runs every script on every upgrade, and the October script
treated 1,800 as a stale NIFTY limit to raise to 3,510. Left in the list it
would raise these rows on each upgrade, one script before this one lowered them
again, and an upgrade stopped between the two would leave limits the exchange
rejects. This script covers every value the October one replaced, so an install
that never ran it lands in the same place.

An empty or missing table is left alone: the app seeds it from the CSV, which
already carries the new limits, and a single inserted row would stop that.

The running app reads the table into memory at startup, so the new limits
apply once the app restarts (the update scripts restart it after migrating).

Idempotent, and safe to re-run.

Usage:
    cd upgrade
    uv run migrate_qty_freeze_nov_2026.py
    uv run migrate_qty_freeze_nov_2026.py --status
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
from sqlalchemy import create_engine, inspect  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

TABLE = "qty_freeze"
EXCHANGE = "NFO"

#: Underlying -> (new freeze limit, values it may hold that this revision replaces).
#: None in the old values means the row may be absent and is then added.
REVISION = {
    "NIFTY": (1800, {3510}),
    "BANKNIFTY": (900, {600, 1440}),
    "FINNIFTY": (1800, {1200, 3240}),
    "MIDCPNIFTY": (2800, {5760}),
    "NIFTYNXT50": (600, {1125}),
    "NIFTYFPI": (8500, {53900, None}),
}


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


def plan(engine):
    """What this migration would do to each underlying.

    Args:
        engine: An engine bound to the target database.

    Returns:
        list[tuple[str, int | None, int, str]] | None: One (symbol, current,
        new, action) per underlying, where action is "update", "insert",
        "current" (already at the new limit) or "custom" (left alone). None
        when the table is missing or empty and the app will seed it.
    """
    if TABLE not in set(inspect(engine).get_table_names()):
        return None

    from database.qty_freeze_db import QtyFreeze

    with Session(engine) as session:
        if session.query(QtyFreeze).count() == 0:
            return None
        rows = (
            session.query(QtyFreeze)
            .filter(QtyFreeze.exchange == EXCHANGE, QtyFreeze.symbol.in_(list(REVISION)))
            .all()
        )
        current = {row.symbol: row.freeze_qty for row in rows}

    steps = []
    for symbol, (new, replaces) in REVISION.items():
        value = current.get(symbol)
        if value == new:
            action = "current"
        elif value in replaces:
            action = "insert" if value is None else "update"
        else:
            action = "custom"
        steps.append((symbol, value, new, action))
    return steps


def describe(step):
    """One report line for a planned step.

    Args:
        step: A (symbol, current, new, action) tuple from plan().

    Returns:
        str: The line.
    """
    symbol, value, new, action = step
    shown = "absent" if value is None else str(value)
    if action == "update":
        return f"  {symbol:<11} {shown:>7} -> {new}"
    if action == "insert":
        return f"  {symbol:<11} {shown:>7} -> {new} (row added)"
    if action == "current":
        return f"  {symbol:<11} {shown:>7}    already at the new limit"
    return f"  {symbol:<11} {shown:>7}    set by an admin, left alone (NSE limit is {new})"


def status(engine):
    """Report what would change, without changing anything.

    Args:
        engine: An engine bound to the target database, or None when the
            database file does not exist yet.

    Returns:
        bool: True when the report was produced.
    """
    print("NSE index freeze limits (2 November 2026) status")
    print("-" * 62)
    steps = plan(engine) if engine is not None else None
    if steps is None:
        print("No freeze quantities stored yet. The app seeds them from")
        print("data/qtyfreeze.csv, which already has the new limits.")
        return True
    for step in steps:
        print(describe(step))
    pending = sum(1 for step in steps if step[3] in ("update", "insert"))
    print(f"Would change {pending} row(s)." if pending else "Nothing to change.")
    return True


def apply(engine):
    """Write the new limits to every row this revision replaces.

    Args:
        engine: An engine bound to the target database.

    Returns:
        bool: True on success.
    """
    try:
        steps = plan(engine)
    except Exception as exc:
        print(f"  [FAIL] Could not read the freeze quantities: {type(exc).__name__}: {exc}")
        return False

    if steps is None:
        print("  No freeze quantities stored yet. The app seeds them from")
        print("  data/qtyfreeze.csv, which already has the new limits.")
        return True

    pending = [step for step in steps if step[3] in ("update", "insert")]
    try:
        from database.qty_freeze_db import QtyFreeze

        with Session(engine) as session:
            for symbol, value, new, action in pending:
                if action == "insert":
                    session.add(QtyFreeze(exchange=EXCHANGE, symbol=symbol, freeze_qty=new))
                    continue
                # Guarded on the old value, so a change an admin made since
                # plan() read the row is not overwritten.
                session.query(QtyFreeze).filter(
                    QtyFreeze.exchange == EXCHANGE,
                    QtyFreeze.symbol == symbol,
                    QtyFreeze.freeze_qty == value,
                ).update({QtyFreeze.freeze_qty: new}, synchronize_session=False)
            session.commit()
    except Exception as exc:
        print(f"  [FAIL] Could not update the freeze quantities: {type(exc).__name__}: {exc}")
        return False

    for step in steps:
        print(describe(step))
    if pending:
        print(f"  [OK] Updated {len(pending)} row(s). Restart OpenAlgo to apply them.")
    else:
        print("  [OK] Nothing to change.")
    return True


def main():
    """Entry point.

    Returns:
        int: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(
        description="Set the NSE index freeze limits to the 2 November 2026 values"
    )
    parser.add_argument(
        "--status", action="store_true", help="Report what would change without changing it"
    )
    args = parser.parse_args()

    db_url = get_database_url()
    # database.qty_freeze_db builds its own engine from DATABASE_URL at import;
    # unset, that import fails. Nothing is written through that engine.
    os.environ.setdefault("DATABASE_URL", db_url)
    path = sqlite_file(db_url)
    if path is not None and not os.path.exists(path):
        # Nothing to migrate, and connecting would create an empty file.
        return 0 if status(None) else 1

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        if args.status:
            return 0 if status(engine) else 1
        print("=" * 62)
        print("Migration: NSE index freeze limits from 2 November 2026")
        print("=" * 62)
        ok = apply(engine)
        print("-" * 62)
        print("Migration complete." if ok else "Migration failed. See the messages above.")
        return 0 if ok else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
