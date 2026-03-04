#!/usr/bin/env python3
"""
Migration script to add the 'contract_value' column to the symtoken table.

The SymToken model defines a 'contract_value' (Float) column that was added
to the model but never applied to existing databases via a migration. This
causes SQLAlchemy to fail on every query touching the symtoken table, which
in turn causes all symbol lookups (quotes, orders, etc.) to return
"Symbol not found" errors even when master contracts are downloaded.

Usage:
    uv run python upgrade/migrate_contract_value.py

This script is safe to run multiple times — it checks if the column
already exists before attempting to add it.
"""

import os
import sys

# Set UTF-8 encoding for output to handle Unicode characters on Windows
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Add parent directory to path so imports work correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_project_root():
    """Get project root directory"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_database_url(env_var="DATABASE_URL"):
    """Get database URL from environment, resolving relative SQLite paths to absolute."""
    from dotenv import load_dotenv

    project_root = get_project_root()
    load_dotenv(os.path.join(project_root, ".env"))

    database_url = os.getenv(env_var)

    if not database_url:
        print(f"ERROR: {env_var} environment variable not set in .env")
        sys.exit(1)

    # Convert relative SQLite paths to absolute paths
    if database_url.startswith("sqlite:///"):
        relative_path = database_url.replace("sqlite:///", "", 1)
        if not os.path.isabs(relative_path):
            absolute_path = os.path.join(project_root, relative_path)
            database_url = f"sqlite:///{absolute_path}"

    return database_url


def column_exists(engine, table_name, column_name):
    """Check if a column already exists in the given table."""
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(engine)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def table_exists(engine, table_name):
    """Check if a table exists in the database."""
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(engine)
    return table_name in inspector.get_table_names()


def migrate_contract_value():
    """Add contract_value column to the symtoken table if it doesn't exist."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    print("=" * 60)
    print("Migration: Add contract_value column to symtoken table")
    print("=" * 60)

    database_url = get_database_url("DATABASE_URL")
    print(f"\nConnecting to database: {database_url}")

    try:
        engine = create_engine(database_url)

        # Verify the symtoken table exists
        if not table_exists(engine, "symtoken"):
            print(
                "\nINFO: symtoken table does not exist yet. "
                "It will be created with the correct schema when master contracts are downloaded. "
                "No migration needed."
            )
            return True

        # Check if contract_value column already exists
        if column_exists(engine, "symtoken", "contract_value"):
            print("\n✓ contract_value column already exists in symtoken table.")
            print("  No migration needed — database schema is up to date.")
            return True

        # Add the missing column
        print("\nAdding contract_value column to symtoken table...")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE symtoken ADD COLUMN contract_value FLOAT"))
            conn.commit()

        # Verify it was added successfully
        if column_exists(engine, "symtoken", "contract_value"):
            print("✓ Successfully added contract_value column to symtoken table.")
            print("\nMigration complete! The quotes API should now work correctly.")
            print(
                "NOTE: If you still see 'Symbol not found' errors, please re-download "
                "master contracts from the OpenAlgo dashboard."
            )
            return True
        else:
            print("ERROR: Column was not added successfully. Please check your database.")
            return False

    except OperationalError as e:
        print(f"\nERROR: Database operation failed: {e}")
        return False
    except Exception as e:
        print(f"\nERROR: Unexpected error during migration: {e}")
        return False


if __name__ == "__main__":
    success = migrate_contract_value()
    sys.exit(0 if success else 1)
