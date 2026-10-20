#!/usr/bin/env python
"""
Historify Scheduler Migration Script for OpenAlgo

This migration adds scheduler tables to the Historify DuckDB database:
- historify_schedules: Store schedule configurations
- historify_schedule_executions: Store execution history

and the scheduler's job store to the main SQLite database (DATABASE_URL):
- historify_apscheduler_jobs: APScheduler job store for scheduled downloads

Usage:
    cd upgrade
    uv run migrate_historify_scheduler.py           # Apply migration
    uv run migrate_historify_scheduler.py --status  # Check status

Migration: 011
Created: 2025-01-25
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Register the app's SQLite pragmas on this process's engines, so a migration
# waits the same 15s for a write lock the running app does instead of the
# sqlite3 default of 5s (GitHub issue #1726).
import _pragmas  # noqa: F401,E402
from dotenv import load_dotenv

from utils.logging import get_logger

logger = get_logger(__name__)

# Migration metadata
MIGRATION_NAME = "historify_scheduler_tables"
MIGRATION_VERSION = "011"

# Load environment
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(parent_dir, ".env"))

# Database path
HISTORIFY_DB_PATH = os.getenv("HISTORIFY_DATABASE_PATH", "db/historify.duckdb")


def get_db_path():
    """Get absolute path to the DuckDB database file."""
    if os.path.isabs(HISTORIFY_DB_PATH):
        return HISTORIFY_DB_PATH
    return os.path.join(parent_dir, HISTORIFY_DB_PATH)


def check_duckdb_available():
    """Check if DuckDB is installed."""
    try:
        import duckdb

        logger.info(f"DuckDB version: {duckdb.__version__}")
        return True
    except ImportError:
        logger.error("DuckDB is not installed. Please run: pip install duckdb")
        return False


def table_exists(conn, table_name):
    """Check if a table exists in the database."""
    result = conn.execute(f"""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = '{table_name}'
    """).fetchone()
    return result[0] > 0


def create_scheduler_tables():
    """Create scheduler tables in the DuckDB database."""
    import duckdb

    db_path = get_db_path()

    # Check if database file exists
    if not os.path.exists(db_path):
        logger.error(f"Historify database not found at: {db_path}")
        logger.error("Please run migrate_historify.py first")
        return False

    logger.info(f"Adding scheduler tables to: {db_path}")

    conn = duckdb.connect(db_path)

    try:
        # Check if tables already exist
        if table_exists(conn, "historify_schedules"):
            logger.info("historify_schedules table already exists - skipping")
        else:
            logger.info("Creating historify_schedules table...")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS historify_schedules (
                    id VARCHAR PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    description VARCHAR,
                    schedule_type VARCHAR NOT NULL,
                    interval_value INTEGER,
                    interval_unit VARCHAR,
                    time_of_day VARCHAR,
                    download_source VARCHAR DEFAULT 'watchlist',
                    data_interval VARCHAR NOT NULL,
                    lookback_days INTEGER DEFAULT 1,
                    is_enabled BOOLEAN DEFAULT TRUE,
                    is_paused BOOLEAN DEFAULT FALSE,
                    status VARCHAR DEFAULT 'idle',
                    apscheduler_job_id VARCHAR,
                    created_at TIMESTAMP DEFAULT current_timestamp,
                    last_run_at TIMESTAMP,
                    next_run_at TIMESTAMP,
                    last_run_status VARCHAR,
                    total_runs INTEGER DEFAULT 0,
                    successful_runs INTEGER DEFAULT 0,
                    failed_runs INTEGER DEFAULT 0
                )
            """)
            logger.info("Created historify_schedules table")

        if table_exists(conn, "historify_schedule_executions"):
            logger.info("historify_schedule_executions table already exists - skipping")
        else:
            logger.info("Creating historify_schedule_executions table...")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS historify_schedule_executions (
                    id INTEGER PRIMARY KEY,
                    schedule_id VARCHAR NOT NULL,
                    download_job_id VARCHAR,
                    status VARCHAR NOT NULL,
                    started_at TIMESTAMP DEFAULT current_timestamp,
                    completed_at TIMESTAMP,
                    symbols_processed INTEGER DEFAULT 0,
                    symbols_success INTEGER DEFAULT 0,
                    symbols_failed INTEGER DEFAULT 0,
                    records_downloaded INTEGER DEFAULT 0,
                    error_message VARCHAR
                )
            """)
            logger.info("Created historify_schedule_executions table")

        # Create indexes
        logger.info("Creating indexes...")
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_historify_schedules_enabled
            ON historify_schedules (is_enabled, is_paused)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_historify_schedule_executions_schedule_id
            ON historify_schedule_executions (schedule_id)
        """)
        logger.info("Created all indexes")

        conn.close()
        return True

    except Exception as e:
        logger.error(f"Error creating scheduler tables: {e}")
        conn.close()
        return False


#: Lives in DATABASE_URL, not DuckDB - historify_scheduler_service points
#: SQLAlchemyJobStore at DATABASE_URL while the schedule definitions above are
#: DuckDB tables.
JOBSTORE_TABLE = "historify_apscheduler_jobs"


def get_sqlite_url():
    """DATABASE_URL, with a relative sqlite path resolved against the root.

    The documented invocation is `cd upgrade && uv run ...`, and the default
    "sqlite:///db/openalgo.db" is relative, so left alone it would resolve to
    upgrade/db/openalgo.db and SQLAlchemy would create an empty database there.
    """
    db_url = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return db_url
    path = db_url[len(prefix) :]
    if not path or path == ":memory:" or os.path.isabs(path):
        return db_url
    return prefix + os.path.join(parent_dir, path)


def _jobstore_engine(db_url):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    if "sqlite" in db_url:
        return create_engine(db_url, poolclass=NullPool)
    return create_engine(db_url)


def create_jobstore_table():
    """Create the APScheduler job store table in the main database.

    Built from APScheduler's own table metadata rather than hand-written SQL,
    so the schema cannot drift from what APScheduler expects and the
    ix_<tablename>_next_run_time index is created with it.

    Doing this here rather than leaving it to the runtime is the point.
    SQLAlchemyJobStore.start() issues this CREATE TABLE itself, and at startup
    that DDL lands in the middle of the boot write burst needing an exclusive
    write lock. An install that loses that race logs "database is locked", the
    scheduler never initializes, and since init runs once at boot with no
    retry, scheduled downloads silently never run. See issue #1750.
    """
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from sqlalchemy import inspect

    db_url = get_sqlite_url()
    engine = _jobstore_engine(db_url)
    try:
        jobs_t = SQLAlchemyJobStore(engine=engine, tablename=JOBSTORE_TABLE).jobs_t

        if JOBSTORE_TABLE in inspect(engine).get_table_names():
            logger.info(f"{JOBSTORE_TABLE} table already exists - skipping")
        else:
            logger.info(f"Creating {JOBSTORE_TABLE} table...")
            jobs_t.create(engine, checkfirst=True)
            logger.info(f"Created {JOBSTORE_TABLE} table")

        # checkfirst tests only for the table, so one that exists without its
        # index would never acquire one and every due-job poll would scan.
        existing = {idx["name"] for idx in inspect(engine).get_indexes(JOBSTORE_TABLE)}
        for index in jobs_t.indexes:
            if index.name not in existing:
                index.create(engine)
                logger.info(f"Created index {index.name}")
        return True
    except Exception:
        logger.exception(f"Failed to create {JOBSTORE_TABLE}")
        return False
    finally:
        engine.dispose()


def jobstore_status():
    """Report whether the job store table and its index exist."""
    from sqlalchemy import inspect

    engine = _jobstore_engine(get_sqlite_url())
    try:
        inspector = inspect(engine)
        if JOBSTORE_TABLE not in inspector.get_table_names():
            logger.info(f"   {JOBSTORE_TABLE}: MISSING - migration needed")
            return False

        index_name = f"ix_{JOBSTORE_TABLE}_next_run_time"
        names = {idx["name"] for idx in inspector.get_indexes(JOBSTORE_TABLE)}
        if index_name not in names:
            logger.info(f"   {JOBSTORE_TABLE}: present, but {index_name} is MISSING")
            return False

        logger.info(f"   {JOBSTORE_TABLE}: present, with index")
        return True
    except Exception:
        logger.exception("Failed to check job store status")
        return False
    finally:
        engine.dispose()


def upgrade():
    """Apply the Historify Scheduler migration."""
    try:
        logger.info(f"Starting migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})")

        # Check DuckDB is available
        if not check_duckdb_available():
            return False

        # Create the scheduler tables
        if not create_scheduler_tables():
            return False

        # Job store table, in SQLite rather than DuckDB
        if not create_jobstore_table():
            return False

        logger.info(f"Migration {MIGRATION_NAME} completed successfully")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def status():
    """Check migration status."""
    try:
        logger.info(f"Checking status of migration: {MIGRATION_NAME}")

        # Check DuckDB is available
        if not check_duckdb_available():
            logger.info("DuckDB not installed - migration needed")
            return False

        import duckdb

        db_path = get_db_path()

        # Check if database file exists
        if not os.path.exists(db_path):
            logger.info(f"Database file not found: {db_path}")
            logger.info("   Run migrate_historify.py first")
            return False

        conn = duckdb.connect(db_path)

        try:
            # Check scheduler tables exist
            required_tables = ["historify_schedules", "historify_schedule_executions"]
            missing_tables = []

            for table in required_tables:
                if not table_exists(conn, table):
                    missing_tables.append(table)

            if missing_tables:
                logger.info(f"Missing tables: {', '.join(missing_tables)}")
                logger.info("   Migration needed")
                conn.close()
                return False

            # Show scheduler statistics
            schedules_count = conn.execute("SELECT COUNT(*) FROM historify_schedules").fetchone()[0]
            active_count = conn.execute("""
                SELECT COUNT(*) FROM historify_schedules
                WHERE is_enabled = TRUE AND is_paused = FALSE
            """).fetchone()[0]
            executions_count = conn.execute(
                "SELECT COUNT(*) FROM historify_schedule_executions"
            ).fetchone()[0]

            logger.info("Historify scheduler tables are configured")
            logger.info(f"   Total Schedules: {schedules_count}")
            logger.info(f"   Active Schedules: {active_count}")
            logger.info(f"   Total Executions: {executions_count}")

            conn.close()
            return jobstore_status()

        except Exception as e:
            logger.error(f"Error checking status: {e}")
            conn.close()
            return False

    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"Migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--status", action="store_true", help="Check migration status")

    args = parser.parse_args()

    if args.status:
        success = status()
    else:
        success = upgrade()

    sys.exit(0 if success else 1)
