# database/market_calendar_db.py
"""
Market Calendar Database Module
Handles holidays and market timings for Indian exchanges:
NSE, BSE, NFO, BFO, MCX, BCD, CDS, NCO

Supports:
- Trading holidays (full day closed)
- Special sessions (Muhurat trading, etc.)
- Partial holidays (some exchanges open with special timings)
"""

import os
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional, Tuple

import pytz
from sqlalchemy import BigInteger, Boolean, Column, Date, Index, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from utils.constants import CRYPTO_EXCHANGES, EXCHANGE_CRYPTO
from utils.logging import get_logger
from utils.thread_safe_cache import MISSING, LockedTTLCache

# IST Timezone
IST = pytz.timezone("Asia/Kolkata")

logger = get_logger(__name__)

# Cache for market timings - 1 hour TTL
_timings_cache = LockedTTLCache(maxsize=500, ttl=3600)
_holidays_cache = LockedTTLCache(maxsize=50, ttl=3600)

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

# Supported exchanges
SUPPORTED_EXCHANGES = ["NSE", "BSE", "NFO", "BFO", "MCX", "BCD", "CDS", "NCO", "CRYPTO"]

# Holiday types
HOLIDAY_TYPES = ["TRADING_HOLIDAY", "SETTLEMENT_HOLIDAY", "SPECIAL_SESSION"]

# Default market timings (in epoch milliseconds offset from midnight IST)
DEFAULT_MARKET_TIMINGS = {
    "NSE": {"start_offset": 33300000, "end_offset": 55800000},  # 09:15 - 15:30
    "BSE": {"start_offset": 33300000, "end_offset": 55800000},  # 09:15 - 15:30
    # F&O runs past the cash close. SEBI's Closing Auction Session (circular
    # HO/47/11/11(3)2025-MRD-POD2/I/2765/2026, effective 2026-08-03) applies to
    # the equity cash segment only: cash pauses continuous trading at 15:15 and
    # its close is derived by auction, while the derivatives segment keeps
    # trading to roughly 15:40. Cutting NFO/BFO off at 15:30 would make the last
    # ten minutes of live F&O invisible to anything driven by these timings.
    "NFO": {"start_offset": 33300000, "end_offset": 56400000},  # 09:15 - 15:40
    "BFO": {"start_offset": 33300000, "end_offset": 56400000},  # 09:15 - 15:40
    "CDS": {"start_offset": 32400000, "end_offset": 61200000},  # 09:00 - 17:00
    "BCD": {"start_offset": 32400000, "end_offset": 61200000},  # 09:00 - 17:00
    "MCX": {"start_offset": 32400000, "end_offset": 86100000},  # 09:00 - 23:55
    "NCO": {"start_offset": 32400000, "end_offset": 86100000},  # 09:00 - 23:55 (NSE Commodities mirrors MCX)
    "CRYPTO": {"start_offset": 0, "end_offset": 86399000},  # 00:00 - 23:59:59 (24/7)
}


class Holiday(Base):
    """
    Stores market holidays with exchange-specific information
    """

    __tablename__ = "market_holidays"

    id = Column(Integer, primary_key=True)
    holiday_date = Column(Date, nullable=False, index=True)
    description = Column(String(150), nullable=False)
    holiday_type = Column(String(30), nullable=False, default="TRADING_HOLIDAY")
    year = Column(Integer, nullable=False, index=True)

    __table_args__ = (Index("idx_holiday_date_year", "holiday_date", "year"),)


class HolidayExchange(Base):
    """
    Stores exchange-specific holiday information
    Allows tracking which exchanges are closed and which have special sessions
    """

    __tablename__ = "market_holiday_exchanges"

    id = Column(Integer, primary_key=True)
    holiday_id = Column(Integer, nullable=False, index=True)
    exchange_code = Column(String(10), nullable=False, index=True)
    is_open = Column(Boolean, nullable=False, default=False)
    start_time = Column(BigInteger, nullable=True)  # epoch millis
    end_time = Column(BigInteger, nullable=True)  # epoch millis

    __table_args__ = (Index("idx_holiday_exchange", "holiday_id", "exchange_code"),)


class MarketTiming(Base):
    """
    Stores custom market timings for each exchange.
    Allows overriding the default hardcoded timings.
    """

    __tablename__ = "market_timings"

    id = Column(Integer, primary_key=True)
    exchange_code = Column(String(10), nullable=False, unique=True, index=True)
    start_time = Column(String(5), nullable=False)  # HH:MM format
    end_time = Column(String(5), nullable=False)  # HH:MM format
    start_offset = Column(BigInteger, nullable=False)  # milliseconds from midnight
    end_offset = Column(BigInteger, nullable=False)  # milliseconds from midnight


def init_db():
    """Initialize the market calendar database and seed holiday data"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Market Calendar DB", logger)

    # Seed holiday data if table is empty
    try:
        if not Holiday.query.first():
            logger.debug("Market Calendar DB: Seeding holiday data")
            seed_holidays_2025()
            seed_holidays_2026()
            logger.debug("Market Calendar DB: Holiday data seeded successfully")
    except Exception as e:
        db_session.rollback()
        logger.debug(f"Market Calendar DB: Holiday seeding may have race condition: {e}")


def seed_holidays_2025():
    """Seed the 2025 calendar OpenAlgo ships into an empty table."""
    _seed_holidays(shipped_holidays_2025(), 2025)


def shipped_holidays_2025() -> list[dict]:
    """
    2025 market holidays based on NSE/BSE/MCX official calendar
    Includes Muhurat Trading session for Diwali
    """
    holidays_2025 = [
        # February
        {
            "date": "2025-02-26",
            "description": "Maha Shivaratri",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1740549000000, "end_time": 1740602700000}
            ],  # MCX evening 17:00-23:55
        },
        # March
        {
            "date": "2025-03-14",
            "description": "Holi",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1741964400000, "end_time": 1742018100000}
            ],  # MCX evening
        },
        {
            "date": "2025-03-31",
            "description": "Id-Ul-Fitr (Ramadan)",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [{"exchange": "MCX", "start_time": 1743433800000, "end_time": 1743487500000}],
        },
        # April
        {
            "date": "2025-04-10",
            "description": "Shri Mahavir Jayanti",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [{"exchange": "MCX", "start_time": 1744297800000, "end_time": 1744351500000}],
        },
        {
            "date": "2025-04-14",
            "description": "Dr. Baba Saheb Ambedkar Jayanti",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [{"exchange": "MCX", "start_time": 1744643400000, "end_time": 1744697100000}],
        },
        {
            "date": "2025-04-18",
            "description": "Good Friday",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
            "open": [],
        },
        # May
        {
            "date": "2025-05-01",
            "description": "Maharashtra Day",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [{"exchange": "MCX", "start_time": 1745766600000, "end_time": 1745820300000}],
        },
        # August
        {
            "date": "2025-08-15",
            "description": "Independence Day",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
            "open": [],
        },
        {
            "date": "2025-08-27",
            "description": "Janmashtami",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [{"exchange": "MCX", "start_time": 1756383000000, "end_time": 1756436700000}],
        },
        # October
        {
            "date": "2025-10-02",
            "description": "Mahatma Gandhi Jayanti",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
            "open": [],
        },
        {
            "date": "2025-10-21",
            "description": "Dussehra",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [{"exchange": "MCX", "start_time": 1761091800000, "end_time": 1761145500000}],
        },
        # November - Diwali with Muhurat Trading
        {
            "date": "2025-11-01",
            "description": "Diwali Laxmi Pujan (Muhurat Trading)",
            "holiday_type": "SPECIAL_SESSION",
            "closed": [],  # No exchange fully closed - all have special session
            "open": [
                # Muhurat Trading session - typically 6:00 PM to 7:15 PM IST
                {
                    "exchange": "NSE",
                    "start_time": 1730469000000,
                    "end_time": 1730473500000,
                },  # 18:00-19:15
                {
                    "exchange": "BSE",
                    "start_time": 1730469000000,
                    "end_time": 1730473500000,
                },  # 18:00-19:15
                {
                    "exchange": "NFO",
                    "start_time": 1730469000000,
                    "end_time": 1730473500000,
                },  # 18:00-19:15
                {
                    "exchange": "BFO",
                    "start_time": 1730469000000,
                    "end_time": 1730473500000,
                },  # 18:00-19:15
                {
                    "exchange": "CDS",
                    "start_time": 1730469000000,
                    "end_time": 1730473500000,
                },  # 18:00-19:15
                {
                    "exchange": "BCD",
                    "start_time": 1730469000000,
                    "end_time": 1730473500000,
                },  # 18:00-19:15
                {
                    "exchange": "MCX",
                    "start_time": 1730469000000,
                    "end_time": 1730491500000,
                },  # 18:00-00:15 (next day)
            ],
        },
        {
            "date": "2025-11-14",
            "description": "Guru Nanak Jayanti",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [{"exchange": "MCX", "start_time": 1763152200000, "end_time": 1763205900000}],
        },
        # December
        {
            "date": "2025-12-25",
            "description": "Christmas",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
            "open": [],
        },
    ]

    return holidays_2025


#: Diwali Muhurat 2026: Sunday 8 November, as NSE, BSE and MCX published it on
#: 19 October (MCX circular MCX/TRD/590/2026). Trading runs 14:20 to 15:30 IST
#: after a pre-open from 14:05, and equity derivatives run to 15:40, as on any
#: day since the Closing Auction Session. NCO is NSE's commodity segment, which
#: the NSE schedule lists with the rest. Epoch milliseconds, like every window
#: in the holiday tables.
MUHURAT_2026_DATE = date(2026, 11, 8)
MUHURAT_2026_SESSION = {
    "NSE": (1794127800000, 1794132000000),  # 14:20 - 15:30
    "BSE": (1794127800000, 1794132000000),
    "NFO": (1794127800000, 1794132600000),  # 14:20 - 15:40
    "BFO": (1794127800000, 1794132600000),
    "CDS": (1794127800000, 1794132000000),
    "BCD": (1794127800000, 1794132000000),
    "MCX": (1794127800000, 1794132000000),
    "NCO": (1794127800000, 1794132000000),
}

#: What the 2026 seed carried before the exchanges published the timings: a
#: guess of 18:00 to 19:15, with MCX running to 00:15 the next morning and no
#: NCO row. A row still holding it is moved to the published session.
_MUHURAT_2026_GUESS = {
    "NSE": (1794141000000, 1794145500000),
    "BSE": (1794141000000, 1794145500000),
    "NFO": (1794141000000, 1794145500000),
    "BFO": (1794141000000, 1794145500000),
    "CDS": (1794141000000, 1794145500000),
    "BCD": (1794141000000, 1794145500000),
    "MCX": (1794141000000, 1794163500000),
}


def seed_holidays_2026():
    """Seed the 2026 calendar OpenAlgo ships into an empty table."""
    _seed_holidays(shipped_holidays_2026(), 2026)


def shipped_holidays_2026() -> list[dict]:
    """
    2026 market holidays based on official NSE and MCX calendars.
    Source: NSE Circular & MCX Circular for Calendar Year 2026.

    Includes:
    - Trading holidays (market closed)
    - Special sessions (Muhurat trading)

    MCX evening session on holidays: 17:00–23:55 IST
    MCX fully closed on: Republic Day, Good Friday, Gandhi Jayanti, Christmas
    """
    holidays_2026 = [
        # January
        {
            "date": "2026-01-15",
            "description": "Municipal Corporation Election - Maharashtra",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1768476600000, "end_time": 1768501500000}
            ],  # MCX evening 17:00-23:55
        },
        {
            "date": "2026-01-26",
            "description": "Republic Day",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
            "open": [],
        },
        # March
        {
            "date": "2026-03-03",
            "description": "Holi",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1772537400000, "end_time": 1772562300000}
            ],  # MCX evening 17:00-23:55
        },
        {
            "date": "2026-03-26",
            "description": "Shri Ram Navami",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1774524600000, "end_time": 1774549500000}
            ],  # MCX evening 17:00-23:55
        },
        {
            "date": "2026-03-31",
            "description": "Shri Mahavir Jayanti",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1774956600000, "end_time": 1774981500000}
            ],  # MCX evening 17:00-23:55
        },
        # April
        {
            "date": "2026-04-03",
            "description": "Good Friday",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
            "open": [],
        },
        {
            "date": "2026-04-14",
            "description": "Dr. Baba Saheb Ambedkar Jayanti",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1776166200000, "end_time": 1776191100000}
            ],  # MCX evening 17:00-23:55
        },
        # May
        {
            "date": "2026-05-01",
            "description": "Maharashtra Day",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1777635000000, "end_time": 1777659900000}
            ],  # MCX evening 17:00-23:55
        },
        {
            "date": "2026-05-28",
            "description": "Bakri Id",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1779967800000, "end_time": 1779992700000}
            ],  # MCX evening 17:00-23:55
        },
        # June
        {
            "date": "2026-06-26",
            "description": "Muharram",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1782473400000, "end_time": 1782498300000}
            ],  # MCX evening 17:00-23:55
        },
        # September
        {
            "date": "2026-09-14",
            "description": "Ganesh Chaturthi",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1789385400000, "end_time": 1789410300000}
            ],  # MCX evening 17:00-23:55
        },
        # October
        {
            "date": "2026-10-02",
            "description": "Mahatma Gandhi Jayanti",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
            "open": [],
        },
        {
            "date": "2026-10-20",
            "description": "Dussehra",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1792495800000, "end_time": 1792520700000}
            ],  # MCX evening 17:00-23:55
        },
        # November - Diwali with Muhurat Trading
        {
            "date": "2026-11-08",
            "description": "Diwali Laxmi Pujan (Muhurat Trading)",
            "holiday_type": "SPECIAL_SESSION",
            "closed": [],
            # The published session; see MUHURAT_2026_SESSION.
            "open": [
                {"exchange": exchange, "start_time": start, "end_time": end}
                for exchange, (start, end) in MUHURAT_2026_SESSION.items()
            ],
        },
        {
            "date": "2026-11-10",
            "description": "Diwali Balipratipada",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1794310200000, "end_time": 1794335100000}
            ],  # MCX evening 17:00-23:55
        },
        {
            "date": "2026-11-24",
            "description": "Prakash Gurpurb Sri Guru Nanak Dev",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open": [
                {"exchange": "MCX", "start_time": 1795519800000, "end_time": 1795544700000}
            ],  # MCX evening 17:00-23:55
        },
        # December
        {
            "date": "2026-12-25",
            "description": "Christmas",
            "holiday_type": "TRADING_HOLIDAY",
            "closed": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
            "open": [],
        },
    ]

    return holidays_2026


def _add_holiday(holiday_info: dict, year: int) -> None:
    """Add one calendar entry and its exchanges to the session, uncommitted."""
    holiday_date = datetime.strptime(holiday_info["date"], "%Y-%m-%d").date()

    # Create holiday record
    holiday = Holiday(
        holiday_date=holiday_date,
        description=holiday_info["description"],
        holiday_type=holiday_info.get("holiday_type", "TRADING_HOLIDAY"),
        year=year,
    )
    db_session.add(holiday)
    db_session.flush()  # Get the holiday.id

    # Add closed exchanges
    for exchange in holiday_info["closed"]:
        exchange_entry = HolidayExchange(
            holiday_id=holiday.id,
            exchange_code=exchange,
            is_open=False,
            start_time=None,
            end_time=None,
        )
        db_session.add(exchange_entry)

    # Add open exchanges with special timings
    for open_exchange in holiday_info["open"]:
        exchange_entry = HolidayExchange(
            holiday_id=holiday.id,
            exchange_code=open_exchange["exchange"],
            is_open=True,
            start_time=open_exchange["start_time"],
            end_time=open_exchange["end_time"],
        )
        db_session.add(exchange_entry)


def _seed_holidays(holidays_data: list[dict], year: int):
    """Internal function to seed holidays for a specific year"""
    try:
        for holiday_info in holidays_data:
            _add_holiday(holiday_info, year)

        db_session.commit()
    except Exception as e:
        db_session.rollback()
        raise e


def get_holidays_by_year(year: int) -> list[dict[str, Any]]:
    """
    Get all holidays for a specific year

    Args:
        year: The year to get holidays for

    Returns:
        List of holiday dictionaries with exchange information
    """
    cache_key = f"holidays_{year}"

    # Check cache first
    cached = _holidays_cache.get(cache_key, MISSING)
    if cached is not MISSING:
        return cached
    # Read before the query, so a write that commits while this
    # read is in flight keeps its invalidation (see LockedTTLCache).
    generation = _holidays_cache.generation

    try:
        holidays = Holiday.query.filter(Holiday.year == year).order_by(Holiday.holiday_date).all()

        result = []
        for holiday in holidays:
            # Get exchange information for this holiday
            exchanges = HolidayExchange.query.filter(HolidayExchange.holiday_id == holiday.id).all()

            closed_exchanges = []
            open_exchanges = []

            for ex in exchanges:
                if ex.is_open:
                    open_exchanges.append(
                        {
                            "exchange": ex.exchange_code,
                            "start_time": ex.start_time,
                            "end_time": ex.end_time,
                        }
                    )
                else:
                    closed_exchanges.append(ex.exchange_code)

            result.append(
                {
                    "date": holiday.holiday_date.strftime("%Y-%m-%d"),
                    "description": holiday.description,
                    "holiday_type": holiday.holiday_type,
                    "closed_exchanges": closed_exchanges,
                    "open_exchanges": open_exchanges,
                }
            )

        # Cache the result
        _holidays_cache.fill(cache_key, result, generation)
        return result

    except Exception as e:
        logger.exception(f"Error fetching holidays for year {year}: {e}")
        return []


def _get_timing_offsets() -> dict[str, dict[str, int]]:
    """
    Get timing offsets from database or fallback to defaults.
    This ensures edited timings from admin page are used.
    """
    try:
        timings = MarketTiming.query.all()
        if timings:
            return {
                t.exchange_code: {"start_offset": t.start_offset, "end_offset": t.end_offset}
                for t in timings
            }
    except Exception as e:
        logger.debug(f"Error fetching timing offsets from DB, using defaults: {e}")

    return DEFAULT_MARKET_TIMINGS


def get_market_timings_for_date(query_date: date) -> list[dict[str, Any]]:
    """
    Get market timings for a specific date
    Returns empty list if it's a full holiday for all exchanges
    Returns special session timings for Muhurat trading etc.

    Args:
        query_date: The date to get timings for

    Returns:
        List of exchange timings with start_time and end_time in epoch milliseconds
    """
    cache_key = f"timings_{query_date.isoformat()}"

    # Check cache first
    cached = _timings_cache.get(cache_key, MISSING)
    if cached is not MISSING:
        return cached
    # Read before the query, so a write that commits while this
    # read is in flight keeps its invalidation (see LockedTTLCache).
    generation = _timings_cache.generation

    try:
        # Calculate midnight timestamp for the date in IST
        midnight_ist = datetime.combine(query_date, datetime.min.time())
        midnight_epoch = int(midnight_ist.timestamp() * 1000)

        # Get timing offsets from database (or defaults if not in DB)
        timing_offsets = _get_timing_offsets()

        # Check if it's a holiday/special session FIRST (before weekend check)
        # This allows special sessions like Budget Day or Muhurat Trading on weekends
        holiday = Holiday.query.filter(Holiday.holiday_date == query_date).first()

        if holiday:
            # Get exchange-specific information
            exchanges = HolidayExchange.query.filter(HolidayExchange.holiday_id == holiday.id).all()

            closed_exchanges = set()
            open_with_timings = {}

            for ex in exchanges:
                if ex.is_open:
                    open_with_timings[ex.exchange_code] = {
                        "exchange": ex.exchange_code,
                        "start_time": ex.start_time,
                        "end_time": ex.end_time,
                    }
                else:
                    closed_exchanges.add(ex.exchange_code)

            # For SPECIAL_SESSION (like Muhurat), return the special timings
            if holiday.holiday_type == "SPECIAL_SESSION":
                result = list(open_with_timings.values())
                _timings_cache.fill(cache_key, result, generation)
                return result

            # For SETTLEMENT_HOLIDAY, trading is open with normal hours
            if holiday.holiday_type == "SETTLEMENT_HOLIDAY":
                result = []
                for exchange in SUPPORTED_EXCHANGES:
                    timings = timing_offsets.get(exchange, DEFAULT_MARKET_TIMINGS.get(exchange, {}))
                    if timings:
                        result.append(
                            {
                                "exchange": exchange,
                                "start_time": midnight_epoch + timings["start_offset"],
                                "end_time": midnight_epoch + timings["end_offset"],
                            }
                        )
                _timings_cache.fill(cache_key, result, generation)
                return result

            # For regular TRADING_HOLIDAY, if all exchanges are closed, return empty
            if closed_exchanges == set(SUPPORTED_EXCHANGES) and not open_with_timings:
                _timings_cache.fill(cache_key, [], generation)
                return []

            # Build result with open exchanges only (closed exchanges not included)
            result = list(open_with_timings.values())
            _timings_cache.fill(cache_key, result, generation)
            return result

        # No holiday entry found - on weekends only crypto trades.
        # Weekend check is done AFTER holiday check so special sessions
        # on weekends (e.g., Sunday Muhurat) are honored above.
        if query_date.weekday() >= 5:
            crypto_only = []
            for exch in CRYPTO_EXCHANGES:
                timings = timing_offsets.get(exch, DEFAULT_MARKET_TIMINGS.get(exch, {}))
                if timings:
                    crypto_only.append(
                        {
                            "exchange": exch,
                            "start_time": midnight_epoch + timings["start_offset"],
                            "end_time": midnight_epoch + timings["end_offset"],
                        }
                    )
            _timings_cache.fill(cache_key, crypto_only, generation)
            return crypto_only

        # Normal trading day - return timings for all exchanges from DB
        result = []
        for exchange in SUPPORTED_EXCHANGES:
            timings = timing_offsets.get(exchange, DEFAULT_MARKET_TIMINGS.get(exchange, {}))
            if timings:
                result.append(
                    {
                        "exchange": exchange,
                        "start_time": midnight_epoch + timings["start_offset"],
                        "end_time": midnight_epoch + timings["end_offset"],
                    }
                )

        _timings_cache.fill(cache_key, result, generation)
        return result

    except Exception as e:
        logger.exception(f"Error fetching market timings for {query_date}: {e}")
        return []


def get_special_session(query_date: date, exchange: str) -> Optional[Dict[str, Any]]:
    """
    Return the SPECIAL_SESSION window for (date, exchange) if one exists and
    the exchange is marked open. Returns None otherwise.

    Used by /python's exchange-aware scheduler so a Sunday Muhurat (or any
    weekend special session) overrides the standard weekend reject.

    Returns:
        {"start_ms": int, "end_ms": int, "description": str} or None
    """
    if not exchange:
        return None
    exch = exchange.upper()
    if exch in CRYPTO_EXCHANGES:
        return None  # Crypto has no special-session concept

    cache_key = f"special_{query_date.isoformat()}_{exch}"
    cached = _timings_cache.get(cache_key, MISSING)
    if cached is not MISSING:
        return cached if cached else None
    generation = _timings_cache.generation

    try:
        holiday = (
            Holiday.query.filter(Holiday.holiday_date == query_date)
            .filter(Holiday.holiday_type == "SPECIAL_SESSION")
            .first()
        )
        if not holiday:
            _timings_cache.fill(cache_key, None, generation)
            return None

        ex_row = HolidayExchange.query.filter(
            HolidayExchange.holiday_id == holiday.id,
            HolidayExchange.exchange_code == exch,
            HolidayExchange.is_open == True,  # noqa: E712
        ).first()

        if not ex_row or ex_row.start_time is None or ex_row.end_time is None:
            _timings_cache.fill(cache_key, None, generation)
            return None

        result = {
            "start_ms": int(ex_row.start_time),
            "end_ms": int(ex_row.end_time),
            "description": holiday.description,
        }
        _timings_cache.fill(cache_key, result, generation)
        return result
    except Exception as e:
        logger.debug(f"get_special_session failed for {query_date} {exch}: {e}")
        return None


def get_holiday_exchange_window(
    query_date: date, exchange: str
) -> Optional[Dict[str, Any]]:
    """
    Return the open-window for (date, exchange) when a TRADING_HOLIDAY row
    explicitly leaves this exchange open with custom timings (e.g., MCX
    evening session 17:00-23:55 on an NSE/BSE holiday).

    Returns None when:
      - no holiday row for the date, or
      - the row marks this exchange closed, or
      - the row marks it open but supplies no start/end (treat as full day).

    Returns:
        {"start_ms": int, "end_ms": int} or None
    """
    if not exchange:
        return None
    exch = exchange.upper()
    if exch in CRYPTO_EXCHANGES:
        return None

    cache_key = f"holopen_{query_date.isoformat()}_{exch}"
    cached = _timings_cache.get(cache_key, MISSING)
    if cached is not MISSING:
        return cached if cached else None
    generation = _timings_cache.generation

    try:
        holiday = (
            Holiday.query.filter(Holiday.holiday_date == query_date)
            .filter(Holiday.holiday_type == "TRADING_HOLIDAY")
            .first()
        )
        if not holiday:
            _timings_cache.fill(cache_key, None, generation)
            return None

        ex_row = HolidayExchange.query.filter(
            HolidayExchange.holiday_id == holiday.id,
            HolidayExchange.exchange_code == exch,
            HolidayExchange.is_open == True,  # noqa: E712
        ).first()

        if not ex_row or ex_row.start_time is None or ex_row.end_time is None:
            _timings_cache.fill(cache_key, None, generation)
            return None

        result = {"start_ms": int(ex_row.start_time), "end_ms": int(ex_row.end_time)}
        _timings_cache.fill(cache_key, result, generation)
        return result
    except Exception as e:
        logger.debug(f"get_holiday_exchange_window failed for {query_date} {exch}: {e}")
        return None


def get_effective_session_window(
    query_date: date, exchange: str
) -> Optional[Dict[str, Any]]:
    """
    Single source of truth for "what is the trading window for <exchange> on
    <date>?".

    Returns a dict with epoch-ms `start_ms` / `end_ms` (in IST midnight terms)
    plus an `is_special` flag, or None if the exchange is closed that day.

    Resolution order:
      1. CRYPTO -> always 00:00-23:59:59 (24/7)
      2. SPECIAL_SESSION row for (date, exchange) -> custom window
      3. TRADING_HOLIDAY row with an explicit open window for this exchange
         (e.g. MCX evening on NSE holiday) -> custom window
      4. TRADING_HOLIDAY row with this exchange closed -> None
      5. Weekend with no special session -> None
      6. Otherwise -> default exchange timings from MarketTiming/DEFAULT_MARKET_TIMINGS
    """
    if not exchange:
        return None
    exch = exchange.upper()

    # Compute IST-midnight epoch-ms anchor for this date so default-timing
    # offsets can be expressed as absolute epoch-ms values too.
    midnight_ist = IST.localize(datetime.combine(query_date, datetime.min.time()))
    midnight_ms = int(midnight_ist.timestamp() * 1000)

    # 1. CRYPTO is always open
    if exch in CRYPTO_EXCHANGES:
        timings = _get_timing_offsets().get(exch, DEFAULT_MARKET_TIMINGS.get(exch, {}))
        if not timings:
            return None
        return {
            "start_ms": midnight_ms + timings["start_offset"],
            "end_ms": midnight_ms + timings["end_offset"],
            "is_special": False,
        }

    try:
        # 2. Special session
        special = get_special_session(query_date, exch)
        if special:
            return {
                "start_ms": special["start_ms"],
                "end_ms": special["end_ms"],
                "is_special": True,
            }

        # 3 & 4. Trading holiday with explicit open window or closed
        holiday = (
            Holiday.query.filter(Holiday.holiday_date == query_date)
            .filter(Holiday.holiday_type == "TRADING_HOLIDAY")
            .first()
        )
        if holiday:
            ex_row = HolidayExchange.query.filter(
                HolidayExchange.holiday_id == holiday.id,
                HolidayExchange.exchange_code == exch,
            ).first()
            if ex_row:
                if not ex_row.is_open:
                    return None
                if ex_row.start_time is not None and ex_row.end_time is not None:
                    return {
                        "start_ms": int(ex_row.start_time),
                        "end_ms": int(ex_row.end_time),
                        "is_special": True,
                    }
            # Exchange not listed on this holiday row -> treat as open with default timings

        # 5. Weekend with no special session
        if query_date.weekday() >= 5:
            return None

        # 6. Default timings
        timings = _get_timing_offsets().get(exch, DEFAULT_MARKET_TIMINGS.get(exch, {}))
        if not timings:
            return None
        return {
            "start_ms": midnight_ms + timings["start_offset"],
            "end_ms": midnight_ms + timings["end_offset"],
            "is_special": False,
        }
    except Exception as e:
        logger.debug(f"get_effective_session_window failed for {query_date} {exch}: {e}")
        return None


def is_market_holiday(query_date: date, exchange: str = None) -> bool:
    """
    Check if a date is a market holiday

    Args:
        query_date: The date to check
        exchange: Optional exchange code to check specific exchange

    Returns:
        True if it's a holiday (or weekend), False otherwise
    """
    try:
        # Crypto exchanges operate 24/7 - no holidays or weekends
        if exchange and exchange.upper() in CRYPTO_EXCHANGES:
            return False

        # Check for special session FIRST (before weekend check)
        # This allows special sessions like Budget Day or Muhurat Trading on weekends
        holiday = Holiday.query.filter(Holiday.holiday_date == query_date).first()

        # Special sessions are not holidays - markets are open with special timings
        if holiday and holiday.holiday_type == "SPECIAL_SESSION":
            return False

        # Weekend check (only if no special session)
        if query_date.weekday() >= 5:
            return True

        if not holiday:
            return False

        if exchange:
            # Check if specific exchange is closed
            exchange_info = HolidayExchange.query.filter(
                HolidayExchange.holiday_id == holiday.id,
                HolidayExchange.exchange_code == exchange.upper(),
            ).first()

            if exchange_info:
                return not exchange_info.is_open
            return False  # Exchange not in holiday list means it's open

        return True  # It's a holiday
    except Exception as e:
        # Handle case where tables don't exist yet (fresh installation)
        # Fall back to simple weekend check
        logger.debug(f"Holiday check unavailable (tables may not exist yet): {e}")
        return query_date.weekday() >= 5  # Return True only for weekends


def clear_market_calendar_cache():
    """Clear all market calendar caches"""
    _timings_cache.clear()
    _holidays_cache.clear()
    logger.info("Market calendar cache cleared")


#: The 2026 entries in the first calendar OpenAlgo shipped (December 2025) that
#: the corrected one (March 2026) changed or dropped, by date, as
#: (description, holiday_type, closed exchanges, open (exchange, start, end)).
#: Generated from that release's seed. A stored row equal to one of these is
#: OpenAlgo's own and was never edited, and it is wrong: Holi on 10 March,
#: Muhurat on 20 October, Guru Nanak on 8 November, settlement holidays nothing
#: trades on, and MCX evening windows stamped with 2025's dates.
_V1_ONLY_ENTRIES = {
    "2026-02-19": (
        "Chhatrapati Shivaji Maharaj Jayanti",
        "SETTLEMENT_HOLIDAY",
        (),
        (),
    ),
    "2026-03-10": (
        "Holi",
        "TRADING_HOLIDAY",
        ("BCD", "BFO", "BSE", "CDS", "NFO", "NSE"),
        (("MCX", 1741624200000, 1741677900000),),
    ),
    "2026-03-20": (
        "Id-Ul-Fitr (Ramadan)",
        "TRADING_HOLIDAY",
        ("BCD", "BFO", "BSE", "CDS", "NFO", "NSE"),
        (("MCX", 1742488200000, 1742541900000),),
    ),
    "2026-03-25": (
        "Holi (Dhuleti)",
        "TRADING_HOLIDAY",
        ("BCD", "BFO", "BSE", "CDS", "NFO", "NSE"),
        (("MCX", 1742920200000, 1742973900000),),
    ),
    "2026-04-01": (
        "Annual Bank Closing",
        "SETTLEMENT_HOLIDAY",
        (),
        (),
    ),
    "2026-04-02": (
        "Ram Navami",
        "TRADING_HOLIDAY",
        ("BCD", "BFO", "BSE", "CDS", "NFO", "NSE"),
        (("MCX", 1743611400000, 1743665100000),),
    ),
    "2026-04-06": (
        "Mahavir Jayanti",
        "TRADING_HOLIDAY",
        ("BCD", "BFO", "BSE", "CDS", "NFO", "NSE"),
        (("MCX", 1743957000000, 1744010700000),),
    ),
    "2026-04-14": (
        "Dr. Baba Saheb Ambedkar Jayanti",
        "TRADING_HOLIDAY",
        ("BCD", "BFO", "BSE", "CDS", "NFO", "NSE"),
        (("MCX", 1744648200000, 1744701900000),),
    ),
    "2026-05-01": (
        "Maharashtra Day",
        "TRADING_HOLIDAY",
        ("BCD", "BFO", "BSE", "CDS", "NFO", "NSE"),
        (("MCX", 1746117000000, 1746170700000),),
    ),
    "2026-05-27": (
        "Bakri Id (Eid ul-Adha)",
        "TRADING_HOLIDAY",
        ("BCD", "BFO", "BSE", "CDS", "NFO", "NSE"),
        (("MCX", 1748363400000, 1748417100000),),
    ),
    "2026-06-25": (
        "Muharram",
        "TRADING_HOLIDAY",
        ("BCD", "BFO", "BSE", "CDS", "NFO", "NSE"),
        (("MCX", 1750868400000, 1750922100000),),
    ),
    "2026-08-15": (
        "Independence Day",
        "TRADING_HOLIDAY",
        ("BCD", "BFO", "BSE", "CDS", "MCX", "NFO", "NSE"),
        (),
    ),
    "2026-08-27": (
        "Id-E-Milad",
        "SETTLEMENT_HOLIDAY",
        (),
        (),
    ),
    "2026-09-04": (
        "Milad-un-Nabi (Birthday of Prophet Mohammad)",
        "TRADING_HOLIDAY",
        ("BCD", "BFO", "BSE", "CDS", "NFO", "NSE"),
        (("MCX", 1756997400000, 1757051100000),),
    ),
    "2026-10-20": (
        "Diwali Laxmi Pujan (Muhurat Trading)",
        "SPECIAL_SESSION",
        (),
        (
            ("BCD", 1761052200000, 1761056700000),
            ("BFO", 1761052200000, 1761056700000),
            ("BSE", 1761052200000, 1761056700000),
            ("CDS", 1761052200000, 1761056700000),
            ("MCX", 1761052200000, 1761074700000),
            ("NFO", 1761052200000, 1761056700000),
            ("NSE", 1761052200000, 1761056700000),
        ),
    ),
    "2026-10-21": (
        "Diwali Balipratipada",
        "TRADING_HOLIDAY",
        ("BCD", "BFO", "BSE", "CDS", "NFO", "NSE"),
        (("MCX", 1761138600000, 1761192300000),),
    ),
    "2026-11-08": (
        "Guru Nanak Jayanti",
        "TRADING_HOLIDAY",
        ("BCD", "BFO", "BSE", "CDS", "NFO", "NSE"),
        (("MCX", 1762693800000, 1762747500000),),
    ),
}

_CORRECTED_DATES = frozenset(
    {
        "2026-01-15",
        "2026-03-03",
        "2026-03-26",
        "2026-03-31",
        "2026-04-14",
        "2026-05-01",
        "2026-05-28",
        "2026-06-26",
        "2026-09-14",
        "2026-10-20",
        "2026-11-08",
        "2026-11-10",
        "2026-11-24",
    }
)


def _stored_entry(holiday: "Holiday") -> tuple:
    """A stored holiday in the shape of _V1_ONLY_ENTRIES."""
    rows = HolidayExchange.query.filter(HolidayExchange.holiday_id == holiday.id).all()
    closed = tuple(sorted(row.exchange_code for row in rows if not row.is_open))
    opened = tuple(
        sorted((row.exchange_code, row.start_time, row.end_time) for row in rows if row.is_open)
    )
    return (holiday.description, holiday.holiday_type, closed, opened)


def _is_first_calendar_row(holiday: "Holiday") -> bool:
    shipped = _V1_ONLY_ENTRIES.get(holiday.holiday_date.isoformat())
    return shipped is not None and shipped == _stored_entry(holiday)


def plan_2026_calendar_correction() -> list[tuple[str, str, str]] | None:
    """What moving an install off the first 2026 calendar would do.

    Only an install that still holds a row exactly as the first calendar
    shipped it is touched. One that has the corrected calendar, or a calendar
    its admin has curated, is left exactly as it is, so a holiday an admin
    added stays and one an admin deleted stays deleted.

    Returns:
        None when no calendar is stored, which the seed handles. Otherwise one
        (action, date, description) per change: "remove" for a first-calendar
        row, "add" for a corrected entry whose date is free once those rows
        are gone. Empty when there is nothing to correct.
    """
    holidays = Holiday.query.all()
    if not holidays:
        return None
    stale = [holiday for holiday in holidays if _is_first_calendar_row(holiday)]
    if not stale:
        return []
    stale_ids = {holiday.id for holiday in stale}
    taken = {
        holiday.holiday_date.isoformat() for holiday in holidays if holiday.id not in stale_ids
    }
    steps = [
        ("remove", holiday.holiday_date.isoformat(), holiday.description)
        for holiday in sorted(stale, key=lambda holiday: holiday.holiday_date)
    ]
    for entry in shipped_holidays_2025() + shipped_holidays_2026():
        if entry["date"] in _CORRECTED_DATES and entry["date"] not in taken:
            steps.append(("add", entry["date"], entry["description"]))
    return steps


def correct_2026_calendar() -> list[tuple[str, str, str]] | None:
    """Move an install off the first 2026 calendar, keeping what an admin set.

    This replaces a reset that deleted every holiday and reseeded from code. It
    ran on every upgrade (upgrade/migrate_market_holidays.py) and at startup
    whenever no special session was stored, and each time it took every
    holiday an admin had added or edited on the Holidays page. Runs at startup
    and from that upgrade script.

    Returns:
        The plan it applied, as plan_2026_calendar_correction describes it, or
        None when no calendar is stored or the change could not be made.
    """
    try:
        steps = plan_2026_calendar_correction()
        if not steps:
            return steps
        adding = {day for action, day, _description in steps if action == "add"}
        for holiday in Holiday.query.all():
            if _is_first_calendar_row(holiday):
                HolidayExchange.query.filter(HolidayExchange.holiday_id == holiday.id).delete(
                    synchronize_session=False
                )
                db_session.delete(holiday)
        db_session.flush()
        for entry in shipped_holidays_2025() + shipped_holidays_2026():
            if entry["date"] in adding:
                _add_holiday(entry, int(entry["date"][:4]))
        db_session.commit()
        clear_market_calendar_cache()
        logger.info(
            f"Market Calendar DB: moved {len(steps) - len(adding)} holiday(s) from the first "
            f"2026 calendar to the corrected one and added {len(adding)}"
        )
        return steps
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Market Calendar DB: could not correct the 2026 calendar: {e}")
        return None


def ensure_market_calendar_tables_exists():
    """Wrapper function for parallel initialization"""
    init_db()
    # An install still on the first 2026 calendar gets the corrected one
    correct_2026_calendar()
    # Seed market timings if not present
    seed_market_timings()
    migrate_fo_close_for_cas()
    migrate_muhurat_2026()


#: Exchanges whose close moved with the Closing Auction Session, and the value
#: they held before it. Only a row still carrying the old close is updated, so
#: an admin who has set their own timing is not overwritten.
CAS_CLOSE_MIGRATION = {
    "NFO": {"old_end": 55800000, "new_end": 56400000},
    "BFO": {"old_end": 55800000, "new_end": 56400000},
}


def migrate_fo_close_for_cas():
    """Move the NFO/BFO close from 15:30 to 15:40 on existing installs.

    seed_market_timings only runs when the table is empty, so every existing
    installation would keep the pre-CAS close indefinitely. Guarded on the old
    value: a row an admin has already customised is left alone rather than
    being reset to a default they did not ask for.
    """
    try:
        changed = 0
        for exchange, spec in CAS_CLOSE_MIGRATION.items():
            row = MarketTiming.query.filter_by(exchange_code=exchange).first()
            if row is None or int(row.end_offset or 0) != spec["old_end"]:
                continue
            row.end_offset = spec["new_end"]
            hours = spec["new_end"] // 3600000
            mins = (spec["new_end"] % 3600000) // 60000
            row.end_time = f"{hours:02d}:{mins:02d}"
            changed += 1
        if changed:
            db_session.commit()
            logger.info(
                f"Market Calendar DB: moved the close to 15:40 for {changed} "
                "F&O exchange(s) following SEBI's Closing Auction Session"
            )
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Market Calendar DB: could not migrate the F&O close: {e}")


def plan_muhurat_2026() -> list[tuple[str, str]] | None:
    """What moving 2026's Muhurat to the published session would do.

    The seed loads only into an empty table, so an existing install keeps
    whatever 2026 row it was seeded with.

    Returns:
        One (exchange, action) per exchange in the published session, where
        action is "update" (the row holds the shipped guess), "insert" (the
        row was never shipped), "current" (already published) or "custom" (set
        or removed by an admin, left alone). None when 8 November 2026 is not
        stored as a special session, which is left to the admin who changed it.
    """
    holiday = (
        Holiday.query.filter(Holiday.holiday_date == MUHURAT_2026_DATE)
        .filter(Holiday.holiday_type == "SPECIAL_SESSION")
        .first()
    )
    if holiday is None:
        return None
    rows = {
        row.exchange_code: row
        for row in HolidayExchange.query.filter(HolidayExchange.holiday_id == holiday.id)
    }
    steps = []
    for exchange, published in MUHURAT_2026_SESSION.items():
        row = rows.get(exchange)
        if row is None:
            action = "custom" if exchange in _MUHURAT_2026_GUESS else "insert"
        else:
            window = (row.start_time, row.end_time) if row.is_open else None
            if window == published:
                action = "current"
            elif window is not None and window == _MUHURAT_2026_GUESS.get(exchange):
                action = "update"
            else:
                action = "custom"
        steps.append((exchange, action))
    return steps


def migrate_muhurat_2026() -> list[tuple[str, str]] | None:
    """Move 2026's Muhurat session from the shipped guess to the published one.

    Guarded on the guess, as `migrate_fo_close_for_cas` is on the old close, so
    a session an admin has already set on the Holidays page stays as it is.
    Runs at startup and from upgrade/migrate_muhurat_2026.py.

    Returns:
        The plan it applied, as `plan_muhurat_2026` describes it.
    """
    try:
        steps = plan_muhurat_2026()
        if not steps:
            return steps
        holiday = (
            Holiday.query.filter(Holiday.holiday_date == MUHURAT_2026_DATE)
            .filter(Holiday.holiday_type == "SPECIAL_SESSION")
            .first()
        )
        changed = 0
        for exchange, action in steps:
            start, end = MUHURAT_2026_SESSION[exchange]
            if action == "insert":
                db_session.add(
                    HolidayExchange(
                        holiday_id=holiday.id,
                        exchange_code=exchange,
                        is_open=True,
                        start_time=start,
                        end_time=end,
                    )
                )
                changed += 1
            elif action == "update":
                guess_start, guess_end = _MUHURAT_2026_GUESS[exchange]
                changed += HolidayExchange.query.filter(
                    HolidayExchange.holiday_id == holiday.id,
                    HolidayExchange.exchange_code == exchange,
                    HolidayExchange.start_time == guess_start,
                    HolidayExchange.end_time == guess_end,
                ).update(
                    {HolidayExchange.start_time: start, HolidayExchange.end_time: end},
                    synchronize_session=False,
                )
        if changed:
            db_session.commit()
            clear_market_calendar_cache()
            logger.info(
                f"Market Calendar DB: set the 8 November 2026 Muhurat session to the "
                f"published timings for {changed} exchange(s)"
            )
        return steps
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Market Calendar DB: could not update the 2026 Muhurat session: {e}")
        return None


def seed_market_timings():
    """Seed default market timings if table is empty"""
    try:
        if MarketTiming.query.count() == 0:
            for exchange, timings in DEFAULT_MARKET_TIMINGS.items():
                start_offset = timings["start_offset"]
                end_offset = timings["end_offset"]

                # Convert offset to HH:MM
                start_hours = start_offset // 3600000
                start_mins = (start_offset % 3600000) // 60000
                end_hours = end_offset // 3600000
                end_mins = (end_offset % 3600000) // 60000

                timing = MarketTiming(
                    exchange_code=exchange,
                    start_time=f"{start_hours:02d}:{start_mins:02d}",
                    end_time=f"{end_hours:02d}:{end_mins:02d}",
                    start_offset=start_offset,
                    end_offset=end_offset,
                )
                db_session.add(timing)

            db_session.commit()
            logger.debug("Market Calendar DB: Market timings seeded successfully")
    except Exception as e:
        db_session.rollback()
        logger.debug(f"Market Calendar DB: Timing seeding may have race condition: {e}")


def get_all_market_timings() -> list[dict[str, Any]]:
    """Get all market timings from database or defaults"""
    try:
        timings = MarketTiming.query.order_by(MarketTiming.exchange_code).all()

        if timings:
            return [
                {
                    "id": t.id,
                    "exchange": t.exchange_code,
                    "start_time": t.start_time,
                    "end_time": t.end_time,
                    "start_offset": t.start_offset,
                    "end_offset": t.end_offset,
                }
                for t in timings
            ]

        # Fallback to defaults if no DB entries
        result = []
        for exchange, timing in DEFAULT_MARKET_TIMINGS.items():
            start_offset = timing["start_offset"]
            end_offset = timing["end_offset"]
            start_hours = start_offset // 3600000
            start_mins = (start_offset % 3600000) // 60000
            end_hours = end_offset // 3600000
            end_mins = (end_offset % 3600000) // 60000

            result.append(
                {
                    "id": None,
                    "exchange": exchange,
                    "start_time": f"{start_hours:02d}:{start_mins:02d}",
                    "end_time": f"{end_hours:02d}:{end_mins:02d}",
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                }
            )
        return result

    except Exception as e:
        logger.exception(f"Error fetching market timings: {e}")
        return []


def update_market_timing(exchange: str, start_time: str, end_time: str) -> bool:
    """
    Update market timing for an exchange.

    Args:
        exchange: Exchange code (e.g., 'NSE', 'MCX')
        start_time: Start time in HH:MM format
        end_time: End time in HH:MM format

    Returns:
        True if successful, False otherwise
    """
    try:
        # Parse times to calculate offsets
        start_parts = start_time.split(":")
        end_parts = end_time.split(":")

        start_offset = int(start_parts[0]) * 3600000 + int(start_parts[1]) * 60000
        end_offset = int(end_parts[0]) * 3600000 + int(end_parts[1]) * 60000

        # Update or create timing
        timing = MarketTiming.query.filter_by(exchange_code=exchange.upper()).first()

        if timing:
            timing.start_time = start_time
            timing.end_time = end_time
            timing.start_offset = start_offset
            timing.end_offset = end_offset
        else:
            timing = MarketTiming(
                exchange_code=exchange.upper(),
                start_time=start_time,
                end_time=end_time,
                start_offset=start_offset,
                end_offset=end_offset,
            )
            db_session.add(timing)

        db_session.commit()

        # Clear cache
        clear_market_calendar_cache()

        # Update DEFAULT_MARKET_TIMINGS for current session
        DEFAULT_MARKET_TIMINGS[exchange.upper()] = {
            "start_offset": start_offset,
            "end_offset": end_offset,
        }

        logger.info(f"Updated market timing for {exchange}: {start_time} - {end_time}")
        return True

    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error updating market timing: {e}")
        return False


def get_market_timing(exchange: str) -> dict[str, Any] | None:
    """Get market timing for a specific exchange"""
    try:
        timing = MarketTiming.query.filter_by(exchange_code=exchange.upper()).first()

        if timing:
            return {
                "id": timing.id,
                "exchange": timing.exchange_code,
                "start_time": timing.start_time,
                "end_time": timing.end_time,
                "start_offset": timing.start_offset,
                "end_offset": timing.end_offset,
            }

        # Fallback to default
        if exchange.upper() in DEFAULT_MARKET_TIMINGS:
            timing_data = DEFAULT_MARKET_TIMINGS[exchange.upper()]
            start_offset = timing_data["start_offset"]
            end_offset = timing_data["end_offset"]
            start_hours = start_offset // 3600000
            start_mins = (start_offset % 3600000) // 60000
            end_hours = end_offset // 3600000
            end_mins = (end_offset % 3600000) // 60000

            return {
                "id": None,
                "exchange": exchange.upper(),
                "start_time": f"{start_hours:02d}:{start_mins:02d}",
                "end_time": f"{end_hours:02d}:{end_mins:02d}",
                "start_offset": start_offset,
                "end_offset": end_offset,
            }

        return None

    except Exception as e:
        logger.exception(f"Error fetching market timing for {exchange}: {e}")
        return None


def is_market_open(exchange: str = None) -> bool:
    """
    Check if market is currently open for an exchange.

    Honors holiday-specific windows (e.g., MCX 17:00-23:55 evening session
    on an NSE/BSE holiday) and SPECIAL_SESSION rows on weekends.

    Args:
        exchange: Exchange code (NSE, BSE, NFO, BFO, MCX, BCD, CDS, CRYPTO)
                  If None, checks if ANY exchange is open

    Returns:
        True if market is open, False otherwise
    """
    try:
        # Crypto exchanges are always open (24/7)
        if exchange and exchange.upper() in CRYPTO_EXCHANGES:
            return True

        now = datetime.now(IST)
        today = now.date()
        now_epoch_ms = int(now.timestamp() * 1000)

        if exchange:
            window = get_effective_session_window(today, exchange)
            if not window:
                return False
            return window["start_ms"] <= now_epoch_ms <= window["end_ms"]

        # Check if ANY exchange is open
        for exch in SUPPORTED_EXCHANGES:
            if exch in CRYPTO_EXCHANGES:
                return True
            window = get_effective_session_window(today, exch)
            if window and window["start_ms"] <= now_epoch_ms <= window["end_ms"]:
                return True
        return False

    except Exception as e:
        logger.exception(f"Error checking if market is open: {e}")
        return False


def get_market_hours_status() -> dict[str, Any]:
    """
    Get comprehensive market hours status for all exchanges.

    Returns:
        Dict with:
        - is_trading_day: bool
        - any_market_open: bool
        - exchanges: dict of exchange -> {is_open, start_time, end_time, next_open, next_close}
        - next_market_open: datetime (when any market opens next)
        - next_market_close: datetime (when all markets close)
    """
    try:
        now = datetime.now(IST)
        today = now.date()
        current_ms = (now.hour * 3600 + now.minute * 60 + now.second) * 1000
        now_epoch_ms = int(now.timestamp() * 1000)
        midnight_ist = IST.localize(datetime.combine(today, datetime.min.time()))
        midnight_epoch_ms = int(midnight_ist.timestamp() * 1000)

        # is_trading_day reflects the most permissive view: any non-crypto
        # exchange has a session today (regular, special, or partial holiday).
        is_trading = False

        exchanges_status = {}
        any_open = False
        earliest_open_ms = None
        latest_close_ms = None

        for exch in SUPPORTED_EXCHANGES:
            timing = get_market_timing(exch)
            window = get_effective_session_window(today, exch)

            if exch in CRYPTO_EXCHANGES:
                is_open = True
                start_offset = timing["start_offset"] if timing else 0
                end_offset = timing["end_offset"] if timing else 86399000
                start_label = timing["start_time"] if timing else "00:00"
                end_label = timing["end_time"] if timing else "23:59"
            elif window:
                is_open = window["start_ms"] <= now_epoch_ms <= window["end_ms"]
                start_offset = window["start_ms"] - midnight_epoch_ms
                end_offset = window["end_ms"] - midnight_epoch_ms
                start_h = max(0, start_offset) // 3600000
                start_m = (max(0, start_offset) % 3600000) // 60000
                end_h = max(0, end_offset) // 3600000
                end_m = (max(0, end_offset) % 3600000) // 60000
                start_label = f"{start_h:02d}:{start_m:02d}"
                end_label = f"{end_h:02d}:{end_m:02d}"
                is_trading = True
            else:
                # Closed today
                is_open = False
                start_offset = timing["start_offset"] if timing else 0
                end_offset = timing["end_offset"] if timing else 0
                start_label = timing["start_time"] if timing else ""
                end_label = timing["end_time"] if timing else ""

            if is_open and exch not in CRYPTO_EXCHANGES:
                any_open = True
            elif is_open and exch in CRYPTO_EXCHANGES:
                any_open = True

            exchanges_status[exch] = {
                "is_open": is_open,
                "is_special": bool(window and window.get("is_special")) if exch not in CRYPTO_EXCHANGES else False,
                "start_time": start_label,
                "end_time": end_label,
                "start_offset": start_offset,
                "end_offset": end_offset,
            }

            # Track earliest open and latest close across exchanges that have a session today
            if window or exch in CRYPTO_EXCHANGES:
                if earliest_open_ms is None or start_offset < earliest_open_ms:
                    earliest_open_ms = start_offset
                if latest_close_ms is None or end_offset > latest_close_ms:
                    latest_close_ms = end_offset

        return {
            "is_trading_day": is_trading,
            "any_market_open": any_open,
            "exchanges": exchanges_status,
            "earliest_open_ms": earliest_open_ms,
            "latest_close_ms": latest_close_ms,
            "current_time_ms": current_ms,
            "current_time": now.strftime("%H:%M:%S IST"),
        }

    except Exception as e:
        logger.exception(f"Error getting market hours status: {e}")
        return {"is_trading_day": False, "any_market_open": False, "exchanges": {}, "error": str(e)}


def get_next_market_event() -> tuple[str, datetime]:
    """
    Get the next market event (open or close).

    Returns:
        Tuple of (event_type, event_time) where event_type is 'open' or 'close'
    """
    try:
        now = datetime.now(IST)
        today = now.date()
        current_ms = (now.hour * 3600 + now.minute * 60 + now.second) * 1000

        status = get_market_hours_status()

        if status["any_market_open"]:
            # Market is open, find next close
            # Latest close time across all exchanges
            close_ms = status["latest_close_ms"]
            close_hours = close_ms // 3600000
            close_mins = (close_ms % 3600000) // 60000
            close_time = now.replace(hour=close_hours, minute=close_mins, second=0, microsecond=0)
            return ("close", close_time)
        else:
            # Market is closed, find next open
            if status["is_trading_day"] and current_ms < status["earliest_open_ms"]:
                # Today is trading day and market hasn't opened yet
                open_ms = status["earliest_open_ms"]
                open_hours = open_ms // 3600000
                open_mins = (open_ms % 3600000) // 60000
                open_time = now.replace(hour=open_hours, minute=open_mins, second=0, microsecond=0)
                return ("open", open_time)
            else:
                # Market closed for today or it's a holiday, find next trading day
                from datetime import timedelta

                check_date = today + timedelta(days=1)
                for _ in range(7):  # Check up to 7 days ahead
                    if not is_market_holiday(check_date):
                        # Found next trading day
                        open_ms = status["earliest_open_ms"] or 33300000  # Default 09:15
                        open_hours = open_ms // 3600000
                        open_mins = (open_ms % 3600000) // 60000
                        open_time = datetime(
                            check_date.year,
                            check_date.month,
                            check_date.day,
                            open_hours,
                            open_mins,
                            0,
                            tzinfo=IST,
                        )
                        return ("open", open_time)
                    check_date += timedelta(days=1)

                # Fallback - shouldn't reach here
                return ("open", None)

    except Exception as e:
        logger.exception(f"Error getting next market event: {e}")
        return ("unknown", None)
