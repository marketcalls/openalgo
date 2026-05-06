#!/usr/bin/env python3
"""Strategy v2 — Phase 13: per-leg active-run scoping for CASH routing.

CASH and F&O have different webhook semantics:
  CASH = independent symbols. Each webhook targets one leg; multiple
         symbols in the same strategy can run concurrently.
  F&O  = pack (iron condor / spread / hedge pair). One webhook fires
         all legs together; only one active run per strategy.

Today's `idx_strategy_runs_active` is a unique partial index on
`(strategy_id)` filtered to active states. That blocks two webhooks
for different symbols of the same CASH strategy from running
concurrently — the second 'BUY RELIANCE' webhook gets rejected as a
duplicate of the open 'BUY TCS' run.

Schema changes:
  1. Add `strategy_runs.leg_id INTEGER NULL`. NULL means "strategy-
     level pack run" (F&O); a value means "leg-scoped run" (CASH).
  2. Replace the unique partial index. New one is keyed on
     (strategy_id, IFNULL(leg_id, 0)):
       - F&O runs with leg_id=NULL collapse to (strategy_id, 0) —
         only one active pack run at a time, same as before.
       - CASH runs with leg_id=N enforce per-leg uniqueness — at
         most one active run per (strategy, leg), but parallel
         legs run independently.

Idempotent — checks schema before mutating.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


_NEW_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_strategy_runs_active_per_leg "
    "ON strategy_runs (strategy_id, IFNULL(leg_id, 0)) "
    "WHERE state IN ('ARMED','ENTERING','IN_TRADE','EXITING')"
)


def _column_exists(conn, table: str, column: str) -> bool:
    from sqlalchemy import text

    rows = conn.execute(
        text(f"SELECT name FROM pragma_table_info('{table}')")
    ).fetchall()
    return any(r[0] == column for r in rows)


def _index_exists(conn, name: str) -> bool:
    from sqlalchemy import text

    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='index' AND name=:n"),
        {"n": name},
    ).fetchone()
    return bool(row)


def main() -> int:
    print("=" * 60)
    print("Strategy v2 - Phase 13 (per-leg active-run scoping)")
    print("=" * 60)
    try:
        from sqlalchemy import inspect, text

        from database.strategy_v2_db import engine

        if "strategy_runs" not in set(inspect(engine).get_table_names()):
            print("  [SKIP] strategy_runs table not present; Phase 0 will create it")
            return 0

        with engine.begin() as conn:
            if _column_exists(conn, "strategy_runs", "leg_id"):
                print("  [SKIP] strategy_runs.leg_id already present")
            else:
                conn.execute(text(
                    "ALTER TABLE strategy_runs ADD COLUMN leg_id INTEGER"
                ))
                print("  [OK]   added strategy_runs.leg_id")

            if _index_exists(conn, "idx_strategy_runs_active"):
                conn.execute(text("DROP INDEX idx_strategy_runs_active"))
                print("  [OK]   dropped old idx_strategy_runs_active")
            else:
                print("  [SKIP] idx_strategy_runs_active not present")

            if _index_exists(conn, "idx_strategy_runs_active_per_leg"):
                print("  [SKIP] idx_strategy_runs_active_per_leg already present")
            else:
                conn.execute(text(_NEW_INDEX))
                print("  [OK]   created idx_strategy_runs_active_per_leg")

        print("=" * 60)
        print("Phase 13 schema migration completed successfully")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
