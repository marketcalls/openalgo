#!/usr/bin/env python
"""
Historify DuckDB Migration Script for OpenAlgo

This migration sets up the Historify database for historical market data storage:
- Creates the DuckDB database file in /db directory
- Initializes market_data, watchlist, and data_catalog tables
- Creates required indexes for optimal query performance

Usage:
    cd upgrade
    uv run migrate_historify.py           # Apply migration
    uv run migrate_historify.py --status  # Check status

Migration: 010
Created: 2025-01-14
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from utils.logging import get_logger

logger = get_logger(__name__)

# Migration metadata
MIGRATION_NAME = "historify_duckdb_setup"
MIGRATION_VERSION = "010"

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


def create_database():
    """Create and initialize the DuckDB database."""
    import duckdb

    db_path = get_db_path()
    db_dir = os.path.dirname(db_path)

    # Create directory if it doesn't exist
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        logger.info(f"Created database directory: {db_dir}")

    logger.info(f"Creating Historify database at: {db_path}")

    conn = duckdb.connect(db_path)

    try:
        # Main OHLCV data table - unified table approach for efficiency
        logger.info("Creating market_data table...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_data (
                symbol VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL,
                interval VARCHAR NOT NULL,
                timestamp BIGINT NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                volume BIGINT NOT NULL,
                oi BIGINT DEFAULT 0,
                created_at TIMESTAMP DEFAULT current_timestamp,
                PRIMARY KEY (symbol, exchange, interval, timestamp)
            )
        """)
        logger.info("Created market_data table")

        # Watchlist table
        logger.info("Creating watchlist table...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY,
                symbol VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL,
                display_name VARCHAR,
                added_at TIMESTAMP DEFAULT current_timestamp,
                UNIQUE (symbol, exchange)
            )
        """)
        logger.info("Created watchlist table")

        # Data catalog for tracking downloaded data ranges
        logger.info("Creating data_catalog table...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS data_catalog (
                id INTEGER PRIMARY KEY,
                symbol VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL,
                interval VARCHAR NOT NULL,
                first_timestamp BIGINT,
                last_timestamp BIGINT,
                record_count BIGINT DEFAULT 0,
                last_download_at TIMESTAMP,
                UNIQUE (symbol, exchange, interval)
            )
        """)
        logger.info("Created data_catalog table")

        # Download Jobs Table - for tracking bulk operations
        logger.info("Creating download_jobs table...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS download_jobs (
                id VARCHAR PRIMARY KEY,
                job_type VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                total_symbols INTEGER DEFAULT 0,
                completed_symbols INTEGER DEFAULT 0,
                failed_symbols INTEGER DEFAULT 0,
                interval VARCHAR,
                start_date VARCHAR,
                end_date VARCHAR,
                config VARCHAR,
                created_at TIMESTAMP DEFAULT current_timestamp,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                error_message VARCHAR
            )
        """)
        logger.info("Created download_jobs table")

        # Job Items Table - individual symbol status within a job
        logger.info("Creating job_items table...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_items (
                id INTEGER PRIMARY KEY,
                job_id VARCHAR NOT NULL,
                symbol VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                records_downloaded INTEGER DEFAULT 0,
                error_message VARCHAR,
                started_at TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)
        logger.info("Created job_items table")

        # Symbol Metadata Table - enriched symbol info for display
        logger.info("Creating symbol_metadata table...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS symbol_metadata (
                symbol VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL,
                name VARCHAR,
                expiry VARCHAR,
                strike DOUBLE,
                lotsize INTEGER,
                instrumenttype VARCHAR,
                tick_size DOUBLE,
                last_updated TIMESTAMP DEFAULT current_timestamp,
                PRIMARY KEY (symbol, exchange)
            )
        """)
        logger.info("Created symbol_metadata table")

        # Create indexes for common query patterns
        logger.info("Creating indexes...")
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_market_data_timestamp
            ON market_data (timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_market_data_exchange_time
            ON market_data (exchange, timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_market_data_interval_time
            ON market_data (interval, timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_items_job_id
            ON job_items (job_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_download_jobs_status
            ON download_jobs (status)
        """)
        logger.info("Created all indexes")

        conn.close()
        return True

    except Exception as e:
        logger.error(f"Error creating database: {e}")
        conn.close()
        return False


def upgrade():
    """Apply the Historify migration."""
    try:
        logger.info(f"Starting migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})")

        # Check DuckDB is available
        if not check_duckdb_available():
            return False

        # Create the database and tables
        if not create_database():
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
            logger.info("   Migration needed")
            return False

        conn = duckdb.connect(db_path)

        try:
            # Check all required tables exist
            required_tables = [
                "market_data",
                "watchlist",
                "data_catalog",
                "download_jobs",
                "job_items",
                "symbol_metadata",
            ]
            missing_tables = []

            for table in required_tables:
                result = conn.execute(f"""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_name = '{table}'
                """).fetchone()
                if result[0] == 0:
                    missing_tables.append(table)

            if missing_tables:
                logger.info(f"Missing tables: {', '.join(missing_tables)}")
                logger.info("   Migration needed")
                conn.close()
                return False

            # Show database statistics
            total_records = conn.execute("SELECT COUNT(*) FROM market_data").fetchone()[0]
            total_symbols = conn.execute("""
                SELECT COUNT(DISTINCT symbol || exchange)
                FROM market_data
            """).fetchone()[0]
            watchlist_count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
            catalog_count = conn.execute("SELECT COUNT(*) FROM data_catalog").fetchone()[0]
            jobs_count = conn.execute("SELECT COUNT(*) FROM download_jobs").fetchone()[0]
            metadata_count = conn.execute("SELECT COUNT(*) FROM symbol_metadata").fetchone()[0]

            # Get database file size
            db_size = os.path.getsize(db_path)
            db_size_mb = round(db_size / (1024 * 1024), 2)

            logger.info("Historify database is fully configured")
            logger.info(f"   Database Size: {db_size_mb} MB")
            logger.info(f"   Total Records: {total_records:,}")
            logger.info(f"   Total Symbols: {total_symbols}")
            logger.info(f"   Watchlist Items: {watchlist_count}")
            logger.info(f"   Catalog Entries: {catalog_count}")
            logger.info(f"   Download Jobs: {jobs_count}")
            logger.info(f"   Symbol Metadata: {metadata_count}")

            conn.close()
            return True

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
