#!/usr/bin/env python
"""
Backtest Engine Migration Script for OpenAlgo

This migration creates the backtest database and tables:
- backtest_runs: Stores backtest configurations and results
- backtest_trades: Stores individual trades from backtest runs

Usage:
    cd upgrade
    uv run migrate_backtest.py           # Apply migration
    uv run migrate_backtest.py --status  # Check status

Migration: 020
Created: 2025-03-01
"""

import argparse
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)

# Migration metadata
MIGRATION_NAME = "backtest_engine_setup"
MIGRATION_VERSION = "020"


def get_backtest_db_url():
    """Get the backtest database URL from environment."""
    load_dotenv()
    return os.getenv("BACKTEST_DATABASE_URL", "sqlite:///db/backtest.db")


def check_status():
    """Check current migration status."""
    db_url = get_backtest_db_url()

    # Check if the database file exists
    if "sqlite" in db_url:
        db_path = db_url.replace("sqlite:///", "")
        if not Path(db_path).exists():
            print(f"Database file does not exist: {db_path}")
            print("Status: NOT APPLIED (database not created)")
            return

    engine = create_engine(db_url, poolclass=NullPool)
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    print(f"Database: {db_url}")
    print(f"Tables found: {tables}")

    required_tables = ["backtest_runs", "backtest_trades"]
    missing = [t for t in required_tables if t not in tables]

    if missing:
        print(f"Missing tables: {missing}")
        print("Status: PARTIALLY APPLIED or NOT APPLIED")
    else:
        # Check columns on backtest_runs
        columns = [c["name"] for c in inspector.get_columns("backtest_runs")]
        print(f"backtest_runs columns: {len(columns)}")
        print("Status: APPLIED")

    engine.dispose()


def apply_migration():
    """Apply the backtest migration."""
    db_url = get_backtest_db_url()

    # Ensure db directory exists
    if "sqlite" in db_url:
        db_path = db_url.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    print(f"Applying migration {MIGRATION_VERSION}: {MIGRATION_NAME}")
    print(f"Database: {db_url}")

    engine = create_engine(
        db_url,
        poolclass=NullPool,
        connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
    )

    # Import and create all tables using the ORM models
    try:
        from database.backtest_db import Base
        Base.metadata.create_all(engine)
        print("Tables created successfully:")
        inspector = inspect(engine)
        for table in inspector.get_table_names():
            columns = inspector.get_columns(table)
            print(f"  - {table}: {len(columns)} columns")
        print(f"Migration {MIGRATION_VERSION} applied successfully!")
    except Exception as e:
        print(f"Error applying migration: {e}")
        raise
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description=f"Migration {MIGRATION_VERSION}: {MIGRATION_NAME}"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check migration status without applying changes",
    )
    args = parser.parse_args()

    if args.status:
        check_status()
    else:
        apply_migration()


if __name__ == "__main__":
    main()
