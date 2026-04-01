#!/usr/bin/env python
"""
Samco 2FA Auth Migration Script for OpenAlgo

This migration creates the samco_auth table for storing:
- Secret API key (permanent, generated via OTP flow)
- IP registration details with weekly update tracking

Usage:
    cd upgrade
    uv run migrate_samco_auth.py           # Apply migration
    uv run migrate_samco_auth.py --status  # Check status

Created: 2026-04-01
"""

import argparse
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from utils.logging import get_logger

logger = get_logger(__name__)

# Migration metadata
MIGRATION_NAME = "samco_auth"
MIGRATION_VERSION = "001"

# Load environment
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(parent_dir, ".env"))


def get_engine():
    """Get main database engine"""
    database_url = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")

    if database_url.startswith("sqlite:///"):
        db_path = database_url.replace("sqlite:///", "")
        if not os.path.isabs(db_path):
            db_path = os.path.join(parent_dir, db_path)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        database_url = f"sqlite:///{db_path}"

    return create_engine(database_url)


def upgrade():
    """Apply the migration - create samco_auth table"""
    try:
        logger.info(f"Starting migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})")

        engine = get_engine()

        with engine.connect() as conn:
            # Create samco_auth table
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS samco_auth (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id VARCHAR(50) UNIQUE NOT NULL,
                    secret_api_key TEXT,
                    primary_ip VARCHAR(45),
                    secondary_ip VARCHAR(45),
                    ip_updated_at DATETIME
                )
            """)
            )

            # Create indexes
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_samco_auth_user_id ON samco_auth(user_id)"
                )
            )

            conn.commit()

        logger.info(f"Migration {MIGRATION_NAME} completed successfully")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def status():
    """Check migration status"""
    try:
        logger.info(f"Checking status of migration: {MIGRATION_NAME}")

        engine = get_engine()

        with engine.connect() as conn:
            result = conn.execute(
                text("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='samco_auth'
            """)
            )
            if not result.fetchone():
                logger.info("samco_auth table does not exist - migration needed")
                return False

            # Show record count
            result = conn.execute(text("SELECT COUNT(*) FROM samco_auth"))
            count = result.fetchone()[0]
            logger.info(f"samco_auth table exists with {count} record(s)")
            return True

    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"Migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})",
    )
    parser.add_argument("--status", action="store_true", help="Check migration status")

    args = parser.parse_args()

    if args.status:
        success = status()
    else:
        success = upgrade()

    sys.exit(0 if success else 1)
