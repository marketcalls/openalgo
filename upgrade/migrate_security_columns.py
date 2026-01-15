#!/usr/bin/env python3
"""
Migration script to add security columns to existing settings table.
This resolves the "no such column: settings.security_404_threshold" error.

Usage:
    cd upgrade
    python migrate_security_columns.py
"""

import os
import sys

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text, inspect
from dotenv import load_dotenv

# Load environment from parent directory
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(env_path)

# Import logger after environment is loaded
from utils.logging import get_logger

logger = get_logger(__name__)

def migrate_settings_table():
    """Add missing security columns to the settings table if they don't exist"""

    # Get database URL from environment
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///db/openalgo.db')

    # Adjust path for SQLite if relative (since we're in upgrade folder)
    if DATABASE_URL.startswith('sqlite:///') and not DATABASE_URL.startswith('sqlite:////'):
        # Extract the relative path
        db_path = DATABASE_URL.replace('sqlite:///', '')
        # Make it relative to parent directory (openalgo root)
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_db_path = os.path.join(parent_dir, db_path)
        DATABASE_URL = f'sqlite:///{full_db_path}'
        logger.info(f"Using database: {full_db_path}")

    try:
        # Create engine
        engine = create_engine(DATABASE_URL)

        # Get inspector to check existing columns
        inspector = inspect(engine)

        # Check if settings table exists
        if 'settings' not in inspector.get_table_names():
            logger.info("Settings table doesn't exist. It will be created on first run.")
            return True

        # Get existing columns in settings table
        existing_columns = [col['name'] for col in inspector.get_columns('settings')]
        logger.info(f"Existing columns in settings table: {existing_columns}")

        # Define the security columns that should exist
        security_columns = [
            ('security_404_threshold', 'INTEGER DEFAULT 20'),
            ('security_404_ban_duration', 'INTEGER DEFAULT 24'),
            ('security_api_threshold', 'INTEGER DEFAULT 10'),
            ('security_api_ban_duration', 'INTEGER DEFAULT 48'),
            ('security_repeat_offender_limit', 'INTEGER DEFAULT 3')
        ]

        columns_added = 0
        columns_existing = 0

        # Add missing columns
        with engine.connect() as conn:
            for column_name, column_def in security_columns:
                if column_name not in existing_columns:
                    try:
                        alter_sql = text(f"ALTER TABLE settings ADD COLUMN {column_name} {column_def}")
                        conn.execute(alter_sql)
                        conn.commit()
                        logger.info(f"✅ Added column: {column_name}")
                        columns_added += 1
                    except Exception as col_error:
                        # Column might already exist in some edge cases
                        logger.warning(f"Could not add column {column_name}: {col_error}")
                else:
                    logger.info(f"✓ Column already exists: {column_name}")
                    columns_existing += 1

        logger.info(f"\n📊 Migration Summary:")
        logger.info(f"   - Columns added: {columns_added}")
        logger.info(f"   - Columns already existing: {columns_existing}")
        logger.info(f"   - Total security columns: {len(security_columns)}")

        if columns_added > 0:
            logger.info("\n✅ Settings table migration completed successfully!")
            logger.info("   New security columns have been added to your database.")
        else:
            logger.info("\n✅ No migration needed - all security columns already exist!")

        return True

    except Exception as e:
        logger.error(f"❌ Error during migration: {e}")
        return False

def main():
    """Main function to run the migration"""
    logger.info("=" * 60)
    logger.info("OpenAlgo Security Columns Migration Script")
    logger.info("=" * 60)
    logger.info("This script adds missing security columns to the settings table")
    logger.info("to fix the 'no such column: settings.security_404_threshold' error")
    logger.info("-" * 60)

    success = migrate_settings_table()

    logger.info("-" * 60)
    if success:
        logger.info("Migration process completed!")
        logger.info("\n📌 Next Steps:")
        logger.info("   1. Restart your OpenAlgo application")
        logger.info("   2. The /security endpoint should now work properly")
        logger.info("   3. You can access security settings at: http://127.0.0.1:5000/security")
        return 0
    else:
        logger.error("Migration failed! Please check the error messages above.")
        logger.error("\n📌 Troubleshooting:")
        logger.error("   1. Ensure the database file exists and is accessible")
        logger.error("   2. Check that you have write permissions to the database")
        logger.error("   3. Verify your DATABASE_URL in the .env file")
        logger.error("\nIf the problem persists, you may need to:")
        logger.error("   - Backup your data and recreate the database")
        logger.error("   - Or manually add the columns using a SQLite tool")
        return 1

if __name__ == "__main__":
    sys.exit(main())