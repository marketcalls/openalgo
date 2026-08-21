#!/usr/bin/env python
"""
Sandbox GTT + CAS Close Migration Script for OpenAlgo

Covers three schema changes that ship together with sandbox GTT support:

1. ``sandbox_gtt_legs.trigger_direction`` - which way the market must move for
   a leg to fire. Direction is a property of the trigger's role, not of the
   leg's action: ``triggerprice_sl`` sits below the last price and fires on a
   fall, ``triggerprice_tg`` sits above and fires on a rise. Existing legs are
   backfilled from their trigger price relative to the price recorded when the
   GTT was placed, rather than all defaulting to one direction - a target leg
   labelled "below" would fire on the wrong side.

2. ``sandbox_orders.gtt_leg_id`` plus a unique index - the durable link from a
   child order back to the GTT leg that placed it, written in the same INSERT
   as the order. Recovery reads this rather than a flag set in a later commit,
   so a process that dies between the two cannot re-arm a GTT that already
   fired. The index is unique so a replayed claim cannot create a second order.

3. NFO/BFO market close 15:30 -> 15:40. SEBI's Closing Auction Session
   (circular HO/47/11/11(3)2025-MRD-POD2/I/2765/2026, effective 2026-08-03)
   pauses continuous trading in the equity cash segment at 15:15 and derives
   its close by auction, while the derivatives segment keeps trading to roughly
   15:40. Only rows still holding the old 15:30 close are moved, so an
   administrator who has set their own timing is not overwritten.

All three are also applied automatically at startup, so an installation that
simply restarts is upgraded. This script exists so the change can be applied
and inspected on its own, the way the rest of the upgrade tooling works.

Every step is idempotent: running it twice changes nothing the second time.

Usage:
    cd upgrade
    uv run migrate_gtt_sandbox.py           # Apply migration
    uv run migrate_gtt_sandbox.py --status  # Check status without changing

Migration: 006
Created: 2026-08-04
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Register the app's SQLite pragmas on this process's engines, so a migration
# waits the same 15s for a write lock the running app does instead of the
# sqlite3 default of 5s (GitHub issue #1726).
import _pragmas  # noqa: F401,E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

load_dotenv()

SANDBOX_DATABASE_URL = os.getenv("SANDBOX_DATABASE_URL", "sqlite:///db/sandbox.db")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")

OLD_FO_CLOSE_MS = (15 * 3600 + 30 * 60) * 1000  # 15:30
NEW_FO_CLOSE_MS = (15 * 3600 + 40 * 60) * 1000  # 15:40
FO_EXCHANGES = ("NFO", "BFO")


def _columns(conn, table):
    """Column names of ``table``, or an empty set when it does not exist."""
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}


def _table_exists(conn, table):
    return bool(
        conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table},
        ).fetchone()
    )


def check_status():
    """Report what is already applied, without changing anything."""
    print("\nSandbox GTT + CAS close migration status\n" + "=" * 44)
    applied = True

    sandbox = create_engine(SANDBOX_DATABASE_URL)
    with sandbox.connect() as conn:
        if not _table_exists(conn, "sandbox_gtt_legs"):
            print("  sandbox_gtt_legs      : table absent (created on first startup)")
        else:
            has = "trigger_direction" in _columns(conn, "sandbox_gtt_legs")
            print(f"  trigger_direction     : {'present' if has else 'MISSING'}")
            applied = applied and has

        if not _table_exists(conn, "sandbox_orders"):
            print("  sandbox_orders        : table absent (created on first startup)")
        else:
            has = "gtt_leg_id" in _columns(conn, "sandbox_orders")
            print(f"  gtt_leg_id            : {'present' if has else 'MISSING'}")
            applied = applied and has

    main = create_engine(DATABASE_URL)
    with main.connect() as conn:
        if not _table_exists(conn, "market_timings"):
            print("  market_timings        : table absent (seeded on first startup)")
        else:
            rows = conn.execute(
                text(
                    "SELECT exchange_code, end_time, end_offset FROM market_timings "
                    "WHERE exchange_code IN ('NFO','BFO') ORDER BY exchange_code"
                )
            ).fetchall()
            for code, end_time, end_offset in rows:
                state = "old 15:30" if int(end_offset or 0) == OLD_FO_CLOSE_MS else "ok"
                print(f"  {code} close            : {end_time} ({state})")
                applied = applied and int(end_offset or 0) != OLD_FO_CLOSE_MS

    print("=" * 44)
    print("All changes applied." if applied else "Migration needed.")
    return applied


def migrate_sandbox_columns():
    """Add the two sandbox columns and backfill trigger_direction."""
    engine = create_engine(SANDBOX_DATABASE_URL)
    changed = False

    with engine.connect() as conn:
        if _table_exists(conn, "sandbox_gtt_legs"):
            if "trigger_direction" not in _columns(conn, "sandbox_gtt_legs"):
                conn.execute(
                    text(
                        "ALTER TABLE sandbox_gtt_legs ADD COLUMN trigger_direction "
                        "VARCHAR(5) NOT NULL DEFAULT 'below'"
                    )
                )
                # Backfilled from the data, not left at the column default: a
                # leg whose trigger sits above the price recorded when the GTT
                # was placed is a rise trigger, and calling it a fall trigger
                # would fire it on the wrong side.
                result = conn.execute(
                    text(
                        "UPDATE sandbox_gtt_legs SET trigger_direction = 'above' "
                        "WHERE gtt_id IN (SELECT gtt_id FROM sandbox_gtt) "
                        "AND trigger_price > ("
                        "  SELECT last_price FROM sandbox_gtt "
                        "  WHERE sandbox_gtt.gtt_id = sandbox_gtt_legs.gtt_id)"
                    )
                )
                conn.commit()
                changed = True
                print(
                    f"  Added trigger_direction; backfilled {result.rowcount} "
                    "leg(s) as rise triggers"
                )
            else:
                print("  trigger_direction already present")

        if _table_exists(conn, "sandbox_orders"):
            if "gtt_leg_id" not in _columns(conn, "sandbox_orders"):
                conn.execute(text("ALTER TABLE sandbox_orders ADD COLUMN gtt_leg_id INTEGER"))
                # SQLite cannot add a UNIQUE column by ALTER, so the constraint
                # is a partial index: every non-GTT order leaves this NULL and
                # many NULLs must remain allowed.
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sandbox_orders_gtt_leg "
                        "ON sandbox_orders(gtt_leg_id) WHERE gtt_leg_id IS NOT NULL"
                    )
                )
                conn.commit()
                changed = True
                print("  Added gtt_leg_id and its unique index")
            else:
                print("  gtt_leg_id already present")

    return changed


def migrate_fo_close():
    """Move the NFO/BFO close to 15:40, leaving customised rows alone."""
    engine = create_engine(DATABASE_URL)
    changed = False

    with engine.connect() as conn:
        if not _table_exists(conn, "market_timings"):
            print("  market_timings absent; it is seeded with 15:40 on first startup")
            return False

        for code in FO_EXCHANGES:
            row = conn.execute(
                text(
                    "SELECT end_offset FROM market_timings WHERE exchange_code = :c"
                ),
                {"c": code},
            ).fetchone()
            if row is None:
                print(f"  {code}: no row; seeded on first startup")
                continue
            if int(row[0] or 0) != OLD_FO_CLOSE_MS:
                print(f"  {code}: not on the old 15:30 close, left unchanged")
                continue
            conn.execute(
                text(
                    "UPDATE market_timings SET end_time = '15:40', end_offset = :e "
                    "WHERE exchange_code = :c AND end_offset = :old"
                ),
                {"e": NEW_FO_CLOSE_MS, "c": code, "old": OLD_FO_CLOSE_MS},
            )
            conn.commit()
            changed = True
            print(f"  {code}: close moved 15:30 -> 15:40")

    return changed


def main():
    parser = argparse.ArgumentParser(description="Sandbox GTT + CAS close migration")
    parser.add_argument(
        "--status", action="store_true", help="Report status without changing anything"
    )
    args = parser.parse_args()

    if args.status:
        return check_status()

    print("\nSandbox GTT + CAS close migration\n" + "=" * 44)
    print(f"  Sandbox DB : {SANDBOX_DATABASE_URL}")
    print(f"  Main DB    : {DATABASE_URL}\n")

    try:
        a = migrate_sandbox_columns()
        b = migrate_fo_close()
    except Exception as e:
        print(f"\nMigration failed: {e}")
        return False

    print("=" * 44)
    print("Migration complete." if (a or b) else "Nothing to do; already up to date.")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
