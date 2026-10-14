"""The 5 October 2026 index freeze limits reach new and existing installs.

The startup hook seeds qty_freeze from data/qtyfreeze.csv only when the table
is empty, so a new CSV reaches a new install and nothing else. Without the
migration an existing install kept splitting NIFTY at 1,800 a slice when the
exchange takes 3,510, and NIFTYFPI options fell through the prefix match to
NIFTY's limit because they had no row of their own.
"""

import csv
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import text

import database.qty_freeze_db as qf
from database.engine_factory import create_db_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "upgrade"))

import migrate_qty_freeze_oct_2026 as migration  # noqa: E402

#: The rows OpenAlgo shipped before this revision, plus rows it must not touch.
SHIPPED = {
    ("NFO", "NIFTY"): 1800,
    ("NFO", "BANKNIFTY"): 600,
    ("NFO", "FINNIFTY"): 1200,
    ("NFO", "MIDCPNIFTY"): 2800,
    ("NFO", "NIFTYNXT50"): 600,
    ("NFO", "RELIANCE"): 25000,
    ("MCX", "CRUDEOIL"): 10000,
}

NEW = {symbol: new for symbol, (new, _old) in migration.REVISION.items()}


def _engine(tmp_path, rows):
    """A scratch database with the qty_freeze table holding ``rows``."""
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'openalgo.db').as_posix()}")
    qf.Base.metadata.create_all(engine, tables=[qf.QtyFreeze.__table__])
    with engine.begin() as connection:
        for (exchange, symbol), qty in rows.items():
            connection.execute(
                text("INSERT INTO qty_freeze (exchange, symbol, freeze_qty) VALUES (:e, :s, :q)"),
                {"e": exchange, "s": symbol, "q": qty},
            )
    return engine


def _rows(engine):
    with engine.connect() as connection:
        result = connection.execute(text("SELECT exchange, symbol, freeze_qty FROM qty_freeze"))
        return {(exchange, symbol): qty for exchange, symbol, qty in result}


def test_an_existing_install_moves_to_the_new_limits(tmp_path):
    engine = _engine(tmp_path, SHIPPED)
    try:
        assert migration.apply(engine)
        rows = _rows(engine)
    finally:
        engine.dispose()

    for symbol, new in NEW.items():
        assert rows[("NFO", symbol)] == new, symbol
    # NIFTYFPI never had a row, so it is added; nothing else is.
    assert len(rows) == len(SHIPPED) + 1
    assert rows[("NFO", "RELIANCE")] == 25000
    assert rows[("MCX", "CRUDEOIL")] == 10000


@pytest.mark.parametrize(
    "symbol,published,new",
    [
        ("FINNIFTY", 1800, 3240),  # NSE's limit in most months; the seed shipped 1,200
        ("BANKNIFTY", 900, 1440),  # NSE's limit from 1 April to 30 June 2026
    ],
)
def test_an_earlier_published_limit_moves_too(tmp_path, symbol, published, new):
    """An admin who copied in an NSE value that has since gone stale is updated."""
    engine = _engine(tmp_path, {("NFO", symbol): published, ("NFO", "NIFTY"): 1800})
    try:
        assert migration.apply(engine)
        assert _rows(engine)[("NFO", symbol)] == new
    finally:
        engine.dispose()


def test_an_admin_value_is_left_alone(tmp_path):
    rows = dict(SHIPPED)
    rows[("NFO", "BANKNIFTY")] = 750
    del rows[("NFO", "NIFTYNXT50")]  # an admin deleted it
    engine = _engine(tmp_path, rows)
    try:
        steps = {symbol: action for symbol, _v, _n, action in migration.plan(engine)}
        assert steps["BANKNIFTY"] == "custom"
        assert steps["NIFTYNXT50"] == "custom"
        assert migration.apply(engine)
        after = _rows(engine)
    finally:
        engine.dispose()

    assert after[("NFO", "BANKNIFTY")] == 750
    assert ("NFO", "NIFTYNXT50") not in after
    assert after[("NFO", "NIFTY")] == 3510


def test_rerunning_changes_nothing(tmp_path):
    engine = _engine(tmp_path, SHIPPED)
    try:
        assert migration.apply(engine)
        first = _rows(engine)
        assert all(action == "current" for *_rest, action in migration.plan(engine))
        assert migration.apply(engine)
        assert _rows(engine) == first
    finally:
        engine.dispose()


def test_status_changes_nothing(tmp_path, capsys):
    engine = _engine(tmp_path, SHIPPED)
    try:
        assert migration.status(engine)
        assert _rows(engine) == SHIPPED
    finally:
        engine.dispose()
    assert "Would change 6 row(s)." in capsys.readouterr().out


@pytest.mark.parametrize("make_table", [True, False])
def test_an_empty_or_missing_table_is_left_for_the_startup_seed(tmp_path, make_table):
    """A row inserted here would stop the CSV seed, which runs only when empty."""
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'openalgo.db').as_posix()}")
    try:
        if make_table:
            qf.Base.metadata.create_all(engine, tables=[qf.QtyFreeze.__table__])
        assert migration.plan(engine) is None
        assert migration.apply(engine)
        if make_table:
            assert _rows(engine) == {}
    finally:
        engine.dispose()


def test_the_seed_csv_carries_the_same_limits():
    """A new install and a migrated one end up with the same values."""
    with open(ROOT / "data" / "qtyfreeze.csv", newline="") as handle:
        reader = csv.reader(handle)
        next(reader)
        seed = {row[1].strip(): int(row[2]) for row in reader if len(row) == 3}
    for symbol, new in NEW.items():
        assert seed[symbol] == new, symbol


def test_the_migration_is_registered():
    # On Windows migrate_all rewraps stdout at import, which closes pytest's capture.
    with patch.object(sys, "platform", "test"):
        from upgrade import migrate_all

    names = [script for script, _description in migrate_all.MIGRATIONS]
    assert names.count("migrate_qty_freeze_oct_2026.py") == 1


def test_niftyfpi_options_resolve_their_own_limit(monkeypatch):
    """NIFTYFPI starts with NIFTY, so it must be matched before NIFTY."""
    monkeypatch.setattr(qf, "_cache_loaded", True)
    monkeypatch.setattr(qf, "_freeze_qty_cache", {"NFO:NIFTY": 3510, "NFO:NIFTYFPI": 53900})
    assert qf.get_freeze_qty_for_option("NIFTYFPI27OCT2618000CE", "NFO") == 53900
    assert qf.get_freeze_qty_for_option("NIFTYFPI27OCT26FUT", "NFO") == 53900
    assert qf.get_freeze_qty_for_option("NIFTY27OCT2625000CE", "NFO") == 3510
