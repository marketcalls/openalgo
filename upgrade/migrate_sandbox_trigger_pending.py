#!/usr/bin/env python
"""
Sandbox Trigger-Pending Status Migration Script for OpenAlgo

SL and SL-M orders in sandbox mode used to sit as "open" from the moment
they were placed until the trigger price was hit, with no way to tell them
apart from a normal resting LIMIT order. Real exchanges keep SL/SL-M orders
in a separate Stop-Loss order book until the trigger fires, reported back as
order_status "trigger pending" - not "open" (see broker/zerodha/streaming/
zerodha_order_adapter.py's _STATUS_MAP and docs/api/websocket-streaming/
order-updates.md, which already document "trigger pending" as a live-broker
status). This migration lets the sandbox engine store that same status.

SQLite does not support altering a CHECK constraint in place, so this
rebuilds sandbox_orders with the widened constraint via the standard
create-new / copy-data / drop-old / rename procedure, preserving every
existing row and every existing index.

Changes:
- Widens sandbox_orders.order_status CHECK constraint to also allow
  'trigger pending'

Usage:
    cd upgrade
    uv run migrate_sandbox_trigger_pending.py           # Apply migration
    uv run migrate_sandbox_trigger_pending.py --status  # Check status

Migration: 005
Created: 2026-07-24
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
MIGRATION_NAME = "sandbox_trigger_pending_status"
MIGRATION_VERSION = "005"

# Load environment
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(parent_dir, ".env"))

NEW_ORDER_STATUS_VALUES = "'open', 'trigger pending', 'complete', 'cancelled', 'rejected'"

# Every index that migrate_sandbox.py's create_all_tables() creates on
# sandbox_orders - recreated after the rebuild so nothing is lost.
SANDBOX_ORDERS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_orderid ON sandbox_orders(orderid)",
    "CREATE INDEX IF NOT EXISTS idx_user_id ON sandbox_orders(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_symbol ON sandbox_orders(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_exchange ON sandbox_orders(exchange)",
    "CREATE INDEX IF NOT EXISTS idx_order_status ON sandbox_orders(order_status)",
    "CREATE INDEX IF NOT EXISTS idx_user_status ON sandbox_orders(user_id, order_status)",
    "CREATE INDEX IF NOT EXISTS idx_symbol_exchange ON sandbox_orders(symbol, exchange)",
    # Also created by the SQLAlchemy model's own __table_args__ (database/sandbox_db.py)
    "CREATE INDEX IF NOT EXISTS idx_sandbox_user_status ON sandbox_orders(user_id, order_status)",
    "CREATE INDEX IF NOT EXISTS idx_sandbox_symbol_exchange ON sandbox_orders(symbol, exchange)",
]


def get_sandbox_db_engine():
    """Get sandbox database engine"""
    sandbox_db_url = os.getenv("SANDBOX_DATABASE_URL", "sqlite:///db/sandbox.db")

    if sandbox_db_url.startswith("sqlite:///"):
        db_path = sandbox_db_url.replace("sqlite:///", "")

        if not os.path.isabs(db_path):
            db_path = os.path.join(parent_dir, db_path)

        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        sandbox_db_url = f"sqlite:///{db_path}"
        logger.info(f"Sandbox DB path: {db_path}")

    return create_engine(sandbox_db_url)


def _constraint_allows_trigger_pending(conn) -> bool:
    """Inspect the live CHECK constraint text on sandbox_orders for 'trigger pending'."""
    result = conn.execute(
        text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='sandbox_orders'"
        )
    )
    row = result.fetchone()
    if not row or not row[0]:
        return False
    return "trigger pending" in row[0]


def widen_order_status_constraint(conn):
    """Rebuild sandbox_orders with 'trigger pending' added to the CHECK constraint.

    Idempotent: if the constraint already allows 'trigger pending' (e.g. a
    fresh install created via database/sandbox_db.py's up-to-date model, or
    this migration already ran), this is a no-op.
    """
    result = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='sandbox_orders'")
    )
    if not result.fetchone():
        logger.info("sandbox_orders table does not exist yet, nothing to migrate")
        return

    if _constraint_allows_trigger_pending(conn):
        logger.info("order_status CHECK constraint already allows 'trigger pending', skipping")
        return

    logger.info("Rebuilding sandbox_orders to widen the order_status CHECK constraint...")

    conn.execute(text("PRAGMA foreign_keys=OFF"))

    conn.execute(text("ALTER TABLE sandbox_orders RENAME TO sandbox_orders_old"))

    conn.execute(
        text(f"""
        CREATE TABLE sandbox_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            orderid VARCHAR(50) UNIQUE NOT NULL,
            user_id VARCHAR(50) NOT NULL,
            strategy VARCHAR(100),
            symbol VARCHAR(50) NOT NULL,
            exchange VARCHAR(20) NOT NULL,
            action VARCHAR(10) NOT NULL CHECK(action IN ('BUY', 'SELL')),
            quantity INTEGER NOT NULL,
            price DECIMAL(10, 2),
            trigger_price DECIMAL(10, 2),
            price_type VARCHAR(20) NOT NULL CHECK(price_type IN ('MARKET', 'LIMIT', 'SL', 'SL-M')),
            product VARCHAR(20) NOT NULL CHECK(product IN ('CNC', 'NRML', 'MIS')),
            order_status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK(order_status IN ({NEW_ORDER_STATUS_VALUES})),
            average_price DECIMAL(10, 2),
            filled_quantity INTEGER DEFAULT 0,
            pending_quantity INTEGER NOT NULL,
            rejection_reason TEXT,
            margin_blocked DECIMAL(10, 2) DEFAULT 0.00,
            order_timestamp DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            update_timestamp DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
        )
    """)
    )

    conn.execute(
        text("""
        INSERT INTO sandbox_orders (
            id, orderid, user_id, strategy, symbol, exchange, action, quantity,
            price, trigger_price, price_type, product, order_status,
            average_price, filled_quantity, pending_quantity, rejection_reason,
            margin_blocked, order_timestamp, update_timestamp
        )
        SELECT
            id, orderid, user_id, strategy, symbol, exchange, action, quantity,
            price, trigger_price, price_type, product, order_status,
            average_price, filled_quantity, pending_quantity, rejection_reason,
            margin_blocked, order_timestamp, update_timestamp
        FROM sandbox_orders_old
    """)
    )

    result = conn.execute(text("SELECT COUNT(*) FROM sandbox_orders_old"))
    old_count = result.scalar()
    result = conn.execute(text("SELECT COUNT(*) FROM sandbox_orders"))
    new_count = result.scalar()
    if old_count != new_count:
        raise RuntimeError(
            f"Row count mismatch after rebuild: sandbox_orders_old had {old_count}, "
            f"new sandbox_orders has {new_count} - aborting, not dropping old table"
        )
    logger.info(f"Copied {new_count} existing orders to the rebuilt table")

    conn.execute(text("DROP TABLE sandbox_orders_old"))

    for stmt in SANDBOX_ORDERS_INDEXES:
        conn.execute(text(stmt))

    conn.execute(text("PRAGMA foreign_keys=ON"))

    conn.commit()
    logger.info("sandbox_orders rebuilt with widened order_status CHECK constraint")


def upgrade():
    """Apply the migration"""
    try:
        logger.info(f"Starting migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})")

        engine = get_sandbox_db_engine()

        with engine.connect() as conn:
            widen_order_status_constraint(conn)

        logger.info(f"Migration {MIGRATION_NAME} completed successfully")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def status():
    """Check migration status"""
    try:
        logger.info(f"Checking status of migration: {MIGRATION_NAME}")

        engine = get_sandbox_db_engine()

        with engine.connect() as conn:
            if _constraint_allows_trigger_pending(conn):
                logger.info("order_status CHECK constraint allows 'trigger pending'")
                return True
            logger.info("order_status CHECK constraint does NOT allow 'trigger pending'")
            logger.info("   Migration needed")
            return False

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
