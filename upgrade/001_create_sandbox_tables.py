# upgrade/001_create_sandbox_tables.py
"""
Sandbox Mode Database Migration
Creates all required tables for sandbox/virtual trading functionality

Migration: 001
Created: 2025-10-01
Description: Initial sandbox database schema with orders, trades, positions, holdings, funds, and config tables
"""

import sys
import os
from dotenv import load_dotenv

# Add parent directory to path
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(parent_dir)

# Load environment variables
dotenv_path = os.path.join(parent_dir, '.env')
load_dotenv(dotenv_path)

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, DECIMAL, Date
from sqlalchemy import create_engine, CheckConstraint, Index, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base = declarative_base()


def create_sandbox_tables():
    """Create sandbox tables in sandbox.db"""

    # Get sandbox database path
    sandbox_db_path = os.path.join(parent_dir, 'sandbox', 'sandbox.db')
    sandbox_db_url = f"sqlite:///{sandbox_db_path}"

    logger.info(f"Creating sandbox tables in: {sandbox_db_path}")

    # Create engine for sandbox database
    engine = create_engine(sandbox_db_url)

    # Import sandbox database module to create tables
    try:
        from database.sandbox_db import init_db
        init_db()
        logger.info("✅ Successfully created all sandbox tables")
        return True
    except Exception as e:
        logger.error(f"❌ Error creating sandbox tables: {e}")
        return False


def drop_sandbox_tables():
    """Drop sandbox tables"""

    # Get sandbox database path
    sandbox_db_path = os.path.join(parent_dir, 'sandbox', 'sandbox.db')

    if os.path.exists(sandbox_db_path):
        try:
            os.remove(sandbox_db_path)
            logger.info("✅ Successfully removed sandbox database")
            return True
        except Exception as e:
            logger.error(f"❌ Error removing sandbox database: {e}")
            return False
    else:
        logger.info("Sandbox database does not exist")
        return True


if __name__ == '__main__':
    """Run migration when executed directly"""
    import argparse

    parser = argparse.ArgumentParser(description='Sandbox database migration')
    parser.add_argument('action', choices=['upgrade', 'downgrade'], help='Migration action')
    args = parser.parse_args()

    if args.action == 'upgrade':
        logger.info("Running upgrade migration for sandbox tables...")
        if create_sandbox_tables():
            logger.info("Migration completed successfully")
        else:
            logger.error("Migration failed")
            sys.exit(1)
    elif args.action == 'downgrade':
        logger.info("Running downgrade migration for sandbox tables...")
        if drop_sandbox_tables():
            logger.info("Downgrade completed successfully")
        else:
            logger.error("Downgrade failed")
            sys.exit(1)
