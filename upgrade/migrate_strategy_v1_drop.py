#!/usr/bin/env python3
"""Strategy v1 — Phase 8 finalization. Drop legacy v1 tables.

This migration runs AFTER `migrate_strategy_v2.py` has converted every
v1 strategy into a v2 strategy. It performs a safety check first: if any
v1 webhook_id has no matching v2 row, the drop is refused — the operator
must investigate (likely a partial conversion that hit a data error).

Tables dropped:
  - strategy_symbol_mappings (FK -> strategies.id, drop first)
  - strategies

A DB snapshot is taken before any DDL. Idempotent — safe to re-run after
the tables are gone.

Why a separate migration (not folded into migrate_strategy_v2.py):
  - migrate_strategy_v2.py is "ensure tables + best-effort convert" —
    safe to run on any version, including pre-Phase-7. Mixing in a
    destructive DROP would make the converter unsafe to retry on
    failure.
  - migrate_all.py runs migrations in order. Putting the converter
    first and the drop second guarantees no row is destroyed before
    being mirrored into v2.
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _resolve_db_path() -> str | None:
    """Return the on-disk path of db/openalgo.db, or None if not SQLite."""
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("sqlite:"):
        return None
    path = url.replace("sqlite:///", "", 1)
    if not os.path.isabs(path):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path
        )
    return path if os.path.exists(path) else None


def _snapshot_db_once(reason: str) -> None:
    """Copy db/openalgo.db to db/openalgo.db.bak.<date>. No-op on
    non-SQLite or when today's snapshot already exists."""
    src = _resolve_db_path()
    if not src:
        print("  [SKIP] DB snapshot — non-SQLite or path not found")
        return
    today = _dt.date.today().isoformat()
    dst = f"{src}.bak.{today}"
    if os.path.exists(dst):
        print(f"  [SKIP] DB snapshot — today's backup already at {dst}")
        return
    shutil.copy2(src, dst)
    print(f"  [OK] DB snapshot ({reason}) -> {dst}")


def _drop_v1_tables() -> None:
    from sqlalchemy import inspect, text

    from database.strategy_v2_db import db_session as v2_session
    from database.strategy_v2_db import engine as v2_engine

    existing = set(inspect(v2_engine).get_table_names())

    if "strategies" not in existing and "strategy_symbol_mappings" not in existing:
        print("  [OK] v1 tables already dropped; nothing to do")
        return

    # Safety gate: every v1 strategy must have a v2 counterpart.
    if "strategies" in existing:
        with v2_engine.connect() as conn:
            v1_webhooks = {
                r[0]
                for r in conn.execute(text("SELECT webhook_id FROM strategies"))
            }
        if v1_webhooks:
            from database.strategy_v2_db import StrategyV2

            v2_webhooks = {
                wh
                for (wh,) in v2_session.query(StrategyV2.webhook_id).all()
            }
            unconverted = v1_webhooks - v2_webhooks
            if unconverted:
                # Keep the message generic — webhook_ids are sensitive.
                raise RuntimeError(
                    f"Refusing to drop v1 tables: {len(unconverted)} v1 "
                    "strategy webhook_id(s) have no v2 counterpart. "
                    "Run `uv run upgrade/migrate_strategy_v2.py` first, "
                    "investigate any [FAIL] rows in its output, then re-run "
                    "this migration."
                )
            print(f"  [OK] All {len(v1_webhooks)} v1 strategies confirmed "
                  "present in v2; safe to drop")
        else:
            print("  [OK] v1 'strategies' is empty; safe to drop")

    _snapshot_db_once(reason="dropping v1 strategy tables")

    # Drop child first (FK), then parent. SQLite tolerates missing tables
    # via IF EXISTS, but be explicit about the order anyway.
    with v2_engine.begin() as conn:
        if "strategy_symbol_mappings" in existing:
            conn.execute(text("DROP TABLE IF EXISTS strategy_symbol_mappings"))
            print("  [OK] Dropped table 'strategy_symbol_mappings'")
        if "strategies" in existing:
            conn.execute(text("DROP TABLE IF EXISTS strategies"))
            print("  [OK] Dropped table 'strategies'")


def main() -> int:
    print("=" * 60)
    print("Strategy v1 -> drop legacy tables")
    print("=" * 60)
    try:
        _drop_v1_tables()
        print("=" * 60)
        print("Strategy v1 cleanup completed successfully")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
