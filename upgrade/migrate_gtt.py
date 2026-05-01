#!/usr/bin/env python
"""
GTT (Good Till Triggered) Order Support Migration Script for OpenAlgo

Adds two tables to the sandbox database:

- ``sandbox_gtt``      — one row per GTT trigger (single or two-leg OCO)
- ``sandbox_gtt_legs`` — one row per order leg

Also seeds two ``sandbox_config`` entries used by the sandbox GTT monitor:

- ``gtt_oco_margin_mode``  — ``max`` (default) | ``sum``
- ``gtt_claim_timeout_sec`` — reaper threshold for stranded ``triggering`` legs

Idempotent — safe to run multiple times. Runs against the sandbox database
(same file as sandbox_orders / sandbox_trades / sandbox_config) so that GTT
mutations commit under the same fund-manager lock scope as regular orders.

Usage:
    cd upgrade
    uv run migrate_gtt.py           # Apply migration
    uv run migrate_gtt.py --status  # Check status

Migration: 004-gtt
Created: 2026-04-24
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

MIGRATION_NAME = "gtt_order_support"
MIGRATION_VERSION = "004-gtt"

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(parent_dir, ".env"))


def get_sandbox_db_engine():
    """Get sandbox database engine (same DB as sandbox_orders)."""
    sandbox_db_url = os.getenv("SANDBOX_DATABASE_URL", "sqlite:///db/sandbox.db")

    if sandbox_db_url.startswith("sqlite:///"):
        db_path = sandbox_db_url.replace("sqlite:///", "")
        if not os.path.isabs(db_path):
            db_path = os.path.join(parent_dir, db_path)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        sandbox_db_url = f"sqlite:///{db_path}"
        logger.info(f"Sandbox DB path: {db_path}")

    return create_engine(sandbox_db_url)


def create_gtt_tables(conn):
    """Create the GTT tables if they do not exist."""
    logger.info("Creating GTT tables...")

    # sandbox_gtt — parent trigger
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS sandbox_gtt (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gtt_id VARCHAR(50) UNIQUE NOT NULL,
            user_id VARCHAR(50) NOT NULL,
            strategy VARCHAR(100),
            trigger_type VARCHAR(10) NOT NULL CHECK(trigger_type IN ('single', 'two-leg')),
            symbol VARCHAR(50) NOT NULL,
            exchange VARCHAR(20) NOT NULL,
            last_price DECIMAL(10, 2) NOT NULL,
            gtt_status VARCHAR(20) NOT NULL DEFAULT 'active'
                CHECK(gtt_status IN ('active', 'triggered', 'cancelled', 'expired', 'rejected')),
            margin_blocked DECIMAL(15, 2) NOT NULL DEFAULT 0.00,
            expires_at DATETIME,
            created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
        )
    """)
    )

    # sandbox_gtt_legs — child legs
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS sandbox_gtt_legs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gtt_id VARCHAR(50) NOT NULL,
            leg_number INTEGER NOT NULL,
            trigger_price DECIMAL(10, 2) NOT NULL,
            action VARCHAR(10) NOT NULL CHECK(action IN ('BUY', 'SELL')),
            quantity INTEGER NOT NULL,
            price DECIMAL(10, 2) NOT NULL,
            pricetype VARCHAR(10) NOT NULL DEFAULT 'LIMIT',
            product VARCHAR(10) NOT NULL CHECK(product IN ('CNC', 'NRML', 'MIS')),
            leg_status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK(leg_status IN ('pending', 'triggering', 'triggered', 'cancelled')),
            triggered_order_id VARCHAR(50),
            leg_margin DECIMAL(15, 2) NOT NULL DEFAULT 0.00,
            claimed_at DATETIME,
            created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            FOREIGN KEY (gtt_id) REFERENCES sandbox_gtt(gtt_id) ON DELETE CASCADE
        )
    """)
    )

    conn.commit()
    logger.info("✅ GTT tables created (or already present)")


def create_gtt_indexes(conn):
    """Create indexes needed by the GTT monitor + reaper."""
    logger.info("Creating GTT indexes...")

    # sandbox_gtt
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_gtt_gtt_id ON sandbox_gtt(gtt_id)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_gtt_user_id ON sandbox_gtt(user_id)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_gtt_symbol ON sandbox_gtt(symbol)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_gtt_exchange ON sandbox_gtt(exchange)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_gtt_status ON sandbox_gtt(gtt_status)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_gtt_user_status ON sandbox_gtt(user_id, gtt_status)")
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_gtt_symbol_exchange ON sandbox_gtt(symbol, exchange)"
        )
    )

    # sandbox_gtt_legs — covers both the active scan (leg_status='pending')
    # and the reaper (leg_status='triggering' AND claimed_at < cutoff).
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_gtt_leg_gtt_id ON sandbox_gtt_legs(gtt_id)")
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_gtt_leg_status_claimed "
            "ON sandbox_gtt_legs(leg_status, claimed_at)"
        )
    )

    conn.commit()
    logger.info("✅ GTT indexes created (or already present)")


def _sandbox_config_exists(conn):
    """Return True if the sandbox_config table is present."""
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='sandbox_config'")
    ).fetchone()
    return row is not None


def insert_default_config(conn):
    """Seed the two sandbox_config entries used by the GTT monitor.

    Skips silently (with a clear warning) if ``sandbox_config`` does not yet
    exist — it is created by ``migrate_sandbox.py``, which ``migrate_all.py``
    runs ahead of this migration. Standalone runs on a fresh DB will land here.
    """
    if not _sandbox_config_exists(conn):
        logger.warning(
            "sandbox_config table missing — skipping GTT defaults. "
            "Run migrate_sandbox.py first (or use migrate_all.py which sequences migrations)."
        )
        return

    logger.info("Seeding GTT sandbox configuration...")

    defaults = [
        (
            "gtt_oco_margin_mode",
            "max",
            "OCO GTT margin mode: 'max' (block only the larger leg) or 'sum'",
        ),
        (
            "gtt_claim_timeout_sec",
            "60",
            "Seconds after which a leg stuck in 'triggering' is reclaimed to 'pending' by the reaper",
        ),
    ]

    added = 0
    for key, value, description in defaults:
        exists = conn.execute(
            text("SELECT 1 FROM sandbox_config WHERE config_key = :key"), {"key": key}
        ).fetchone()
        if not exists:
            # Explicit updated_at: sandbox_config may have been created via
            # SQLAlchemy create_all() (ORM-level default only, no SQL DEFAULT),
            # in which case a raw INSERT without updated_at hits the NOT NULL
            # constraint. CURRENT_TIMESTAMP is SQL-standard and portable.
            conn.execute(
                text(
                    "INSERT INTO sandbox_config (config_key, config_value, description, updated_at) "
                    "VALUES (:key, :value, :description, CURRENT_TIMESTAMP)"
                ),
                {"key": key, "value": value, "description": description},
            )
            added += 1

    conn.commit()
    logger.info(f"✅ Added {added} GTT default config entries")


def upgrade():
    """Apply the GTT schema migration."""
    try:
        logger.info(f"Starting migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})")

        engine = get_sandbox_db_engine()

        with engine.connect() as conn:
            create_gtt_tables(conn)
            create_gtt_indexes(conn)
            insert_default_config(conn)

        logger.info(f"✅ Migration {MIGRATION_NAME} completed successfully")
        return True

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def status():
    """Check whether the GTT schema is fully applied."""
    try:
        logger.info(f"Checking status of migration: {MIGRATION_NAME}")
        engine = get_sandbox_db_engine()

        required_tables = ["sandbox_gtt", "sandbox_gtt_legs"]
        required_configs = ["gtt_oco_margin_mode", "gtt_claim_timeout_sec"]

        with engine.connect() as conn:
            # Tables present?
            missing_tables = []
            for t in required_tables:
                row = conn.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name=:name"
                    ),
                    {"name": t},
                ).fetchone()
                if not row:
                    missing_tables.append(t)
            if missing_tables:
                logger.info(f"❌ Missing tables: {', '.join(missing_tables)}")
                return False

            # Config present? (sandbox_config may be absent on a truly fresh DB.)
            if not _sandbox_config_exists(conn):
                logger.info(
                    "⚠️  sandbox_config table is missing — run migrate_sandbox.py first."
                )
                return False

            missing_configs = []
            for k in required_configs:
                row = conn.execute(
                    text("SELECT 1 FROM sandbox_config WHERE config_key = :key"),
                    {"key": k},
                ).fetchone()
                if not row:
                    missing_configs.append(k)
            if missing_configs:
                logger.info(f"⚠️  Missing config keys: {', '.join(missing_configs)}")
                return False

            # Stats
            gtt_count = conn.execute(text("SELECT COUNT(*) FROM sandbox_gtt")).scalar()
            leg_count = conn.execute(text("SELECT COUNT(*) FROM sandbox_gtt_legs")).scalar()
            logger.info("✅ GTT schema is fully configured")
            logger.info(f"   Total GTTs: {gtt_count}")
            logger.info(f"   Total GTT legs: {leg_count}")
            return True

    except Exception as e:
        logger.error(f"❌ Status check failed: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"Migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--status", action="store_true", help="Check migration status")

    args = parser.parse_args()
    success = status() if args.status else upgrade()
    sys.exit(0 if success else 1)
