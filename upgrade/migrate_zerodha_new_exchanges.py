#!/usr/bin/env python3
"""
Migration: Zerodha new exchange codes (NCO, GLOBAL_INDEX) and GIFTNIFTY rename.

Background
----------
The Zerodha master-contract loader previously only mapped 9 exchange codes
(NSE, NFO, CDS, BSE, BFO, BCD, MCX, NSE_INDEX, BSE_INDEX). Anything else
returned by the Kite instruments dump silently became NULL via
df['exchange'].map(exchange_map).

That dropped three categories on the floor:
  - NCO        (NSE Commodities, ~35.5k rows: futures + options + underlyings)
  - GLOBAL     (12 global indices: US30, JAPAN225, HANGSENG, ...)
  - NSEIX      (1 row: GIFT NIFTY from NSE IFSC)

This release maps NSEIX into GLOBAL_INDEX (one bucket for all index-only
quote feeds) and renames the lone "GIFT NIFTY" tradingsymbol to "GIFTNIFTY"
so it's a single-token symbol like every other OpenAlgo identifier.

What this migration does (idempotent)
-------------------------------------
1. UPDATE any symtoken row with exchange='NSEIX_INDEX' to exchange='GLOBAL_INDEX'
   and symbol='GIFT NIFTY' to symbol='GIFTNIFTY'. Only relevant for users who
   ran an intermediate version of this fix.
2. DELETE any symtoken row with exchange IS NULL. These are stale rows from
   the pre-fix loader; the next daily master-contract download (3 AM IST) or
   manual refresh will repopulate them with the correct exchange.

Both operations are safe no-ops on healthy databases.

Usage:
    cd upgrade
    uv run migrate_zerodha_new_exchanges.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(env_path)

from utils.logging import get_logger

logger = get_logger(__name__)


def _resolve_database_url() -> str:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")
    if DATABASE_URL.startswith("sqlite:///") and not DATABASE_URL.startswith("sqlite:////"):
        db_path = DATABASE_URL.replace("sqlite:///", "")
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_db_path = os.path.join(parent_dir, db_path)
        DATABASE_URL = f"sqlite:///{full_db_path}"
        logger.info(f"Using database: {full_db_path}")
    return DATABASE_URL


def migrate_zerodha_new_exchanges() -> bool:
    """Apply NSEIX_INDEX → GLOBAL_INDEX rename and clear stale NULL exchange rows."""
    DATABASE_URL = _resolve_database_url()

    try:
        engine = create_engine(DATABASE_URL)
        inspector = inspect(engine)

        if "symtoken" not in inspector.get_table_names():
            logger.info("symtoken table doesn't exist yet. Nothing to migrate.")
            return True

        with engine.connect() as conn:
            # 1. Rename + re-bucket the NSEIX_INDEX rows (in practice only the
            #    GIFT NIFTY row, but the WHERE clause is generic in case Zerodha
            #    adds more NSE-IFSC instruments later).
            result = conn.execute(
                text(
                    """
                    UPDATE symtoken
                    SET symbol = CASE WHEN symbol = 'GIFT NIFTY' THEN 'GIFTNIFTY' ELSE symbol END,
                        exchange = 'GLOBAL_INDEX'
                    WHERE exchange = 'NSEIX_INDEX'
                    """
                )
            )
            conn.commit()
            renamed = result.rowcount or 0
            if renamed > 0:
                logger.info(f"Migrated {renamed} NSEIX_INDEX row(s) to GLOBAL_INDEX")
            else:
                logger.info("No NSEIX_INDEX rows to migrate.")

            # 2. Delete any rows with NULL exchange. The Zerodha loader used to
            #    silently drop NCO/GLOBAL/NSEIX rows here; the next master-contract
            #    download will repopulate them with the correct exchange values.
            result = conn.execute(text("DELETE FROM symtoken WHERE exchange IS NULL"))
            conn.commit()
            cleared = result.rowcount or 0
            if cleared > 0:
                logger.info(
                    f"Cleared {cleared} stale symtoken row(s) with NULL exchange. "
                    "These will be repopulated on the next master-contract refresh."
                )
            else:
                logger.info("No NULL-exchange symtoken rows found.")

        logger.info("Migration completed successfully.")
        return True

    except Exception as e:
        logger.error(f"Error during migration: {e}")
        return False


def main() -> int:
    logger.info("=" * 60)
    logger.info("OpenAlgo Zerodha New Exchanges Migration")
    logger.info("=" * 60)
    logger.info("Cleaning up stale NULL/NSEIX_INDEX symtoken rows so NCO and")
    logger.info("GLOBAL_INDEX (incl. GIFTNIFTY) populate correctly on next refresh.")
    logger.info("-" * 60)

    success = migrate_zerodha_new_exchanges()

    logger.info("-" * 60)
    if success:
        logger.info("Migration process completed!")
        return 0
    else:
        logger.error("Migration failed! Check error messages above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
