#!/usr/bin/env python3
"""Strategy v2 — Phase 11: trading_mode column.

Adds the per-strategy trading direction selector that the v2 webhook
contract dispatches on:

  strategies_v2.trading_mode VARCHAR(10) NOT NULL DEFAULT 'LONG'

Values:
  LONG   — BUY enters long, SELL closes long
  SHORT  — SELL enters short, BUY closes short
  BOTH   — BUY/SELL with position_size>0 opens that direction;
           position_size=0 closes the opposite-direction position

Existing rows default to LONG (the safe choice — a webhook with
"action": "BUY" will keep behaving as it did before this migration).

Idempotent. Also normalizes any legacy 'LONG_ONLY' / 'SHORT_ONLY'
values an interim version of this migration may have written into
'LONG' / 'SHORT'.
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
    from sqlalchemy import text

    cols = _existing_columns(conn, table)
    if column_name in cols:
        return False
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
    return True


def main() -> int:
    print("=" * 60)
    print("Strategy v2 - Phase 11 (trading_mode)")
    print("=" * 60)
    try:
        from sqlalchemy import inspect, text

        from database.strategy_v2_db import engine

        if "strategies_v2" not in set(inspect(engine).get_table_names()):
            print("  [SKIP] strategies_v2 table not present; Phase 0 will create it")
            return 0

        with engine.begin() as conn:
            added = _add_column_if_missing(
                conn,
                "strategies_v2",
                "trading_mode",
                "trading_mode VARCHAR(10) NOT NULL DEFAULT 'LONG'",
            )
            if added:
                print("  [OK]   added strategies_v2.trading_mode")
            else:
                print("  [SKIP] strategies_v2.trading_mode already present")

            # Normalize any rows that an interim version of this
            # migration wrote with the longer 'LONG_ONLY' / 'SHORT_ONLY'
            # spelling.
            r1 = conn.execute(
                text(
                    "UPDATE strategies_v2 SET trading_mode='LONG' "
                    "WHERE trading_mode='LONG_ONLY'"
                )
            )
            r2 = conn.execute(
                text(
                    "UPDATE strategies_v2 SET trading_mode='SHORT' "
                    "WHERE trading_mode='SHORT_ONLY'"
                )
            )
            if r1.rowcount or r2.rowcount:
                print(
                    f"  [OK]   normalized trading_mode: "
                    f"LONG_ONLY->LONG ({r1.rowcount}), "
                    f"SHORT_ONLY->SHORT ({r2.rowcount})"
                )

        print("=" * 60)
        print("Phase 11 schema migration completed successfully")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
