# database/qty_freeze_db.py
"""
Quantity Freeze Database Module
Handles freeze quantity limits for F&O instruments.

Freeze quantity is the maximum order quantity allowed in a single order.
Orders exceeding this limit need to be split.

Freeze quantities are admin-managed per exchange + underlying (NFO seeded from
NSE's qtyfreeze.csv; BFO/CDS/MCX and others added via the Freeze Quantities page
or a CSV upload). Any F&O exchange with a configured entry is honored; symbols
without an entry return 0, meaning no limit is known and none is enforced.
"""

import csv
import os
import threading

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
#
# Published whole: a load builds a new dict and rebinds this name in one
# assignment, and readers bind it once per call. The dict used to be cleared
# and refilled in place, so under the gthread worker a reader could land in
# the gap and get 0 ("no limit known") for an underlying that has one, and
# the order then went out unsplit above the exchange's freeze quantity.
_freeze_qty_cache: dict[str, int] = {}
_cache_loaded: bool = False

# Serialises loads, including the lazy first one, which several threads can
# reach at once at boot. A plain stdlib lock (green under eventlet), because
# the load does database I/O. Readers never take it.
_load_lock = threading.Lock()


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
    with _load_lock:
        return _load_freeze_qty_cache_locked()


def _load_freeze_qty_cache_locked() -> bool:
    """The load behind load_freeze_qty_cache. Call with ``_load_lock`` held."""
    global _freeze_qty_cache, _cache_loaded

    try:
        # Load all entries from database
        entries = QtyFreeze.query.all()

        fresh: dict[str, int] = {}
        for entry in entries:
            # Cache key: "EXCHANGE:SYMBOL" (e.g., "NFO:NIFTY")
            cache_key = f"{entry.exchange}:{entry.symbol}"
            fresh[cache_key] = entry.freeze_qty

        _freeze_qty_cache = fresh
        _cache_loaded = True
        logger.debug(f"Loaded {len(fresh)} freeze quantities into cache")
        return True

    except Exception as e:
        # As before, a failed load leaves the cache empty rather than stale.
        _freeze_qty_cache = {}
        logger.exception(f"Error loading freeze qty cache: {e}")
        return False


def _ensure_loaded() -> None:
    """Load the cache once, however many threads arrive cold at the same time."""
    if _cache_loaded:
        return
    with _load_lock:
        if not _cache_loaded:
            _load_freeze_qty_cache_locked()


def get_freeze_qty(symbol: str, exchange: str) -> int:
    """
    Get freeze quantity for a symbol.
    Uses in-memory cache for fast lookups.

    Returns the configured freeze quantity for any F&O exchange (NFO, BFO, CDS,
    MCX, ...) that has an entry, and 0 when none is configured.

    0 means "no freeze limit known", which is what every caller already tests
    for. It must not be 1: the table is seeded with NFO rows only, so BFO, CDS,
    MCX and any NFO underlying without a row resolved to a freeze limit of one
    unit, and callers that reject `quantity > freeze` then refused every order
    on those exchanges -- one lot of SENSEX (20) or CRUDEOIL (100) is above 1.
    The only reason this went unnoticed is that NFO index options, which do
    have rows, are the common case.

    Args:
        symbol: The underlying symbol (e.g., "NIFTY", "RELIANCE", "SENSEX", "CRUDEOIL")
        exchange: Exchange code (NFO, BFO, CDS, MCX, ...)

    Returns:
        Freeze quantity, or 0 when none is configured.
    """
    # Ensure cache is loaded
    _ensure_loaded()

    # Look up the configured entry for this exchange+symbol, in one bound dict.
    # Not configured: 0, never 1 -- see the note above.
    return _freeze_qty_cache.get(f"{exchange}:{symbol}", 0)


def get_freeze_qty_for_option(option_symbol: str, exchange: str) -> int:
    """
    Get freeze quantity for an option/futures symbol.
    Extracts the underlying from the symbol and looks up freeze qty.

    Examples:
        NIFTY24DEC24000CE -> NIFTY (NFO)
        SENSEX25DEC2480000CE -> SENSEX (BFO)
        CRUDEOIL25DEC246000CE -> CRUDEOIL (MCX)
        USDINR25DEC2487CE -> USDINR (CDS)

    Args:
        option_symbol: Full option/futures symbol
        exchange: Exchange code

    Returns:
        Freeze quantity, or 0 when the underlying has no configured limit.
    """
    import re

    # Extract underlying from option/futures symbol
    # Pattern: SYMBOL + DATE + optional(STRIKE) + TYPE(FUT/CE/PE)
    # Examples: NIFTY24DEC24FUT, NIFTY24DEC2424000CE, SENSEX25DEC2480000PE

    # Try to match known index symbols first. Longest-prefix-first so e.g. NIFTYNXT50
    # is not shadowed by NIFTY, and SENSEX50 is not shadowed by SENSEX.
    index_symbols = [
        "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "NIFTY",
        "SENSEX50", "BANKEX", "SENSEX",
    ]
    for idx_sym in index_symbols:
        if option_symbol.upper().startswith(idx_sym):
            return get_freeze_qty(idx_sym, exchange)

    # For stock symbols, extract up to the first digit
    match = re.match(r"^([A-Z&-]+)", option_symbol.upper())
    if match:
        underlying = match.group(1)
        # Handle special cases like M&M, BAJAJ-AUTO
        return get_freeze_qty(underlying, exchange)

    # The symbol did not parse (e.g. it starts with a digit, like 360ONE).
    # Unknown, not "one unit".
    return 0


def get_all_freeze_qty(exchange: str = None) -> dict[str, int]:
    """
    Get all freeze quantities, optionally filtered by exchange.

    Args:
        exchange: Optional exchange filter

    Returns:
        Dictionary of symbol -> freeze_qty
    """
    _ensure_loaded()
    cache = _freeze_qty_cache

    if exchange:
        prefix = f"{exchange}:"
        return {
            key.replace(prefix, ""): value
            for key, value in cache.items()
            if key.startswith(prefix)
        }

    return dict(cache)


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
