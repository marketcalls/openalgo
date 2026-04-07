#!/usr/bin/env python
"""
Token Expiry Migration Script for OpenAlgo

Adds expires_at column to the auth table for token expiry tracking.

Usage:
    cd upgrade
    uv run migrate_token_expiry.py           # Apply migration
    uv run migrate_token_expiry.py --status  # Check status

Created: 2026-04-08
"""

import argparse
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

from utils.logging import get_logger

logger = get_logger(__name__)

# Migration metadata
MIGRATION_NAME = "token_expiry_column"
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
    """Apply the migration - add expires_at column to auth table"""
    try:
        logger.info(f"Starting migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})")

        engine = get_engine()
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("auth")}

        with engine.connect() as conn:
            if "expires_at" not in existing_columns:
                conn.execute(text("ALTER TABLE auth ADD COLUMN expires_at DATETIME"))
                conn.commit()
                logger.info("Added column: expires_at")
            else:
                logger.info("Column already exists: expires_at")

        logger.info(f"Migration {MIGRATION_NAME} completed")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def status():
    """Check migration status"""
    try:
        engine = get_engine()
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("auth")}

        if "expires_at" not in existing_columns:
            logger.info("Missing column: expires_at - migration needed")
            return False

        logger.info("expires_at column exists in auth table")
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
