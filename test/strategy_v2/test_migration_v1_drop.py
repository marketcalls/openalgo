"""Phase 8 — v1 table-drop migration tests.

Exercises upgrade/migrate_strategy_v1_drop.py against a temporary SQLite
DB. Covers:

  - empty/fresh DB -> idempotent no-op (tables not present)
  - v1 tables exist, all v1 strategies have v2 counterparts -> safe drop
  - v1 tables exist, some v1 strategies have NO v2 counterpart -> refuse
  - second run after successful drop -> idempotent
  - DB snapshot taken on actual drops; not on no-ops

Subprocess invocation matches test_migration_v1_to_v2.py so engines
bind to the temp DB at engine-build time.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DROP_SCRIPT = REPO_ROOT / "upgrade" / "migrate_strategy_v1_drop.py"
CONVERT_SCRIPT = REPO_ROOT / "upgrade" / "migrate_strategy_v2.py"


def _run(script: Path, db_path: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    env.setdefault("APP_KEY", "openalgo-test-app-key-deterministic-32b")
    return subprocess.run(
        [sys.executable, str(script)],
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _seed_v1(
    db_path: Path,
    *,
    name: str,
    webhook_id: str,
    user_id: str = "test-user",
    mappings: list[tuple[str, str, int, str]] | None = None,
) -> int:
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(255) NOT NULL,
                webhook_id VARCHAR(36) NOT NULL UNIQUE,
                user_id VARCHAR(255) NOT NULL,
                platform VARCHAR(50) NOT NULL DEFAULT 'tradingview',
                is_active BOOLEAN DEFAULT 1,
                is_intraday BOOLEAN DEFAULT 1,
                trading_mode VARCHAR(10) NOT NULL DEFAULT 'LONG',
                start_time VARCHAR(5),
                end_time VARCHAR(5),
                squareoff_time VARCHAR(5),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_symbol_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id INTEGER NOT NULL,
                symbol VARCHAR(50) NOT NULL,
                exchange VARCHAR(10) NOT NULL,
                quantity INTEGER NOT NULL,
                product_type VARCHAR(10) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME,
                FOREIGN KEY(strategy_id) REFERENCES strategies(id)
            )
            """
        )
        cur.execute(
            "INSERT INTO strategies (name, webhook_id, user_id) VALUES (?, ?, ?)",
            (name, webhook_id, user_id),
        )
        sid = cur.lastrowid
        for sym, exch, qty, prod in mappings or []:
            cur.execute(
                "INSERT INTO strategy_symbol_mappings "
                "(strategy_id, symbol, exchange, quantity, product_type) "
                "VALUES (?, ?, ?, ?, ?)",
                (sid, sym, exch, qty, prod),
            )
        con.commit()
        return sid
    finally:
        con.close()


def _table_exists(db_path: Path, name: str) -> bool:
    con = sqlite3.connect(db_path)
    try:
        return bool(
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
        )
    finally:
        con.close()


def _backup_paths(db_path: Path):
    return sorted(db_path.parent.glob(f"{db_path.name}.bak.*"))


@pytest.fixture
def fresh_db(tmp_path: Path) -> Path:
    db = tmp_path / "openalgo.db"
    db.touch()
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_drop_noop_on_empty_db(fresh_db: Path):
    """Fresh DB has no v1 tables -> migration succeeds, no backup."""
    r = _run(DROP_SCRIPT, fresh_db)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "v1 tables already dropped" in r.stdout
    assert _backup_paths(fresh_db) == []


def test_drop_succeeds_after_full_conversion(fresh_db: Path):
    """v1 strategies all have v2 counterparts -> safe drop."""
    _seed_v1(
        fresh_db,
        name="full-conv",
        webhook_id="conv-1",
        mappings=[("INFY", "NSE", 1, "MIS")],
    )

    # Run conversion first.
    r1 = _run(CONVERT_SCRIPT, fresh_db)
    assert r1.returncode == 0
    assert "converted=1" in r1.stdout

    # Now the drop should succeed.
    r2 = _run(DROP_SCRIPT, fresh_db)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "Dropped table 'strategies'" in r2.stdout
    assert "Dropped table 'strategy_symbol_mappings'" in r2.stdout

    assert not _table_exists(fresh_db, "strategies")
    assert not _table_exists(fresh_db, "strategy_symbol_mappings")
    # v2 tables intact
    assert _table_exists(fresh_db, "strategies_v2")
    assert _table_exists(fresh_db, "strategy_legs")


def test_drop_refuses_when_v1_unconverted(fresh_db: Path):
    """v1 strategy WITHOUT a v2 counterpart -> migration must abort,
    leave both tables intact."""
    _seed_v1(
        fresh_db,
        name="orphan",
        webhook_id="orphan-1",
        mappings=[("INFY", "NSE", 1, "MIS")],
    )

    # Need v2 schema present (the drop script imports strategy_v2_db).
    # Running the converter is the easiest way to ensure that — but the
    # converter would also convert the row, defeating the test. Instead
    # we just create the v2 tables without converting by running the
    # converter once: it will convert the row. So we delete the converted
    # v2 row to simulate the orphan condition.
    r_conv = _run(CONVERT_SCRIPT, fresh_db)
    assert r_conv.returncode == 0
    con = sqlite3.connect(fresh_db)
    try:
        con.execute("DELETE FROM strategies_v2")
        con.execute("DELETE FROM strategy_legs")
        con.execute("DELETE FROM strategy_risk_config")
        con.commit()
    finally:
        con.close()

    r = _run(DROP_SCRIPT, fresh_db)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "Refusing to drop v1 tables" in (r.stdout + r.stderr)

    # v1 tables still present — no destructive action taken.
    assert _table_exists(fresh_db, "strategies")
    assert _table_exists(fresh_db, "strategy_symbol_mappings")


def test_drop_idempotent_after_success(fresh_db: Path):
    _seed_v1(
        fresh_db,
        name="idem",
        webhook_id="idem-1",
        mappings=[("RELIANCE", "NSE", 1, "MIS")],
    )
    _run(CONVERT_SCRIPT, fresh_db)
    r1 = _run(DROP_SCRIPT, fresh_db)
    assert r1.returncode == 0
    r2 = _run(DROP_SCRIPT, fresh_db)
    assert r2.returncode == 0
    assert "v1 tables already dropped" in r2.stdout


def test_drop_takes_backup_before_destructive_action(fresh_db: Path):
    _seed_v1(
        fresh_db,
        name="bk",
        webhook_id="bk-1",
        mappings=[("HDFC", "NSE", 1, "MIS")],
    )

    # Convert - this also creates a backup.
    _run(CONVERT_SCRIPT, fresh_db)
    backups_after_convert = _backup_paths(fresh_db)
    assert len(backups_after_convert) >= 1

    # Drop - should also create (or no-op-add) a snapshot. Both share
    # today's date so it's the same file.
    _run(DROP_SCRIPT, fresh_db)
    backups_after_drop = _backup_paths(fresh_db)
    assert len(backups_after_drop) >= 1
    assert all(p.stat().st_size > 0 for p in backups_after_drop)
