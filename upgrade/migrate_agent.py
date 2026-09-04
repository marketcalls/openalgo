#!/usr/bin/env python3
"""
Migration: Agent module (/agent)

Adds the six tables backing the LLM agent, all prefixed ``ag_``:

- ag_provider_model   one row per model the operator has enabled
- ag_secret           Fernet ciphertext for a provider or per-model API key
- ag_setting          key/value agent settings, so a new setting needs no migration
- ag_conversation     what the chat and chart surfaces list
- ag_message          what those surfaces render
- ag_audit            append-only record of every mutating tool call

All six are new, so there is nothing to backfill and no existing value to
preserve. This script adds tables and touches nothing else: no other feature's
table is read, altered or dropped by it.

Why this exists at all, given init_db() already creates them. Roughly 290k live
deployments upgrade with `cd upgrade && uv run migrate_all.py`, and a schema
change that lives only in init_db() never reaches them: create_all skips a
database whose tables are already there, and a seeding function typically only
runs against an empty table. This script is the path that reaches an existing
installation.

The DDL is read from the ORM metadata in database/agent_db.py rather than
written out by hand. Six tables with a dozen indexes between them is a lot of
surface for a transcription error, and a hand-written CREATE TABLE that drifts
from the model produces the worst kind of bug: the app starts, the query
compiles, and one column silently holds the wrong thing.

Three arrival orders, all of which this survives:

1. Fresh install. The tables do not exist and this creates them.
2. App started first. init_db() has already created them through create_all,
   so this finds them present and reports nothing to do. It does not fail and
   it does not recreate anything.
3. Run twice. Identical to the second case.

Column and index drift is read from the same metadata, not from a hand-kept
list. create_all(checkfirst=True) skips a table it finds present, so a column
added to a model after the table first shipped never reaches an installation
that already has the table: the migration used to report "Up to date. Nothing to
do." while ``list_models()`` was raising ``no such column`` on every call and
returning an empty list to the settings page. Comparing the live schema against
the metadata is what makes that impossible to miss, and it costs the next author
nothing to remember.

What the repair will and will not do. A missing index is created, and a missing
column is added when SQLite can add one in place - that is, when it is nullable,
or carries a default constant enough to write into the ALTER. Anything else
(a new primary key, a new UNIQUE column, a new NOT NULL column with no usable
default) is **reported and refused** rather than guessed at, because SQLite
cannot add those in place at all and the fix is a table rebuild with a backfill
derived from the rows themselves. See CLAUDE.md on migrations, and
``migrate_sandbox_trigger_pending.py`` for what a rebuild looks like. Refusing
is the point: a migration that cannot finish the job must say so instead of
reporting success.

There is deliberately **no seed step**, and adding one would be a defect rather
than an omission:

- Every agent setting resolves to a code default when its ``ag_setting`` row is
  absent (``services/agent/settings.py``). Writing the shipped defaults out as
  rows would turn "the operator never chose" into "the operator chose this", so
  the next release could no longer change a default for anyone who had run the
  migration. ``trading_enabled`` and ``require_analyzer_mode`` are the two that
  matter, and both are meant to follow the shipped value until an operator sets
  them.
- The ChatGPT subscription credential is an ``ag_secret`` row named
  ``oauth:chatgpt``, and every web search key is one named ``websearch:{id}``.
  They are rows in a table this script creates, written by the operator through
  the UI. None of them is a schema object and none can be seeded: there is no
  credential to write until somebody signs in.

This migration is idempotent - safe to run multiple times.

Usage:
    cd upgrade
    uv run migrate_agent.py           # Apply migration
    uv run migrate_agent.py --status  # Check status without changing anything
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add parent directory to path for imports
sys.path.insert(0, PROJECT_ROOT)
# Register the app's SQLite pragmas on this process's engines, so a migration
# waits the same 15s for a write lock the running app does instead of the
# sqlite3 default of 5s (GitHub issue #1726).
import _pragmas  # noqa: F401,E402
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateIndex

#: Table names in dependency order: ag_conversation before ag_message, which
#: carries a foreign key to it. create_all sorts this itself, but --status reads
#: better in this order and a human comparing the two lists should not have to.
#:
#: This is a display order and nothing more. :func:`expected_tables` takes the
#: set from the models, so a table added there and forgotten here is still
#: created.
TABLES = (
    "ag_provider_model",
    "ag_secret",
    "ag_setting",
    "ag_conversation",
    "ag_message",
    "ag_audit",
)


def resolve_sqlite_path(db_url):
    """Make a relative sqlite:/// path absolute against the project root.

    The documented invocation is `cd upgrade && uv run migrate_agent.py`, and
    DATABASE_URL is relative by default ("sqlite:///db/openalgo.db"). Left
    relative it resolves against the current directory, so running from upgrade/
    would point at upgrade/db/openalgo.db - which SQLAlchemy creates empty on
    connect. The migration would then report success having created its tables
    in a database the app never opens.

    Args:
        db_url: The DATABASE_URL as configured.

    Returns:
        The same URL with any relative sqlite path made absolute. A non-sqlite
        URL is returned unchanged.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return db_url
    path = db_url[len(prefix) :]
    if os.path.isabs(path):
        return db_url
    return prefix + os.path.join(PROJECT_ROOT, path).replace("\\", "/")


def get_database_url():
    """Read DATABASE_URL from the environment, with the project default.

    Returns:
        The resolved database URL.
    """
    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    return resolve_sqlite_path(os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db"))


def sqlite_file(db_url):
    """The filesystem path a sqlite URL points at, or None for other backends.

    Args:
        db_url: A resolved database URL.

    Returns:
        The absolute path, or None when the URL is not sqlite.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return None
    return db_url[len(prefix) :]


def load_metadata():
    """The agent ORM metadata, which is the source of the DDL.

    Imported here rather than at module scope so nothing is built until it is
    needed. --status calls this too, once it has found at least one table to
    compare against, and that is safe: importing the module builds a lazy
    SQLAlchemy engine and a scoped session, neither of which opens a connection
    or creates a file. Only ``apply`` ever writes.

    Returns:
        The SQLAlchemy MetaData carrying the six ``ag_`` tables.
    """
    from database.agent_db import Base

    return Base.metadata


def expected_tables():
    """Every table the models declare, in a stable and readable order.

    ``TABLES`` is the order a human wants to read them in; the metadata is the
    authority on which of them exist. Deriving the set from the metadata closes
    the same gap ``schema_drift`` closes for columns: a seventh model added
    without an entry in ``TABLES`` would otherwise be skipped entirely on every
    installation that already has the six, because the branch which never calls
    ``create_all`` is the one taken when nothing in ``TABLES`` is missing.

    Returns:
        The declared table names, those named in TABLES first.
    """
    declared = set(load_metadata().tables)
    return [name for name in TABLES if name in declared] + sorted(declared - set(TABLES))


def missing_tables(engine):
    """Which of our tables are not in the database yet.

    Args:
        engine: An engine bound to the target database.

    Returns:
        The absent table names, in :func:`expected_tables` order.
    """
    present = set(inspect(engine).get_table_names())
    return [table for table in expected_tables() if table not in present]


def _sql_literal(value):
    """One Python default rendered as a SQL literal, or None when it cannot be.

    Only the constant kinds a column default is ever written as. Anything else
    (a callable, a SQL expression, a sequence) has no single value to put in an
    ALTER and is refused by the caller rather than guessed at.

    Args:
        value: The default's own value.

    Returns:
        The literal text, or None.
    """
    if isinstance(value, bool):
        # SQLite has no boolean literal; SQLAlchemy stores these as 0 and 1.
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return None


def _default_literal(column):
    """The constant a new column should be filled with, or None.

    Args:
        column: The SQLAlchemy Column.

    Returns:
        The literal text for a DEFAULT clause, or None when the column's
        default is not a constant. ``created_at``'s default is a lambda, which
        is exactly the case that must come back None: every existing row would
        otherwise be stamped with the moment the migration ran.
    """
    if column.server_default is not None:
        arg = getattr(column.server_default, "arg", None)
        return None if arg is None else str(arg)
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    return _sql_literal(default.arg)


def column_add_clause(engine, column):
    """The ``ADD COLUMN`` clause for one column, or None when SQLite refuses it.

    SQLite's ALTER TABLE will not add a primary key, a UNIQUE column, or a NOT
    NULL column with no non-null default, and a column with a foreign key has
    its own restrictions. Each of those needs the table rebuilt, so None is the
    honest answer and the caller reports it rather than attempting the ALTER
    and reporting whatever SQLite says.

    Args:
        engine: An engine bound to the target database, for its dialect.
        column: The SQLAlchemy Column the ORM expects.

    Returns:
        The clause text, or None when the column cannot be added in place.
    """
    if column.primary_key or column.unique or column.foreign_keys:
        return None

    spec = engine.dialect.ddl_compiler(engine.dialect, None).get_column_specification(column)
    if column.nullable or " DEFAULT " in spec.upper():
        return spec

    literal = _default_literal(column)
    if literal is None:
        return None
    return f"{spec} DEFAULT {literal}"


def schema_drift(engine):
    """What the models expect that the database does not have, table by table.

    Only tables that already exist are compared. One that is absent is created
    whole by ``create_all``, with every column, index and constraint on it.

    Args:
        engine: An engine bound to the target database.

    Returns:
        ``(columns, indexes, rebuilds)``. ``columns`` is a list of
        ``(table, name, clause)`` that can be added in place; ``indexes`` is a
        list of ``(table, name, ddl)``; ``rebuilds`` is a list of
        ``(table, what, reason)`` naming everything that needs the table rebuilt
        instead, which this script will not do unattended.
    """
    inspector = inspect(engine)
    present = set(inspector.get_table_names())
    metadata = load_metadata()

    columns = []
    indexes = []
    rebuilds = []

    for name in TABLES:
        if name not in present:
            continue
        table = metadata.tables[name]

        live_columns = {item["name"] for item in inspector.get_columns(name)}
        for column in table.columns:
            if column.name in live_columns:
                continue
            clause = column_add_clause(engine, column)
            if clause is None:
                rebuilds.append(
                    (name, f"column {column.name}", "SQLite cannot add this column in place")
                )
            else:
                columns.append((name, column.name, clause))

        live_indexes = {item["name"] for item in inspector.get_indexes(name)}
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            if index.name not in live_indexes:
                ddl = str(CreateIndex(index).compile(engine)).strip()
                indexes.append((name, index.name, ddl))

        # A UNIQUE constraint is separate from a unique index and SQLite cannot
        # add one to an existing table at all. Reported so it cannot pass
        # unnoticed; CLAUDE.md's answer is a partial unique index or a rebuild.
        live_unique = {item["name"] for item in inspector.get_unique_constraints(name)}
        for constraint in table.constraints:
            if constraint.__class__.__name__ != "UniqueConstraint" or not constraint.name:
                continue
            if constraint.name not in live_unique:
                rebuilds.append(
                    (
                        name,
                        f"unique constraint {constraint.name}",
                        "SQLite cannot add a UNIQUE constraint in place",
                    )
                )

    return columns, indexes, rebuilds


def apply_drift(engine, columns, indexes):
    """Add the missing columns, then the missing indexes.

    Columns first: an index declared over a column that is not there yet cannot
    be created, and a partially applied run has to be able to finish on the
    next one.

    Args:
        engine: An engine bound to the target database.
        columns: ``(table, name, clause)`` triples from :func:`schema_drift`.
        indexes: ``(table, name, ddl)`` triples from :func:`schema_drift`.

    Returns:
        True when everything asked for is now in place.
    """
    for table, name, clause in columns:
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {clause}")
        except Exception as exc:
            print(f"  [FAIL] Could not add {table}.{name}: {exc}")
            return False
        print(f"  [OK] Added column {table}.{name}")

    for table, name, ddl in indexes:
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(ddl)
        except Exception as exc:
            print(f"  [FAIL] Could not create index {name} on {table}: {exc}")
            return False
        print(f"  [OK] Created index {name} on {table}")

    return True


def status(engine, db_url):
    """Report what would change, without changing anything.

    Reads nothing when the sqlite file does not exist yet: connecting would
    create it, and an empty database file is exactly the kind of side effect
    --status must not have.

    Args:
        engine: An engine bound to the target database.
        db_url: The resolved database URL, used to find the sqlite file.

    Returns:
        True when the schema is already up to date, False when work is pending.
    """
    print("\nAgent module table status")
    print("-" * 46)

    path = sqlite_file(db_url)
    if path is not None and not os.path.exists(path):
        for table in TABLES:
            print(f"  {table:<22} MISSING")
        print("-" * 46)
        print("Database file does not exist yet. Not created: --status changes nothing.")
        print(f"Migration needed. Would create {len(TABLES)} table(s).")
        return False

    inspector = inspect(engine)
    present = set(inspector.get_table_names())

    try:
        declared = expected_tables()
        columns, indexes, rebuilds = schema_drift(engine)
    except Exception as exc:
        # Reported rather than raised. The models are imported for this, and a
        # half-finished install is exactly the state in which that import can
        # fail; a traceback out of a command that promises to change nothing
        # tells an operator far less than one line naming the cause.
        print("-" * 46)
        print(f"Could not read the agent models: {type(exc).__name__}: {exc}")
        print("Nothing was changed. Fix the installation and run --status again.")
        return False

    for table in declared:
        if table in present:
            count = len(inspector.get_indexes(table))
            print(f"  {table:<22} present, {count} index(es)")
        else:
            print(f"  {table:<22} MISSING")
    print("-" * 46)

    absent = [table for table in declared if table not in present]

    if not absent and not columns and not indexes and not rebuilds:
        print("Up to date. Nothing to do.")
        return True

    if absent:
        print(f"Migration needed. Would create {len(absent)} table(s):")
        for table in absent:
            print(f"  {table}")
    if columns:
        print(f"Migration needed. Would add {len(columns)} column(s):")
        for table, name, _clause in columns:
            print(f"  {table}.{name}")
    if indexes:
        print(f"Migration needed. Would create {len(indexes)} index(es):")
        for table, name, _ddl in indexes:
            print(f"  {name} on {table}")
    if rebuilds:
        # Said here rather than at apply time only, so an operator can see it
        # coming and an author sees it the moment they add the column.
        print(f"Cannot be applied in place ({len(rebuilds)}); the table needs rebuilding:")
        for table, what, reason in rebuilds:
            print(f"  {table}: {what} - {reason}")
    return False


def apply(engine):
    """Create whatever is missing. An existing table keeps its rows.

    Args:
        engine: An engine bound to the target database.

    Returns:
        True on success, False when a table that should exist still does not,
        or when the schema has drifted somewhere SQLite cannot follow in place.
    """
    try:
        metadata = load_metadata()
        absent = missing_tables(engine)
    except Exception as exc:
        # A [FAIL] line and a False return, not a traceback out of main(). The
        # models are imported here, and on a half-finished install that import
        # is the thing most likely to fail.
        print(f"  [FAIL] Could not read the agent models: {type(exc).__name__}: {exc}")
        return False

    if absent:
        # checkfirst=True is what makes this safe to re-run: a table that
        # already exists is skipped rather than raising, so a partially applied
        # migration (interrupted midway, or half created by an app that started
        # first) completes cleanly on the next run.
        try:
            metadata.create_all(bind=engine, checkfirst=True)
        except Exception as exc:
            print(f"  [FAIL] Could not create the agent tables: {exc}")
            return False

        still_missing = missing_tables(engine)
        if still_missing:
            print(f"  [FAIL] These tables were not created: {', '.join(still_missing)}")
            return False

        for table in absent:
            print(f"  [OK] Created {table}")

    # Not "nothing to do" once the tables are there. create_all skips a table it
    # finds present, so a column or an index added to a model after the table
    # first shipped only ever arrives through this path. A partially applied run
    # can also leave some tables new and some old, which is why this runs after
    # the create rather than instead of it.
    columns, indexes, rebuilds = schema_drift(engine)
    if rebuilds:
        print("  [FAIL] The models expect changes SQLite cannot apply in place:")
        for table, what, reason in rebuilds:
            print(f"         {table}: {what} - {reason}")
        print("         Rebuild the table in its own migration script and backfill from")
        print("         the rows themselves. See upgrade/migrate_sandbox_trigger_pending.py.")
        return False

    if not absent and not columns and not indexes:
        print("  All agent tables already present and current. Nothing to do.")
        return True

    return apply_drift(engine, columns, indexes)


def main():
    """Entry point.

    Returns:
        0 on success, 1 when the migration could not be applied.
    """
    parser = argparse.ArgumentParser(description="Agent module schema migration")
    parser.add_argument(
        "--status",
        action="store_true",
        help="Report what would change without changing anything",
    )
    args = parser.parse_args()

    db_url = get_database_url()
    shown = db_url if not db_url.startswith("sqlite") else "sqlite://..."
    print("\nAgent Module Migration")
    print("-" * 46)
    print(f"Database: {shown}")

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        if args.status:
            status(engine, db_url)
            return 0

        print("\nApplying migration...")
        ok = apply(engine)
        print("-" * 46)
        if ok:
            print("Migration complete.")
            return 0
        print("Migration failed. See the messages above.")
        return 1
    finally:
        # A migration is a short-lived process, but disposing is what keeps the
        # SQLite file unlocked for the app that may be waiting on it.
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
