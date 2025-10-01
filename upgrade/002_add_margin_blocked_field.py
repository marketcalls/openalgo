#!/usr/bin/env python3
"""
Add margin_blocked field to SandboxOrders table

Migration: 002
Created: 2025-10-01
Description: Adds margin_blocked field to track exact margin blocked per order,
             enabling accurate margin release on order cancellation and better
             margin tracking across various trading scenarios.

Changes:
- Adds margin_blocked DECIMAL(10,2) column to sandbox_orders table
- Default value is 0.00 for backward compatibility
"""

import sys
import os
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(parent_dir)

# Load environment variables
dotenv_path = os.path.join(parent_dir, '.env')
load_dotenv(dotenv_path)

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_sandbox_db_path():
    """Get the path to sandbox database"""
    # Check multiple possible locations
    db_locations = [
        os.path.join(parent_dir, 'sandbox_data', 'sandbox.db'),
        os.path.join(parent_dir, 'db', 'sandbox.db'),
        os.path.join(parent_dir, 'sandbox', 'sandbox.db'),
    ]

    for db_path in db_locations:
        if os.path.exists(db_path):
            return db_path

    # If not found, use default location
    return db_locations[0]


def upgrade():
    """Apply migration - add margin_blocked field"""
    try:
        sandbox_db_path = get_sandbox_db_path()
        sandbox_db_url = f"sqlite:///{sandbox_db_path}"

        logger.info(f"Applying migration to: {sandbox_db_path}")

        # Create engine
        engine = create_engine(sandbox_db_url)

        with engine.connect() as conn:
            # Check if column already exists
            result = conn.execute(text("PRAGMA table_info(sandbox_orders)"))
            columns = [row[1] for row in result]

            if 'margin_blocked' not in columns:
                # Add the column
                conn.execute(text("""
                    ALTER TABLE sandbox_orders
                    ADD COLUMN margin_blocked DECIMAL(10,2) DEFAULT 0.00
                """))
                conn.commit()

                logger.info("✅ Successfully added margin_blocked column to sandbox_orders table")

                # Update existing open orders with estimated margin
                # This helps maintain consistency for orders placed before this migration
                conn.execute(text("""
                    UPDATE sandbox_orders
                    SET margin_blocked = 0.00
                    WHERE margin_blocked IS NULL
                """))
                conn.commit()

                logger.info("✅ Set default margin_blocked values for existing orders")
            else:
                logger.info("ℹ️  margin_blocked column already exists - skipping")

        logger.info("✅ Migration 002 completed successfully")
        return True

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def rollback():
    """Rollback migration - remove margin_blocked field"""
    try:
        sandbox_db_path = get_sandbox_db_path()
        sandbox_db_url = f"sqlite:///{sandbox_db_path}"

        logger.info(f"Rolling back migration on: {sandbox_db_path}")

        # Create engine
        engine = create_engine(sandbox_db_url)

        with engine.connect() as conn:
            # Check if column exists
            result = conn.execute(text("PRAGMA table_info(sandbox_orders)"))
            columns = [row[1] for row in result]

            if 'margin_blocked' in columns:
                # SQLite doesn't support DROP COLUMN directly
                # We need to recreate the table without the column

                # Get current table schema
                result = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='sandbox_orders'"))
                create_sql = result.fetchone()[0]

                # Create temporary table without margin_blocked
                conn.execute(text("""
                    CREATE TABLE sandbox_orders_temp (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        orderid VARCHAR(50) UNIQUE NOT NULL,
                        user_id VARCHAR(50) NOT NULL,
                        strategy VARCHAR(100),
                        symbol VARCHAR(50) NOT NULL,
                        exchange VARCHAR(20) NOT NULL,
                        action VARCHAR(10) NOT NULL,
                        quantity INTEGER NOT NULL,
                        price DECIMAL(10, 2),
                        trigger_price DECIMAL(10, 2),
                        price_type VARCHAR(20) NOT NULL,
                        product VARCHAR(20) NOT NULL,
                        order_status VARCHAR(20) NOT NULL DEFAULT 'open',
                        average_price DECIMAL(10, 2),
                        filled_quantity INTEGER DEFAULT 0,
                        pending_quantity INTEGER NOT NULL,
                        rejection_reason TEXT,
                        order_timestamp DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                        update_timestamp DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
                    )
                """))

                # Copy data (excluding margin_blocked)
                conn.execute(text("""
                    INSERT INTO sandbox_orders_temp
                    SELECT id, orderid, user_id, strategy, symbol, exchange, action,
                           quantity, price, trigger_price, price_type, product,
                           order_status, average_price, filled_quantity, pending_quantity,
                           rejection_reason, order_timestamp, update_timestamp
                    FROM sandbox_orders
                """))

                # Drop original table
                conn.execute(text("DROP TABLE sandbox_orders"))

                # Rename temp table
                conn.execute(text("ALTER TABLE sandbox_orders_temp RENAME TO sandbox_orders"))

                # Recreate indexes (check if they exist first)
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_orderid ON sandbox_orders(orderid)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_id ON sandbox_orders(user_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_symbol ON sandbox_orders(symbol)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_exchange ON sandbox_orders(exchange)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_order_status ON sandbox_orders(order_status)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_status ON sandbox_orders(user_id, order_status)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_symbol_exchange ON sandbox_orders(symbol, exchange)"))

                conn.commit()

                logger.info("✅ Successfully removed margin_blocked column from sandbox_orders table")
            else:
                logger.info("ℹ️  margin_blocked column doesn't exist - skipping rollback")

        logger.info("✅ Rollback of migration 002 completed successfully")
        return True

    except Exception as e:
        logger.error(f"❌ Rollback failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def status():
    """Check migration status"""
    try:
        sandbox_db_path = get_sandbox_db_path()
        sandbox_db_url = f"sqlite:///{sandbox_db_path}"

        engine = create_engine(sandbox_db_url)

        with engine.connect() as conn:
            # Check if table exists
            result = conn.execute(text("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='sandbox_orders'
            """))

            if not result.fetchone():
                logger.info("❌ sandbox_orders table does not exist")
                return False

            # Check if column exists
            result = conn.execute(text("PRAGMA table_info(sandbox_orders)"))
            columns = [row[1] for row in result]

            if 'margin_blocked' in columns:
                logger.info("✅ Migration 002 is applied - margin_blocked column exists")

                # Show statistics
                result = conn.execute(text("""
                    SELECT
                        COUNT(*) as total_orders,
                        COUNT(CASE WHEN margin_blocked > 0 THEN 1 END) as orders_with_margin
                    FROM sandbox_orders
                """))

                stats = result.fetchone()
                logger.info(f"   Total orders: {stats[0]}")
                logger.info(f"   Orders with margin tracked: {stats[1]}")

                return True
            else:
                logger.info("⚠️  Migration 002 not applied - margin_blocked column missing")
                return False

    except Exception as e:
        logger.error(f"❌ Status check failed: {e}")
        return False


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Migration 002: Add margin_blocked field')
    parser.add_argument('command', choices=['upgrade', 'rollback', 'status'],
                        help='Migration command to execute')

    args = parser.parse_args()

    if args.command == 'upgrade':
        success = upgrade()
        sys.exit(0 if success else 1)
    elif args.command == 'rollback':
        success = rollback()
        sys.exit(0 if success else 1)
    elif args.command == 'status':
        success = status()
        sys.exit(0 if success else 1)