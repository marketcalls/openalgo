#!/usr/bin/env python3
"""
Migration script to create or update the leverage_config table.

The leverage_config table stores a single common leverage value
for all crypto futures orders. Replaces the earlier per-symbol design.

Usage:
    cd upgrade
    python migrate_leverage.py
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


def migrate_leverage():
    """Create or recreate leverage_config as a single-row config table."""

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

        if "leverage_config" in inspector.get_table_names():
            # Check if it has the old per-symbol schema (symbol column)
            columns = [col["name"] for col in inspector.get_columns("leverage_config")]
            if "symbol" in columns:
                logger.info("Found old per-symbol leverage_config table. Recreating...")
                with engine.connect() as conn:
                    conn.execute(text("DROP TABLE leverage_config"))
                    conn.commit()
            else:
                logger.info("Table leverage_config already exists with correct schema.")
                return True

        # Create the simple single-row table
        with engine.connect() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE leverage_config (
                        id INTEGER PRIMARY KEY DEFAULT 1,
                        leverage REAL NOT NULL DEFAULT 0.0,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            conn.execute(
                text("INSERT INTO leverage_config (id, leverage) VALUES (1, 0.0)")
            )
            conn.commit()
            logger.info("Created table: leverage_config (single-row config)")

        logger.info("Migration completed successfully.")
        return True

    except Exception as e:
        logger.error(f"Error during migration: {e}")
        return False


def main():
    """Main function to run the migration"""
    logger.info("=" * 60)
    logger.info("OpenAlgo Leverage Configuration Migration")
    logger.info("=" * 60)
    logger.info("Creating leverage_config table for common crypto leverage setting")
    logger.info("-" * 60)

    success = migrate_leverage()

    logger.info("-" * 60)
    if success:
        logger.info("Migration process completed!")
        return 0
    else:
        logger.error("Migration failed! Check error messages above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
