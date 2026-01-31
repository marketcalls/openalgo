#!/usr/bin/env python3
"""
Migration: Health Metrics Process Details Column

Adds process_details JSON column to health_metrics table.
This migration is idempotent - safe to run multiple times.
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool


def get_health_database_url():
    """Get health database URL from environment"""
    from dotenv import load_dotenv

    load_dotenv()
    return os.getenv("HEALTH_DATABASE_URL", "sqlite:///db/health.db")


def column_exists(engine, table_name, column_name):
    """Check if a column exists in a table"""
    inspector = inspect(engine)
    for column in inspector.get_columns(table_name):
        if column.get("name") == column_name:
            return True
    return False


def add_process_details_column(engine):
    """Add process_details column to health_metrics table"""
    inspector = inspect(engine)
    if "health_metrics" not in inspector.get_table_names():
        print("  [SKIP] health_metrics table not found")
        return True

    if column_exists(engine, "health_metrics", "process_details"):
        print("  [SKIP] process_details column already exists")
        return True

    db_url = str(engine.url)
    if "sqlite" in db_url:
        column_type = "JSON"
    else:
        column_type = "JSONB"

    sql = f"ALTER TABLE health_metrics ADD COLUMN process_details {column_type}"
    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print("  [OK] Added process_details column to health_metrics")
    return True


def main():
    """Run the migration"""
    print()
    print("Health Metrics Process Details Migration")
    print("-" * 40)

    try:
        db_url = get_health_database_url()
        print(f"Database: {db_url.split('://')[0]}://...")

        if "sqlite" in db_url:
            engine = create_engine(db_url, poolclass=NullPool)
        else:
            engine = create_engine(db_url)

        print()
        add_process_details_column(engine)

        print()
        print("[OK] Migration completed")
        return 0
    except Exception as e:
        print(f"[X] Migration failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
