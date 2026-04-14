#!/usr/bin/env python
"""
Sandbox PnL Day-wise Tracking Migration Script for OpenAlgo

This migration adds today_realized_pnl columns to sandbox tables
to enable proper day-wise P&L tracking that resets at session boundary.

Changes:
- Updates reset_day default from 'Sunday' to 'Never' (auto-reset disabled by default)
- Adds today_realized_pnl column to sandbox_positions table
- Adds today_realized_pnl column to sandbox_funds table

Usage:
    cd upgrade
    uv run migrate_sandbox_pnl.py           # Apply migration
    uv run migrate_sandbox_pnl.py --status  # Check status

Migration: 004
Created: 2025-12-23
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError

from utils.logging import get_logger

logger = get_logger(__name__)

# Migration metadata
MIGRATION_NAME = "sandbox_pnl_daywise"
MIGRATION_VERSION = "004"

# Load environment
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(parent_dir, ".env"))


def get_sandbox_db_engine():
    """Get sandbox database engine"""
    sandbox_db_url = os.getenv("SANDBOX_DATABASE_URL", "sqlite:///db/sandbox.db")

    if sandbox_db_url.startswith("sqlite:///"):
        db_path = sandbox_db_url.replace("sqlite:///", "")

        if not os.path.isabs(db_path):
            db_path = os.path.join(parent_dir, db_path)

        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        sandbox_db_url = f"sqlite:///{db_path}"
        logger.info(f"Sandbox DB path: {db_path}")

    return create_engine(sandbox_db_url)


def update_reset_day_default(conn):
    """Update reset_day from Sunday to Never for existing databases"""
    try:
        # Check if sandbox_config table exists
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='sandbox_config'")
        )
        if not result.fetchone():
            logger.info("sandbox_config table does not exist, skipping reset_day update")
            return

        # Update reset_day from Sunday to Never
        result = conn.execute(
            text(
                "UPDATE sandbox_config SET config_value = 'Never' "
                "WHERE config_key = 'reset_day' AND config_value = 'Sunday'"
            )
        )
        conn.commit()

        if result.rowcount > 0:
            logger.info(f"Updated reset_day from 'Sunday' to 'Never' ({result.rowcount} rows)")
        else:
            logger.info("reset_day is already set to 'Never' or not 'Sunday'")

    except Exception as e:
        logger.warning(f"Could not update reset_day default: {e}")


def add_today_realized_pnl_columns(conn):
    """Add today_realized_pnl columns to sandbox tables"""

    logger.info("Checking for today_realized_pnl columns...")

    # Check and add today_realized_pnl to sandbox_positions if missing
    result = conn.execute(text("PRAGMA table_info(sandbox_positions)"))
    columns = [row[1] for row in result]

    if "today_realized_pnl" not in columns:
        conn.execute(
            text("""
            ALTER TABLE sandbox_positions
            ADD COLUMN today_realized_pnl DECIMAL(10,2) DEFAULT 0.00
        """)
        )
        logger.info("Added today_realized_pnl column to sandbox_positions")
    else:
        logger.info("today_realized_pnl column already exists in sandbox_positions")

    # Check and add today_realized_pnl to sandbox_funds if missing
    result = conn.execute(text("PRAGMA table_info(sandbox_funds)"))
    columns = [row[1] for row in result]

    if "today_realized_pnl" not in columns:
        conn.execute(
            text("""
            ALTER TABLE sandbox_funds
            ADD COLUMN today_realized_pnl DECIMAL(15,2) DEFAULT 0.00
        """)
        )
        logger.info("Added today_realized_pnl column to sandbox_funds")
    else:
        logger.info("today_realized_pnl column already exists in sandbox_funds")

    conn.commit()


def upgrade():
    """Apply the migration"""
    try:
        logger.info(f"Starting migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})")

        engine = get_sandbox_db_engine()

        with engine.connect() as conn:
            # Update reset_day default from Sunday to Never
            update_reset_day_default(conn)

            # Add today_realized_pnl columns
            add_today_realized_pnl_columns(conn)

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

        engine = get_sandbox_db_engine()

        with engine.connect() as conn:
            # Check today_realized_pnl in sandbox_positions
            result = conn.execute(text("PRAGMA table_info(sandbox_positions)"))
            positions_columns = [row[1] for row in result]

            # Check today_realized_pnl in sandbox_funds
            result = conn.execute(text("PRAGMA table_info(sandbox_funds)"))
            funds_columns = [row[1] for row in result]

            missing = []
            if "today_realized_pnl" not in positions_columns:
                missing.append("sandbox_positions.today_realized_pnl")
            if "today_realized_pnl" not in funds_columns:
                missing.append("sandbox_funds.today_realized_pnl")

            if missing:
                logger.info(f"Missing columns: {', '.join(missing)}")
                logger.info("   Migration needed")
                return False

            logger.info("Sandbox PnL day-wise tracking is configured")
            logger.info("   today_realized_pnl column exists in sandbox_positions")
            logger.info("   today_realized_pnl column exists in sandbox_funds")
            return True

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
