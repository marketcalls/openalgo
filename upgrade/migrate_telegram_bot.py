#!/usr/bin/env python
"""
Telegram Bot Migration Script for OpenAlgo

This migration creates all necessary tables for the Telegram bot integration.
It handles both new installations and updates from previous versions.

Usage:
    python upgrade/migrate_telegram_bot.py           # Apply migration
    python upgrade/migrate_telegram_bot.py --status  # Check status
    python upgrade/migrate_telegram_bot.py --downgrade  # Rollback
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

logger = get_logger(__name__)

# Migration metadata
MIGRATION_NAME = "telegram_bot"
MIGRATION_VERSION = "1.1.0"  # Updated version for schema changes
MIGRATION_DESCRIPTION = "Create Telegram bot integration tables (polling mode only)"

class TelegramBotMigration:
    def __init__(self, db_path=None):
        """Initialize migration with database path"""
        if db_path is None:
            # Auto-detect correct database path
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if os.path.basename(script_dir) == 'upgrade':
                # Running from upgrade directory
                db_path = os.path.join(os.path.dirname(script_dir), 'db', 'openalgo.db')
            else:
                # Running from root directory
                db_path = 'db/openalgo.db'
        self.db_path = db_path
        self.db_url = f"sqlite:///{db_path}"
        self.engine = None

    def connect(self):
        """Establish database connection"""
        try:
            # Ensure database directory exists
            db_dir = os.path.dirname(self.db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir)
                logger.info(f"Created database directory: {db_dir}")

            self.engine = create_engine(self.db_url, echo=False)

            # Test connection
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            logger.info(f"Connected to database: {self.db_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            return False

    def create_migration_history_table(self):
        """Create migration history table if it doesn't exist"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS migration_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(100) NOT NULL,
                        version VARCHAR(20) NOT NULL,
                        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        description TEXT,
                        UNIQUE(name)
                    )
                """))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to create migration history table: {e}")

    def check_migration_status(self):
        """Check if this migration has been applied"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT * FROM migration_history WHERE name = :name"),
                    {"name": MIGRATION_NAME}
                ).fetchone()

                if result:
                    return {
                        'applied': True,
                        'version': result[2],
                        'applied_at': result[3]
                    }
                return {'applied': False}

        except OperationalError:
            # Table doesn't exist
            return {'applied': False}
        except Exception as e:
            logger.error(f"Failed to check migration status: {e}")
            return None

    def record_migration(self):
        """Record successful migration in history"""
        try:
            with self.engine.connect() as conn:
                # First, delete any existing record
                conn.execute(
                    text("DELETE FROM migration_history WHERE name = :name"),
                    {"name": MIGRATION_NAME}
                )

                # Insert new record
                conn.execute(
                    text("""
                        INSERT INTO migration_history (name, version, description)
                        VALUES (:name, :version, :description)
                    """),
                    {
                        "name": MIGRATION_NAME,
                        "version": MIGRATION_VERSION,
                        "description": MIGRATION_DESCRIPTION
                    }
                )
                conn.commit()

            logger.info(f"✓ Recorded migration: {MIGRATION_NAME} v{MIGRATION_VERSION}")
            return True

        except Exception as e:
            logger.error(f"Failed to record migration: {e}")
            return False

    def table_exists(self, table_name):
        """Check if a table exists in the database"""
        try:
            inspector = inspect(self.engine)
            return table_name in inspector.get_table_names()
        except Exception as e:
            logger.error(f"Failed to check if table {table_name} exists: {e}")
            return False

    def column_exists(self, table_name, column_name):
        """Check if a column exists in a table"""
        try:
            inspector = inspect(self.engine)
            columns = [col['name'] for col in inspector.get_columns(table_name)]
            return column_name in columns
        except Exception:
            return False

    def upgrade(self):
        """Apply the migration (create tables and handle schema updates)"""
        logger.info(f"Starting upgrade migration: {MIGRATION_NAME} v{MIGRATION_VERSION}")

        if not self.connect():
            return False

        # Create migration history table if needed
        self.create_migration_history_table()

        # Check current status
        status = self.check_migration_status()

        try:
            with self.engine.connect() as conn:
                # Handle bot_config table updates for existing installations
                if self.table_exists('bot_config'):
                    logger.info("bot_config table exists, checking for deprecated columns...")

                    # Create a temporary table with new schema
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS bot_config_new (
                            id INTEGER PRIMARY KEY DEFAULT 1,
                            token TEXT,
                            is_active BOOLEAN DEFAULT 0,
                            bot_username VARCHAR(255),
                            max_message_length INTEGER DEFAULT 4096,
                            rate_limit_per_minute INTEGER DEFAULT 30,
                            broadcast_enabled BOOLEAN DEFAULT 1,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            CONSTRAINT single_config CHECK (id = 1)
                        )
                    """))

                    # Copy data from old table (only columns that exist in new schema)
                    conn.execute(text("""
                        INSERT OR REPLACE INTO bot_config_new
                        (id, token, is_active, bot_username, max_message_length,
                         rate_limit_per_minute, broadcast_enabled, created_at, updated_at)
                        SELECT
                            id,
                            token,
                            is_active,
                            bot_username,
                            COALESCE(max_message_length, 4096),
                            COALESCE(rate_limit_per_minute, 30),
                            COALESCE(broadcast_enabled, 1),
                            COALESCE(created_at, CURRENT_TIMESTAMP),
                            COALESCE(updated_at, CURRENT_TIMESTAMP)
                        FROM bot_config
                    """))

                    # Drop old table and rename new one
                    conn.execute(text("DROP TABLE bot_config"))
                    conn.execute(text("ALTER TABLE bot_config_new RENAME TO bot_config"))
                    logger.info("✓ Updated bot_config table schema (removed webhook_url and polling_mode)")
                else:
                    # Create new bot_config table
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS bot_config (
                            id INTEGER PRIMARY KEY DEFAULT 1,
                            token TEXT,
                            is_active BOOLEAN DEFAULT 0,
                            bot_username VARCHAR(255),
                            max_message_length INTEGER DEFAULT 4096,
                            rate_limit_per_minute INTEGER DEFAULT 30,
                            broadcast_enabled BOOLEAN DEFAULT 1,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            CONSTRAINT single_config CHECK (id = 1)
                        )
                    """))
                    logger.info("✓ Created bot_config table")

                # Create telegram_users table if it doesn't exist
                if not self.table_exists('telegram_users'):
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS telegram_users (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            telegram_id INTEGER UNIQUE NOT NULL,
                            openalgo_username VARCHAR(255) NOT NULL,
                            encrypted_api_key TEXT,
                            host_url VARCHAR(500),
                            first_name VARCHAR(255),
                            last_name VARCHAR(255),
                            telegram_username VARCHAR(255),
                            broker VARCHAR(50) DEFAULT 'default',
                            is_active BOOLEAN DEFAULT 1,
                            notifications_enabled BOOLEAN DEFAULT 1,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            last_command_at TIMESTAMP
                        )
                    """))
                    logger.info("✓ Created telegram_users table")
                else:
                    logger.info("✓ telegram_users table already exists")

                # Create command_logs table if it doesn't exist
                if not self.table_exists('command_logs'):
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS command_logs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            telegram_id INTEGER NOT NULL,
                            command VARCHAR(100) NOT NULL,
                            chat_id INTEGER,
                            parameters TEXT,
                            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (telegram_id) REFERENCES telegram_users(telegram_id)
                        )
                    """))
                    logger.info("✓ Created command_logs table")
                else:
                    logger.info("✓ command_logs table already exists")

                # Create notification_queue table if it doesn't exist
                if not self.table_exists('notification_queue'):
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS notification_queue (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            telegram_id INTEGER NOT NULL,
                            message TEXT NOT NULL,
                            priority INTEGER DEFAULT 5,
                            status VARCHAR(20) DEFAULT 'pending',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            sent_at TIMESTAMP,
                            error_message TEXT,
                            FOREIGN KEY (telegram_id) REFERENCES telegram_users(telegram_id)
                        )
                    """))
                    logger.info("✓ Created notification_queue table")
                else:
                    logger.info("✓ notification_queue table already exists")

                # Create user_preferences table if it doesn't exist
                if not self.table_exists('user_preferences'):
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS user_preferences (
                            telegram_id INTEGER PRIMARY KEY,
                            order_notifications BOOLEAN DEFAULT 1,
                            trade_notifications BOOLEAN DEFAULT 1,
                            pnl_notifications BOOLEAN DEFAULT 1,
                            daily_summary BOOLEAN DEFAULT 1,
                            summary_time VARCHAR(10) DEFAULT '18:00',
                            language VARCHAR(10) DEFAULT 'en',
                            timezone VARCHAR(50) DEFAULT 'Asia/Kolkata',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (telegram_id) REFERENCES telegram_users(telegram_id)
                        )
                    """))
                    logger.info("✓ Created user_preferences table")
                else:
                    logger.info("✓ user_preferences table already exists")

                # Commit all changes
                conn.commit()

            # Record successful migration
            if self.record_migration():
                logger.info(f"✅ Migration {MIGRATION_NAME} v{MIGRATION_VERSION} completed successfully!")
                logger.info("\nTelegram bot tables are ready. You can now:")
                logger.info("1. Configure your bot token in the web interface")
                logger.info("2. Start the bot from the Telegram dashboard")
                return True
            else:
                logger.error("Failed to record migration in history")
                return False

        except Exception as e:
            logger.error(f"Migration failed: {e}")
            return False

    def downgrade(self):
        """Rollback the migration (drop tables)"""
        logger.info(f"Starting downgrade migration: {MIGRATION_NAME}")

        if not self.connect():
            return False

        try:
            with self.engine.connect() as conn:
                # Drop tables in reverse order (due to foreign keys)
                tables = [
                    'user_preferences',
                    'notification_queue',
                    'command_logs',
                    'telegram_users',
                    'bot_config'
                ]

                for table in tables:
                    try:
                        conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
                        logger.info(f"✓ Dropped {table} table")
                    except Exception as e:
                        logger.warning(f"Could not drop {table}: {e}")

                # Remove migration history
                conn.execute(
                    text("DELETE FROM migration_history WHERE name = :name"),
                    {"name": MIGRATION_NAME}
                )
                conn.commit()

            logger.info(f"✅ Downgrade completed. Telegram bot tables removed.")
            return True

        except Exception as e:
            logger.error(f"Downgrade failed: {e}")
            return False

    def status(self):
        """Check and display migration status"""
        if not self.connect():
            return False

        status = self.check_migration_status()

        if status is None:
            logger.error("Could not determine migration status")
            return False

        if status['applied']:
            logger.info(f"✓ Migration '{MIGRATION_NAME}' is APPLIED")
            logger.info(f"  Version: {status['version']}")
            logger.info(f"  Applied at: {status['applied_at']}")

            # Check table existence
            with self.engine.connect() as conn:
                tables = ['telegram_users', 'bot_config', 'command_logs',
                         'notification_queue', 'user_preferences']

                logger.info("\n  Table status:")
                for table in tables:
                    exists = self.table_exists(table)
                    status_icon = "✓" if exists else "✗"
                    logger.info(f"    {status_icon} {table}")

                # Check for deprecated columns in bot_config
                if self.table_exists('bot_config'):
                    deprecated = []
                    if self.column_exists('bot_config', 'webhook_url'):
                        deprecated.append('webhook_url')
                    if self.column_exists('bot_config', 'polling_mode'):
                        deprecated.append('polling_mode')

                    if deprecated:
                        logger.warning(f"\n  ⚠️  Deprecated columns found in bot_config: {', '.join(deprecated)}")
                        logger.warning("  Run migration upgrade to update schema")
        else:
            logger.info(f"✗ Migration '{MIGRATION_NAME}' is NOT APPLIED")
            logger.info("  Run with no arguments to apply the migration")

        return True

def main():
    parser = argparse.ArgumentParser(
        description=f"Telegram Bot Migration for OpenAlgo - {MIGRATION_DESCRIPTION}"
    )
    parser.add_argument(
        '--downgrade',
        action='store_true',
        help='Rollback migration (remove tables)'
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Check migration status'
    )
    parser.add_argument(
        '--db',
        default=None,
        help='Database path (auto-detects if not specified)'
    )

    args = parser.parse_args()

    # Initialize migration
    migration = TelegramBotMigration(db_path=args.db)

    # Execute requested action
    if args.status:
        success = migration.status()
    elif args.downgrade:
        success = migration.downgrade()
    else:
        success = migration.upgrade()

    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()