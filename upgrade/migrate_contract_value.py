#!/usr/bin/env python3
"""
Migration script to add contract_value column to the symtoken table.

New columns:
- contract_value: Float multiplier for crypto contracts (e.g. 0.01 for ETHUSD.P)

Usage:
    cd upgrade
    python migrate_contract_value.py
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


def migrate_contract_value():
    """Add contract_value column to symtoken table if it doesn't exist"""

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
        if "symtoken" not in inspector.get_table_names():
            logger.info("symtoken table doesn't exist. It will be created on first run.")
            return True

        # Get existing columns
        existing_columns = [col["name"] for col in inspector.get_columns("symtoken")]

        if "contract_value" in existing_columns:
            logger.info("Column contract_value already exists. No migration needed.")
            return True

        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE symtoken ADD COLUMN contract_value REAL DEFAULT 1.0"))
            conn.commit()
            logger.info("Added column: contract_value (REAL DEFAULT 1.0)")

        logger.info("Migration completed successfully.")
        return True

    except Exception as e:
        logger.error(f"Error during migration: {e}")
        return False


def main():
    """Main function to run the migration"""
    logger.info("=" * 60)
    logger.info("OpenAlgo Contract Value Migration")
    logger.info("=" * 60)
    logger.info("Adding contract_value column to symtoken table for crypto support")
    logger.info("-" * 60)

    success = migrate_contract_value()

    logger.info("-" * 60)
    if success:
        logger.info("Migration process completed!")
        return 0
    else:
        logger.error("Migration failed! Check error messages above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
