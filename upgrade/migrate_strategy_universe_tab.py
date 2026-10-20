#!/usr/bin/env python3
"""
Migration: normalize sm_strategy.universe_tab

The universe tab says which instrument family a strategy trades, and it is the
only thing that decides which segments its legs may use: cash appears on the
stocks tab alone, because an index has no cash instrument of its own and an MCX
commodity has no spot. Until now the column was validated as free text up to
thirty characters and every rule hanging off it lived in the browser, so a cash
leg on an index tab was accepted and refused only at run start.

The validator now checks the tab against the four known values and checks each
leg's segment against that tab. This script brings existing rows up to what the
validator will demand, so an operator is never locked out of editing a strategy
that saved cleanly under the old rules.

Nothing about what a strategy trades is changed. The tab is a grouping, not a
trading parameter: no symbol, expiry, strike, quantity, product or risk value is
touched. A row whose tab is already valid for its own legs is left exactly as it
is, including a row whose tab is broader than its legs need.

Where a row does have to move, the new tab is derived from what the row already
says rather than defaulted:

  a leg with segment "cash"          -> stocks_fno
  an MCX, NCDEX or NCO underlying    -> mcx
  a leg on a weekly expiry rank      -> weekly_monthly
  anything else                      -> monthly_only

This migration is idempotent - safe to run multiple times.

Usage:
    cd upgrade
    uv run migrate_strategy_universe_tab.py           # Apply migration
    uv run migrate_strategy_universe_tab.py --status  # Report without changing anything
"""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, PROJECT_ROOT)
# Register the app's SQLite pragmas on this process's engines, so a migration
# waits the same 15s for a write lock the running app does instead of the
# sqlite3 default of 5s (GitHub issue #1726).
import _pragmas  # noqa: F401,E402
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

TABLE = "sm_strategy"

#: The four the validator accepts, and which segments each one offers. Mirrors
#: UNIVERSE_TABS and TAB_SEGMENTS in blueprints/strategy_module.py.
TAB_SEGMENTS = {
    "weekly_monthly": {"futures", "options"},
    "monthly_only": {"futures", "options"},
    "stocks_fno": {"cash", "futures", "options"},
    "mcx": {"futures", "options"},
}

#: Exchanges whose underlying belongs to the commodity tab.
COMMODITY_EXCHANGES = {"MCX", "NCDEX", "NCO"}

#: Expiry ranks that only exist where an instrument lists weekly contracts.
WEEKLY_RANKS = {"weekly", "next_week"}


def resolve_sqlite_path(db_url):
    """Make a relative sqlite:/// path absolute against the project root.

    The documented invocation is `cd upgrade && uv run ...`, and DATABASE_URL is
    relative by default ("sqlite:///db/openalgo.db"). Left relative it resolves
    against the current directory, so running from upgrade/ would point at
    upgrade/db/openalgo.db, which SQLAlchemy creates empty on connect. The
    migration would then report success having read a database the app never
    opens.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return db_url
    path = db_url[len(prefix) :]
    if os.path.isabs(path):
        return db_url
    return prefix + os.path.join(PROJECT_ROOT, path).replace("\\", "/")


def get_database_url():
    """Read DATABASE_URL from the environment, with the project default."""
    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    return resolve_sqlite_path(os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db"))


def parse_legs(raw):
    """The legs column as a list, whatever the driver handed back.

    JSON columns come back decoded on some drivers and as text on others, and a
    row written before the column existed can be NULL. None of those is a
    reason to fail the migration: a row whose legs cannot be read simply has no
    segment to check, and is left alone.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def derive_tab(row):
    """The tab this strategy's own configuration says it belongs to."""
    legs = parse_legs(row["legs"])
    segments = {str(leg.get("segment") or "").lower() for leg in legs if isinstance(leg, dict)}

    # Cash is offered on one tab only, so a cash leg settles it outright.
    if "cash" in segments:
        return "stocks_fno"

    exchange = str(row["underlying_exchange"] or "").upper()
    if exchange in COMMODITY_EXCHANGES:
        return "mcx"

    ranks = {str(leg.get("expiry") or "").lower() for leg in legs if isinstance(leg, dict)}
    if ranks & WEEKLY_RANKS:
        return "weekly_monthly"
    return "monthly_only"


def needs_change(row):
    """The tab this row should carry, or None when it is already correct.

    A tab is correct when it is one of the four and it offers every segment the
    row's legs actually use. A row whose tab is valid but broader than it needs
    is left alone: narrowing it would be a preference, not a correction.
    """
    tab = str(row["universe_tab"] or "")
    allowed = TAB_SEGMENTS.get(tab)
    if allowed is None:
        return derive_tab(row)

    legs = parse_legs(row["legs"])
    segments = {str(leg.get("segment") or "").lower() for leg in legs if isinstance(leg, dict)}
    segments.discard("")
    if segments - allowed:
        return derive_tab(row)
    return None


def read_rows(engine):
    if TABLE not in set(inspect(engine).get_table_names()):
        return None
    sql = text(f"SELECT id, name, universe_tab, underlying_exchange, legs FROM {TABLE}")
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(sql).mappings()]


def plan(rows):
    """Every row that has to move, as (id, name, old tab, new tab)."""
    changes = []
    for row in rows:
        target = needs_change(row)
        if target and target != row["universe_tab"]:
            changes.append((row["id"], row["name"], row["universe_tab"], target))
    return changes


def show_status(engine):
    rows = read_rows(engine)
    if rows is None:
        print(f"  [SKIP] {TABLE} does not exist yet. Run migrate_strategy_module.py first.")
        return True
    changes = plan(rows)
    print(f"  {len(rows)} strategy row(s) present")
    if not changes:
        print("  [OK] Every universe_tab is already valid for its own legs")
        return True
    print(f"  [PENDING] {len(changes)} row(s) would be normalized:")
    for strategy_id, name, old, new in changes:
        print(f"    id={strategy_id} {name!r}: {old!r} -> {new!r}")
    return True


def apply_migration(engine):
    rows = read_rows(engine)
    if rows is None:
        print(f"  [SKIP] {TABLE} does not exist yet. Run migrate_strategy_module.py first.")
        return True
    changes = plan(rows)
    if not changes:
        print("  [OK] Every universe_tab is already valid for its own legs")
        return True

    sql = text(f"UPDATE {TABLE} SET universe_tab = :tab WHERE id = :id")
    try:
        with engine.begin() as connection:
            for strategy_id, _name, _old, new in changes:
                connection.execute(sql, {"tab": new, "id": strategy_id})
    except Exception as exc:
        print(f"  [FAIL] Could not normalize universe_tab: {exc}")
        return False

    for strategy_id, name, old, new in changes:
        print(f"  [OK] id={strategy_id} {name!r}: {old!r} -> {new!r}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Normalize sm_strategy.universe_tab")
    parser.add_argument(
        "--status", action="store_true", help="Report what would change without changing it"
    )
    args = parser.parse_args()

    print("Strategy module: universe_tab normalization")
    print("-" * 60)

    engine = create_engine(get_database_url(), poolclass=NullPool)
    try:
        ok = show_status(engine) if args.status else apply_migration(engine)
    finally:
        engine.dispose()

    print("-" * 60)
    print("Done" if ok else "Failed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
