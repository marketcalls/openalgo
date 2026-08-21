#!/usr/bin/env python3
"""
Migration: Flow Workflow Tables

This migration adds the tables required for Flow workflow automation:
- flow_workflows: Stores workflow definitions (nodes, edges, webhook config)
- flow_workflow_executions: Stores workflow execution history and logs
- flow_apscheduler_jobs: APScheduler job store for scheduled workflows

This migration is idempotent - safe to run multiple times.

Usage:
    cd upgrade
    uv run migrate_flow.py           # Apply migration
    uv run migrate_flow.py --status  # Check status without changing anything
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
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

#: Job store tables are named per scheduler so Flow and Historify do not share
#: a queue. Both live in DATABASE_URL, which is where the schedulers point.
FLOW_JOBSTORE_TABLE = "flow_apscheduler_jobs"


def resolve_sqlite_path(db_url):
    """Make a relative sqlite:/// path absolute against the project root.

    The documented invocation is `cd upgrade && uv run migrate_flow.py`, and
    DATABASE_URL is relative by default ("sqlite:///db/openalgo.db"). Left
    relative it resolves against the current directory, so running from
    upgrade/ would point at upgrade/db/openalgo.db - which SQLAlchemy creates
    empty on connect. The migration would then report success having created
    its tables in a database the app never opens. migrate_all.py happens to
    avoid this by running each script with cwd set to the project root.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return db_url
    path = db_url[len(prefix) :]
    if not path or path == ":memory:" or os.path.isabs(path):
        return db_url
    return prefix + os.path.join(PROJECT_ROOT, path)


def get_database_url():
    """Get database URL from environment"""
    from dotenv import load_dotenv

    load_dotenv()
    return resolve_sqlite_path(os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db"))


def table_exists(engine, table_name):
    """Check if a table exists in the database"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def create_flow_workflows_table(engine):
    """Create flow_workflows table"""
    if table_exists(engine, "flow_workflows"):
        print("  [SKIP] flow_workflows table already exists")
        return True

    print("  [CREATE] Creating flow_workflows table...")

    # Determine SQL based on database type
    db_url = str(engine.url)
    if "sqlite" in db_url:
        sql = """
        CREATE TABLE flow_workflows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            nodes JSON DEFAULT '[]',
            edges JSON DEFAULT '[]',
            is_active BOOLEAN DEFAULT 0,
            schedule_job_id VARCHAR(255),
            webhook_token VARCHAR(64) UNIQUE,
            webhook_secret VARCHAR(64),
            webhook_enabled BOOLEAN DEFAULT 0,
            webhook_auth_type VARCHAR(20) DEFAULT 'payload',
            api_key VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    else:
        # PostgreSQL
        sql = """
        CREATE TABLE flow_workflows (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            nodes JSONB DEFAULT '[]'::jsonb,
            edges JSONB DEFAULT '[]'::jsonb,
            is_active BOOLEAN DEFAULT FALSE,
            schedule_job_id VARCHAR(255),
            webhook_token VARCHAR(64) UNIQUE,
            webhook_secret VARCHAR(64),
            webhook_enabled BOOLEAN DEFAULT FALSE,
            webhook_auth_type VARCHAR(20) DEFAULT 'payload',
            api_key VARCHAR(255),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print("  [OK] flow_workflows table created")
    return True


def column_exists(engine, table_name, column_name):
    """Whether a column is present on an existing table."""
    if not table_exists(engine, table_name):
        return False
    return column_name in {col["name"] for col in inspect(engine).get_columns(table_name)}


def add_api_key_column(engine):
    """Add flow_workflows.api_key to an installation that predates it.

    create_flow_workflows_table() returns early when the table exists, so an
    installation created before this column shipped could never gain it here.
    The only thing adding it was a startup ALTER in database/flow_db.py whose
    failures were swallowed at debug level -- so on a deployment where that
    ALTER could not run, --status still reported "All changes applied" against a
    schema with no api_key, and every workflow activation then failed silently.

    Idempotent: safe to re-run, and it never touches existing rows.
    """
    if not table_exists(engine, "flow_workflows"):
        return True
    if column_exists(engine, "flow_workflows", "api_key"):
        print("  [SKIP] flow_workflows.api_key already present")
        return True

    print("  [ALTER] Adding flow_workflows.api_key...")
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE flow_workflows ADD COLUMN api_key VARCHAR(255)"))
        conn.commit()

    print("  [OK] flow_workflows.api_key added")
    return True


def backfill_execution_started_at(engine):
    """Give historical executions a start time.

    create_execution never stamped started_at -- only
    update_execution_status("running") did, and nothing passed that status --
    so every row written before that fix has NULL. The history query ordered on
    that column, and an all-NULL sort collapsed to insertion order ascending,
    which listed the oldest runs first and made the dashboard's "last run" show
    the workflow's first ever run.

    completed_at is the best evidence available for when a finished run
    happened. A row with neither timestamp is left alone; ordering is by id now,
    so a null start time no longer misplaces it.

    Idempotent: only rows that are still NULL are touched.
    """
    if not table_exists(engine, "flow_workflow_executions"):
        return True

    with engine.connect() as conn:
        pending = conn.execute(
            text(
                "SELECT COUNT(*) FROM flow_workflow_executions "
                "WHERE started_at IS NULL AND completed_at IS NOT NULL"
            )
        ).scalar()

        if not pending:
            print("  [SKIP] execution start times already populated")
            return True

        print(f"  [BACKFILL] Setting started_at on {pending} execution(s)...")
        conn.execute(
            text(
                "UPDATE flow_workflow_executions SET started_at = completed_at "
                "WHERE started_at IS NULL AND completed_at IS NOT NULL"
            )
        )
        conn.commit()

    print("  [OK] execution start times backfilled")
    return True


def create_flow_workflow_executions_table(engine):
    """Create flow_workflow_executions table"""
    if table_exists(engine, "flow_workflow_executions"):
        print("  [SKIP] flow_workflow_executions table already exists")
        return True

    print("  [CREATE] Creating flow_workflow_executions table...")

    # Determine SQL based on database type
    db_url = str(engine.url)
    if "sqlite" in db_url:
        sql = """
        CREATE TABLE flow_workflow_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            status VARCHAR(50) DEFAULT 'pending',
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            logs JSON DEFAULT '[]',
            error TEXT,
            FOREIGN KEY (workflow_id) REFERENCES flow_workflows(id) ON DELETE CASCADE
        )
        """
    else:
        # PostgreSQL
        sql = """
        CREATE TABLE flow_workflow_executions (
            id SERIAL PRIMARY KEY,
            workflow_id INTEGER NOT NULL,
            status VARCHAR(50) DEFAULT 'pending',
            started_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            logs JSONB DEFAULT '[]'::jsonb,
            error TEXT,
            FOREIGN KEY (workflow_id) REFERENCES flow_workflows(id) ON DELETE CASCADE
        )
        """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print("  [OK] flow_workflow_executions table created")
    return True


def create_indexes(engine):
    """Create indexes for Flow tables"""
    indexes = [
        ("idx_flow_workflows_webhook_token", "flow_workflows", "webhook_token"),
        ("idx_flow_workflows_is_active", "flow_workflows", "is_active"),
        ("idx_flow_executions_workflow_id", "flow_workflow_executions", "workflow_id"),
        ("idx_flow_executions_status", "flow_workflow_executions", "status"),
        ("idx_flow_executions_started_at", "flow_workflow_executions", "started_at"),
    ]

    for index_name, table_name, column_name in indexes:
        if not table_exists(engine, table_name):
            continue

        try:
            # Check if index already exists
            inspector = inspect(engine)
            existing_indexes = [idx["name"] for idx in inspector.get_indexes(table_name)]

            if index_name in existing_indexes:
                print(f"  [SKIP] Index {index_name} already exists")
                continue

            sql = f"CREATE INDEX {index_name} ON {table_name} ({column_name})"
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            print(f"  [OK] Created index {index_name}")

        except Exception as e:
            # Index might already exist with different name
            print(f"  [SKIP] Index {index_name}: {e}")

    return True


def ensure_jobstore_index(engine, jobs_t, tablename):
    """Create the job store's next_run_time index if the table predates it.

    Table.create(checkfirst=True) tests only for the table, so a job store
    table that exists without its index would never acquire one and every
    due-job poll would scan. Checked separately for that reason.
    """
    existing = {idx["name"] for idx in inspect(engine).get_indexes(tablename)}
    for index in jobs_t.indexes:
        if index.name in existing:
            print(f"  [SKIP] Index {index.name} already exists")
            continue
        index.create(engine)
        print(f"  [OK] Created index {index.name}")


def create_apscheduler_jobstore_table(engine, tablename):
    """Create an APScheduler job store table.

    Built from APScheduler's own table metadata rather than hand-written SQL,
    so the schema cannot drift from whatever APScheduler expects and the
    ix_<tablename>_next_run_time index is created with it.

    Creating this in the migration rather than leaving it to the runtime is the
    point of the change. SQLAlchemyJobStore.start() issues this CREATE TABLE
    itself, and at startup that DDL lands in the middle of the boot write burst
    needing an exclusive write lock on the database. An install that loses that
    race logs "database is locked", the scheduler never initializes, and since
    init runs once at boot with no retry, scheduled workflows silently never
    run for the life of the process. See issue #1750.
    """
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

    # engine= rather than url= so this reuses the caller's engine instead of
    # opening a second one that would then have to be disposed.
    jobs_t = SQLAlchemyJobStore(engine=engine, tablename=tablename).jobs_t

    if table_exists(engine, tablename):
        print(f"  [SKIP] {tablename} table already exists")
    else:
        print(f"  [CREATE] Creating {tablename} table...")
        jobs_t.create(engine, checkfirst=True)
        print(f"  [OK] {tablename} table created")

    ensure_jobstore_index(engine, jobs_t, tablename)
    return True


def status(engine):
    """Report what exists without changing anything."""
    print()
    print("Flow migration status")
    print("-" * 40)

    applied = True
    for table in ("flow_workflows", "flow_workflow_executions", FLOW_JOBSTORE_TABLE):
        present = table_exists(engine, table)
        print(f"  {table:<26} {'present' if present else 'MISSING'}")
        applied = applied and present

    if table_exists(engine, "flow_workflows"):
        present = column_exists(engine, "flow_workflows", "api_key")
        print(f"  {'flow_workflows.api_key':<26} {'present' if present else 'MISSING'}")
        applied = applied and present

    if table_exists(engine, "flow_workflow_executions"):
        with engine.connect() as conn:
            pending = conn.execute(
                text(
                    "SELECT COUNT(*) FROM flow_workflow_executions "
                    "WHERE started_at IS NULL AND completed_at IS NOT NULL"
                )
            ).scalar()
        label = "execution started_at"
        print(f"  {label:<26} {'present' if not pending else f'{pending} MISSING'}")
        applied = applied and not pending

    if table_exists(engine, FLOW_JOBSTORE_TABLE):
        index_name = f"ix_{FLOW_JOBSTORE_TABLE}_next_run_time"
        names = {idx["name"] for idx in inspect(engine).get_indexes(FLOW_JOBSTORE_TABLE)}
        present = index_name in names
        print(f"  {index_name:<26} {'present' if present else 'MISSING'}")
        applied = applied and present

    print("-" * 40)
    print("All changes applied." if applied else "Migration needed.")
    return applied


def main():
    """Run the migration"""
    parser = argparse.ArgumentParser(description="Flow workflow tables migration")
    parser.add_argument(
        "--status", action="store_true", help="Report status without changing anything"
    )
    args = parser.parse_args()

    print()
    print("Flow Workflow Tables Migration")
    print("-" * 40)

    try:
        # Get database URL
        db_url = get_database_url()
        print(f"Database: {db_url.split('://')[0]}://...")

        # Create engine
        if "sqlite" in db_url:
            engine = create_engine(db_url, poolclass=NullPool)
        else:
            engine = create_engine(db_url)

        if args.status:
            return 0 if status(engine) else 1

        # Run migrations
        print()
        print("Creating tables...")
        create_flow_workflows_table(engine)
        add_api_key_column(engine)
        create_flow_workflow_executions_table(engine)
        backfill_execution_started_at(engine)
        create_apscheduler_jobstore_table(engine, FLOW_JOBSTORE_TABLE)

        print()
        print("Creating indexes...")
        create_indexes(engine)

        print()
        print("[OK] Flow migration completed successfully!")
        return 0

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
