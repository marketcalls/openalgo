"""Regression tests for the agent-module schema migration.

The failure these exist for: ``create_all(checkfirst=True)`` skips a table it
finds present, so a column added to a model after the table first shipped never
reaches an installation that already has the table. Before ``schema_drift``,
``upgrade/migrate_agent.py`` printed "Up to date. Nothing to do." against
exactly that database, while ``database.agent_db.list_models`` raised
``no such column`` on every call and returned an empty list to the settings
page. A migration that cannot finish the job has to say so.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import Boolean, Column, DateTime, Integer, String, inspect

from database.engine_factory import create_db_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "upgrade"))

import migrate_agent as migration  # noqa: E402


def _metadata():
    """The ORM metadata the migration builds its DDL from."""
    return migration.load_metadata()


def _engine(tmp_path, name):
    """An engine on a scratch SQLite file. The caller disposes it."""
    return create_db_engine(f"sqlite:///{(tmp_path / name).as_posix()}")


def _seed_unrelated_tables(engine):
    """Two non-agent tables with rows, standing in for an existing install."""
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE auth (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        connection.exec_driver_sql(
            "CREATE TABLE symtoken (id INTEGER PRIMARY KEY, symbol TEXT NOT NULL)"
        )
        connection.exec_driver_sql("INSERT INTO auth VALUES (1, 'keep-me')")
        connection.exec_driver_sql("INSERT INTO symtoken VALUES (1, 'SBIN')")


def _unrelated_snapshot(engine):
    """Everything about the non-agent half of the database.

    The ESCAPE clause is not decoration. SQLite's LIKE knows only ``%`` and
    ``_``, so the character class an author reaches for first, ``'ag[_]%'``,
    matches nothing at all: every comparison built on it holds trivially and
    the test proves the opposite of what it claims.
    """
    with engine.connect() as connection:
        schema = connection.exec_driver_sql(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE tbl_name NOT LIKE 'ag@_%' ESCAPE '@' ORDER BY type, name"
        ).all()
        rows = {
            "auth": connection.exec_driver_sql("SELECT id, name FROM auth ORDER BY id").all(),
            "symtoken": connection.exec_driver_sql(
                "SELECT id, symbol FROM symtoken ORDER BY id"
            ).all(),
        }
    assert schema, "the non-agent snapshot is empty; the comparison would be vacuous"
    return schema, rows


def _agent_schema(engine):
    """Every agent object in the database, as SQLite stored it.

    See :func:`_unrelated_snapshot` on the ESCAPE clause.
    """
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE tbl_name LIKE 'ag@_%' ESCAPE '@' ORDER BY type, name"
        ).all()
    assert rows, "the agent snapshot is empty; the comparison would be vacuous"
    return rows


def _columns(engine, table):
    return {column["name"] for column in inspect(engine).get_columns(table)}


def _indexes(engine, table):
    return {index["name"] for index in inspect(engine).get_indexes(table)}


def test_a_model_missing_from_the_readable_list_is_still_created(tmp_path, monkeypatch):
    """TABLES is a display order, not the authority on what exists.

    Left as the authority, a seventh model added without an entry there would be
    skipped on every installation that already has the six, because the branch
    which never calls create_all is the one taken when nothing listed is
    missing.
    """
    monkeypatch.setattr(migration, "TABLES", migration.TABLES[:-1])
    engine = _engine(tmp_path, "unlisted.db")
    try:
        assert "ag_audit" in migration.expected_tables()
        assert migration.apply(engine)

        assert "ag_audit" in inspect(engine).get_table_names()
        assert migration.missing_tables(engine) == []
    finally:
        engine.dispose()


def test_unreadable_models_are_reported_not_raised(tmp_path, monkeypatch, capsys):
    """A half-finished install must get one line, never a traceback."""

    def _broken():
        raise ImportError("simulated: the application package is not installed")

    monkeypatch.setattr(migration, "load_metadata", _broken)
    engine = _engine(tmp_path, "broken.db")
    try:
        # The file has to exist, or status returns before it needs the models.
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
        capsys.readouterr()

        assert migration.status(engine, "postgresql://x") is False
        assert "Could not read the agent models" in capsys.readouterr().out

        assert migration.apply(engine) is False
        assert "Could not read the agent models" in capsys.readouterr().out
    finally:
        engine.dispose()


def test_fresh_database_gets_every_table_column_and_index(tmp_path):
    """A first run builds exactly what the models declare, nothing missing."""
    engine = _engine(tmp_path, "fresh.db")
    try:
        assert migration.apply(engine)

        metadata = _metadata()
        assert set(migration.TABLES) == set(metadata.tables)
        assert migration.missing_tables(engine) == []
        for name in migration.TABLES:
            table = metadata.tables[name]
            assert _columns(engine, name) == {column.name for column in table.columns}
            assert _indexes(engine, name) >= {index.name for index in table.indexes}

        columns, indexes, rebuilds = migration.schema_drift(engine)
        assert (columns, indexes, rebuilds) == ([], [], [])
    finally:
        engine.dispose()


def test_second_run_is_a_no_op(tmp_path, capsys):
    """Re-running changes nothing and still succeeds."""
    engine = _engine(tmp_path, "twice.db")
    try:
        assert migration.apply(engine)
        first = _agent_schema(engine)
        capsys.readouterr()

        assert migration.apply(engine)

        assert "Nothing to do" in capsys.readouterr().out
        assert _agent_schema(engine) == first
        assert migration.status(engine, "postgresql://x") is True
    finally:
        engine.dispose()


def test_install_that_never_ran_this_migration_keeps_its_other_data(tmp_path):
    """The populated-database case: agent tables arrive, nothing else moves."""
    engine = _engine(tmp_path, "old_schema.db")
    try:
        _seed_unrelated_tables(engine)
        before = _unrelated_snapshot(engine)

        assert migration.apply(engine)

        assert migration.missing_tables(engine) == []
        assert _unrelated_snapshot(engine) == before
    finally:
        engine.dispose()


def test_table_that_predates_a_column_is_repaired_and_keeps_its_rows(tmp_path):
    """The silent-pass defect: a present table one column and one index short."""
    engine = _engine(tmp_path, "drifted.db")
    try:
        assert migration.apply(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO ag_provider_model (provider_kind, model_name, display_name, "
                "enabled, is_default, supports_reasoning, default_reasoning_effort, "
                "supports_vision, tools_unreliable, created_at, updated_at) "
                "VALUES ('openai', 'gpt-5.4', 'Kept', 1, 1, 0, 'off', 0, 0, "
                "'2026-09-01 00:00:00', '2026-09-01 00:00:00')"
            )
            connection.exec_driver_sql("ALTER TABLE ag_provider_model DROP COLUMN tools_unreliable")
            connection.exec_driver_sql("DROP INDEX ix_ag_message_conversation_created")

        columns, indexes, rebuilds = migration.schema_drift(engine)
        assert [(t, c) for t, c, _clause in columns] == [("ag_provider_model", "tools_unreliable")]
        assert [(t, i) for t, i, _ddl in indexes] == [
            ("ag_message", "ix_ag_message_conversation_created")
        ]
        assert rebuilds == []

        assert migration.status(engine, "postgresql://x") is False
        assert migration.apply(engine)

        assert "tools_unreliable" in _columns(engine, "ag_provider_model")
        assert "ix_ag_message_conversation_created" in _indexes(engine, "ag_message")
        with engine.connect() as connection:
            kept = connection.exec_driver_sql(
                "SELECT display_name, tools_unreliable FROM ag_provider_model"
            ).all()
        # The row survives, and the new column holds the model's own default
        # rather than anything invented for it.
        assert kept == [("Kept", 0)]

        assert migration.apply(engine)
        assert migration.schema_drift(engine) == ([], [], [])
    finally:
        engine.dispose()


def test_a_column_sqlite_cannot_add_is_refused_rather_than_half_applied(tmp_path, capsys):
    """A NOT NULL column with no constant default needs a rebuild, not a guess."""
    engine = _engine(tmp_path, "refused.db")
    try:
        assert migration.apply(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE ag_conversation DROP COLUMN created_at")
            connection.exec_driver_sql("DROP INDEX ix_ag_message_conversation_id")
        before = _agent_schema(engine)
        capsys.readouterr()

        assert migration.apply(engine) is False

        output = capsys.readouterr().out
        assert "ag_conversation: column created_at" in output
        assert "migrate_sandbox_trigger_pending.py" in output
        # Refused wholesale: the index that could have been created is left
        # alone, so a half-repaired schema is never reported as a failure that
        # already changed something.
        assert _agent_schema(engine) == before
    finally:
        engine.dispose()


def test_status_previews_without_touching_the_database(tmp_path, capsys):
    """--status is read-only on a drifted database as well as a fresh one."""
    engine = _engine(tmp_path, "preview.db")
    try:
        _seed_unrelated_tables(engine)
        assert migration.apply(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE ag_provider_model DROP COLUMN tools_unreliable")
        before_agent = _agent_schema(engine)
        before_other = _unrelated_snapshot(engine)
        capsys.readouterr()

        assert migration.status(engine, "postgresql://x") is False

        assert "ag_provider_model.tools_unreliable" in capsys.readouterr().out
        assert _agent_schema(engine) == before_agent
        assert _unrelated_snapshot(engine) == before_other
    finally:
        engine.dispose()


def test_status_does_not_create_a_missing_sqlite_file(tmp_path, capsys):
    """Previewing an install that has no database yet must not make one."""
    target = tmp_path / "absent.db"
    url = f"sqlite:///{target.as_posix()}"
    engine = create_db_engine(url)
    try:
        assert migration.status(engine, url) is False

        assert "--status changes nothing" in capsys.readouterr().out
        assert not target.exists()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("column", "addable"),
    [
        (Column("nullable_text", String(20)), True),
        (Column("flag", Boolean, nullable=False, default=False), True),
        (Column("effort", String(16), nullable=False, default="off"), True),
        (Column("count", Integer, nullable=False, default=7), True),
        # A lambda default has no single value to write into an ALTER, and
        # stamping every existing row with the moment the migration ran would
        # be a backfill from a uniform default rather than from the data.
        (Column("stamped", DateTime, nullable=False, default=lambda: None), False),
        (Column("ident", Integer, primary_key=True), False),
        (Column("handle", String(40), unique=True), False),
    ],
)
def test_column_add_clause_only_accepts_what_sqlite_can_add_in_place(tmp_path, column, addable):
    """The rule that decides between an ALTER and a table rebuild."""
    engine = _engine(tmp_path, "clause.db")
    try:
        clause = migration.column_add_clause(engine, column)

        assert (clause is not None) is addable
        if addable and not column.nullable:
            assert " DEFAULT " in clause
    finally:
        engine.dispose()


def test_boolean_and_text_defaults_render_as_sqlite_literals():
    """Booleans become 0/1 and a quote inside a text default is escaped."""
    assert migration._sql_literal(True) == "1"
    assert migration._sql_literal(False) == "0"
    assert migration._sql_literal("o'clock") == "'o''clock'"
    assert migration._sql_literal(None) is None
    assert migration._sql_literal([1]) is None


def test_relative_sqlite_path_is_resolved_from_project_root(tmp_path, monkeypatch):
    """The documented upgrade-directory invocation still targets the app DB."""
    monkeypatch.setattr(migration, "PROJECT_ROOT", str(tmp_path))

    resolved = migration.resolve_sqlite_path("sqlite:///db/openalgo.db")

    assert resolved == f"sqlite:///{(tmp_path / 'db' / 'openalgo.db').as_posix()}"


def test_absolute_sqlite_path_is_not_rewritten(tmp_path):
    """An absolute path is already unambiguous on every platform."""
    absolute_url = f"sqlite:///{(tmp_path / 'openalgo.db').as_posix()}"

    assert migration.resolve_sqlite_path(absolute_url) == absolute_url


def test_migration_is_registered_in_the_master_runner_exactly_once():
    """A schema migration nothing dispatches never reaches an installation."""
    # Imported under a patched platform for the same reason test_migrate_all.py
    # does it: on win32 the runner replaces sys.stdout at import, which breaks
    # pytest's capture for every test that runs after this one.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with patch.object(sys, "platform", "test"):
        from upgrade import migrate_all

    names = [script for script, _description in migrate_all.MIGRATIONS]

    assert names.count("migrate_agent.py") == 1
    assert names.index("migrate_agent.py") > names.index("migrate_strategy_module.py")
