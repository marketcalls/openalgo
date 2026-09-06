#!/usr/bin/env python
"""
Order Idempotency Store Migration Script for OpenAlgo

Creates the application-level order idempotency store (see
database/idempotency_db.py): a (api_key, client_order_id) -> broker orderid
mapping so a client that retries a timed-out placement gets the existing
order echoed back instead of a duplicate position.

Changes:
- Creates the client_order_ids table in db/idempotency.db if absent
- Creates the lookup indexes (created_at, (api_key_hash, orderid))

Usage:
    cd upgrade
    uv run migrate_idempotency_store.py           # Apply migration
    uv run migrate_idempotency_store.py --status  # Check status
"""

import argparse
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Register the app's SQLite pragmas on this process's engines, so a migration
# waits the same 15s for a write lock the running app does instead of the
# sqlite3 default of 5s (GitHub issue #1726).
import _pragmas  # noqa: F401,E402
from dotenv import load_dotenv
from sqlalchemy import inspect, text

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

# Migration metadata
MIGRATION_NAME = "order_idempotency_store"

# Load environment
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(parent_dir, ".env"))

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS client_order_ids (
    id INTEGER NOT NULL PRIMARY KEY,
    api_key_hash VARCHAR(64) NOT NULL,
    client_order_id VARCHAR(128) NOT NULL,
    orderid VARCHAR(64),
    tag VARCHAR(128),
    status VARCHAR(16) NOT NULL DEFAULT 'in_flight',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT uq_client_order_ids_key UNIQUE (api_key_hash, client_order_id)
)
"""

INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_client_order_ids_api_key_hash "
    "ON client_order_ids (api_key_hash)",
    "CREATE INDEX IF NOT EXISTS ix_client_order_ids_created_at ON client_order_ids (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_client_order_ids_api_key_hash_orderid "
    "ON client_order_ids (api_key_hash, orderid)",
]


def get_idempotency_db_engine():
    """Get the idempotency store engine (db/idempotency.db by default)."""
    db_url = os.getenv("IDEMPOTENCY_DATABASE_URL", "sqlite:///db/idempotency.db")

    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        if not os.path.isabs(db_path):
            # Resolve relative paths against the repo root, not the CWD the
            # migration was invoked from (upgrade/ per migrate_all.py).
            db_path = os.path.join(parent_dir, db_path)
            db_url = f"sqlite:///{db_path}"
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    return create_db_engine(db_url)


def migration_status(engine):
    """Return (table_exists, missing_index_names)."""
    insp = inspect(engine)
    table_exists = insp.has_table("client_order_ids")
    missing = []
    if table_exists:
        existing = {ix["name"] for ix in insp.get_indexes("client_order_ids")}
        missing = [
            name
            for name in (
                "ix_client_order_ids_api_key_hash",
                "ix_client_order_ids_created_at",
                "ix_client_order_ids_api_key_hash_orderid",
            )
            if name not in existing
        ]
    return table_exists, missing


def migrate(engine):
    applied = False
    with engine.connect() as conn:
        conn.execute(text(TABLE_SQL))
        for stmt in INDEX_SQL:
            conn.execute(text(stmt))
        conn.commit()
        applied = True
    return applied


def main():
    parser = argparse.ArgumentParser(description=MIGRATION_NAME)
    parser.add_argument(
        "--status", action="store_true", help="Show migration status without applying"
    )
    args = parser.parse_args()

    engine = get_idempotency_db_engine()

    table_exists, missing = migration_status(engine)

    if args.status:
        print(f"Migration: {MIGRATION_NAME}")
        if not table_exists:
            print("  Table client_order_ids: MISSING (indexes: n/a)")
        else:
            print("  Table client_order_ids: present")
            print(f"  Missing indexes: {', '.join(missing)}" if missing else "  Indexes: present")
        print(f"  Status: {'applied' if table_exists and not missing else 'pending'}")
        return 0

    if table_exists and not missing:
        print(f"[{MIGRATION_NAME}] already applied, skipping")
        return 0

    migrate(engine)
    print(f"[{MIGRATION_NAME}] applied: client_order_ids table and indexes ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
