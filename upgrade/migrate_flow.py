#!/usr/bin/env python3
"""
Migration: Flow Workflow Tables

This migration adds the tables required for Flow workflow automation:
- flow_workflows: Stores workflow definitions (nodes, edges, webhook config)
- flow_workflow_executions: Stores workflow execution history and logs
- flow_apscheduler_jobs: APScheduler job store for scheduled workflows

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


def create_flow_workflows_table(engine):
    """Create flow_workflows table"""
    if table_exists(engine, "flow_workflows"):
        print("  [SKIP] flow_workflows table already exists")
        return True

    print("  [CREATE] Creating flow_workflows table...")

    # Determine SQL based on database type
    db_url = str(engine.url)
    if "sqlite" in db_url:
        sql = """
        CREATE TABLE flow_workflows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            nodes JSON DEFAULT '[]',
            edges JSON DEFAULT '[]',
            is_active BOOLEAN DEFAULT 0,
            schedule_job_id VARCHAR(255),
            webhook_token VARCHAR(64) UNIQUE,
            webhook_secret VARCHAR(64),
            webhook_enabled BOOLEAN DEFAULT 0,
            webhook_auth_type VARCHAR(20) DEFAULT 'payload',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    else:
        # PostgreSQL
        sql = """
        CREATE TABLE flow_workflows (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            nodes JSONB DEFAULT '[]'::jsonb,
            edges JSONB DEFAULT '[]'::jsonb,
            is_active BOOLEAN DEFAULT FALSE,
            schedule_job_id VARCHAR(255),
            webhook_token VARCHAR(64) UNIQUE,
            webhook_secret VARCHAR(64),
            webhook_enabled BOOLEAN DEFAULT FALSE,
            webhook_auth_type VARCHAR(20) DEFAULT 'payload',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print("  [OK] flow_workflows table created")
    return True


def create_flow_workflow_executions_table(engine):
    """Create flow_workflow_executions table"""
    if table_exists(engine, "flow_workflow_executions"):
        print("  [SKIP] flow_workflow_executions table already exists")
        return True

    print("  [CREATE] Creating flow_workflow_executions table...")

    # Determine SQL based on database type
    db_url = str(engine.url)
    if "sqlite" in db_url:
        sql = """
        CREATE TABLE flow_workflow_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            status VARCHAR(50) DEFAULT 'pending',
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            logs JSON DEFAULT '[]',
            error TEXT,
            FOREIGN KEY (workflow_id) REFERENCES flow_workflows(id) ON DELETE CASCADE
        )
        """
    else:
        # PostgreSQL
        sql = """
        CREATE TABLE flow_workflow_executions (
            id SERIAL PRIMARY KEY,
            workflow_id INTEGER NOT NULL,
            status VARCHAR(50) DEFAULT 'pending',
            started_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            logs JSONB DEFAULT '[]'::jsonb,
            error TEXT,
            FOREIGN KEY (workflow_id) REFERENCES flow_workflows(id) ON DELETE CASCADE
        )
        """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    print("  [OK] flow_workflow_executions table created")
    return True


def create_indexes(engine):
    """Create indexes for Flow tables"""
    indexes = [
        ("idx_flow_workflows_webhook_token", "flow_workflows", "webhook_token"),
        ("idx_flow_workflows_is_active", "flow_workflows", "is_active"),
        ("idx_flow_executions_workflow_id", "flow_workflow_executions", "workflow_id"),
        ("idx_flow_executions_status", "flow_workflow_executions", "status"),
        ("idx_flow_executions_started_at", "flow_workflow_executions", "started_at"),
    ]

    for index_name, table_name, column_name in indexes:
        if not table_exists(engine, table_name):
            continue

        try:
            # Check if index already exists
            inspector = inspect(engine)
            existing_indexes = [idx["name"] for idx in inspector.get_indexes(table_name)]

            if index_name in existing_indexes:
                print(f"  [SKIP] Index {index_name} already exists")
                continue

            sql = f"CREATE INDEX {index_name} ON {table_name} ({column_name})"
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            print(f"  [OK] Created index {index_name}")

        except Exception as e:
            # Index might already exist with different name
            print(f"  [SKIP] Index {index_name}: {e}")

    return True


def main():
    """Run the migration"""
    print()
    print("Flow Workflow Tables Migration")
    print("-" * 40)

    try:
        # Get database URL
        db_url = get_database_url()
        print(f"Database: {db_url.split('://')[0]}://...")

        # Create engine
        if "sqlite" in db_url:
            engine = create_engine(db_url, poolclass=NullPool)
        else:
            engine = create_engine(db_url)

        # Run migrations
        print()
        print("Creating tables...")
        create_flow_workflows_table(engine)
        create_flow_workflow_executions_table(engine)

        print()
        print("Creating indexes...")
        create_indexes(engine)

        print()
        print("[OK] Flow migration completed successfully!")
        return 0

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
