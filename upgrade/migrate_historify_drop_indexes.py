#!/usr/bin/env python
"""
Historify Secondary Index Removal Migration for OpenAlgo

Drops the three unused secondary indexes on market_data that keep DuckDB
ART index memory fully resident as the table grows, which causes
out-of-memory failures on large 1m backfills (#1779):

- idx_market_data_timestamp
- idx_market_data_exchange_time
- idx_market_data_interval_time

Every query against market_data leads with `symbol`; none of these
indexes contains that column, the planner never selects them, and range
scans are served by DuckDB's per-row-group zone maps. Measured in #1779,
removing them roughly halves the database file, speeds up ingest about
1.6x, and costs no query performance. The primary key on
(symbol, exchange, interval, timestamp) is untouched and remains
enforced after the drop.

DROP INDEX is a catalog-only operation - it never reads or rewrites
table data. An explicit CHECKPOINT follows the drop so the file size
actually shrinks.

Usage:
    cd upgrade
    uv run migrate_historify_drop_indexes.py           # Apply migration
    uv run migrate_historify_drop_indexes.py --status  # Check status

Migration: 012
Created: 2026-08-18
Issue: #1779
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
MIGRATION_NAME = "historify_drop_unused_indexes"
MIGRATION_VERSION = "012"

# The unused secondary indexes on market_data (see #1779).
# The primary key's implicit index is NOT listed: it is required for
# duplicate protection and is not visible in duckdb_indexes() anyway.
SECONDARY_INDEXES = [
    "idx_market_data_timestamp",
    "idx_market_data_exchange_time",
    "idx_market_data_interval_time",
]

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


def existing_secondary_indexes(conn):
    """Return which of the target secondary indexes currently exist."""
    rows = conn.execute(
        "SELECT index_name FROM duckdb_indexes() WHERE table_name = 'market_data'"
    ).fetchall()
    present = {row[0] for row in rows}
    return [name for name in SECONDARY_INDEXES if name in present]


def drop_indexes():
    """Drop the unused secondary indexes on market_data."""
    import duckdb

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
        existing = existing_secondary_indexes(conn)

        if not existing:
            logger.info("Unused secondary indexes already absent - nothing to do")
            return True

        for index_name in existing:
            conn.execute(f'DROP INDEX IF EXISTS "{index_name}"')

        # Reclaim the space the dropped index ARTs occupied. Without an
        # explicit CHECKPOINT the file keeps its old size and the
        # migration looks like it did nothing.
        conn.execute("CHECKPOINT")

        logger.info(
            f"Dropped {len(existing)} unused secondary index(es) on market_data: "
            + ", ".join(existing)
        )
        logger.info(f"Migration {MIGRATION_NAME} completed at {datetime.now().isoformat()}")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False
    finally:
        conn.close()


def status():
    """Check migration status."""
    import duckdb

    db_path = get_db_path()

    if not os.path.exists(db_path):
        logger.info(f"No Historify database at {db_path} - nothing to migrate")
        return True

    try:
        conn = duckdb.connect(db_path)

        try:
            existing = existing_secondary_indexes(conn)
            db_size = os.path.getsize(db_path)
            db_size_mb = round(db_size / (1024 * 1024), 2)

            if existing:
                logger.info(f"Unused secondary indexes still present: {', '.join(existing)}")
                logger.info("   Migration needed")
                conn.close()
                return False

            logger.info("No unused secondary indexes on market_data")
            logger.info(f"   Database Size: {db_size_mb} MB")
            logger.info("   Migration already applied")
            conn.close()
            return True

        except Exception as e:
            logger.error(f"Error checking status: {e}")
            conn.close()
            return False

    except duckdb.IOException as e:
        logger.error(
            "Historify database is locked by another process (most likely a "
            "running OpenAlgo server). Stop OpenAlgo first, then re-run this "
            f"status check. Details: {e}"
        )
        return False
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return False


def upgrade():
    """Apply the Historify secondary index removal migration."""
    try:
        logger.info(f"Starting migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})")

        if not check_duckdb_available():
            return False

        return drop_indexes()

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback

        traceback.print_exc()
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
