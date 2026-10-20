"""Historify's ID sequences reach existing databases and survive a round trip.

Four Historify tables take their IDs from DuckDB sequences instead of computing
MAX(id) + 1 (two gthread requests could read the same MAX and insert it twice).
The sequences were created only when missing, at the table's high-water mark.
That served a first upgrade, but not a return: an install that left for a
version without sequences kept inserting MAX(id) + 1 there, the sequence left
in the file fell behind, and on coming back every insert collided with a
duplicate key, on every attempt, because a failed insert's draw is not kept
once the database is reopened and each Historify call opens it afresh.

Pinned here, against the application's own write path:

* an old database gains sequences that continue after its highest IDs;
* a sequence left behind by a round trip is moved past its table, both when
  OpenAlgo starts and by the upgrade script;
* the upgrade script reports without changing under --status, applies, and
  changes nothing when run again;
* a sequence already ahead of its table is left alone;
* a sequence exactly one behind is caught after a reopen, where DuckDB reports
  the value still to come as last_value rather than the value last drawn.

The next value is measured by drawing from a copy of the database, not read
back through the formula under test.
"""

from __future__ import annotations

import ast
import importlib
import shutil
import sys
from pathlib import Path

import duckdb
import pytest

from database import historify_db

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "upgrade"))
migration = importlib.import_module("migrate_historify_sequences")


@pytest.fixture
def db_path(monkeypatch, tmp_path):
    path = tmp_path / "historify.duckdb"
    monkeypatch.setattr(historify_db, "HISTORIFY_DB_PATH", str(path))
    monkeypatch.setattr(migration, "HISTORIFY_DB_PATH", str(path))
    return path


def _sql(path, statement, params=None):
    conn = duckdb.connect(str(path))
    try:
        result = conn.execute(statement, params or [])
        return result.fetchall() if result.description else None
    finally:
        conn.close()


def _next_value(path, sequence):
    """The ID the sequence hands out next, drawn from a throwaway copy."""
    probe = path.with_name(f"probe-{sequence}.duckdb")
    for suffix in ("", ".wal"):
        source = Path(f"{path}{suffix}")
        target = Path(f"{probe}{suffix}")
        target.unlink(missing_ok=True)
        if source.exists():
            shutil.copyfile(source, target)
    conn = duckdb.connect(str(probe))
    try:
        exists = conn.execute(
            "SELECT 1 FROM duckdb_sequences() WHERE sequence_name = ?", [sequence]
        ).fetchone()
        return conn.execute(f"SELECT nextval('{sequence}')").fetchone()[0] if exists else None
    finally:
        conn.close()


def _insert_like_main(path, symbols):
    """Insert watchlist rows the way a version without sequences does."""
    for symbol in symbols:
        _sql(
            path,
            "INSERT INTO watchlist (id, symbol, exchange, display_name) "
            "SELECT COALESCE(MAX(id), 0) + 1, ?, 'NSE', ? FROM watchlist",
            [symbol, symbol],
        )


SEQUENCES = (
    "watchlist_id_seq",
    "data_catalog_id_seq",
    "job_items_id_seq",
    "historify_schedule_executions_id_seq",
)


def _drop_sequences(path):
    for sequence in SEQUENCES:
        _sql(path, f"DROP SEQUENCE IF EXISTS {sequence}")


def _watchlist_ids(path):
    return [row[0] for row in _sql(path, "SELECT id FROM watchlist ORDER BY id")]


def test_an_old_database_gains_sequences_after_its_highest_ids(db_path):
    historify_db.init_database()
    _drop_sequences(db_path)  # the schema before sequences existed
    _insert_like_main(db_path, ["RELIANCE", "SBIN", "INFY"])

    historify_db.init_database()  # the first start after the update

    assert _next_value(db_path, "watchlist_id_seq") == 4
    ok, message = historify_db.add_to_watchlist("TCS", "NSE")
    assert ok, message
    assert _watchlist_ids(db_path) == [1, 2, 3, 4]


def test_a_round_trip_through_a_version_without_sequences_does_not_collide(db_path):
    historify_db.init_database()
    for symbol in ("RELIANCE", "SBIN"):
        ok, message = historify_db.add_to_watchlist(symbol, "NSE")
        assert ok, message
    # Away on a version without sequences: it assigns MAX(id) + 1 and never
    # touches the sequence left in the file.
    _insert_like_main(db_path, ["INFY", "TCS", "HDFCBANK"])
    assert _next_value(db_path, "watchlist_id_seq") == 3  # behind: IDs 3 to 5 are taken

    historify_db.init_database()  # back on this version, first start

    assert _next_value(db_path, "watchlist_id_seq") == 6
    ok, message = historify_db.add_to_watchlist("ITC", "NSE")
    assert ok, f"a new watchlist entry collided after the round trip: {message}"
    assert _watchlist_ids(db_path) == [1, 2, 3, 4, 5, 6]


def test_the_upgrade_script_reports_applies_and_is_idempotent(db_path):
    historify_db.init_database()
    ok, _ = historify_db.add_to_watchlist("RELIANCE", "NSE")
    assert ok
    _insert_like_main(db_path, ["SBIN", "INFY"])
    _sql(db_path, "DROP SEQUENCE job_items_id_seq")

    assert migration.status() is False, "--status must report that the migration is needed"
    assert _next_value(db_path, "watchlist_id_seq") == 2, "--status changed the database"
    assert _next_value(db_path, "job_items_id_seq") is None, "--status changed the database"

    assert migration.upgrade() is True
    assert _next_value(db_path, "watchlist_id_seq") == 4
    assert _next_value(db_path, "job_items_id_seq") == 1

    assert migration.upgrade() is True  # nothing left to do
    assert _next_value(db_path, "watchlist_id_seq") == 4
    assert migration.status() is True


def test_a_sequence_ahead_of_its_table_is_left_alone(db_path):
    historify_db.init_database()
    for symbol in ("RELIANCE", "SBIN", "INFY"):
        ok, _ = historify_db.add_to_watchlist(symbol, "NSE")
        assert ok
    _sql(db_path, "DELETE FROM watchlist WHERE id > 1")  # the table's MAX(id) drops to 1

    historify_db.init_database()
    assert _next_value(db_path, "watchlist_id_seq") == 4, "an ahead sequence was moved back"


def test_a_sequence_one_behind_after_a_reopen_is_advanced(db_path):
    historify_db.init_database()
    for symbol in ("RELIANCE", "SBIN"):
        ok, _ = historify_db.add_to_watchlist(symbol, "NSE")
        assert ok
    _insert_like_main(db_path, ["INFY"])  # takes ID 3, the sequence's next value
    assert _next_value(db_path, "watchlist_id_seq") == 3

    historify_db.init_database()

    assert _next_value(db_path, "watchlist_id_seq") == 4
    ok, message = historify_db.add_to_watchlist("TCS", "NSE")
    assert ok, f"a sequence one behind its table was not caught: {message}"


def test_no_historify_database_is_nothing_to_migrate(db_path):
    assert not db_path.exists()
    assert migration.upgrade() is True
    assert migration.status() is True
    assert not db_path.exists(), "the migration created a database that did not exist"


def test_the_migration_runs_with_every_update():
    # Read the list rather than import the runner, which rewraps stdout on Windows.
    tree = ast.parse((ROOT / "upgrade" / "migrate_all.py").read_text(encoding="utf-8"))
    listing = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "MIGRATIONS" for t in node.targets)
    )
    names = [name for name, _description in ast.literal_eval(listing)]
    assert "migrate_historify_sequences.py" in names
    assert names.index("migrate_historify_sequences.py") > names.index(
        "migrate_historify_drop_indexes.py"
    )
