#!/usr/bin/env python
"""
Strategy Risk Management Migration Script for OpenAlgo

Creates new tables for strategy-level risk management, position tracking,
and order tracking. Adds risk columns to existing Strategy/ChartinkStrategy
and SymbolMapping tables.

This migration ensures:
- 5 new tables: strategy_order, strategy_position, strategy_trade,
  strategy_daily_pnl, strategy_position_group
- Risk columns added to strategies, chartink_strategies
- Mapping columns added to strategy_symbol_mappings, chartink_symbol_mappings
- Performance indexes on new tables
- SQLite WAL mode for concurrent access

Usage:
    cd upgrade
    uv run migrate_strategy_risk.py           # Apply migration
    uv run migrate_strategy_risk.py --status  # Check status

Migration: strategy_risk_management
Created: 2026-02-06
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
MIGRATION_NAME = "strategy_risk_management"
MIGRATION_VERSION = "001"

# Load environment
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(parent_dir, ".env"))


def get_main_db_engine():
    """Get main database engine (db/openalgo.db)"""
    db_url = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")

    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        if not os.path.isabs(db_path):
            db_path = os.path.join(parent_dir, db_path)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        db_url = f"sqlite:///{db_path}"
        logger.info(f"Main DB path: {db_path}")

    return create_engine(db_url)


def set_sqlite_pragmas(conn):
    """Configure SQLite for concurrent access (WAL mode)."""
    conn.execute(text("PRAGMA journal_mode=WAL"))
    conn.execute(text("PRAGMA busy_timeout=5000"))
    conn.execute(text("PRAGMA synchronous=NORMAL"))
    conn.execute(text("PRAGMA wal_autocheckpoint=1000"))
    conn.commit()
    logger.info("SQLite PRAGMA settings applied (WAL mode, busy_timeout=5000)")


def get_table_columns(conn, table_name):
    """Get list of column names for a table."""
    result = conn.execute(text(f"PRAGMA table_info({table_name})"))
    return [row[1] for row in result]


def table_exists(conn, table_name):
    """Check if a table exists."""
    result = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    )
    return result.fetchone() is not None


def create_new_tables(conn):
    """Create all new strategy risk tables."""
    logger.info("Creating new tables...")

    # 1. strategy_order — tracks every order placed by a strategy
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS strategy_order (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id       INTEGER NOT NULL,
            strategy_type     VARCHAR(10) NOT NULL,
            user_id           VARCHAR(255) NOT NULL,
            orderid           VARCHAR(50) NOT NULL,
            symbol            VARCHAR(50) NOT NULL,
            exchange          VARCHAR(10) NOT NULL,
            action            VARCHAR(4) NOT NULL,
            quantity          INTEGER NOT NULL,
            product_type      VARCHAR(10) NOT NULL,
            price_type        VARCHAR(10) NOT NULL,
            price             FLOAT DEFAULT 0,
            trigger_price     FLOAT DEFAULT 0,
            order_status      VARCHAR(20) NOT NULL,
            average_price     FLOAT DEFAULT 0,
            filled_quantity   INTEGER DEFAULT 0,
            is_entry          BOOLEAN DEFAULT TRUE,
            exit_reason       VARCHAR(20),
            created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at        DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    )

    # 2. strategy_position — live + historical positions with risk columns
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS strategy_position (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id           INTEGER NOT NULL,
            strategy_type         VARCHAR(10) NOT NULL,
            user_id               VARCHAR(255) NOT NULL,
            symbol                VARCHAR(50) NOT NULL,
            exchange              VARCHAR(10) NOT NULL,
            product_type          VARCHAR(10) NOT NULL,
            action                VARCHAR(4) NOT NULL,
            quantity              INTEGER NOT NULL,
            intended_quantity     INTEGER NOT NULL,
            average_entry_price   FLOAT NOT NULL,
            ltp                   FLOAT DEFAULT 0,
            unrealized_pnl        FLOAT DEFAULT 0,
            unrealized_pnl_pct    FLOAT DEFAULT 0,
            peak_price            FLOAT DEFAULT 0,
            position_state        VARCHAR(15) DEFAULT 'active',
            stoploss_type         VARCHAR(10),
            stoploss_value        FLOAT,
            stoploss_price        FLOAT,
            target_type           VARCHAR(10),
            target_value          FLOAT,
            target_price          FLOAT,
            trailstop_type        VARCHAR(10),
            trailstop_value       FLOAT,
            trailstop_price       FLOAT,
            breakeven_type        VARCHAR(10),
            breakeven_threshold   FLOAT,
            breakeven_activated   BOOLEAN DEFAULT FALSE,
            tick_size             FLOAT DEFAULT 0.05,
            position_group_id     VARCHAR(36),
            risk_mode             VARCHAR(10),
            realized_pnl          FLOAT DEFAULT 0,
            exit_reason           VARCHAR(20),
            exit_detail           VARCHAR(30),
            exit_price            FLOAT,
            closed_at             DATETIME,
            created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at            DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    )

    # 3. strategy_trade — filled trade audit trail
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS strategy_trade (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id       INTEGER NOT NULL,
            strategy_type     VARCHAR(10) NOT NULL,
            user_id           VARCHAR(255) NOT NULL,
            orderid           VARCHAR(50) NOT NULL,
            symbol            VARCHAR(50) NOT NULL,
            exchange          VARCHAR(10) NOT NULL,
            action            VARCHAR(4) NOT NULL,
            quantity          INTEGER NOT NULL,
            price             FLOAT NOT NULL,
            trade_type        VARCHAR(5) NOT NULL,
            exit_reason       VARCHAR(20),
            pnl               FLOAT DEFAULT 0,
            created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    )

    # 4. strategy_daily_pnl — end-of-day snapshots
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS strategy_daily_pnl (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id           INTEGER NOT NULL,
            strategy_type         VARCHAR(10) NOT NULL,
            user_id               VARCHAR(255) NOT NULL,
            date                  DATE NOT NULL,
            realized_pnl          FLOAT DEFAULT 0,
            unrealized_pnl        FLOAT DEFAULT 0,
            total_pnl             FLOAT DEFAULT 0,
            total_trades          INTEGER DEFAULT 0,
            winning_trades        INTEGER DEFAULT 0,
            losing_trades         INTEGER DEFAULT 0,
            gross_profit          FLOAT DEFAULT 0,
            gross_loss            FLOAT DEFAULT 0,
            max_trade_profit      FLOAT DEFAULT 0,
            max_trade_loss        FLOAT DEFAULT 0,
            cumulative_pnl        FLOAT DEFAULT 0,
            peak_cumulative_pnl   FLOAT DEFAULT 0,
            drawdown              FLOAT DEFAULT 0,
            drawdown_pct          FLOAT DEFAULT 0,
            max_drawdown          FLOAT DEFAULT 0,
            max_drawdown_pct      FLOAT DEFAULT 0,
            created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(strategy_id, strategy_type, date)
        )
    """)
    )

    # 5. strategy_position_group — combined P&L group state
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS strategy_position_group (
            id                    VARCHAR(36) PRIMARY KEY,
            strategy_id           INTEGER NOT NULL,
            strategy_type         VARCHAR(10) NOT NULL,
            user_id               VARCHAR(255) NOT NULL,
            symbol_mapping_id     INTEGER NOT NULL,
            expected_legs         INTEGER NOT NULL,
            filled_legs           INTEGER DEFAULT 0,
            group_status          VARCHAR(15) DEFAULT 'filling',
            combined_peak_pnl     FLOAT DEFAULT 0,
            combined_pnl          FLOAT DEFAULT 0,
            entry_value           FLOAT DEFAULT 0,
            initial_stop          FLOAT,
            current_stop          FLOAT,
            exit_triggered        BOOLEAN DEFAULT FALSE,
            created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at            DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    )

    conn.commit()
    logger.info("All new tables created successfully")


def create_indexes(conn):
    """Create performance indexes on new tables."""
    logger.info("Creating indexes...")

    # strategy_order indexes
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_so_strategy ON strategy_order(strategy_id, strategy_type)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_so_orderid ON strategy_order(orderid)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_so_user ON strategy_order(user_id)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_so_status ON strategy_order(order_status)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_so_symbol ON strategy_order(symbol, exchange)")
    )

    # strategy_position indexes
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_sp_strategy ON strategy_position(strategy_id, strategy_type)"
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_sp_user ON strategy_position(user_id)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_sp_symbol ON strategy_position(symbol, exchange)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_sp_state ON strategy_position(position_state)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_sp_group ON strategy_position(position_group_id)")
    )
    # Composite index for active position lookups
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_sp_active ON strategy_position(strategy_id, strategy_type, symbol, exchange, product_type, quantity)"
        )
    )

    # strategy_trade indexes
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_st_strategy ON strategy_trade(strategy_id, strategy_type)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_st_orderid ON strategy_trade(orderid)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_st_user ON strategy_trade(user_id)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_st_symbol ON strategy_trade(symbol, exchange)")
    )

    # strategy_daily_pnl indexes
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_sdp_strategy ON strategy_daily_pnl(strategy_id, strategy_type)"
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_sdp_date ON strategy_daily_pnl(date)")
    )

    # strategy_position_group indexes
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_spg_strategy ON strategy_position_group(strategy_id, strategy_type)"
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_spg_status ON strategy_position_group(group_status)")
    )

    conn.commit()
    logger.info("All indexes created successfully")


def _add_columns_if_missing(conn, table_name, columns):
    """Add columns to a table if they don't already exist.

    Args:
        conn: Database connection
        table_name: Name of the table
        columns: List of (column_name, column_definition) tuples
    """
    existing = get_table_columns(conn, table_name)
    added = 0
    for col_name, col_def in columns:
        if col_name not in existing:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}"))
            added += 1
            logger.info(f"  Added {col_name} to {table_name}")
    conn.commit()
    return added


# Risk columns shared by strategies and chartink_strategies
STRATEGY_RISK_COLUMNS = [
    ("default_stoploss_type", "VARCHAR(10)"),
    ("default_stoploss_value", "FLOAT"),
    ("default_target_type", "VARCHAR(10)"),
    ("default_target_value", "FLOAT"),
    ("default_trailstop_type", "VARCHAR(10)"),
    ("default_trailstop_value", "FLOAT"),
    ("default_breakeven_type", "VARCHAR(10)"),
    ("default_breakeven_threshold", "FLOAT"),
    ("risk_monitoring", "VARCHAR(10) DEFAULT 'active'"),
    ("auto_squareoff_time", "VARCHAR(5) DEFAULT '15:15'"),
    ("default_exit_execution", "VARCHAR(20) DEFAULT 'market'"),
]

# Mapping columns shared by strategy_symbol_mappings and chartink_symbol_mappings
MAPPING_COLUMNS = [
    ("order_mode", "VARCHAR(15) DEFAULT 'equity'"),
    ("underlying", "VARCHAR(50)"),
    ("underlying_exchange", "VARCHAR(15)"),
    ("expiry_type", "VARCHAR(15)"),
    ("offset", "VARCHAR(10)"),
    ("option_type", "VARCHAR(2)"),
    ("risk_mode", "VARCHAR(10)"),
    ("preset", "VARCHAR(20)"),
    ("legs_config", "TEXT"),
    ("combined_stoploss_type", "VARCHAR(10)"),
    ("combined_stoploss_value", "FLOAT"),
    ("combined_target_type", "VARCHAR(10)"),
    ("combined_target_value", "FLOAT"),
    ("combined_trailstop_type", "VARCHAR(10)"),
    ("combined_trailstop_value", "FLOAT"),
    ("stoploss_type", "VARCHAR(10)"),
    ("stoploss_value", "FLOAT"),
    ("target_type", "VARCHAR(10)"),
    ("target_value", "FLOAT"),
    ("trailstop_type", "VARCHAR(10)"),
    ("trailstop_value", "FLOAT"),
    ("breakeven_type", "VARCHAR(10)"),
    ("breakeven_threshold", "FLOAT"),
    ("exit_execution", "VARCHAR(20)"),
]


def add_risk_columns_to_strategies(conn):
    """Add risk management columns to strategies table."""
    logger.info("Adding risk columns to strategies...")
    added = _add_columns_if_missing(conn, "strategies", STRATEGY_RISK_COLUMNS)
    logger.info(f"  {added} columns added to strategies")


def add_risk_columns_to_chartink(conn):
    """Add risk management columns to chartink_strategies table."""
    logger.info("Adding risk columns to chartink_strategies...")

    # Also add trading_mode which is missing from chartink_strategies
    chartink_columns = [("trading_mode", "VARCHAR(10) DEFAULT 'LONG'")] + STRATEGY_RISK_COLUMNS
    added = _add_columns_if_missing(conn, "chartink_strategies", chartink_columns)
    logger.info(f"  {added} columns added to chartink_strategies")


def add_mapping_columns_to_strategy_symbol_mappings(conn):
    """Add order mode and risk columns to strategy_symbol_mappings table."""
    logger.info("Adding mapping columns to strategy_symbol_mappings...")
    added = _add_columns_if_missing(conn, "strategy_symbol_mappings", MAPPING_COLUMNS)
    logger.info(f"  {added} columns added to strategy_symbol_mappings")


def add_mapping_columns_to_chartink_symbol_mappings(conn):
    """Add order mode and risk columns to chartink_symbol_mappings table."""
    logger.info("Adding mapping columns to chartink_symbol_mappings...")
    added = _add_columns_if_missing(conn, "chartink_symbol_mappings", MAPPING_COLUMNS)
    logger.info(f"  {added} columns added to chartink_symbol_mappings")


GROUP_RISK_COLUMNS = [
    ("entry_value", "FLOAT DEFAULT 0"),
    ("initial_stop", "FLOAT"),
    ("current_stop", "FLOAT"),
    ("exit_triggered", "BOOLEAN DEFAULT FALSE"),
]


def add_group_risk_columns(conn):
    """Add AFL-style TSL columns to strategy_position_group for existing databases."""
    if not table_exists(conn, "strategy_position_group"):
        return
    logger.info("Adding risk columns to strategy_position_group...")
    added = _add_columns_if_missing(conn, "strategy_position_group", GROUP_RISK_COLUMNS)
    logger.info(f"  {added} columns added to strategy_position_group")


def upgrade():
    """Apply complete strategy risk management setup."""
    try:
        logger.info(f"Starting migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})")

        engine = get_main_db_engine()

        with engine.connect() as conn:
            # Set WAL mode for concurrent access
            set_sqlite_pragmas(conn)

            # Create new tables
            create_new_tables(conn)

            # Create performance indexes
            create_indexes(conn)

            # Add columns to existing tables
            add_risk_columns_to_strategies(conn)
            add_risk_columns_to_chartink(conn)
            add_mapping_columns_to_strategy_symbol_mappings(conn)
            add_mapping_columns_to_chartink_symbol_mappings(conn)
            add_group_risk_columns(conn)

        logger.info(f"Migration {MIGRATION_NAME} completed successfully")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def status():
    """Check migration status."""
    try:
        logger.info(f"Checking status of migration: {MIGRATION_NAME}")

        engine = get_main_db_engine()

        required_tables = [
            "strategy_order",
            "strategy_position",
            "strategy_trade",
            "strategy_daily_pnl",
            "strategy_position_group",
        ]

        with engine.connect() as conn:
            # Check all required tables
            missing_tables = []
            for tbl in required_tables:
                if not table_exists(conn, tbl):
                    missing_tables.append(tbl)

            if missing_tables:
                logger.info(f"Missing tables: {', '.join(missing_tables)}")
                logger.info("   Migration needed")
                return False

            # Check risk columns on strategies
            strategy_cols = get_table_columns(conn, "strategies")
            missing_strategy_cols = [
                c for c, _ in STRATEGY_RISK_COLUMNS if c not in strategy_cols
            ]
            if missing_strategy_cols:
                logger.info(f"Missing columns on strategies: {', '.join(missing_strategy_cols)}")
                logger.info("   Migration needed")
                return False

            # Check risk columns on chartink_strategies
            chartink_cols = get_table_columns(conn, "chartink_strategies")
            missing_chartink_cols = [
                c
                for c, _ in [("trading_mode", "")] + STRATEGY_RISK_COLUMNS
                if c not in chartink_cols
            ]
            if missing_chartink_cols:
                logger.info(
                    f"Missing columns on chartink_strategies: {', '.join(missing_chartink_cols)}"
                )
                logger.info("   Migration needed")
                return False

            # Check mapping columns on strategy_symbol_mappings
            sm_cols = get_table_columns(conn, "strategy_symbol_mappings")
            missing_sm_cols = [c for c, _ in MAPPING_COLUMNS if c not in sm_cols]
            if missing_sm_cols:
                logger.info(
                    f"Missing columns on strategy_symbol_mappings: {', '.join(missing_sm_cols)}"
                )
                logger.info("   Migration needed")
                return False

            # Check mapping columns on chartink_symbol_mappings
            csm_cols = get_table_columns(conn, "chartink_symbol_mappings")
            missing_csm_cols = [c for c, _ in MAPPING_COLUMNS if c not in csm_cols]
            if missing_csm_cols:
                logger.info(
                    f"Missing columns on chartink_symbol_mappings: {', '.join(missing_csm_cols)}"
                )
                logger.info("   Migration needed")
                return False

            # Check group risk columns on strategy_position_group
            spg_cols = get_table_columns(conn, "strategy_position_group")
            missing_spg_cols = [c for c, _ in GROUP_RISK_COLUMNS if c not in spg_cols]
            if missing_spg_cols:
                logger.info(
                    f"Missing columns on strategy_position_group: {', '.join(missing_spg_cols)}"
                )
                logger.info("   Migration needed")
                return False

            # Show statistics
            result = conn.execute(
                text("""
                SELECT
                    (SELECT COUNT(*) FROM strategy_order) as total_orders,
                    (SELECT COUNT(*) FROM strategy_position) as total_positions,
                    (SELECT COUNT(*) FROM strategy_trade) as total_trades,
                    (SELECT COUNT(*) FROM strategy_daily_pnl) as total_snapshots,
                    (SELECT COUNT(*) FROM strategy_position_group) as total_groups
            """)
            )

            stats = result.fetchone()
            logger.info("Strategy risk management database is fully configured")
            logger.info(f"   Strategy Orders: {stats[0]}")
            logger.info(f"   Strategy Positions: {stats[1]}")
            logger.info(f"   Strategy Trades: {stats[2]}")
            logger.info(f"   Daily PnL Snapshots: {stats[3]}")
            logger.info(f"   Position Groups: {stats[4]}")

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
