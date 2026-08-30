"""Regression tests for the strategy-module schema migration."""

import sys
from pathlib import Path

from sqlalchemy import inspect

from database.engine_factory import create_db_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "upgrade"))

import migrate_strategy_module as migration  # noqa: E402


def _legacy_strategy_engine(tmp_path):
    """Build a populated database from before the runtime-safety columns."""
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'legacy-strategy.db').as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE sm_strategy (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE sm_strategy_run (id INTEGER PRIMARY KEY, strategy_id INTEGER NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE sm_strategy_order ("
            "id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, leg_id INTEGER NOT NULL, "
            "kind VARCHAR(30) NOT NULL)"
        )
        connection.exec_driver_sql("INSERT INTO sm_strategy (id) VALUES (1)")
        connection.exec_driver_sql("INSERT INTO sm_strategy_run (id, strategy_id) VALUES (1, 1)")
        connection.exec_driver_sql(
            "INSERT INTO sm_strategy_order (id, run_id, leg_id, kind) VALUES (1, 1, 1, 'entry')"
        )
    return engine


def _column_names(engine, table):
    return {column["name"] for column in inspect(engine).get_columns(table)}


def _row_counts(engine):
    with engine.connect() as connection:
        return {
            table: connection.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one()
            for table in ("sm_strategy", "sm_strategy_run", "sm_strategy_order")
        }


def test_apply_adds_runtime_safety_columns_without_changing_rows(tmp_path):
    engine = _legacy_strategy_engine(tmp_path)
    try:
        before = _row_counts(engine)

        assert migration.apply(engine)
        assert _column_names(engine, "sm_strategy_order") >= {"position_ref"}
        assert _column_names(engine, "sm_strategy_run") >= {
            "stop_requested_at",
            "stop_requested_reason",
        }
        assert {index["name"] for index in inspect(engine).get_indexes("sm_strategy_order")} >= {
            "ix_sm_order_run_leg_position"
        }
        assert _row_counts(engine) == before
        assert migration.apply(engine)
    finally:
        engine.dispose()


def test_status_reports_missing_runtime_safety_columns_and_index(tmp_path, capsys):
    engine = _legacy_strategy_engine(tmp_path)
    try:
        assert migration.status(engine) is False

        output = capsys.readouterr().out
        assert "sm_strategy_order.position_ref" in output
        assert "sm_strategy_run.stop_requested_at" in output
        assert "sm_strategy_run.stop_requested_reason" in output
        assert "ix_sm_order_run_leg_position" in output
    finally:
        engine.dispose()
