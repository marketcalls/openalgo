#!/usr/bin/env python
"""
Historify ID Sequence Migration for OpenAlgo

Four Historify tables take their IDs from DuckDB sequences:

- watchlist           -> watchlist_id_seq
- data_catalog        -> data_catalog_id_seq
- job_items           -> job_items_id_seq
- historify_schedule_executions -> historify_schedule_executions_id_seq

They used to compute MAX(id) + 1 themselves. Under the gthread worker two
requests can read the same MAX(id) at the same moment and both insert it, so
the IDs now come from sequences, which DuckDB hands out one at a time.

This migration creates each missing sequence at its table's high-water mark,
and moves a sequence that has fallen behind its table past it. The second case
arises when an install leaves this version for one without sequences (whose
code keeps assigning MAX(id) + 1 and never advances the sequence left in the
file) and later returns: without this step every insert into that table fails
with a duplicate key, on every attempt. A sequence already ahead is untouched,
so running the migration again changes nothing.

OpenAlgo applies the same step each time it starts (database/historify_db.py,
sync_id_sequences), so this script is not required for the application to
work. It makes the change part of the upgrade, where it can be checked with
--status, instead of leaving it to the first start.

Usage:
    cd upgrade
    uv run migrate_historify_sequences.py           # Apply migration
    uv run migrate_historify_sequences.py --status  # Check status

Migration: 013
Created: 2026-09-30
"""

import argparse
import os
import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from utils.logging import get_logger

logger = get_logger(__name__)

# Migration metadata
MIGRATION_NAME = "historify_id_sequences"
MIGRATION_VERSION = "013"

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


def _describe(change):
    before = "missing" if change["next_before"] is None else f"next {change['next_before']}"
    return f"{change['sequence']}: {before} -> next {change['next_after']}"


def _run(apply):
    """Open the database and sync the sequences, or report what would change."""
    try:
        import duckdb
    except ImportError:
        logger.error("DuckDB is not installed. Please run: uv sync")
        return False

    from database.historify_db import sync_id_sequences

    db_path = get_db_path()

    # Most installs have never opened Historify - nothing to migrate.
    if not os.path.exists(db_path):
        logger.info(f"No Historify database at {db_path} - nothing to migrate")
        return True

    try:
        conn = duckdb.connect(db_path)
    except duckdb.IOException as e:
        logger.error(
            "Historify database is locked by another process (most likely a "
            "running OpenAlgo server). Stop OpenAlgo first, then re-run this "
            f"migration. Details: {e}"
        )
        return False

    try:
        changes = sync_id_sequences(conn, apply=apply)
        if not changes:
            logger.info(
                "Historify ID sequences are all present and ahead of their tables - nothing to do"
            )
            return True
        if not apply:
            logger.info("Historify ID sequences that need the migration:")
            for change in changes:
                logger.info(f"   {_describe(change)}")
            return False
        for change in changes:
            logger.info(f"   {change['action']}: {_describe(change)}")
        logger.info(f"Migration {MIGRATION_NAME} completed at {datetime.now().isoformat()}")
        return True
    except Exception:
        logger.exception("Historify ID sequence migration failed")
        return False
    finally:
        conn.close()


def upgrade():
    """Create missing Historify ID sequences and advance any that fell behind."""
    logger.info(f"Starting migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})")
    return _run(apply=True)


def status():
    """Report whether the migration is needed, without changing anything."""
    return _run(apply=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"Migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--status", action="store_true", help="Check migration status")

    args = parser.parse_args()
    success = status() if args.status else upgrade()
    sys.exit(0 if success else 1)
