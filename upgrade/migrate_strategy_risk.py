#!/usr/bin/env python3
"""
Migration: Strategy Risk Management Tables

This migration adds:
- 6 new tables: strategy_order, strategy_position, strategy_trade,
  strategy_daily_pnl, strategy_position_group, alert_log
- Risk columns to strategies and strategy_symbol_mappings tables
- Risk columns to chartink_strategies and chartink_symbol_mappings tables
- Indexes for efficient lookups

This migration is idempotent - safe to run multiple times.
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool


def get_database_url():
    """Get database URL from environment"""
    from dotenv import load_dotenv

    load_dotenv()
    return os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")


def table_exists(engine, table_name):
    """Check if a table exists in the database"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def column_exists(engine, table_name, column_name):
    """Check if a column exists in a table"""
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return False
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def is_sqlite(engine):
    """Check if the database is SQLite"""
    return "sqlite" in str(engine.url)


# ─── New Table Creation ───────────────────────────────────────────────────


def create_strategy_order_table(engine):
    """Create strategy_order table"""
    if table_exists(engine, "strategy_order"):
        print("  [SKIP] strategy_order table already exists")
        return True

    print("  [CREATE] Creating strategy_order table...")

    if is_sqlite(engine):
        sql = """
        CREATE TABLE strategy_order (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id INTEGER NOT NULL,
            strategy_type VARCHAR(10) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            orderid VARCHAR(50) NOT NULL,
            symbol VARCHAR(50) NOT NULL,
            exchange VARCHAR(10) NOT NULL,
            action VARCHAR(4) NOT NULL,
            quantity INTEGER NOT NULL,
            product_type VARCHAR(10) NOT NULL,
            price_type VARCHAR(10) NOT NULL,
            price FLOAT DEFAULT 0,
            trigger_price FLOAT DEFAULT 0,
            order_status VARCHAR(20) NOT NULL,
            average_price FLOAT DEFAULT 0,
            filled_quantity INTEGER DEFAULT 0,
            is_entry BOOLEAN DEFAULT 1,
            exit_reason VARCHAR(20),
            position_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    else:
        sql = """
        CREATE TABLE strategy_order (
            id SERIAL PRIMARY KEY,
            strategy_id INTEGER NOT NULL,
            strategy_type VARCHAR(10) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            orderid VARCHAR(50) NOT NULL,
            symbol VARCHAR(50) NOT NULL,
            exchange VARCHAR(10) NOT NULL,
            action VARCHAR(4) NOT NULL,
            quantity INTEGER NOT NULL,
            product_type VARCHAR(10) NOT NULL,
            price_type VARCHAR(10) NOT NULL,
            price FLOAT DEFAULT 0,
            trigger_price FLOAT DEFAULT 0,
            order_status VARCHAR(20) NOT NULL,
            average_price FLOAT DEFAULT 0,
            filled_quantity INTEGER DEFAULT 0,
            is_entry BOOLEAN DEFAULT TRUE,
            exit_reason VARCHAR(20),
            position_id INTEGER,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print("  [OK] strategy_order table created")
    return True


def create_strategy_position_table(engine):
    """Create strategy_position table"""
    if table_exists(engine, "strategy_position"):
        print("  [SKIP] strategy_position table already exists")
        return True

    print("  [CREATE] Creating strategy_position table...")

    if is_sqlite(engine):
        sql = """
        CREATE TABLE strategy_position (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id INTEGER NOT NULL,
            strategy_type VARCHAR(10) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            symbol VARCHAR(50) NOT NULL,
            exchange VARCHAR(10) NOT NULL,
            product_type VARCHAR(10) NOT NULL,
            action VARCHAR(4) NOT NULL,
            quantity INTEGER NOT NULL,
            intended_quantity INTEGER NOT NULL,
            average_entry_price FLOAT NOT NULL,
            ltp FLOAT DEFAULT 0,
            unrealized_pnl FLOAT DEFAULT 0,
            unrealized_pnl_pct FLOAT DEFAULT 0,
            peak_price FLOAT DEFAULT 0,
            position_state VARCHAR(15) DEFAULT 'pending_entry',
            stoploss_type VARCHAR(10),
            stoploss_value FLOAT,
            stoploss_price FLOAT,
            target_type VARCHAR(10),
            target_value FLOAT,
            target_price FLOAT,
            trailstop_type VARCHAR(10),
            trailstop_value FLOAT,
            trailstop_price FLOAT,
            breakeven_type VARCHAR(10),
            breakeven_threshold FLOAT,
            breakeven_activated BOOLEAN DEFAULT 0,
            tick_size FLOAT DEFAULT 0.05,
            position_group_id VARCHAR(36),
            risk_mode VARCHAR(10),
            realized_pnl FLOAT DEFAULT 0,
            exit_reason VARCHAR(20),
            exit_detail VARCHAR(30),
            exit_price FLOAT,
            closed_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    else:
        sql = """
        CREATE TABLE strategy_position (
            id SERIAL PRIMARY KEY,
            strategy_id INTEGER NOT NULL,
            strategy_type VARCHAR(10) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            symbol VARCHAR(50) NOT NULL,
            exchange VARCHAR(10) NOT NULL,
            product_type VARCHAR(10) NOT NULL,
            action VARCHAR(4) NOT NULL,
            quantity INTEGER NOT NULL,
            intended_quantity INTEGER NOT NULL,
            average_entry_price FLOAT NOT NULL,
            ltp FLOAT DEFAULT 0,
            unrealized_pnl FLOAT DEFAULT 0,
            unrealized_pnl_pct FLOAT DEFAULT 0,
            peak_price FLOAT DEFAULT 0,
            position_state VARCHAR(15) DEFAULT 'pending_entry',
            stoploss_type VARCHAR(10),
            stoploss_value FLOAT,
            stoploss_price FLOAT,
            target_type VARCHAR(10),
            target_value FLOAT,
            target_price FLOAT,
            trailstop_type VARCHAR(10),
            trailstop_value FLOAT,
            trailstop_price FLOAT,
            breakeven_type VARCHAR(10),
            breakeven_threshold FLOAT,
            breakeven_activated BOOLEAN DEFAULT FALSE,
            tick_size FLOAT DEFAULT 0.05,
            position_group_id VARCHAR(36),
            risk_mode VARCHAR(10),
            realized_pnl FLOAT DEFAULT 0,
            exit_reason VARCHAR(20),
            exit_detail VARCHAR(30),
            exit_price FLOAT,
            closed_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print("  [OK] strategy_position table created")
    return True


def create_strategy_trade_table(engine):
    """Create strategy_trade table"""
    if table_exists(engine, "strategy_trade"):
        print("  [SKIP] strategy_trade table already exists")
        return True

    print("  [CREATE] Creating strategy_trade table...")

    if is_sqlite(engine):
        sql = """
        CREATE TABLE strategy_trade (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id INTEGER NOT NULL,
            strategy_type VARCHAR(10) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            orderid VARCHAR(50) NOT NULL,
            symbol VARCHAR(50) NOT NULL,
            exchange VARCHAR(10) NOT NULL,
            action VARCHAR(4) NOT NULL,
            quantity INTEGER NOT NULL,
            price FLOAT NOT NULL,
            trade_type VARCHAR(5) NOT NULL,
            exit_reason VARCHAR(20),
            pnl FLOAT DEFAULT 0,
            position_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    else:
        sql = """
        CREATE TABLE strategy_trade (
            id SERIAL PRIMARY KEY,
            strategy_id INTEGER NOT NULL,
            strategy_type VARCHAR(10) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            orderid VARCHAR(50) NOT NULL,
            symbol VARCHAR(50) NOT NULL,
            exchange VARCHAR(10) NOT NULL,
            action VARCHAR(4) NOT NULL,
            quantity INTEGER NOT NULL,
            price FLOAT NOT NULL,
            trade_type VARCHAR(5) NOT NULL,
            exit_reason VARCHAR(20),
            pnl FLOAT DEFAULT 0,
            position_id INTEGER,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print("  [OK] strategy_trade table created")
    return True


def create_strategy_daily_pnl_table(engine):
    """Create strategy_daily_pnl table"""
    if table_exists(engine, "strategy_daily_pnl"):
        print("  [SKIP] strategy_daily_pnl table already exists")
        return True

    print("  [CREATE] Creating strategy_daily_pnl table...")

    if is_sqlite(engine):
        sql = """
        CREATE TABLE strategy_daily_pnl (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id INTEGER NOT NULL,
            strategy_type VARCHAR(10) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            date DATE NOT NULL,
            realized_pnl FLOAT DEFAULT 0,
            unrealized_pnl FLOAT DEFAULT 0,
            total_pnl FLOAT DEFAULT 0,
            total_trades INTEGER DEFAULT 0,
            winning_trades INTEGER DEFAULT 0,
            losing_trades INTEGER DEFAULT 0,
            gross_profit FLOAT DEFAULT 0,
            gross_loss FLOAT DEFAULT 0,
            max_trade_profit FLOAT DEFAULT 0,
            max_trade_loss FLOAT DEFAULT 0,
            cumulative_pnl FLOAT DEFAULT 0,
            peak_cumulative_pnl FLOAT DEFAULT 0,
            drawdown FLOAT DEFAULT 0,
            drawdown_pct FLOAT DEFAULT 0,
            max_drawdown FLOAT DEFAULT 0,
            max_drawdown_pct FLOAT DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(strategy_id, strategy_type, date)
        )
        """
    else:
        sql = """
        CREATE TABLE strategy_daily_pnl (
            id SERIAL PRIMARY KEY,
            strategy_id INTEGER NOT NULL,
            strategy_type VARCHAR(10) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            date DATE NOT NULL,
            realized_pnl FLOAT DEFAULT 0,
            unrealized_pnl FLOAT DEFAULT 0,
            total_pnl FLOAT DEFAULT 0,
            total_trades INTEGER DEFAULT 0,
            winning_trades INTEGER DEFAULT 0,
            losing_trades INTEGER DEFAULT 0,
            gross_profit FLOAT DEFAULT 0,
            gross_loss FLOAT DEFAULT 0,
            max_trade_profit FLOAT DEFAULT 0,
            max_trade_loss FLOAT DEFAULT 0,
            cumulative_pnl FLOAT DEFAULT 0,
            peak_cumulative_pnl FLOAT DEFAULT 0,
            drawdown FLOAT DEFAULT 0,
            drawdown_pct FLOAT DEFAULT 0,
            max_drawdown FLOAT DEFAULT 0,
            max_drawdown_pct FLOAT DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(strategy_id, strategy_type, date)
        )
        """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print("  [OK] strategy_daily_pnl table created")
    return True


def create_strategy_position_group_table(engine):
    """Create strategy_position_group table"""
    if table_exists(engine, "strategy_position_group"):
        print("  [SKIP] strategy_position_group table already exists")
        return True

    print("  [CREATE] Creating strategy_position_group table...")

    if is_sqlite(engine):
        sql = """
        CREATE TABLE strategy_position_group (
            id VARCHAR(36) PRIMARY KEY,
            strategy_id INTEGER NOT NULL,
            strategy_type VARCHAR(10) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            symbol_mapping_id INTEGER NOT NULL,
            expected_legs INTEGER NOT NULL,
            filled_legs INTEGER DEFAULT 0,
            group_status VARCHAR(15) DEFAULT 'filling',
            combined_peak_pnl FLOAT DEFAULT 0,
            combined_pnl FLOAT DEFAULT 0,
            entry_value FLOAT DEFAULT 0,
            initial_stop FLOAT,
            current_stop FLOAT,
            exit_triggered BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    else:
        sql = """
        CREATE TABLE strategy_position_group (
            id VARCHAR(36) PRIMARY KEY,
            strategy_id INTEGER NOT NULL,
            strategy_type VARCHAR(10) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            symbol_mapping_id INTEGER NOT NULL,
            expected_legs INTEGER NOT NULL,
            filled_legs INTEGER DEFAULT 0,
            group_status VARCHAR(15) DEFAULT 'filling',
            combined_peak_pnl FLOAT DEFAULT 0,
            combined_pnl FLOAT DEFAULT 0,
            entry_value FLOAT DEFAULT 0,
            initial_stop FLOAT,
            current_stop FLOAT,
            exit_triggered BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print("  [OK] strategy_position_group table created")
    return True


def create_alert_log_table(engine):
    """Create alert_log table"""
    if table_exists(engine, "alert_log"):
        print("  [SKIP] alert_log table already exists")
        return True

    print("  [CREATE] Creating alert_log table...")

    if is_sqlite(engine):
        sql = """
        CREATE TABLE alert_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id VARCHAR(50) NOT NULL,
            alert_type VARCHAR(20) NOT NULL,
            symbol VARCHAR(50),
            exchange VARCHAR(10),
            strategy_id INTEGER,
            strategy_type VARCHAR(10),
            trigger_reason VARCHAR(30),
            trigger_price FLOAT,
            ltp_at_trigger FLOAT,
            pnl FLOAT,
            message TEXT,
            channels_attempted TEXT,
            channels_delivered TEXT,
            errors TEXT,
            priority VARCHAR(10) DEFAULT 'normal',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    else:
        sql = """
        CREATE TABLE alert_log (
            id SERIAL PRIMARY KEY,
            alert_id VARCHAR(50) NOT NULL,
            alert_type VARCHAR(20) NOT NULL,
            symbol VARCHAR(50),
            exchange VARCHAR(10),
            strategy_id INTEGER,
            strategy_type VARCHAR(10),
            trigger_reason VARCHAR(30),
            trigger_price FLOAT,
            ltp_at_trigger FLOAT,
            pnl FLOAT,
            message TEXT,
            channels_attempted JSONB,
            channels_delivered JSONB,
            errors JSONB,
            priority VARCHAR(10) DEFAULT 'normal',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print("  [OK] alert_log table created")
    return True


# ─── Column Additions ─────────────────────────────────────────────────────


def add_strategy_risk_columns(engine):
    """Add risk columns to strategies table"""
    columns = [
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
    ]

    _add_columns_to_table(engine, "strategies", columns)


def add_strategy_mapping_columns(engine):
    """Add order mode and risk columns to strategy_symbol_mappings table"""
    columns = [
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
    ]

    _add_columns_to_table(engine, "strategy_symbol_mappings", columns)


def add_chartink_risk_columns(engine):
    """Add risk columns to chartink_strategies table"""
    columns = [
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
    ]

    _add_columns_to_table(engine, "chartink_strategies", columns)


def add_chartink_mapping_columns(engine):
    """Add order mode and risk columns to chartink_symbol_mappings table"""
    columns = [
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
    ]

    _add_columns_to_table(engine, "chartink_symbol_mappings", columns)


def _add_columns_to_table(engine, table_name, columns):
    """Add columns to a table if they don't already exist"""
    if not table_exists(engine, table_name):
        print(f"  [SKIP] {table_name} table does not exist")
        return

    for col_name, col_type in columns:
        if column_exists(engine, table_name, col_name):
            print(f"  [SKIP] {table_name}.{col_name} already exists")
            continue

        try:
            sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            print(f"  [OK] Added {table_name}.{col_name}")
        except Exception as e:
            print(f"  [WARN] Could not add {table_name}.{col_name}: {e}")


# ─── Index Creation ───────────────────────────────────────────────────────


def create_indexes(engine):
    """Create indexes for strategy risk tables"""
    indexes = [
        # strategy_order indexes
        ("idx_strategy_order_strategy", "strategy_order", "strategy_id, strategy_type"),
        ("idx_strategy_order_orderid", "strategy_order", "orderid"),
        ("idx_strategy_order_status", "strategy_order", "order_status"),
        # strategy_position indexes
        ("idx_strategy_position_active", "strategy_position", "strategy_id, strategy_type, symbol, exchange, product_type"),
        ("idx_strategy_position_state", "strategy_position", "position_state"),
        ("idx_strategy_position_group", "strategy_position", "position_group_id"),
        ("idx_strategy_position_user", "strategy_position", "user_id"),
        # strategy_trade indexes
        ("idx_strategy_trade_strategy", "strategy_trade", "strategy_id, strategy_type"),
        ("idx_strategy_trade_orderid", "strategy_trade", "orderid"),
        # strategy_daily_pnl indexes
        ("idx_strategy_daily_pnl_strategy", "strategy_daily_pnl", "strategy_id, strategy_type"),
        # alert_log indexes
        ("idx_alert_log_symbol", "alert_log", "symbol, exchange"),
        ("idx_alert_log_strategy", "alert_log", "strategy_id, strategy_type"),
        ("idx_alert_log_type", "alert_log", "alert_type, created_at"),
    ]

    for index_name, table_name, column_spec in indexes:
        if not table_exists(engine, table_name):
            continue

        try:
            inspector = inspect(engine)
            existing_indexes = [idx["name"] for idx in inspector.get_indexes(table_name)]

            if index_name in existing_indexes:
                print(f"  [SKIP] Index {index_name} already exists")
                continue

            sql = f"CREATE INDEX {index_name} ON {table_name} ({column_spec})"
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            print(f"  [OK] Created index {index_name}")

        except Exception as e:
            print(f"  [SKIP] Index {index_name}: {e}")

    return True


# ─── Main ─────────────────────────────────────────────────────────────────


def main():
    """Run the migration"""
    print()
    print("Strategy Risk Management Migration")
    print("-" * 40)

    try:
        db_url = get_database_url()
        print(f"Database: {db_url.split('://')[0]}://...")

        if "sqlite" in db_url:
            engine = create_engine(db_url, poolclass=NullPool)
        else:
            engine = create_engine(db_url)

        # Create new tables
        print()
        print("Creating new tables...")
        create_strategy_order_table(engine)
        create_strategy_position_table(engine)
        create_strategy_trade_table(engine)
        create_strategy_daily_pnl_table(engine)
        create_strategy_position_group_table(engine)
        create_alert_log_table(engine)

        # Add columns to existing tables
        print()
        print("Adding risk columns to strategies table...")
        add_strategy_risk_columns(engine)

        print()
        print("Adding columns to strategy_symbol_mappings table...")
        add_strategy_mapping_columns(engine)

        print()
        print("Adding risk columns to chartink_strategies table...")
        add_chartink_risk_columns(engine)

        print()
        print("Adding columns to chartink_symbol_mappings table...")
        add_chartink_mapping_columns(engine)

        # Create indexes
        print()
        print("Creating indexes...")
        create_indexes(engine)

        print()
        print("[OK] Strategy Risk Management migration completed successfully!")
        return 0

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
