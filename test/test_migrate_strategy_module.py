"""Regression tests for the strategy-module schema migration."""

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import inspect

from database.engine_factory import create_db_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "upgrade"))

import migrate_strategy_module as migration  # noqa: E402

OLD_SCHEMA_STAGES = (
    "initial",
    "product_release",
    "interrupted_after_position",
    "interrupted_after_stop_timestamp",
    "missing_index_only",
)


def _legacy_strategy_engine(tmp_path, stage="initial"):
    """Build a populated database at one plausible prior migration stage."""
    stage_number = OLD_SCHEMA_STAGES.index(stage)
    engine = create_db_engine(f"sqlite:///{(tmp_path / f'{stage}.db').as_posix()}")

    run_columns = ["id INTEGER PRIMARY KEY", "strategy_id INTEGER NOT NULL"]
    order_columns = [
        "id INTEGER PRIMARY KEY",
        "run_id INTEGER NOT NULL",
        "leg_id INTEGER NOT NULL",
        "kind VARCHAR(30) NOT NULL",
    ]
    if stage_number >= 1:
        order_columns.append("product VARCHAR(10)")
    if stage_number >= 2:
        order_columns.append("position_ref VARCHAR(32)")
    if stage_number >= 3:
        run_columns.append("stop_requested_at DATETIME")
    if stage_number >= 4:
        run_columns.append("stop_requested_reason VARCHAR(30)")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE sm_strategy (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
        )
        connection.exec_driver_sql(f"CREATE TABLE sm_strategy_run ({', '.join(run_columns)})")
        connection.exec_driver_sql(f"CREATE TABLE sm_strategy_order ({', '.join(order_columns)})")
        connection.exec_driver_sql("INSERT INTO sm_strategy VALUES (1, 'keep-strategy')")

        run_insert_columns = ["id", "strategy_id"]
        run_insert_values = ["1", "1"]
        if stage_number >= 3:
            run_insert_columns.append("stop_requested_at")
            run_insert_values.append("'2026-08-30 21:55:00'")
        if stage_number >= 4:
            run_insert_columns.append("stop_requested_reason")
            run_insert_values.append("'operator'")
        connection.exec_driver_sql(
            f"INSERT INTO sm_strategy_run ({', '.join(run_insert_columns)}) "
            f"VALUES ({', '.join(run_insert_values)})"
        )

        order_insert_columns = ["id", "run_id", "leg_id", "kind"]
        order_insert_values = ["1", "1", "7", "'entry'"]
        if stage_number >= 1:
            order_insert_columns.append("product")
            order_insert_values.append("'NRML'")
        if stage_number >= 2:
            order_insert_columns.append("position_ref")
            order_insert_values.append("'position-7'")
        connection.exec_driver_sql(
            f"INSERT INTO sm_strategy_order ({', '.join(order_insert_columns)}) "
            f"VALUES ({', '.join(order_insert_values)})"
        )

    return engine


def _column_details(engine, table):
    return {column["name"]: column for column in inspect(engine).get_columns(table)}


def _original_row_snapshot(engine):
    """Read only facts that existed before any runtime-safety migration."""
    with engine.connect() as connection:
        return {
            "strategy": connection.exec_driver_sql(
                "SELECT id, marker FROM sm_strategy ORDER BY id"
            ).all(),
            "run": connection.exec_driver_sql(
                "SELECT id, strategy_id FROM sm_strategy_run ORDER BY id"
            ).all(),
            "order": connection.exec_driver_sql(
                "SELECT id, run_id, leg_id, kind FROM sm_strategy_order ORDER BY id"
            ).all(),
        }


def _schema_snapshot(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name LIKE 'sm_%' ORDER BY type, name"
        ).all()


@pytest.mark.parametrize("stage", OLD_SCHEMA_STAGES)
def test_apply_upgrades_every_populated_old_stage_idempotently(tmp_path, stage):
    """Each released or interrupted old shape keeps its rows and stored truth."""
    engine = _legacy_strategy_engine(tmp_path, stage)
    try:
        before = _original_row_snapshot(engine)

        assert migration.apply(engine)
        first_schema = _schema_snapshot(engine)
        assert migration.apply(engine)

        run_columns = _column_details(engine, "sm_strategy_run")
        order_columns = _column_details(engine, "sm_strategy_order")
        assert order_columns.keys() >= {"product", "position_ref"}
        assert run_columns.keys() >= {"stop_requested_at", "stop_requested_reason"}
        assert order_columns["product"]["nullable"] is True
        assert order_columns["position_ref"]["nullable"] is True
        assert run_columns["stop_requested_at"]["nullable"] is True
        assert run_columns["stop_requested_reason"]["nullable"] is True

        indexes = {item["name"]: item for item in inspect(engine).get_indexes("sm_strategy_order")}
        assert indexes["ix_sm_order_run_leg_position"]["column_names"] == [
            "run_id",
            "leg_id",
            "position_ref",
        ]
        assert indexes["ix_sm_order_run_leg_position"]["unique"] == 0
        assert _original_row_snapshot(engine) == before
        assert _schema_snapshot(engine) == first_schema

        with engine.connect() as connection:
            migrated_order = connection.exec_driver_sql(
                "SELECT product, position_ref FROM sm_strategy_order WHERE id = 1"
            ).one()
            migrated_run = connection.exec_driver_sql(
                "SELECT stop_requested_at, stop_requested_reason FROM sm_strategy_run WHERE id = 1"
            ).one()

        assert migrated_order.product == (None if stage == "initial" else "NRML")
        assert migrated_order.position_ref == (
            "position-7" if OLD_SCHEMA_STAGES.index(stage) >= 2 else None
        )
        assert migrated_run.stop_requested_at == (
            "2026-08-30 21:55:00" if OLD_SCHEMA_STAGES.index(stage) >= 3 else None
        )
        assert migrated_run.stop_requested_reason == (
            "operator" if OLD_SCHEMA_STAGES.index(stage) >= 4 else None
        )
    finally:
        engine.dispose()


def test_status_reports_changes_without_modifying_the_database(tmp_path, capsys):
    """Status is a read-only preview even on a populated prior release."""
    engine = _legacy_strategy_engine(tmp_path, "product_release")
    try:
        before_schema = _schema_snapshot(engine)
        before_rows = _original_row_snapshot(engine)

        assert migration.status(engine) is False

        output = capsys.readouterr().out
        assert "sm_strategy_order.position_ref" in output
        assert "sm_strategy_run.stop_requested_at" in output
        assert "sm_strategy_run.stop_requested_reason" in output
        assert "ix_sm_order_run_leg_position" in output
        assert _schema_snapshot(engine) == before_schema
        assert _original_row_snapshot(engine) == before_rows
    finally:
        engine.dispose()


def test_relative_sqlite_path_is_resolved_from_project_root(tmp_path, monkeypatch):
    """The documented upgrade-directory invocation still targets the app DB."""
    monkeypatch.setattr(migration, "PROJECT_ROOT", str(tmp_path))

    resolved = migration.resolve_sqlite_path("sqlite:///db/openalgo.db")

    expected = f"sqlite:///{(tmp_path / 'db' / 'openalgo.db').as_posix()}"
    assert resolved == expected


def test_native_absolute_sqlite_path_is_not_rewritten(tmp_path):
    """Native absolute paths remain valid on both Windows and Linux runners."""
    absolute_url = f"sqlite:///{(tmp_path / 'openalgo.db').as_posix()}"

    assert migration.resolve_sqlite_path(absolute_url) == absolute_url


@pytest.mark.skipif(os.name != "nt", reason="Windows path contract")
def test_windows_drive_sqlite_path_is_not_rewritten():
    assert migration.resolve_sqlite_path("sqlite:///D:/OpenAlgo/db/openalgo.db") == (
        "sqlite:///D:/OpenAlgo/db/openalgo.db"
    )


@pytest.mark.skipif(os.name == "nt", reason="Linux path contract")
def test_linux_rooted_sqlite_path_is_not_rewritten():
    assert migration.resolve_sqlite_path("sqlite:////var/lib/openalgo/openalgo.db") == (
        "sqlite:////var/lib/openalgo/openalgo.db"
    )
