#!/usr/bin/env python
"""
Sandbox Complete Setup Migration Script for OpenAlgo

This migration ensures the complete sandbox/analyzer mode setup:
- Creates all sandbox tables if they don't exist
- Adds any missing columns (like margin_blocked)
- Creates all required indexes
- Sets up default configuration values
- Updates database path to /db directory

Usage:
    cd upgrade
    uv run migrate_sandbox_complete.py           # Apply migration
    uv run migrate_sandbox_complete.py --status  # Check status

Migration: 003
Created: 2025-10-01
"""

import sys
import os
import argparse
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import OperationalError, IntegrityError
from utils.logging import get_logger
from dotenv import load_dotenv

logger = get_logger(__name__)

# Migration metadata
MIGRATION_NAME = "sandbox_complete_setup"
MIGRATION_VERSION = "003"

# Load environment
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(parent_dir, '.env'))


def get_sandbox_db_engine():
    """Get sandbox database engine"""
    # Get from environment variable or use default
    sandbox_db_url = os.getenv('SANDBOX_DATABASE_URL', 'sqlite:///db/sandbox.db')

    # Extract path from URL and make absolute
    if sandbox_db_url.startswith('sqlite:///'):
        db_path = sandbox_db_url.replace('sqlite:///', '')

        if not os.path.isabs(db_path):
            db_path = os.path.join(parent_dir, db_path)

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        sandbox_db_url = f"sqlite:///{db_path}"
        logger.info(f"Sandbox DB path: {db_path}")

    return create_engine(sandbox_db_url)


def create_all_tables(conn):
    """Create all sandbox tables"""

    logger.info("Creating sandbox tables...")

    # 1. SandboxOrders table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS sandbox_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            orderid VARCHAR(50) UNIQUE NOT NULL,
            user_id VARCHAR(50) NOT NULL,
            strategy VARCHAR(100),
            symbol VARCHAR(50) NOT NULL,
            exchange VARCHAR(20) NOT NULL,
            action VARCHAR(10) NOT NULL CHECK(action IN ('BUY', 'SELL')),
            quantity INTEGER NOT NULL,
            price DECIMAL(10, 2),
            trigger_price DECIMAL(10, 2),
            price_type VARCHAR(20) NOT NULL CHECK(price_type IN ('MARKET', 'LIMIT', 'SL', 'SL-M')),
            product VARCHAR(20) NOT NULL CHECK(product IN ('CNC', 'NRML', 'MIS')),
            order_status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK(order_status IN ('open', 'complete', 'cancelled', 'rejected')),
            average_price DECIMAL(10, 2),
            filled_quantity INTEGER DEFAULT 0,
            pending_quantity INTEGER NOT NULL,
            rejection_reason TEXT,
            margin_blocked DECIMAL(10, 2) DEFAULT 0.00,
            order_timestamp DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            update_timestamp DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
        )
    """))

    # 2. SandboxTrades table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS sandbox_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tradeid VARCHAR(50) UNIQUE NOT NULL,
            orderid VARCHAR(50) NOT NULL,
            user_id VARCHAR(50) NOT NULL,
            symbol VARCHAR(50) NOT NULL,
            exchange VARCHAR(20) NOT NULL,
            action VARCHAR(10) NOT NULL,
            quantity INTEGER NOT NULL,
            price DECIMAL(10, 2) NOT NULL,
            product VARCHAR(20) NOT NULL,
            strategy VARCHAR(100),
            trade_timestamp DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
        )
    """))

    # 3. SandboxPositions table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS sandbox_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id VARCHAR(50) NOT NULL,
            symbol VARCHAR(50) NOT NULL,
            exchange VARCHAR(20) NOT NULL,
            product VARCHAR(20) NOT NULL,
            quantity INTEGER NOT NULL,
            average_price DECIMAL(10, 2) NOT NULL,
            ltp DECIMAL(10, 2),
            pnl DECIMAL(10, 2) DEFAULT 0.00,
            pnl_percent DECIMAL(10, 4) DEFAULT 0.00,
            accumulated_realized_pnl DECIMAL(10, 2) DEFAULT 0.00,
            margin_blocked DECIMAL(15, 2) DEFAULT 0.00,
            created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            UNIQUE(user_id, symbol, exchange, product)
        )
    """))

    # 4. SandboxHoldings table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS sandbox_holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id VARCHAR(50) NOT NULL,
            symbol VARCHAR(50) NOT NULL,
            exchange VARCHAR(20) NOT NULL,
            quantity INTEGER NOT NULL,
            average_price DECIMAL(10, 2) NOT NULL,
            ltp DECIMAL(10, 2),
            pnl DECIMAL(10, 2) DEFAULT 0.00,
            pnl_percent DECIMAL(10, 4) DEFAULT 0.00,
            settlement_date DATE NOT NULL,
            created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            UNIQUE(user_id, symbol, exchange)
        )
    """))

    # 5. SandboxFunds table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS sandbox_funds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id VARCHAR(50) UNIQUE NOT NULL,
            total_capital DECIMAL(15, 2) DEFAULT 10000000.00,
            available_balance DECIMAL(15, 2) DEFAULT 10000000.00,
            used_margin DECIMAL(15, 2) DEFAULT 0.00,
            realized_pnl DECIMAL(15, 2) DEFAULT 0.00,
            unrealized_pnl DECIMAL(15, 2) DEFAULT 0.00,
            total_pnl DECIMAL(15, 2) DEFAULT 0.00,
            last_reset_date DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            reset_count INTEGER DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
        )
    """))

    # 6. SandboxConfig table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS sandbox_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_key VARCHAR(100) UNIQUE NOT NULL,
            config_value TEXT NOT NULL,
            description TEXT,
            updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
        )
    """))

    conn.commit()
    logger.info("✅ All sandbox tables created successfully")


def create_all_indexes(conn):
    """Create all required indexes"""

    logger.info("Creating indexes...")

    # Indexes for sandbox_orders
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_orderid ON sandbox_orders(orderid)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_id ON sandbox_orders(user_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_symbol ON sandbox_orders(symbol)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_exchange ON sandbox_orders(exchange)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_order_status ON sandbox_orders(order_status)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_status ON sandbox_orders(user_id, order_status)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_symbol_exchange ON sandbox_orders(symbol, exchange)"))

    # Indexes for sandbox_trades
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tradeid ON sandbox_trades(tradeid)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_trade_orderid ON sandbox_trades(orderid)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_trade_user ON sandbox_trades(user_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_symbol_trade ON sandbox_trades(user_id, symbol)"))

    # Indexes for sandbox_positions
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_position_user ON sandbox_positions(user_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_symbol ON sandbox_positions(user_id, symbol)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_product ON sandbox_positions(user_id, product)"))

    # Indexes for sandbox_holdings
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_holding_user ON sandbox_holdings(user_id)"))

    # Index for sandbox_funds
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_funds_user ON sandbox_funds(user_id)"))

    # Index for sandbox_config
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_config_key ON sandbox_config(config_key)"))

    conn.commit()
    logger.info("✅ All indexes created successfully")


def add_missing_columns(conn):
    """Add any missing columns to existing tables"""

    logger.info("Checking for missing columns...")

    # Check and add margin_blocked to sandbox_orders if missing
    result = conn.execute(text("PRAGMA table_info(sandbox_orders)"))
    columns = [row[1] for row in result]

    if 'margin_blocked' not in columns:
        conn.execute(text("""
            ALTER TABLE sandbox_orders
            ADD COLUMN margin_blocked DECIMAL(10,2) DEFAULT 0.00
        """))
        logger.info("✅ Added margin_blocked column to sandbox_orders")

    # Check and add accumulated_realized_pnl to sandbox_positions if missing
    result = conn.execute(text("PRAGMA table_info(sandbox_positions)"))
    columns = [row[1] for row in result]

    if 'accumulated_realized_pnl' not in columns:
        conn.execute(text("""
            ALTER TABLE sandbox_positions
            ADD COLUMN accumulated_realized_pnl DECIMAL(10,2) DEFAULT 0.00
        """))
        logger.info("✅ Added accumulated_realized_pnl column to sandbox_positions")

    # Check and add margin_blocked to sandbox_positions if missing
    if 'margin_blocked' not in columns:
        conn.execute(text("""
            ALTER TABLE sandbox_positions
            ADD COLUMN margin_blocked DECIMAL(15,2) DEFAULT 0.00
        """))
        logger.info("✅ Added margin_blocked column to sandbox_positions")

    conn.commit()


def insert_default_config(conn):
    """Insert default configuration values"""

    logger.info("Inserting default configuration...")

    default_configs = [
        ('starting_capital', '10000000.00', 'Starting sandbox capital in INR (₹1 Crore) - Min: ₹1000'),
        ('reset_day', 'Sunday', 'Day of week for automatic fund reset'),
        ('reset_time', '00:00', 'Time for automatic fund reset (IST)'),
        ('order_check_interval', '5', 'Interval in seconds to check pending orders - Range: 1-30 seconds'),
        ('mtm_update_interval', '5', 'Interval in seconds to update MTM - Range: 0-60 seconds (0 = manual only)'),
        ('nse_bse_square_off_time', '15:15', 'Square-off time for NSE/BSE MIS positions (IST)'),
        ('cds_bcd_square_off_time', '16:45', 'Square-off time for CDS/BCD MIS positions (IST)'),
        ('mcx_square_off_time', '23:30', 'Square-off time for MCX MIS positions (IST)'),
        ('ncdex_square_off_time', '17:00', 'Square-off time for NCDEX MIS positions (IST)'),
        ('equity_mis_leverage', '5', 'Leverage multiplier for equity MIS (NSE/BSE) - Range: 1-50x'),
        ('equity_cnc_leverage', '1', 'Leverage multiplier for equity CNC (NSE/BSE) - Range: 1-50x'),
        ('futures_leverage', '10', 'Leverage multiplier for all futures (NFO/BFO/CDS/BCD/MCX/NCDEX) - Range: 1-50x'),
        ('option_buy_leverage', '1', 'Leverage multiplier for buying options (full premium) - Range: 1-50x'),
        ('option_sell_leverage', '1', 'Leverage multiplier for selling options (same as buying - full premium) - Range: 1-50x'),
        ('order_rate_limit', '10', 'Maximum orders per second - Range: 1-100 orders/sec'),
        ('api_rate_limit', '50', 'Maximum API calls per second - Range: 1-1000 calls/sec'),
        ('smart_order_rate_limit', '2', 'Maximum smart orders per second - Range: 1-50 orders/sec'),
        ('smart_order_delay', '0.5', 'Delay between multi-leg smart orders - Range: 0.1-10 seconds'),
    ]

    added_count = 0
    for key, value, description in default_configs:
        # Check if config exists
        result = conn.execute(text("SELECT 1 FROM sandbox_config WHERE config_key = :key"), {'key': key})
        if not result.fetchone():
            conn.execute(text("""
                INSERT INTO sandbox_config (config_key, config_value, description)
                VALUES (:key, :value, :description)
            """), {'key': key, 'value': value, 'description': description})
            added_count += 1

    conn.commit()
    logger.info(f"✅ Added {added_count} default configuration entries")


def upgrade():
    """Apply complete sandbox setup"""
    try:
        logger.info(f"Starting migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})")

        engine = get_sandbox_db_engine()

        with engine.connect() as conn:
            # Create all tables
            create_all_tables(conn)

            # Create all indexes
            create_all_indexes(conn)

            # Add missing columns
            add_missing_columns(conn)

            # Insert default config
            insert_default_config(conn)

        logger.info(f"✅ Migration {MIGRATION_NAME} completed successfully")
        return True

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def status():
    """Check migration status"""
    try:
        logger.info(f"Checking status of migration: {MIGRATION_NAME}")

        engine = get_sandbox_db_engine()

        required_tables = [
            'sandbox_orders', 'sandbox_trades', 'sandbox_positions',
            'sandbox_holdings', 'sandbox_funds', 'sandbox_config'
        ]

        with engine.connect() as conn:
            # Check all required tables
            missing_tables = []
            for table in required_tables:
                result = conn.execute(text(f"""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='{table}'
                """))
                if not result.fetchone():
                    missing_tables.append(table)

            if missing_tables:
                logger.info(f"❌ Missing tables: {', '.join(missing_tables)}")
                logger.info("   Migration needed")
                return False

            # Check critical columns
            result = conn.execute(text("PRAGMA table_info(sandbox_orders)"))
            columns = [row[1] for row in result]

            if 'margin_blocked' not in columns:
                logger.info("⚠️  Missing margin_blocked column in sandbox_orders")
                logger.info("   Migration needed")
                return False

            # Check for accumulated_realized_pnl and margin_blocked in sandbox_positions
            result = conn.execute(text("PRAGMA table_info(sandbox_positions)"))
            columns = [row[1] for row in result]

            if 'accumulated_realized_pnl' not in columns:
                logger.info("⚠️  Missing accumulated_realized_pnl column in sandbox_positions")
                logger.info("   Migration needed")
                return False

            if 'margin_blocked' not in columns:
                logger.info("⚠️  Missing margin_blocked column in sandbox_positions")
                logger.info("   Migration needed")
                return False

            # Show statistics
            result = conn.execute(text("""
                SELECT
                    (SELECT COUNT(*) FROM sandbox_orders) as total_orders,
                    (SELECT COUNT(*) FROM sandbox_trades) as total_trades,
                    (SELECT COUNT(*) FROM sandbox_positions WHERE quantity != 0) as open_positions,
                    (SELECT COUNT(DISTINCT user_id) FROM sandbox_funds) as total_users,
                    (SELECT COUNT(*) FROM sandbox_config) as config_entries
            """))

            stats = result.fetchone()
            logger.info("✅ Sandbox database is fully configured")
            logger.info(f"   Total Orders: {stats[0]}")
            logger.info(f"   Total Trades: {stats[1]}")
            logger.info(f"   Open Positions: {stats[2]}")
            logger.info(f"   Total Users: {stats[3]}")
            logger.info(f"   Config Entries: {stats[4]}")

            return True

    except Exception as e:
        logger.error(f"❌ Status check failed: {e}")
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=f'Migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--status', action='store_true',
                        help='Check migration status')

    args = parser.parse_args()

    if args.status:
        success = status()
    else:
        success = upgrade()

    sys.exit(0 if success else 1)
