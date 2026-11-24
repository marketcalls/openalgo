"""Sandbox charges reach an existing install without touching what it holds.

A sandbox database created by any earlier release has no charge columns. Every
balance change reads the funds row's money columns together, so until the two
funds columns exist no sandbox order can be placed at all. They arrive two
ways, and both are tested against a database built with the schema as it
shipped before this release, holding rows:

* ``upgrade/migrate_sandbox_charges.py``, which ``migrate_all.py`` runs.
* The startup hook in ``database/sandbox_db.py``, for an install that pulls
  and restarts without running the upgrade script.

Neither may change a row that is already there. Old trades were never charged,
so they read 0.00, and a brokerage plan the trader has already saved stays as
they saved it.
"""

from __future__ import annotations

import ast
import os
import sqlite3
import subprocess
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "upgrade" / "migrate_sandbox_charges.py"

D = Decimal

#: The four tables as every release before this one created them.
OLD_SCHEMA = """
CREATE TABLE sandbox_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tradeid VARCHAR(50) UNIQUE NOT NULL,
    orderid VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    action VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    product VARCHAR(20) NOT NULL,
    strategy VARCHAR(100),
    trade_timestamp DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
CREATE TABLE sandbox_funds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    total_capital DECIMAL(15, 2) DEFAULT 10000000.00,
    available_balance DECIMAL(15, 2) DEFAULT 10000000.00,
    used_margin DECIMAL(15, 2) DEFAULT 0.00,
    realized_pnl DECIMAL(15, 2) DEFAULT 0.00,
    unrealized_pnl DECIMAL(15, 2) DEFAULT 0.00,
    total_pnl DECIMAL(15, 2) DEFAULT 0.00,
    last_reset_date DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    reset_count INTEGER DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    today_realized_pnl DECIMAL(15, 2) DEFAULT 0.00
);
CREATE TABLE sandbox_daily_pnl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    realized_pnl DECIMAL(15, 2) DEFAULT 0.00,
    positions_unrealized_pnl DECIMAL(15, 2) DEFAULT 0.00,
    holdings_unrealized_pnl DECIMAL(15, 2) DEFAULT 0.00,
    total_mtm DECIMAL(15, 2) DEFAULT 0.00,
    available_balance DECIMAL(15, 2) DEFAULT 0.00,
    used_margin DECIMAL(15, 2) DEFAULT 0.00,
    portfolio_value DECIMAL(15, 2) DEFAULT 0.00,
    created_at DATETIME NOT NULL,
    UNIQUE (user_id, date)
);
CREATE TABLE sandbox_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_key VARCHAR(100) UNIQUE NOT NULL,
    config_value TEXT NOT NULL,
    description TEXT,
    updated_at DATETIME NOT NULL
);
"""

#: Rows a trader's database would hold. The balance is deliberately not the
#: starting capital, so a migration that reset it would be caught.
OLD_ROWS = """
INSERT INTO sandbox_trades
    (tradeid, orderid, user_id, symbol, exchange, action, quantity, price, product, strategy,
     trade_timestamp)
VALUES
    ('TRADE-OLD-1', '26110100000001', 'trader', 'INFY', 'NSE', 'BUY', 10, 1500.50, 'CNC',
     'swing', '2026-11-02 10:15:00'),
    ('TRADE-OLD-2', '26110100000002', 'trader', 'INFY', 'NSE', 'SELL', 10, 1540.00, 'CNC',
     'swing', '2026-11-03 11:20:00');
INSERT INTO sandbox_funds
    (user_id, total_capital, available_balance, used_margin, realized_pnl, unrealized_pnl,
     total_pnl, last_reset_date, reset_count, created_at, updated_at, today_realized_pnl)
VALUES
    ('trader', 10000000.00, 9875395.00, 125000.00, 395.00, 0.00, 395.00,
     '2026-10-01 00:00:00', 2, '2026-10-01 00:00:00', '2026-11-03 11:20:00', 0.00);
INSERT INTO sandbox_daily_pnl
    (user_id, date, realized_pnl, positions_unrealized_pnl, holdings_unrealized_pnl, total_mtm,
     available_balance, used_margin, portfolio_value, created_at)
VALUES
    ('trader', '2026-11-03', 395.00, 0.00, 0.00, 395.00, 9875395.00, 125000.00, 10000395.00,
     '2026-11-03 23:59:00');
INSERT INTO sandbox_config (config_key, config_value, description, updated_at)
VALUES
    ('starting_capital', '10000000.00', 'Starting sandbox capital', '2026-10-01 00:00:00'),
    ('equity_mis_leverage', '8', 'Leverage the trader changed', '2026-10-05 00:00:00');
"""


def _url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _old_database(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.executescript(OLD_ROWS)
    conn.commit()
    conn.close()
    return path


def _columns(path: Path, table: str) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def _rows(path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _run(database_url: str, *args: str, cwd: Path | None = None):
    """Run the script the way migrate_all.py and the documented command do."""
    env = dict(os.environ)
    env["SANDBOX_DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd or ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def _script_columns() -> dict:
    """CHARGE_COLUMNS_BY_TABLE as the script declares it, read without importing it."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == "CHARGE_COLUMNS_BY_TABLE" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("the script no longer declares CHARGE_COLUMNS_BY_TABLE")


@pytest.fixture
def old_db(tmp_path):
    return _old_database(tmp_path / "sandbox.db")


# ---------------------------------------------------------------------------
# The upgrade script
# ---------------------------------------------------------------------------


def test_the_script_adds_every_column_and_leaves_existing_rows_as_they_were(old_db):
    before_trades = _rows(old_db, "SELECT * FROM sandbox_trades ORDER BY id")
    before_funds = _rows(old_db, "SELECT * FROM sandbox_funds")
    before_daily = _rows(old_db, "SELECT * FROM sandbox_daily_pnl")

    result = _run(_url(old_db))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Migration complete" in result.stdout

    for table, columns in _script_columns().items():
        present = _columns(old_db, table)
        for column in columns:
            assert column in present, f"{table}.{column}"

    # Every value that was there is still there, in the same place.
    width = len(before_trades[0])
    assert [row[:width] for row in _rows(old_db, "SELECT * FROM sandbox_trades ORDER BY id")] == (
        before_trades
    )
    width = len(before_funds[0])
    assert [row[:width] for row in _rows(old_db, "SELECT * FROM sandbox_funds")] == before_funds
    width = len(before_daily[0])
    assert [row[:width] for row in _rows(old_db, "SELECT * FROM sandbox_daily_pnl")] == (
        before_daily
    )


def test_trades_from_before_the_upgrade_read_as_uncharged(old_db):
    """Zero is what they paid, so zero is the backfill."""
    assert _run(_url(old_db)).returncode == 0

    charges = _rows(
        old_db,
        "SELECT brokerage, stt, exchange_charges, sebi_charges, stamp_duty, gst, total_charges "
        "FROM sandbox_trades",
    )
    assert charges == [(0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0)]
    assert _rows(old_db, "SELECT total_charges, today_charges FROM sandbox_funds") == [(0, 0)]
    assert _rows(old_db, "SELECT charges FROM sandbox_daily_pnl") == [(0,)]
    # The balance the trader saw is the balance they still have.
    assert _rows(old_db, "SELECT available_balance, used_margin FROM sandbox_funds") == [
        (9875395, 125000)
    ]


def test_the_default_plan_is_seeded_and_other_settings_are_not_touched(old_db):
    from sandbox.charges import default_config_values

    assert _run(_url(old_db)).returncode == 0

    stored = dict(_rows(old_db, "SELECT config_key, config_value FROM sandbox_config"))
    for key, value in default_config_values().items():
        assert stored[key] == value, key
    assert stored["charges_enabled"] == "true"
    assert stored["brokerage_equity_delivery_flat"] == "20"
    assert stored["brokerage_equity_delivery_percent"] == "2.5"
    assert stored["brokerage_equity_intraday_percent"] == "0.1"
    # Settings that belong to the rest of the sandbox, one of them changed.
    assert stored["starting_capital"] == "10000000.00"
    assert stored["equity_mis_leverage"] == "8"
    # Every new row satisfies the table's NOT NULL timestamp.
    assert _rows(old_db, "SELECT COUNT(*) FROM sandbox_config WHERE updated_at IS NULL") == [(0,)]


def test_a_plan_the_trader_already_saved_is_never_overwritten(old_db):
    """The app seeds the plan at startup, so a trader can change it before
    migrate_all.py ever runs. The script must add what is missing around it."""
    conn = sqlite3.connect(old_db)
    conn.executemany(
        "INSERT INTO sandbox_config (config_key, config_value, description, updated_at) "
        "VALUES (?, ?, 'saved by the trader', '2026-11-20 09:00:00')",
        [
            ("charges_enabled", "false"),
            ("brokerage_fno_options_flat", "10"),
            ("brokerage_equity_delivery_percent", "0.3"),
        ],
    )
    conn.commit()
    conn.close()

    assert _run(_url(old_db)).returncode == 0

    stored = dict(_rows(old_db, "SELECT config_key, config_value FROM sandbox_config"))
    assert stored["charges_enabled"] == "false"
    assert stored["brokerage_fno_options_flat"] == "10"
    assert stored["brokerage_equity_delivery_percent"] == "0.3"
    # The keys that were missing arrived at their defaults.
    assert stored["brokerage_equity_delivery_flat"] == "20"
    assert stored["brokerage_fno_futures_percent"] == "0.03"
    assert _rows(
        old_db, "SELECT COUNT(*) FROM sandbox_config WHERE config_key = 'charges_enabled'"
    ) == [(1,)]


def test_a_second_run_changes_nothing(old_db):
    assert _run(_url(old_db)).returncode == 0
    snapshot = {
        table: _rows(old_db, f"SELECT * FROM {table} ORDER BY id")
        for table in ("sandbox_trades", "sandbox_funds", "sandbox_daily_pnl", "sandbox_config")
    }

    again = _run(_url(old_db))
    assert again.returncode == 0, again.stdout + again.stderr
    assert "[SKIP]" in again.stdout

    for table, rows in snapshot.items():
        assert _rows(old_db, f"SELECT * FROM {table} ORDER BY id") == rows, table


def test_status_reports_what_would_change_and_changes_nothing(old_db):
    before = {table: _columns(old_db, table) for table in _script_columns()}

    status = _run(_url(old_db), "--status")
    assert status.returncode == 0, status.stdout + status.stderr
    assert "Would add 10 column(s) and 21 setting(s)." in status.stdout
    assert "missing total_charges, today_charges" in status.stdout
    assert {table: _columns(old_db, table) for table in before} == before
    assert _rows(old_db, "SELECT COUNT(*) FROM sandbox_config") == [(2,)]

    assert _run(_url(old_db)).returncode == 0
    after = _run(_url(old_db), "--status")
    assert after.returncode == 0
    assert "Nothing to change." in after.stdout


def test_a_fresh_install_gets_no_empty_database(tmp_path):
    """Connecting to a path that does not exist would create a file the app
    then finds and treats as its database."""
    missing = tmp_path / "not-there.db"

    result = _run(_url(missing))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No sandbox database yet" in result.stdout
    assert not missing.exists()


def test_a_database_with_only_some_tables_gets_only_their_columns(tmp_path):
    """sandbox_daily_pnl arrived in a later release than the others."""
    path = tmp_path / "partial.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA.split("CREATE TABLE sandbox_daily_pnl")[0])
    conn.commit()
    conn.close()

    result = _run(_url(path))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "total_charges" in _columns(path, "sandbox_funds")
    assert "brokerage" in _columns(path, "sandbox_trades")
    assert _columns(path, "sandbox_daily_pnl") == []


def test_run_from_the_upgrade_folder_it_finds_the_projects_database():
    """The documented command is ``cd upgrade && uv run migrate_sandbox_charges.py``.

    SANDBOX_DATABASE_URL is relative by default. Read against the upgrade
    folder it names a file the app never opens.
    """
    name = f"charges-migration-{uuid.uuid4().hex}.db"
    path = ROOT / "db" / name
    path.parent.mkdir(exist_ok=True)
    _old_database(path)
    try:
        result = _run(f"sqlite:///db/{name}", cwd=ROOT / "upgrade")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "total_charges" in _columns(path, "sandbox_funds")
        assert not (ROOT / "upgrade" / "db" / name).exists()
    finally:
        path.unlink(missing_ok=True)


def test_the_master_script_runs_it_and_treats_a_failure_as_a_failure():
    source = (ROOT / "upgrade" / "migrate_all.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            name = getattr(node.targets[0], "id", "")
            if name == "MIGRATIONS":
                values[name] = ast.literal_eval(node.value)
            elif name == "REQUIRED_MIGRATIONS":
                # frozenset({...}): read the set literal inside the call.
                values[name] = ast.literal_eval(node.value.args[0])

    scripts = [script for script, _description in values["MIGRATIONS"]]
    assert "migrate_sandbox_charges.py" in scripts
    # After the scripts that create the tables it alters.
    assert scripts.index("migrate_sandbox_charges.py") > scripts.index("migrate_sandbox.py")
    assert scripts.index("migrate_sandbox_charges.py") > scripts.index("migrate_sandbox_pnl.py")
    assert "migrate_sandbox_charges.py" in values["REQUIRED_MIGRATIONS"]


# ---------------------------------------------------------------------------
# The two column lists and the models
# ---------------------------------------------------------------------------


def test_the_script_the_startup_hook_and_the_models_name_the_same_columns():
    import database.sandbox_db as sandbox_db

    script = {table: tuple(columns) for table, columns in _script_columns().items()}
    assert script == sandbox_db.CHARGE_COLUMNS_BY_TABLE

    models = {
        "sandbox_trades": sandbox_db.SandboxTrades,
        "sandbox_funds": sandbox_db.SandboxFunds,
        "sandbox_daily_pnl": sandbox_db.SandboxDailyPnL,
    }
    for table, columns in script.items():
        model_columns = set(models[table].__table__.columns.keys())
        assert set(columns) <= model_columns, table

    # And the other way: a column a model has that no old database does must
    # be on the list, or an upgraded install fails on its first query.
    old = {}
    conn = sqlite3.connect(":memory:")
    conn.executescript(OLD_SCHEMA)
    for table in models:
        old[table] = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    conn.close()
    for table, model in models.items():
        new_in_model = set(model.__table__.columns.keys()) - old[table]
        assert new_in_model == set(script[table]), table


def test_the_trade_columns_match_what_the_calculation_returns():
    import database.sandbox_db as sandbox_db
    from sandbox.charges import CHARGE_COLUMNS, Charges

    assert sandbox_db.CHARGE_COLUMNS_BY_TABLE["sandbox_trades"] == CHARGE_COLUMNS
    assert tuple(Charges().as_columns()) == CHARGE_COLUMNS


# ---------------------------------------------------------------------------
# The startup hook, and the app on an upgraded database
# ---------------------------------------------------------------------------


@pytest.fixture
def app_on(monkeypatch):
    """Point the app's sandbox engine and session at a scratch database."""
    import database.sandbox_db as sandbox_db
    from database.engine_factory import create_db_engine

    engines = []
    original = sandbox_db.engine

    def bind(path: Path):
        engine = create_db_engine(_url(path))
        engines.append(engine)
        sandbox_db.db_session.remove()
        sandbox_db.db_session.configure(bind=engine)
        monkeypatch.setattr(sandbox_db, "engine", engine)
        return engine

    yield bind

    sandbox_db.db_session.remove()
    sandbox_db.db_session.configure(bind=original)
    for engine in engines:
        engine.dispose()


def test_the_startup_hook_upgrades_a_database_the_script_never_saw(old_db, app_on):
    import database.sandbox_db as sandbox_db

    app_on(old_db)
    sandbox_db._migrate_add_charge_columns()
    sandbox_db._migrate_add_charge_columns()  # a second start changes nothing

    for table, columns in sandbox_db.CHARGE_COLUMNS_BY_TABLE.items():
        present = _columns(old_db, table)
        for column in columns:
            assert present.count(column) == 1, f"{table}.{column}"

    # The models can read the old rows, and read them as uncharged.
    trades = sandbox_db.SandboxTrades.query.order_by(sandbox_db.SandboxTrades.id).all()
    assert [trade.tradeid for trade in trades] == ["TRADE-OLD-1", "TRADE-OLD-2"]
    assert all(trade.total_charges == 0 and trade.brokerage == 0 for trade in trades)
    funds = sandbox_db.SandboxFunds.query.filter_by(user_id="trader").first()
    assert funds.available_balance == D("9875395.00")
    assert funds.total_charges == 0 and funds.today_charges == 0
    sandbox_db.db_session.remove()


def test_startup_seeds_the_plan_without_overwriting_a_saved_value(old_db, app_on):
    import database.sandbox_db as sandbox_db
    from sandbox.charges import default_config_values

    app_on(old_db)
    sandbox_db._migrate_add_charge_columns()
    assert sandbox_db.set_config("brokerage_fno_options_flat", "10")

    sandbox_db.init_default_config()
    sandbox_db.init_default_config()

    expected = default_config_values()
    expected["brokerage_fno_options_flat"] = "10"
    stored = sandbox_db.get_configs(list(expected))
    assert stored == expected
    sandbox_db.db_session.remove()


def test_an_upgraded_database_charges_its_next_fill(old_db, app_on):
    """The whole point: after the script, the balance arithmetic works again."""
    import database.sandbox_db as sandbox_db
    from sandbox.fund_manager import FundManager, read_funds_snapshot

    assert _run(_url(old_db)).returncode == 0
    app_on(old_db)

    snapshot = read_funds_snapshot("trader")
    assert snapshot.values["total_charges"] == 0
    assert snapshot.values["available_balance"] == D("9875395.00")

    ok, message = FundManager("trader").stage_charges(D("172.03"), "first fill after upgrade")
    assert ok, message
    sandbox_db.db_session.commit()
    sandbox_db.db_session.remove()

    assert _rows(
        old_db, "SELECT available_balance, total_charges, today_charges FROM sandbox_funds"
    ) == [(9875222.97, 172.03, 172.03)]
    # Margin and P&L are exactly what they were.
    assert _rows(old_db, "SELECT used_margin, realized_pnl, total_pnl FROM sandbox_funds") == [
        (125000, 395, 395)
    ]


def test_without_the_columns_no_balance_can_change(old_db, app_on):
    """Why the migration is required rather than best-effort: this is what an
    install that got the code and neither upgrade path would do on every order."""
    from sqlalchemy.exc import OperationalError

    import database.sandbox_db as sandbox_db
    from sandbox.fund_manager import read_funds_snapshot

    app_on(old_db)
    with pytest.raises(OperationalError):
        read_funds_snapshot("trader")
    sandbox_db.db_session.rollback()
    sandbox_db.db_session.remove()
