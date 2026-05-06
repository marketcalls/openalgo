#!/usr/bin/env python3
"""Strategy v2 — Phase 9 schema additions.

Adds four new columns to support the Phase 9 builder UX:

  strategies_v2:
    segment       VARCHAR(10) NOT NULL DEFAULT 'CASH'   - CASH | INDEX_FO
    exit_date     VARCHAR(10)                            - YYYY-MM-DD (positional)
    run_forever   BOOLEAN     NOT NULL DEFAULT 0         - positional, mutually
                                                          exclusive with exit_date

  strategy_legs:
    exchange_cash VARCHAR(15)                            - per-leg exchange for
                                                          CASH legs (was hardcoded
                                                          to NSE by the resolver)

  strategies_v2.end_time was originally NOT NULL. SQLite cannot relax
  NOT NULL via a single ALTER COLUMN, so we leave the existing column
  alone — every existing row already has a value (the form enforced it).
  New positional rows that omit end_time still have it stamped to a
  sentinel ('00:00') by the marshmallow layer to satisfy the constraint.

All additions are pure ADD COLUMN — no data rewrite, no FK changes, safe
on a 150K-user production fleet. Idempotent via inspect().get_columns().
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


def _existing_columns(conn, table: str) -> set:
    from sqlalchemy import text

    rows = conn.execute(
        text(f"SELECT name FROM pragma_table_info('{table}')")
    ).fetchall()
    return {r[0] for r in rows}


def _add_column_if_missing(conn, table: str, column_name: str, ddl: str) -> bool:
    """Run ALTER TABLE ADD COLUMN. Returns True if the column was added."""
    from sqlalchemy import text

    cols = _existing_columns(conn, table)
    if column_name in cols:
        print(f"  [SKIP] {table}.{column_name} already present")
        return False
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
    print(f"  [OK]   added {table}.{column_name}")
    return True


def _ensure_v2_tables_exist(conn) -> bool:
    """Phase 9 only adds columns to tables created by the Phase 0 migration.
    On a *brand new* install (no v2 tables yet), Phase 9's ALTERs would
    fail with 'no such table'. Detect that and bail cleanly — the Phase 0
    migration registered before us in MIGRATIONS will handle creation, and
    the SQLAlchemy model already includes our columns so the table comes
    up correct. Returns True if we should proceed."""
    from sqlalchemy import text

    rows = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name IN "
             "('strategies_v2', 'strategy_legs')")
    ).fetchall()
    return len(rows) >= 2


def main() -> int:
    print("=" * 60)
    print("Strategy v2 — Phase 9 schema additions")
    print("=" * 60)
    try:
        from database.strategy_v2_db import engine

        with engine.begin() as conn:
            if not _ensure_v2_tables_exist(conn):
                print("  [SKIP] v2 tables not present; Phase 0 will create them")
                print("=" * 60)
                return 0

            _add_column_if_missing(
                conn,
                "strategies_v2",
                "segment",
                "segment VARCHAR(10) NOT NULL DEFAULT 'CASH'",
            )
            _add_column_if_missing(
                conn,
                "strategies_v2",
                "exit_date",
                "exit_date VARCHAR(10)",
            )
            _add_column_if_missing(
                conn,
                "strategies_v2",
                "run_forever",
                "run_forever BOOLEAN NOT NULL DEFAULT 0",
            )
            _add_column_if_missing(
                conn,
                "strategy_legs",
                "exchange_cash",
                "exchange_cash VARCHAR(15)",
            )
        print("=" * 60)
        print("Phase 9 schema migration completed successfully")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
