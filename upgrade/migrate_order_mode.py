#!/usr/bin/env python3
"""
Migration script for Order Mode and Action Center feature.

This script:
1. Adds 'order_mode' column to api_keys table (default: 'auto')
2. Creates 'pending_orders' table for semi-automated orders
3. Sets default order_mode to 'auto' for all existing users

Usage:
    python migrate_order_mode.py
"""

import os
import sys
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

# Set UTF-8 encoding for output to handle Unicode characters on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logging import get_logger

logger = get_logger(__name__)

def get_database_url():
    """Get database URL from environment"""
    from dotenv import load_dotenv

    # Get the project root directory (parent of upgrade folder)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Load .env from project root
    load_dotenv(os.path.join(project_root, '.env'))

    database_url = os.getenv('DATABASE_URL')

    # Convert relative SQLite paths to absolute paths
    if database_url and database_url.startswith('sqlite:///'):
        # Extract the relative path after sqlite:///
        relative_path = database_url.replace('sqlite:///', '', 1)

        # If it's not already an absolute path, make it absolute relative to project root
        if not os.path.isabs(relative_path):
            absolute_path = os.path.join(project_root, relative_path)
            database_url = f'sqlite:///{absolute_path}'

    return database_url

def check_column_exists(engine, table_name, column_name):
    """Check if a column exists in a table"""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns

def check_table_exists(engine, table_name):
    """Check if a table exists"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()

def add_order_mode_column(engine):
    """Add order_mode column to api_keys table"""
    try:
        # Check if column already exists
        if check_column_exists(engine, 'api_keys', 'order_mode'):
            logger.info("✓ order_mode column already exists in api_keys table")
            return True

        logger.info("Adding order_mode column to api_keys table...")

        # Add column with default value 'auto'
        with engine.connect() as conn:
            conn.execute(text("""
                ALTER TABLE api_keys
                ADD COLUMN order_mode VARCHAR(20) DEFAULT 'auto'
            """))
            conn.commit()

        logger.info("✓ order_mode column added successfully")
        return True

    except Exception as e:
        logger.error(f"✗ Error adding order_mode column: {e}")
        return False

def create_pending_orders_table(engine):
    """Create pending_orders table"""
    try:
        # Check if table already exists
        if check_table_exists(engine, 'pending_orders'):
            logger.info("✓ pending_orders table already exists")
            return True

        logger.info("Creating pending_orders table...")

        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE pending_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id VARCHAR(255) NOT NULL,
                    api_type VARCHAR(50) NOT NULL,
                    order_data TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_at_ist VARCHAR(50),
                    status VARCHAR(20) DEFAULT 'pending',
                    approved_at DATETIME,
                    approved_at_ist VARCHAR(50),
                    approved_by VARCHAR(255),
                    rejected_at DATETIME,
                    rejected_at_ist VARCHAR(50),
                    rejected_by VARCHAR(255),
                    rejected_reason TEXT,
                    broker_order_id VARCHAR(255),
                    broker_status VARCHAR(20)
                )
            """))
            conn.commit()

        # Create indexes
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE INDEX idx_user_status ON pending_orders(user_id, status)
            """))
            conn.execute(text("""
                CREATE INDEX idx_created_at ON pending_orders(created_at)
            """))
            conn.commit()

        logger.info("✓ pending_orders table created successfully")
        return True

    except Exception as e:
        logger.error(f"✗ Error creating pending_orders table: {e}")
        return False

def set_default_mode(engine):
    """Set default order_mode to 'auto' for all existing users"""
    try:
        logger.info("Setting default order_mode to 'auto' for existing users...")

        with engine.connect() as conn:
            result = conn.execute(text("""
                UPDATE api_keys
                SET order_mode = 'auto'
                WHERE order_mode IS NULL
            """))
            conn.commit()

            rows_updated = result.rowcount
            logger.info(f"✓ Updated {rows_updated} users with default order_mode='auto'")

        return True

    except Exception as e:
        logger.error(f"✗ Error setting default mode: {e}")
        return False

def verify_migration(engine):
    """Verify that migration was successful"""
    try:
        logger.info("Verifying migration...")

        # Check order_mode column
        if not check_column_exists(engine, 'api_keys', 'order_mode'):
            logger.error("✗ order_mode column not found in api_keys table")
            return False

        # Check pending_orders table
        if not check_table_exists(engine, 'pending_orders'):
            logger.error("✗ pending_orders table not found")
            return False

        # Check indexes
        inspector = inspect(engine)
        indexes = inspector.get_indexes('pending_orders')
        index_names = [idx['name'] for idx in indexes]

        if 'idx_user_status' not in index_names:
            logger.warning("⚠ idx_user_status index not found")
        else:
            logger.info("✓ idx_user_status index exists")

        if 'idx_created_at' not in index_names:
            logger.warning("⚠ idx_created_at index not found")
        else:
            logger.info("✓ idx_created_at index exists")

        logger.info("✓ Migration verified successfully")
        return True

    except Exception as e:
        logger.error(f"✗ Error verifying migration: {e}")
        return False

def main():
    """Main migration function"""
    print("="*60)
    print("Order Mode & Action Center Migration")
    print("="*60)
    print()

    # Get database URL
    database_url = get_database_url()
    if not database_url:
        logger.error("DATABASE_URL not found in environment")
        return False

    logger.info(f"Database URL: {database_url}")

    # Create engine
    try:
        engine = create_engine(database_url)
        logger.info("✓ Database connection established")
    except Exception as e:
        logger.error(f"✗ Failed to connect to database: {e}")
        return False

    # Run migrations
    success = True

    # Step 1: Add order_mode column to api_keys
    if not add_order_mode_column(engine):
        success = False

    # Step 2: Create pending_orders table
    if not create_pending_orders_table(engine):
        success = False

    # Step 3: Set default mode for existing users
    if not set_default_mode(engine):
        success = False

    # Step 4: Verify migration
    if not verify_migration(engine):
        success = False

    print()
    if success:
        print("="*60)
        print("✓ Migration completed successfully!")
        print("="*60)
        print()
        print("Summary:")
        print("  - Added order_mode column to api_keys table (default: 'auto')")
        print("  - Created pending_orders table")
        print("  - Set all existing users to 'auto' mode")
        print()
        print("Next steps:")
        print("  - Users can toggle between 'auto' and 'semi_auto' mode in API Key settings")
        print("  - Semi-auto orders will appear in Action Center for approval")
        print()
    else:
        print("="*60)
        print("✗ Migration completed with errors")
        print("="*60)
        print("Please check the logs above for details")
        print()

    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
