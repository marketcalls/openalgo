#!/usr/bin/env python3
"""Strategy v2 — Phase 0 / Phase 7 migration.

Phase 0: ensure the v2 tables exist (additive, no data conversion).
Phase 7: convert legacy v1 strategies + symbol_mappings into 1-leg v2
    strategies. Webhook IDs are preserved so external integrations keep
    working without URL changes.

Idempotent — safe to run any number of times.

Conversion rules (Phase 7):
  For each row in v1 `strategies`:
    - If a `strategies_v2` row already has the same webhook_id -> skip
    - Else create a `strategies_v2` row carrying:
        webhook_id (verbatim), name, user_id, platform, is_intraday,
        start_time, end_time, squareoff_time, mode='live',
        webhook_signing_method='NONE' (v1 had no signing), state='DRAFT',
        is_active=False (admin must explicitly arm post-conversion)
    - For each `strategy_symbol_mappings` row tied to that v1 strategy,
      create a `strategy_legs` row with segment='CASH' (v1 only ever
      modeled cash), product=mapping.product_type, position='B',
      symbol_cash=mapping.symbol, qty=mapping.quantity, leg_index=N
    - Create an empty `strategy_risk_config` row so per-strategy RMS
      defaults to "all knobs disabled"

Backup: before any conversion, snapshot db/openalgo.db to
    db/openalgo.db.bak.<YYYY-MM-DD>. Skipped on subsequent runs that have
    nothing to convert (avoids dumping snapshots indefinitely).
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import sys

# Repo root on sys.path so we can import database.* modules.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env BEFORE any DB import — engines build at import time from
# os.getenv("DATABASE_URL"). This is the same pattern used by every other
# migration script (CLAUDE.md "Migration script requirements" #3).
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv ships in the project deps; if it's missing, fail loud
    # below when DATABASE_URL turns up empty.
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_tables() -> None:
    """Create the v2 tables. Idempotent via SQLAlchemy create_all."""
    from database.strategy_v2_db import init_db

    init_db()
    print("  [OK] Strategy v2 tables ensured")


def _resolve_db_path() -> str | None:
    """Return the on-disk path of db/openalgo.db, or None if not SQLite.

    The migration only knows how to snapshot SQLite. For Postgres deploys
    the user has their own backup tooling; we skip silently rather than
    pretending to back up.
    """
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("sqlite:"):
        return None
    # Strip 'sqlite:///' or 'sqlite:////' prefix to get filesystem path.
    # SQLAlchemy supports 3-slash (relative) and 4-slash (absolute) forms.
    path = url.replace("sqlite:///", "", 1)
    if not os.path.isabs(path):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path
        )
    return path if os.path.exists(path) else None


def _snapshot_db_once(reason: str) -> None:
    """Copy db/openalgo.db to db/openalgo.db.bak.<date>. No-op if the
    backup for today already exists or DB is non-SQLite."""
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


def _phase7_convert_v1_strategies() -> None:
    """Convert v1 -> v2. See module docstring for the rule set.

    The v1 ORM module (database/strategy_db.py) is removed in Phase 8, so
    we read the legacy `strategies` and `strategy_symbol_mappings` tables
    directly via the SQLAlchemy engine. This keeps the converter working
    for users who:
      - have existing v1 data, AND
      - pull a release that no longer ships the v1 ORM

    Reading via raw SQL also avoids triggering v1 SQLAlchemy mapper
    registration on engines that no longer have those models bound.
    """
    from sqlalchemy import inspect, text

    from database.strategy_v2_db import (
        StrategyLeg,
        StrategyRiskConfig,
        StrategyV2,
        db_session as v2_session,
        engine as v2_engine,
    )

    # Bail out cleanly if the v1 tables don't exist (fresh install, or v1
    # has already been dropped by migrate_strategy_v1_drop.py).
    try:
        existing = set(inspect(v2_engine).get_table_names())
    except Exception as exc:  # pragma: no cover — defensive
        print(f"  [SKIP] DB inspection failed ({exc.__class__.__name__}: {exc})")
        return

    if "strategies" not in existing:
        print("  [SKIP] v1 'strategies' table not present; nothing to convert")
        return

    # Read v1 rows via raw SQL — no ORM dependency on the deleted v1 module.
    with v2_engine.connect() as conn:
        v1_rows = conn.execute(
            text(
                "SELECT id, name, webhook_id, user_id, platform, is_intraday, "
                "       start_time, end_time, squareoff_time "
                "FROM strategies"
            )
        ).mappings().all()

    if not v1_rows:
        print("  [OK] No v1 strategies present; nothing to convert")
        return

    existing_v2_webhooks = {
        wh for (wh,) in v2_session.query(StrategyV2.webhook_id).all()
    }
    pending = [r for r in v1_rows if r["webhook_id"] not in existing_v2_webhooks]
    skipped = len(v1_rows) - len(pending)

    print(
        f"  [INFO] v1 strategies: {len(v1_rows)}, "
        f"already-converted: {skipped}, pending: {len(pending)}"
    )

    if not pending:
        print("  [OK] All v1 strategies already have v2 counterparts; nothing to do")
        return

    # Pre-fetch every mapping for the pending v1 strategies in a single
    # query — avoids N round-trips inside the conversion loop.
    pending_ids = [r["id"] for r in pending]
    placeholders = ",".join(f":id_{i}" for i in range(len(pending_ids)))
    params = {f"id_{i}": v for i, v in enumerate(pending_ids)}
    with v2_engine.connect() as conn:
        mapping_rows = conn.execute(
            text(
                "SELECT id, strategy_id, symbol, exchange, quantity, product_type "
                "FROM strategy_symbol_mappings "
                f"WHERE strategy_id IN ({placeholders}) "
                "ORDER BY strategy_id, id"
            ),
            params,
        ).mappings().all()

    mappings_by_strategy: dict[int, list] = {}
    for m in mapping_rows:
        mappings_by_strategy.setdefault(m["strategy_id"], []).append(m)

    # We're about to mutate -> snapshot first.
    _snapshot_db_once(reason=f"converting {len(pending)} v1 strategies")

    converted = 0
    legs_created = 0
    failed = 0

    for v1 in pending:
        try:
            # Re-check inside the loop: another runner could have inserted
            # the row concurrently. Keeps the migration safe under retries
            # from migrate_all.py orchestration.
            already = (
                v2_session.query(StrategyV2.id)
                .filter(StrategyV2.webhook_id == v1["webhook_id"])
                .first()
            )
            if already:
                continue

            v2 = StrategyV2(
                name=(v1["name"] or "")[:80] or f"Migrated {v1['id']}",
                webhook_id=v1["webhook_id"],
                user_id=v1["user_id"],
                platform=v1["platform"] or "tradingview",
                is_intraday=bool(v1["is_intraday"]),
                start_time=v1["start_time"] or "09:15",
                end_time=v1["end_time"] or "15:30",
                squareoff_time=v1["squareoff_time"],
                state="DRAFT",
                is_active=False,
                mode="live",
                webhook_signing_method="NONE",
            )
            v2_session.add(v2)
            v2_session.flush()  # populate v2.id for FK use below

            mappings = mappings_by_strategy.get(v1["id"], [])
            for idx, m in enumerate(mappings, start=1):
                leg = StrategyLeg(
                    strategy_id=v2.id,
                    leg_index=idx,
                    segment="CASH",
                    position="B",
                    product=(m["product_type"] or "MIS")[:10],
                    symbol_cash=(m["symbol"] or "")[:50],
                    qty=int(m["quantity"] or 0),
                )
                v2_session.add(leg)
                legs_created += 1

            # Empty risk config row so per-strategy RMS knobs default to
            # disabled. The schema defaults handle this; we just need a
            # row for the FK relationship to attach to.
            v2_session.add(StrategyRiskConfig(strategy_id=v2.id))

            v2_session.commit()
            converted += 1
            print(
                f"  [OK] Converted v1#{v1['id']} '{v1['name']}' "
                f"-> v2#{v2.id} ({len(mappings)} leg(s))"
            )
        except Exception as exc:
            v2_session.rollback()
            failed += 1
            print(
                f"  [FAIL] v1#{v1['id']} '{v1['name']}': "
                f"{exc.__class__.__name__}: {exc}"
            )

    print(
        f"  [DONE] converted={converted} legs={legs_created} "
        f"skipped={skipped} failed={failed}"
    )

    if failed:
        # Surface failures as a non-zero exit so migrate_all.py aborts the
        # remaining migrations. The v2 rows that *did* commit stay; an
        # operator can re-run after fixing the offending v1 rows.
        raise RuntimeError(
            f"{failed} v1 strategy/strategies failed to convert; see log above"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 60)
    print("Strategy v2 Migration")
    print("=" * 60)
    try:
        _ensure_tables()
        _phase7_convert_v1_strategies()
        print("=" * 60)
        print("Strategy v2 migration completed successfully")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
