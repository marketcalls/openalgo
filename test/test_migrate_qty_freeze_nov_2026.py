"""The 2 November 2026 index freeze limits reach new and existing installs.

The startup hook seeds qty_freeze from data/qtyfreeze.csv only when the table
is empty, so a new CSV reaches a new install and nothing else. Without the
migration an install carrying the 5 October limits would keep sending NIFTY
orders of up to 3,510 when the exchange now rejects anything above 1,800.

The October migration is not run alongside this one: it treated 1,800 as a
stale NIFTY limit and raised it, so in migrate_all's list it would undo this
revision on every upgrade. `test_the_october_migration_is_gone` pins that.
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

import migrate_qty_freeze_nov_2026 as migration  # noqa: E402

#: Rows the migration must never touch, present in every scenario.
OTHERS = {("NFO", "RELIANCE"): 25000, ("MCX", "CRUDEOIL"): 10000}

#: An install that applied the 5 October revision, or was seeded from its CSV.
OCTOBER = {
    ("NFO", "NIFTY"): 3510,
    ("NFO", "BANKNIFTY"): 1440,
    ("NFO", "FINNIFTY"): 3240,
    ("NFO", "MIDCPNIFTY"): 5760,
    ("NFO", "NIFTYNXT50"): 1125,
    ("NFO", "NIFTYFPI"): 53900,
    **OTHERS,
}

#: An install still on the seed OpenAlgo shipped before October, which never
#: carried a NIFTYFPI row.
BEFORE_OCTOBER = {
    ("NFO", "NIFTY"): 1800,
    ("NFO", "BANKNIFTY"): 600,
    ("NFO", "FINNIFTY"): 1200,
    ("NFO", "MIDCPNIFTY"): 2800,
    ("NFO", "NIFTYNXT50"): 600,
    **OTHERS,
}

#: NSE/FAOP/77189, as published.
CIRCULAR = {
    "NIFTY": 1800,
    "BANKNIFTY": 900,
    "FINNIFTY": 1800,
    "MIDCPNIFTY": 2800,
    "NIFTYNXT50": 600,
    "NIFTYFPI": 8500,
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


def _migrated(tmp_path, rows):
    engine = _engine(tmp_path, rows)
    try:
        assert migration.apply(engine)
        return _rows(engine)
    finally:
        engine.dispose()


def test_the_revision_is_the_circular():
    assert NEW == CIRCULAR


def test_an_install_on_the_october_limits_comes_down(tmp_path):
    rows = _migrated(tmp_path, OCTOBER)

    assert {symbol: rows[("NFO", symbol)] for symbol in CIRCULAR} == CIRCULAR
    assert len(rows) == len(OCTOBER)
    for key, qty in OTHERS.items():
        assert rows[key] == qty


def test_an_install_that_never_took_the_october_limits_lands_in_the_same_place(tmp_path):
    rows = _migrated(tmp_path, BEFORE_OCTOBER)

    assert {symbol: rows[("NFO", symbol)] for symbol in CIRCULAR} == CIRCULAR
    # NIFTYFPI never had a row, so it is added; nothing else is.
    assert len(rows) == len(BEFORE_OCTOBER) + 1


@pytest.mark.parametrize(
    "symbol,published,new",
    [
        ("BANKNIFTY", 600, 900),  # NSE's limit in most months to September 2026
        ("FINNIFTY", 1200, 1800),  # the seed OpenAlgo shipped until October
    ],
)
def test_an_earlier_published_limit_moves_too(tmp_path, symbol, published, new):
    """An admin who copied in an NSE value that has since gone stale is updated."""
    rows = _migrated(tmp_path, {("NFO", symbol): published, ("NFO", "NIFTY"): 3510})

    assert rows[("NFO", symbol)] == new


def test_an_admin_value_is_left_alone(tmp_path):
    rows = dict(OCTOBER)
    rows[("NFO", "BANKNIFTY")] = 750  # never published by NSE
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
    assert after[("NFO", "NIFTY")] == 1800


def test_rerunning_changes_nothing(tmp_path):
    engine = _engine(tmp_path, OCTOBER)
    try:
        assert migration.apply(engine)
        first = _rows(engine)
        assert all(action == "current" for *_rest, action in migration.plan(engine))
        assert migration.apply(engine)
        assert _rows(engine) == first
    finally:
        engine.dispose()


def test_status_changes_nothing(tmp_path, capsys):
    engine = _engine(tmp_path, OCTOBER)
    try:
        assert migration.status(engine)
        assert _rows(engine) == OCTOBER
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


def _registered():
    # On Windows migrate_all rewraps stdout at import, which closes pytest's capture.
    with patch.object(sys, "platform", "test"):
        from upgrade import migrate_all

    return [script for script, _description in migrate_all.MIGRATIONS]


def test_the_migration_is_registered():
    assert _registered().count("migrate_qty_freeze_nov_2026.py") == 1


def test_the_october_migration_is_gone():
    """PINNED DEFECT. migrate_all runs every script on every upgrade, in order.
    The October script raised NIFTY from 1,800 to 3,510, so listed before this
    one it would undo this revision each time, and an upgrade stopped between
    the two would leave limits the exchange rejects. Run by hand it would do
    the same, so the file goes too."""
    assert not [name for name in _registered() if name.startswith("migrate_qty_freeze_oct")]
    assert not (ROOT / "upgrade" / "migrate_qty_freeze_oct_2026.py").exists()


def test_niftyfpi_options_resolve_their_own_limit(monkeypatch):
    """NIFTYFPI starts with NIFTY, so it must be matched before NIFTY."""
    monkeypatch.setattr(qf, "_cache_loaded", True)
    monkeypatch.setattr(qf, "_freeze_qty_cache", {"NFO:NIFTY": 1800, "NFO:NIFTYFPI": 8500})
    assert qf.get_freeze_qty_for_option("NIFTYFPI24NOV2618000CE", "NFO") == 8500
    assert qf.get_freeze_qty_for_option("NIFTYFPI24NOV26FUT", "NFO") == 8500
    assert qf.get_freeze_qty_for_option("NIFTY24NOV2625000CE", "NFO") == 1800
