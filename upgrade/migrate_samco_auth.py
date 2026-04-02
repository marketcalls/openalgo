#!/usr/bin/env python
"""
Samco 2FA Auth Migration Script for OpenAlgo

This migration adds auxiliary columns (aux_param1-4) to the existing auth table.
These columns are used by Samco for 2FA data (secret key, IP registration)
and are available for other brokers to store broker-specific data.

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
from sqlalchemy import create_engine, inspect, text

from utils.logging import get_logger

logger = get_logger(__name__)

# Migration metadata
MIGRATION_NAME = "samco_auth_aux_columns"
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


AUX_COLUMNS = [
    # Samco 2FA fields
    ("secret_api_key", "TEXT"),
    ("primary_ip", "VARCHAR(45)"),
    ("secondary_ip", "VARCHAR(45)"),
    ("ip_updated_at", "DATETIME"),
    # Generic auxiliary fields
    ("aux_param1", "TEXT"),
    ("aux_param2", "TEXT"),
    ("aux_param3", "TEXT"),
    ("aux_param4", "TEXT"),
]


def upgrade():
    """Apply the migration - add aux_param columns to auth table"""
    try:
        logger.info(f"Starting migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})")

        engine = get_engine()
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("auth")}

        with engine.connect() as conn:
            added = 0
            for col_name, col_type in AUX_COLUMNS:
                if col_name not in existing_columns:
                    conn.execute(
                        text(f"ALTER TABLE auth ADD COLUMN {col_name} {col_type}")
                    )
                    logger.info(f"Added column: {col_name}")
                    added += 1
                else:
                    logger.info(f"Column already exists: {col_name}")

            conn.commit()

        if added > 0:
            logger.info(f"Migration {MIGRATION_NAME} completed: added {added} column(s)")
        else:
            logger.info(f"Migration {MIGRATION_NAME}: all columns already exist")
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
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("auth")}

        missing = [c for c, _ in AUX_COLUMNS if c not in existing_columns]

        if missing:
            logger.info(f"Missing columns: {', '.join(missing)} - migration needed")
            return False

        logger.info("All aux_param columns exist in auth table")
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
