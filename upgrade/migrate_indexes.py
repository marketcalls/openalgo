#!/usr/bin/env python3
"""
Migration script for Database Performance Indexes.

This script adds performance indexes to existing tables across all databases:
1. Main DB: auth, api_keys, analyzer_logs tables
2. Logs DB: traffic_logs, error_404_tracker, invalid_api_key_tracker tables

Usage:
    python migrate_indexes.py
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

def get_project_root():
    """Get project root directory"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_database_url(env_var='DATABASE_URL'):
    """Get database URL from environment"""
    from dotenv import load_dotenv

    project_root = get_project_root()
    load_dotenv(os.path.join(project_root, '.env'))

    database_url = os.getenv(env_var)

    # Convert relative SQLite paths to absolute paths
    if database_url and database_url.startswith('sqlite:///'):
        relative_path = database_url.replace('sqlite:///', '', 1)
        if not os.path.isabs(relative_path):
            absolute_path = os.path.join(project_root, relative_path)
            database_url = f'sqlite:///{absolute_path}'

    return database_url

def check_index_exists(engine, table_name, index_name):
    """Check if an index exists on a table"""
    try:
        inspector = inspect(engine)
        if table_name not in inspector.get_table_names():
            return False
        indexes = inspector.get_indexes(table_name)
        index_names = [idx['name'] for idx in indexes]
        return index_name in index_names
    except Exception:
        return False

def check_table_exists(engine, table_name):
    """Check if a table exists"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()

def create_index(engine, table_name, index_name, columns, description=""):
    """Create an index if it doesn't exist"""
    try:
        # Check if table exists
        if not check_table_exists(engine, table_name):
            logger.info(f"  - Skipping {index_name}: table '{table_name}' not found")
            return True  # Not an error, table might not exist yet

        # Check if index already exists
        if check_index_exists(engine, table_name, index_name):
            logger.info(f"  [OK] {index_name} already exists")
            return True

        # Create the index
        column_list = ', '.join(columns) if isinstance(columns, list) else columns
        sql = f"CREATE INDEX {index_name} ON {table_name}({column_list})"

        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()

        desc = f" ({description})" if description else ""
        logger.info(f"  [OK] Created {index_name}{desc}")
        return True

    except Exception as e:
        logger.error(f"  [X] Error creating {index_name}: {e}")
        return False

def migrate_main_db_indexes(engine):
    """Add indexes to main database tables (auth, api_keys, analyzer_logs)"""
    logger.info("")
    logger.info("Main Database Indexes:")
    logger.info("-" * 40)

    success = True

    # Auth table indexes
    if check_table_exists(engine, 'auth'):
        success &= create_index(engine, 'auth', 'idx_auth_broker', 'broker',
                               'speeds up broker lookups')
        success &= create_index(engine, 'auth', 'idx_auth_user_id', 'user_id',
                               'speeds up user_id lookups')
        success &= create_index(engine, 'auth', 'idx_auth_is_revoked', 'is_revoked',
                               'speeds up token validity checks')
    else:
        logger.info("  - Skipping auth indexes: table not found")

    # ApiKeys table indexes
    if check_table_exists(engine, 'api_keys'):
        success &= create_index(engine, 'api_keys', 'idx_api_keys_order_mode', 'order_mode',
                               'speeds up order mode filtering')
        success &= create_index(engine, 'api_keys', 'idx_api_keys_created_at', 'created_at',
                               'speeds up time-based queries')
    else:
        logger.info("  - Skipping api_keys indexes: table not found")

    # AnalyzerLog table indexes
    if check_table_exists(engine, 'analyzer_logs'):
        success &= create_index(engine, 'analyzer_logs', 'idx_analyzer_api_type', 'api_type',
                               'speeds up API type filtering')
        success &= create_index(engine, 'analyzer_logs', 'idx_analyzer_created_at', 'created_at',
                               'speeds up time-based queries')
        success &= create_index(engine, 'analyzer_logs', 'idx_analyzer_type_time', ['api_type', 'created_at'],
                               'composite for API type + time range')
    else:
        logger.info("  - Skipping analyzer_logs indexes: table not found")

    return success

def migrate_logs_db_indexes(engine):
    """Add indexes to logs database tables (traffic_logs, error_404_tracker, invalid_api_key_tracker)"""
    logger.info("")
    logger.info("Logs Database Indexes:")
    logger.info("-" * 40)

    success = True

    # TrafficLog table indexes
    if check_table_exists(engine, 'traffic_logs'):
        success &= create_index(engine, 'traffic_logs', 'idx_traffic_timestamp', 'timestamp',
                               'speeds up recent logs retrieval')
        success &= create_index(engine, 'traffic_logs', 'idx_traffic_client_ip', 'client_ip',
                               'speeds up IP-based filtering')
        success &= create_index(engine, 'traffic_logs', 'idx_traffic_status_code', 'status_code',
                               'speeds up error rate calculations')
        success &= create_index(engine, 'traffic_logs', 'idx_traffic_user_id', 'user_id',
                               'speeds up per-user analysis')
        success &= create_index(engine, 'traffic_logs', 'idx_traffic_ip_timestamp', ['client_ip', 'timestamp'],
                               'composite for IP + time range')
    else:
        logger.info("  - Skipping traffic_logs indexes: table not found")

    # Error404Tracker table indexes
    if check_table_exists(engine, 'error_404_tracker'):
        success &= create_index(engine, 'error_404_tracker', 'idx_404_error_count', 'error_count',
                               'speeds up suspicious IP detection')
        success &= create_index(engine, 'error_404_tracker', 'idx_404_first_error_at', 'first_error_at',
                               'speeds up old entry cleanup')
    else:
        logger.info("  - Skipping error_404_tracker indexes: table not found")

    # InvalidAPIKeyTracker table indexes
    if check_table_exists(engine, 'invalid_api_key_tracker'):
        success &= create_index(engine, 'invalid_api_key_tracker', 'idx_api_tracker_attempt_count', 'attempt_count',
                               'speeds up suspicious user detection')
        success &= create_index(engine, 'invalid_api_key_tracker', 'idx_api_tracker_first_attempt_at', 'first_attempt_at',
                               'speeds up old entry cleanup')
    else:
        logger.info("  - Skipping invalid_api_key_tracker indexes: table not found")

    return success

def verify_indexes(engine, db_name, expected_indexes):
    """Verify that indexes were created"""
    logger.info(f"")
    logger.info(f"Verifying {db_name} indexes...")

    all_found = True
    for table_name, index_name in expected_indexes:
        if not check_table_exists(engine, table_name):
            continue  # Skip if table doesn't exist
        if check_index_exists(engine, table_name, index_name):
            logger.info(f"  [OK] {index_name}")
        else:
            logger.warning(f"  [!] {index_name} not found")
            all_found = False

    return all_found

def main():
    """Main migration function"""
    print("=" * 60)
    print("Database Performance Indexes Migration")
    print("=" * 60)
    print()

    success = True

    # ============================================
    # MAIN DATABASE (auth, api_keys, analyzer_logs)
    # ============================================
    database_url = get_database_url('DATABASE_URL')
    if database_url:
        logger.info(f"Main DB: {database_url}")
        try:
            engine = create_engine(database_url)
            logger.info("[OK] Connected to main database")

            if not migrate_main_db_indexes(engine):
                success = False

            # Verify main DB indexes
            main_indexes = [
                ('auth', 'idx_auth_broker'),
                ('auth', 'idx_auth_user_id'),
                ('auth', 'idx_auth_is_revoked'),
                ('api_keys', 'idx_api_keys_order_mode'),
                ('api_keys', 'idx_api_keys_created_at'),
                ('analyzer_logs', 'idx_analyzer_api_type'),
                ('analyzer_logs', 'idx_analyzer_created_at'),
                ('analyzer_logs', 'idx_analyzer_type_time'),
            ]
            verify_indexes(engine, "Main DB", main_indexes)

        except Exception as e:
            logger.error(f"[X] Failed to connect to main database: {e}")
            success = False
    else:
        logger.warning("DATABASE_URL not found, skipping main database")

    # ============================================
    # LOGS DATABASE (traffic_logs, error trackers)
    # ============================================
    logs_url = get_database_url('LOGS_DATABASE_URL')
    if not logs_url:
        # Default fallback
        logs_url = f"sqlite:///{os.path.join(get_project_root(), 'db', 'logs.db')}"

    logger.info("")
    logger.info(f"Logs DB: {logs_url}")

    try:
        logs_engine = create_engine(logs_url)
        logger.info("[OK] Connected to logs database")

        if not migrate_logs_db_indexes(logs_engine):
            success = False

        # Verify logs DB indexes
        logs_indexes = [
            ('traffic_logs', 'idx_traffic_timestamp'),
            ('traffic_logs', 'idx_traffic_client_ip'),
            ('traffic_logs', 'idx_traffic_status_code'),
            ('traffic_logs', 'idx_traffic_user_id'),
            ('traffic_logs', 'idx_traffic_ip_timestamp'),
            ('error_404_tracker', 'idx_404_error_count'),
            ('error_404_tracker', 'idx_404_first_error_at'),
            ('invalid_api_key_tracker', 'idx_api_tracker_attempt_count'),
            ('invalid_api_key_tracker', 'idx_api_tracker_first_attempt_at'),
        ]
        verify_indexes(logs_engine, "Logs DB", logs_indexes)

    except Exception as e:
        logger.error(f"[X] Failed to connect to logs database: {e}")
        success = False

    # ============================================
    # SUMMARY
    # ============================================
    print()
    if success:
        print("=" * 60)
        print("[OK] Migration completed successfully!")
        print("=" * 60)
        print()
        print("Summary of indexes added:")
        print("  Main DB:")
        print("    - auth: broker, user_id, is_revoked")
        print("    - api_keys: order_mode, created_at")
        print("    - analyzer_logs: api_type, created_at, (api_type+created_at)")
        print()
        print("  Logs DB:")
        print("    - traffic_logs: timestamp, client_ip, status_code, user_id, (client_ip+timestamp)")
        print("    - error_404_tracker: error_count, first_error_at")
        print("    - invalid_api_key_tracker: attempt_count, first_attempt_at")
        print()
        print("Benefits:")
        print("  - Faster query execution (O(log n) vs O(n) table scans)")
        print("  - Improved security dashboard performance")
        print("  - Better log retrieval and analytics")
        print()
    else:
        print("=" * 60)
        print("[X] Migration completed with errors")
        print("=" * 60)
        print("Please check the logs above for details")
        print()

    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
