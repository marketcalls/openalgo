# database/qty_freeze_db.py
"""
Quantity Freeze Database Module
Handles freeze quantity limits for F&O instruments.

Freeze quantity is the maximum order quantity allowed in a single order.
Orders exceeding this limit need to be split.

Currently supports:
- NFO: Actual freeze quantities from NSE
- BFO, CDS, MCX: Default value of 1 (to be implemented later)
"""

import csv
import os
from typing import Dict, Optional

from sqlalchemy import Column, Index, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

# Conditionally create engine based on DB type
if DATABASE_URL and "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# In-memory cache for freeze quantities - always warm
_freeze_qty_cache: dict[str, int] = {}
_cache_loaded: bool = False


class QtyFreeze(Base):
    """
    Stores freeze quantity limits for F&O symbols
    """

    __tablename__ = "qty_freeze"

    id = Column(Integer, primary_key=True)
    exchange = Column(String(10), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    freeze_qty = Column(Integer, nullable=False)

    __table_args__ = (Index("idx_exchange_symbol", "exchange", "symbol", unique=True),)


def init_db():
    """Initialize the qty_freeze database table"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Qty Freeze DB", logger)


def load_freeze_qty_from_csv(csv_path: str, exchange: str = "NFO") -> bool:
    """
    Load freeze quantities from CSV file into database

    Args:
        csv_path: Path to the CSV file
        exchange: Exchange code (default: NFO)

    Returns:
        True if successful, False otherwise
    """
    try:
        if not os.path.exists(csv_path):
            logger.error(f"CSV file not found: {csv_path}")
            return False

        # Clear existing data for this exchange
        QtyFreeze.query.filter(QtyFreeze.exchange == exchange).delete()
        db_session.commit()

        # Read and insert CSV data
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            count = 0

            for row in reader:
                # Handle column names with trailing spaces (CSV may have 'SYMBOL    ' instead of 'SYMBOL')
                symbol = None
                freeze_qty_str = None

                for key in row.keys():
                    key_upper = key.upper().strip()
                    if key_upper == "SYMBOL":
                        symbol = row[key].strip()
                    elif "FRZ" in key_upper or key_upper == "VOL_FRZ_QTY":
                        freeze_qty_str = row[key].strip()

                if symbol and freeze_qty_str:
                    try:
                        freeze_qty = int(freeze_qty_str)
                        entry = QtyFreeze(exchange=exchange, symbol=symbol, freeze_qty=freeze_qty)
                        db_session.add(entry)
                        count += 1
                    except ValueError:
                        logger.warning(f"Invalid freeze qty for {symbol}: {freeze_qty_str}")

            db_session.commit()
            logger.info(f"Loaded {count} freeze quantities for {exchange}")

            # Reload cache after loading
            load_freeze_qty_cache()
            return True

    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error loading freeze quantities from CSV: {e}")
        return False


def load_freeze_qty_cache() -> bool:
    """
    Load all freeze quantities into memory cache.
    Called at startup and after CSV import.

    Returns:
        True if successful, False otherwise
    """
    global _freeze_qty_cache, _cache_loaded

    try:
        _freeze_qty_cache.clear()

        # Load all entries from database
        entries = QtyFreeze.query.all()

        for entry in entries:
            # Cache key: "EXCHANGE:SYMBOL" (e.g., "NFO:NIFTY")
            cache_key = f"{entry.exchange}:{entry.symbol}"
            _freeze_qty_cache[cache_key] = entry.freeze_qty

        _cache_loaded = True
        logger.debug(f"Loaded {len(_freeze_qty_cache)} freeze quantities into cache")
        return True

    except Exception as e:
        logger.exception(f"Error loading freeze qty cache: {e}")
        return False


def get_freeze_qty(symbol: str, exchange: str) -> int:
    """
    Get freeze quantity for a symbol.
    Uses in-memory cache for fast lookups.

    For NFO: Returns actual freeze quantity from database
    For other exchanges (BFO, CDS, MCX): Returns 1 (default)

    Args:
        symbol: The underlying symbol (e.g., "NIFTY", "RELIANCE")
        exchange: Exchange code (NFO, BFO, CDS, MCX)

    Returns:
        Freeze quantity (integer)
    """
    global _cache_loaded

    # Ensure cache is loaded
    if not _cache_loaded:
        load_freeze_qty_cache()

    # For non-NFO exchanges, return 1 as default (to be implemented later)
    if exchange not in ["NFO"]:
        return 1

    # Look up in cache
    cache_key = f"{exchange}:{symbol}"
    if cache_key in _freeze_qty_cache:
        return _freeze_qty_cache[cache_key]

    # If not found, return 1 as default
    return 1


def get_freeze_qty_for_option(option_symbol: str, exchange: str) -> int:
    """
    Get freeze quantity for an option/futures symbol.
    Extracts the underlying from the symbol and looks up freeze qty.

    Examples:
        NIFTY24DEC24000CE -> NIFTY
        BANKNIFTY24DEC24FUT -> BANKNIFTY
        RELIANCE24DEC241000CE -> RELIANCE

    Args:
        option_symbol: Full option/futures symbol
        exchange: Exchange code

    Returns:
        Freeze quantity (integer)
    """
    import re

    # For non-NFO exchanges, return 1 as default
    if exchange not in ["NFO"]:
        return 1

    # Extract underlying from option/futures symbol
    # Pattern: SYMBOL + DATE + optional(STRIKE) + TYPE(FUT/CE/PE)
    # Examples: NIFTY24DEC24FUT, NIFTY24DEC2424000CE, RELIANCE24DEC241000PE

    # Try to match known index symbols first
    index_symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]
    for idx_sym in index_symbols:
        if option_symbol.upper().startswith(idx_sym):
            return get_freeze_qty(idx_sym, exchange)

    # For stock symbols, extract up to the first digit
    match = re.match(r"^([A-Z&-]+)", option_symbol.upper())
    if match:
        underlying = match.group(1)
        # Handle special cases like M&M, BAJAJ-AUTO
        return get_freeze_qty(underlying, exchange)

    return 1


def get_all_freeze_qty(exchange: str = None) -> dict[str, int]:
    """
    Get all freeze quantities, optionally filtered by exchange.

    Args:
        exchange: Optional exchange filter

    Returns:
        Dictionary of symbol -> freeze_qty
    """
    global _cache_loaded

    if not _cache_loaded:
        load_freeze_qty_cache()

    if exchange:
        prefix = f"{exchange}:"
        return {
            key.replace(prefix, ""): value
            for key, value in _freeze_qty_cache.items()
            if key.startswith(prefix)
        }

    return dict(_freeze_qty_cache)


def ensure_qty_freeze_tables_exists():
    """Wrapper function for parallel initialization"""
    init_db()

    # Auto-load from CSV if table is empty
    try:
        count = QtyFreeze.query.count()
        if count == 0:
            # Try to load from default CSV location
            csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "qtyfreeze.csv")
            if os.path.exists(csv_path):
                logger.info(f"Qty Freeze DB: Loading freeze quantities from {csv_path}")
                load_freeze_qty_from_csv(csv_path, "NFO")
            else:
                logger.debug("Qty Freeze DB: No CSV file found, table remains empty")
    except Exception as e:
        logger.debug(f"Qty Freeze DB: Auto-load may have race condition: {e}")

    # Load cache at startup
    load_freeze_qty_cache()
