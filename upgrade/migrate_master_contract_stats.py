#!/usr/bin/env python3
"""
Migration script to add smart download columns to master_contract_status table.

New columns:
- last_download_time: When download completed successfully
- download_date: Trading day of the download
- exchange_stats: JSON with exchange-wise symbol counts
- download_duration_seconds: How long download took

Usage:
    cd upgrade
    python migrate_master_contract_stats.py
"""

import os
import sys

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

# Load environment from parent directory
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(env_path)

# Import logger after environment is loaded
from utils.logging import get_logger

logger = get_logger(__name__)


def migrate_master_contract_status_table():
    """Add smart download columns to master_contract_status table if they don't exist"""

    # Get database URL from environment
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")

    # Adjust path for SQLite if relative (since we're in upgrade folder)
    if DATABASE_URL.startswith("sqlite:///") and not DATABASE_URL.startswith("sqlite:////"):
        db_path = DATABASE_URL.replace("sqlite:///", "")
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_db_path = os.path.join(parent_dir, db_path)
        DATABASE_URL = f"sqlite:///{full_db_path}"
        logger.info(f"Using database: {full_db_path}")

    try:
        engine = create_engine(DATABASE_URL)
        inspector = inspect(engine)

        # Check if table exists
        if "master_contract_status" not in inspector.get_table_names():
            logger.info("master_contract_status table doesn't exist. It will be created on first run.")
            return True

        # Get existing columns
        existing_columns = [col["name"] for col in inspector.get_columns("master_contract_status")]
        logger.info(f"Existing columns: {existing_columns}")

        # Define new columns for smart download
        new_columns = [
            ("last_download_time", "DATETIME"),
            ("download_date", "DATE"),
            ("exchange_stats", "TEXT"),  # JSON string
            ("download_duration_seconds", "INTEGER"),
        ]

        columns_added = 0
        columns_existing = 0

        with engine.connect() as conn:
            for column_name, column_def in new_columns:
                if column_name not in existing_columns:
                    try:
                        alter_sql = text(
                            f"ALTER TABLE master_contract_status ADD COLUMN {column_name} {column_def}"
                        )
                        conn.execute(alter_sql)
                        conn.commit()
                        logger.info(f"✅ Added column: {column_name}")
                        columns_added += 1
                    except Exception as col_error:
                        logger.warning(f"Could not add column {column_name}: {col_error}")
                else:
                    logger.info(f"✓ Column already exists: {column_name}")
                    columns_existing += 1

        logger.info("\n📊 Migration Summary:")
        logger.info(f"   - Columns added: {columns_added}")
        logger.info(f"   - Columns already existing: {columns_existing}")
        logger.info(f"   - Total new columns: {len(new_columns)}")

        if columns_added > 0:
            logger.info("\n✅ Master contract status table migration completed!")
            logger.info("   Smart download tracking columns have been added.")
        else:
            logger.info("\n✅ No migration needed - all columns already exist!")

        return True

    except Exception as e:
        logger.error(f"❌ Error during migration: {e}")
        return False


def main():
    """Main function to run the migration"""
    logger.info("=" * 60)
    logger.info("OpenAlgo Master Contract Smart Download Migration")
    logger.info("=" * 60)
    logger.info("This script adds columns for smart master contract download tracking")
    logger.info("-" * 60)

    success = migrate_master_contract_status_table()

    logger.info("-" * 60)
    if success:
        logger.info("Migration process completed!")
        logger.info("\n📌 New Features:")
        logger.info("   - Smart download: Skip if already downloaded after 8 AM IST")
        logger.info("   - Exchange stats: Track symbol counts per exchange")
        logger.info("   - Download duration: Track how long downloads take")
        return 0
    else:
        logger.error("Migration failed! Check error messages above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
