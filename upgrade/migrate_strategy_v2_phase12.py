#!/usr/bin/env python3
"""Strategy v2 — Phase 12: relax strategies_v2.end_time to NULLABLE.

Phase 9 added segment / exit_date / run_forever for positional support
and the SQLAlchemy model marked end_time as nullable, but the original
strategies_v2 table was created with end_time NOT NULL — and SQLite
cannot toggle column nullability via ALTER COLUMN. The Phase 9
migration explicitly punted on this with a comment promising the
application layer would stamp a sentinel for positional rows; that
stamp was never wired in, so creating a positional strategy crashes
with `NOT NULL constraint failed: strategies_v2.end_time`.

Fix: recreate strategies_v2 using the canonical SQLite "rebuild" recipe
(CREATE new schema -> INSERT SELECT * -> DROP old -> RENAME). All
existing rows + columns + the unique index on webhook_id are preserved.
CHECK constraints are re-applied to match the SQLAlchemy model.

Idempotent — checks current end_time nullability before doing the
rebuild.
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


_REBUILD_DDL = """
CREATE TABLE strategies_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(80) NOT NULL,
    webhook_id VARCHAR(36) NOT NULL UNIQUE,
    user_id VARCHAR(255) NOT NULL,
    platform VARCHAR(50),
    segment VARCHAR(10) NOT NULL DEFAULT 'CASH',
    underlying VARCHAR(50),
    underlying_exchange VARCHAR(15),
    is_intraday BOOLEAN DEFAULT 1,
    start_time VARCHAR(5) NOT NULL,
    end_time VARCHAR(5),
    squareoff_time VARCHAR(5),
    exit_date VARCHAR(10),
    run_forever BOOLEAN DEFAULT 0,
    state VARCHAR(15) NOT NULL DEFAULT 'DRAFT',
    is_active BOOLEAN DEFAULT 0,
    mode VARCHAR(10) NOT NULL DEFAULT 'live',
    trading_mode VARCHAR(10) NOT NULL DEFAULT 'LONG',
    webhook_signing_method VARCHAR(20) NOT NULL DEFAULT 'NONE',
    webhook_secret VARCHAR(256),
    webhook_hmac_key VARCHAR(384),
    webhook_replay_window_seconds INTEGER DEFAULT 0,
    webhook_ip_allowlist TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    CONSTRAINT ck_strat_state CHECK (state IN ('DRAFT','ARMED','DISABLED','ARCHIVED')),
    CONSTRAINT ck_strat_mode CHECK (mode IN ('live','sandbox')),
    CONSTRAINT ck_strat_signing CHECK (webhook_signing_method IN ('NONE','BODY_SECRET','HMAC_SHA256','BOTH')),
    CONSTRAINT ck_strat_segment CHECK (segment IN ('CASH','INDEX_FO','STOCK_FO')),
    CONSTRAINT ck_strat_trading_mode CHECK (trading_mode IN ('LONG','SHORT','BOTH'))
)
"""


def _end_time_is_nullable(conn) -> bool:
    from sqlalchemy import text

    rows = conn.execute(
        text("SELECT name, \"notnull\" FROM pragma_table_info('strategies_v2')")
    ).fetchall()
    for name, notnull in rows:
        if name == "end_time":
            return not bool(notnull)
    return True


def main() -> int:
    print("=" * 60)
    print("Strategy v2 - Phase 12 (relax end_time to nullable)")
    print("=" * 60)
    try:
        from sqlalchemy import inspect, text

        from database.strategy_v2_db import engine

        if "strategies_v2" not in set(inspect(engine).get_table_names()):
            print("  [SKIP] strategies_v2 table not present; Phase 0 will create it")
            return 0

        with engine.begin() as conn:
            if _end_time_is_nullable(conn):
                print("  [SKIP] strategies_v2.end_time already nullable")
                print("=" * 60)
                return 0

            print("  [INFO] strategies_v2.end_time is NOT NULL; rebuilding table")

            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("ALTER TABLE strategies_v2 RENAME TO _strategies_v2_old"))
            conn.execute(text(_REBUILD_DDL))
            conn.execute(text(
                "INSERT INTO strategies_v2 ("
                "id, name, webhook_id, user_id, platform, segment, "
                "underlying, underlying_exchange, is_intraday, "
                "start_time, end_time, squareoff_time, exit_date, "
                "run_forever, state, is_active, mode, trading_mode, "
                "webhook_signing_method, webhook_secret, webhook_hmac_key, "
                "webhook_replay_window_seconds, webhook_ip_allowlist, "
                "created_at, updated_at"
                ") SELECT "
                "id, name, webhook_id, user_id, platform, segment, "
                "underlying, underlying_exchange, is_intraday, "
                "start_time, end_time, squareoff_time, exit_date, "
                "run_forever, state, is_active, mode, trading_mode, "
                "webhook_signing_method, webhook_secret, webhook_hmac_key, "
                "webhook_replay_window_seconds, webhook_ip_allowlist, "
                "created_at, updated_at "
                "FROM _strategies_v2_old"
            ))
            conn.execute(text("DROP TABLE _strategies_v2_old"))
            conn.execute(text("PRAGMA foreign_keys=ON"))

            print("  [OK]   rebuilt strategies_v2 with end_time NULLABLE")

        with engine.connect() as conn:
            n = conn.execute(text("SELECT COUNT(*) FROM strategies_v2")).scalar()
            print(f"  [OK]   row count after rebuild: {n}")

        print("=" * 60)
        print("Phase 12 schema migration completed successfully")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
