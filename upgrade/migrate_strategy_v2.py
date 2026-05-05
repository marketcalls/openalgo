#!/usr/bin/env python3
"""Strategy v2 — Phase 0 / Phase 7 migration.

Phase 0 (this version):
    Just creates the v2 tables in db/openalgo.db. No data conversion. The
    actual table creation is also performed by app.py at startup via
    database/strategy_v2_db.py:init_db(); this script exists so a migration
    run in CI / install scripts produces a stable surface.

Phase 7 (later):
    Convert v1 strategies + strategy_symbol_mappings rows into 1-leg v2
    strategies. The conversion logic stub is present below as
    `_phase7_convert_v1_strategies(...)` — disabled for now.

This migration is idempotent — safe to run multiple times.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ensure_tables() -> None:
    """Create the v2 tables. Idempotent via SQLAlchemy create_all."""
    from database.strategy_v2_db import init_db

    init_db()
    print("  [OK] Strategy v2 tables ensured")


def _phase7_convert_v1_strategies() -> None:
    """Convert legacy v1 strategies into 1-leg v2 strategies.

    Disabled in Phase 0. Will be enabled in Phase 7 once the leg builder,
    execution service, and v2 webhook router are in place.

    Conversion plan (for reference; implemented in Phase 7):
      For each row in v1 `strategies`:
        if a v2 strategy with same webhook_id exists → skip
        else → create strategies_v2 row carrying webhook_id, name, user_id,
                  platform, times, mode='live', signing_method='NONE'
              for each v1 strategy_symbol_mappings row → create strategy_legs
                  row with segment inferred from exchange (NSE/BSE → CASH,
                  NFO/BFO → FUT or OPT based on symbol pattern)
              create empty strategy_risk_config row
    """
    print("  [SKIP] v1 → v2 conversion is disabled in Phase 0")


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
