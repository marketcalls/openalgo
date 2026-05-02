"""Idempotent migration: add per-purpose 2FA flags to the ``users`` table.

Adds four boolean columns:

* ``totp_enabled`` — master switch. When False, all per-purpose flags
  are ignored and login behaves exactly as before this feature landed.
* ``totp_required_for_login`` — when master is on, demand TOTP after
  password at the dashboard login.
* ``totp_required_for_mcp`` — when master is on, demand fresh TOTP at
  the remote MCP ``/oauth/authorize`` consent step.
* ``totp_required_for_password_reset`` — when master is on, force the
  TOTP path through password reset (no email fallback).

All four default to ``False`` so existing installs preserve their
current login behavior. Users opt in via the settings UI.

Safe to run multiple times — each ALTER is gated by an inspector check.
"""

import logging
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(parent_dir)

load_dotenv(os.path.join(parent_dir, ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


COLUMNS_TO_ADD = (
    "totp_enabled",
    "totp_required_for_login",
    "totp_required_for_mcp",
    "totp_required_for_password_reset",
)


def run() -> bool:
    """Apply the migration. Returns True on success or no-op."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL is not set; cannot run migration.")
        return False

    engine = create_engine(db_url)
    inspector = inspect(engine)

    if "users" not in inspector.get_table_names():
        logger.info("'users' table does not exist yet; nothing to do.")
        return True

    existing = {col["name"] for col in inspector.get_columns("users")}
    pending = [c for c in COLUMNS_TO_ADD if c not in existing]

    if not pending:
        logger.info("All TOTP purpose flag columns already present; nothing to do.")
        return True

    logger.info(f"Adding {len(pending)} column(s) to users: {', '.join(pending)}")
    with engine.begin() as conn:
        for column in pending:
            conn.execute(
                text(
                    f"ALTER TABLE users ADD COLUMN {column} BOOLEAN NOT NULL DEFAULT 0"
                )
            )
            logger.info(f"  + {column}")

    logger.info("Migration complete.")
    return True


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
