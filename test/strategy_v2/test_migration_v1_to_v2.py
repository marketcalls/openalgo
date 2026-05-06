"""Phase 7 — v1 -> v2 migration tests.

Exercises upgrade/migrate_strategy_v2.py:_phase7_convert_v1_strategies
against a temporary SQLite DB. Tests cover:

  - clean DB / no v1 strategies -> no-op, no backup
  - 1 v1 strategy with 1 mapping -> 1 v2 + 1 leg, webhook_id preserved
  - multi-mapping v1 -> N legs in correct leg_index order
  - already-converted (v2 with same webhook_id) -> skip
  - idempotent: running twice produces the same result
  - backup snapshot is taken before mutations
  - no backup taken when there's nothing to convert

Each test runs in a subprocess so DATABASE_URL is bound at engine
build-time and the production import path is exercised end-to-end.
The subprocess approach keeps this test from polluting the shared
SQLAlchemy engine that the rest of the suite uses.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sqlite3
import tempfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SCRIPT = REPO_ROOT / "upgrade" / "migrate_strategy_v2.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_migration(db_path: Path) -> subprocess.CompletedProcess:
    """Invoke the real migration script as a subprocess so engines bind
    to *this* DB. Returns the CompletedProcess for assertions on stdout."""
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    # APP_KEY is required by utils.secret_box at strategy_v2_db import time.
    env.setdefault("APP_KEY", "openalgo-test-app-key-deterministic-32b")
    # Disable .env loading inside the subprocess — we want the explicit env
    # vars above to win, not whatever the dev's local .env says.
    env["DOTENV_DISABLED"] = "1"
    return subprocess.run(
        [sys.executable, str(MIGRATION_SCRIPT)],
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _seed_v1_strategy(
    db_path: Path,
    *,
    name: str,
    webhook_id: str,
    user_id: str = "test-user",
    mappings: list[tuple[str, str, int, str]] | None = None,
    is_intraday: bool = True,
    start_time: str = "09:20",
    end_time: str = "15:10",
    squareoff_time: str | None = "15:20",
    platform: str = "tradingview",
) -> int:
    """Insert a v1 strategy + its mappings via raw SQLite. Returns the
    new strategy id. Tables are created if they don't exist yet."""
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
            "INSERT INTO strategies "
            "(name, webhook_id, user_id, platform, is_intraday, "
            " start_time, end_time, squareoff_time) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                webhook_id,
                user_id,
                platform,
                1 if is_intraday else 0,
                start_time,
                end_time,
                squareoff_time,
            ),
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


def _query_v2(db_path: Path):
    """Return (strategies_v2 rows, strategy_legs rows) as list-of-dict."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        s = [dict(r) for r in con.execute("SELECT * FROM strategies_v2").fetchall()]
        legs = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM strategy_legs ORDER BY strategy_id, leg_index"
            ).fetchall()
        ]
        return s, legs
    finally:
        con.close()


def _backup_paths(db_path: Path) -> list[Path]:
    """Return any db.bak.* siblings of db_path."""
    return sorted(db_path.parent.glob(f"{db_path.name}.bak.*"))


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_db(tmp_path: Path) -> Path:
    """Empty SQLite file. Migration creates v2 tables on first run."""
    db = tmp_path / "openalgo.db"
    db.touch()
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_migration_no_v1_data(fresh_db: Path):
    """Clean DB (no v1 schema) -> migration succeeds, creates v2 tables,
    no backup. Accepts any 'nothing to convert' skip path."""
    r = _run_migration(fresh_db)
    assert r.returncode == 0, r.stdout + r.stderr
    # Any of the converter's 'nothing to do' messages is fine.
    assert (
        "No v1 strategies present" in r.stdout
        or "'strategies' table not present" in r.stdout
    ), r.stdout

    strats, legs = _query_v2(fresh_db)
    assert strats == []
    assert legs == []

    # No backup should exist — we didn't mutate anything.
    assert _backup_paths(fresh_db) == []


def test_migration_single_strategy_single_mapping(fresh_db: Path):
    _seed_v1_strategy(
        fresh_db,
        name="My TV Strat",
        webhook_id="abc-1234",
        mappings=[("INFY", "NSE", 5, "CNC")],
        is_intraday=False,
        start_time="09:30",
        end_time="15:15",
        squareoff_time=None,
    )

    r = _run_migration(fresh_db)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "converted=1 legs=1" in r.stdout

    strats, legs = _query_v2(fresh_db)
    assert len(strats) == 1
    s = strats[0]
    assert s["webhook_id"] == "abc-1234"
    assert s["name"] == "My TV Strat"
    assert s["mode"] == "live"
    assert s["webhook_signing_method"] == "NONE"
    assert s["state"] == "DRAFT"
    assert int(s["is_active"]) == 0
    assert int(s["is_intraday"]) == 0
    assert s["start_time"] == "09:30"
    assert s["end_time"] == "15:15"

    assert len(legs) == 1
    leg = legs[0]
    assert leg["segment"] == "CASH"
    assert leg["position"] == "B"
    assert leg["product"] == "CNC"
    assert leg["symbol_cash"] == "INFY"
    assert leg["qty"] == 5
    assert leg["leg_index"] == 1


def test_migration_multi_mapping_creates_multi_leg(fresh_db: Path):
    _seed_v1_strategy(
        fresh_db,
        name="Basket10",
        webhook_id="basket-001",
        mappings=[
            ("INFY", "NSE", 10, "CNC"),
            ("TCS", "NSE", 5, "CNC"),
            ("SBIN", "NSE", 50, "MIS"),
        ],
    )

    r = _run_migration(fresh_db)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "converted=1 legs=3" in r.stdout

    strats, legs = _query_v2(fresh_db)
    assert len(strats) == 1
    assert len(legs) == 3
    assert [leg["leg_index"] for leg in legs] == [1, 2, 3]
    assert [leg["symbol_cash"] for leg in legs] == ["INFY", "TCS", "SBIN"]
    assert [leg["qty"] for leg in legs] == [10, 5, 50]
    assert [leg["product"] for leg in legs] == ["CNC", "CNC", "MIS"]


def test_migration_idempotent(fresh_db: Path):
    _seed_v1_strategy(
        fresh_db,
        name="Idem",
        webhook_id="idem-001",
        mappings=[("RELIANCE", "NSE", 1, "MIS")],
    )

    r1 = _run_migration(fresh_db)
    assert r1.returncode == 0
    assert "converted=1" in r1.stdout

    r2 = _run_migration(fresh_db)
    assert r2.returncode == 0
    assert "All v1 strategies already have v2 counterparts" in r2.stdout

    strats, legs = _query_v2(fresh_db)
    assert len(strats) == 1
    assert len(legs) == 1


def test_migration_skips_existing_v2(fresh_db: Path):
    """If a v2 row already has the v1's webhook_id, leave both alone."""
    _seed_v1_strategy(
        fresh_db,
        name="Original v1",
        webhook_id="shared-wh",
        mappings=[("HDFC", "NSE", 1, "MIS")],
    )

    # First run -> creates v2 + 1 leg
    r1 = _run_migration(fresh_db)
    assert r1.returncode == 0

    # Mutate the v2 row to prove the migration doesn't overwrite it.
    con = sqlite3.connect(fresh_db)
    try:
        con.execute("UPDATE strategies_v2 SET name = 'Manually Edited'")
        con.execute("UPDATE strategies_v2 SET mode = 'sandbox'")
        con.commit()
    finally:
        con.close()

    r2 = _run_migration(fresh_db)
    assert r2.returncode == 0

    strats, _ = _query_v2(fresh_db)
    assert len(strats) == 1
    assert strats[0]["name"] == "Manually Edited"
    assert strats[0]["mode"] == "sandbox"


def test_migration_creates_backup_before_conversion(fresh_db: Path):
    _seed_v1_strategy(
        fresh_db,
        name="Backup Check",
        webhook_id="bk-1",
        mappings=[("INFY", "NSE", 1, "MIS")],
    )

    assert _backup_paths(fresh_db) == []
    r = _run_migration(fresh_db)
    assert r.returncode == 0

    backups = _backup_paths(fresh_db)
    assert len(backups) == 1
    # Filename contains today's date.
    import datetime as _dt

    assert backups[0].name.endswith(f".bak.{_dt.date.today().isoformat()}")
    # Backup is non-empty (real copy of the DB).
    assert backups[0].stat().st_size > 0


def test_migration_no_backup_when_nothing_to_convert(fresh_db: Path):
    # Run migration on an empty DB twice — neither should produce a backup.
    _run_migration(fresh_db)
    _run_migration(fresh_db)
    assert _backup_paths(fresh_db) == []


def test_migration_preserves_webhook_id_for_url_continuity(fresh_db: Path):
    """The contract: external integrations (TradingView/Amibroker) keep
    posting to /strategy/webhook/<old_webhook_id> and the v2 router
    finds the converted strategy."""
    seed_id = "tradingview-existing-uuid-2026"
    _seed_v1_strategy(
        fresh_db,
        name="Has Subscribers",
        webhook_id=seed_id,
        mappings=[("INFY", "NSE", 1, "MIS")],
    )

    r = _run_migration(fresh_db)
    assert r.returncode == 0

    strats, _ = _query_v2(fresh_db)
    assert len(strats) == 1
    assert strats[0]["webhook_id"] == seed_id, (
        "webhook_id MUST be preserved verbatim — external URLs depend on it"
    )
