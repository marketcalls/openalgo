# database/intraday_leverage_db.py
# Per-symbol intraday leverage multipliers for NSE equities.
# Stores a lookup table mapping each stock symbol to its intraday
# leverage multiplier (1x, 2x, 4x, or 5x) used for position sizing.

from cachetools import TTLCache
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

_leverage_cache = TTLCache(maxsize=2048, ttl=3600)

engine = create_db_engine()

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class IntradayLeverage(Base):
    __tablename__ = "intraday_leverage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    exchange = Column(String, nullable=False, default="NSE")
    multiplier = Column(Float, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("symbol", "exchange", name="uq_intraday_leverage_symbol_exchange"),
    )


from database.intraday_leverage_data import _LEVERAGE_DATA


def init_db():
    """Initialize the intraday leverage table and seed from embedded data."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Intraday Leverage DB", logger)

    try:
        existing = IntradayLeverage.query.count()
        if existing >= len(_LEVERAGE_DATA):
            logger.debug(f"Intraday Leverage DB: {existing} rows already seeded")
            return
        _seed_data()
    except Exception as e:
        db_session.rollback()
        logger.debug(f"Intraday Leverage DB: seed check skipped: {e}")


def _seed_data():
    """Insert all embedded leverage records. Skips duplicates."""
    count = 0
    for symbol, multiplier in _LEVERAGE_DATA.items():
        existing = IntradayLeverage.query.filter_by(symbol=symbol, exchange="NSE").first()
        if not existing:
            db_session.add(
                IntradayLeverage(symbol=symbol, exchange="NSE", multiplier=float(multiplier))
            )
            count += 1
    if count:
        db_session.commit()
        logger.info(f"Intraday Leverage DB: seeded {count} new records")
    _leverage_cache.clear()


def get_multiplier(symbol, exchange="NSE"):
    """Get intraday leverage multiplier for a symbol (cached)."""
    cache_key = f"{exchange}:{symbol.upper()}"
    if cache_key in _leverage_cache:
        return _leverage_cache[cache_key]

    record = IntradayLeverage.query.filter_by(symbol=symbol.upper(), exchange=exchange).first()
    # Both cash venues share the shipped equity schedule unless a BSE
    # override has explicitly been configured.
    if record is None and exchange == "BSE":
        record = IntradayLeverage.query.filter_by(symbol=symbol.upper(), exchange="NSE").first()
    value = record.multiplier if record else None

    _leverage_cache[cache_key] = value
    return value


def get_multipliers_bulk(symbols, exchange="NSE"):
    """Get leverage multipliers for multiple symbols."""
    results = {}
    uncached = []
    for symbol in symbols:
        cache_key = f"{exchange}:{symbol.upper()}"
        if cache_key in _leverage_cache:
            results[symbol] = _leverage_cache[cache_key]
        else:
            uncached.append(symbol)

    if uncached:
        records = IntradayLeverage.query.filter(
            IntradayLeverage.symbol.in_([s.upper() for s in uncached]),
            IntradayLeverage.exchange == exchange,
        ).all()
        found = {r.symbol: r.multiplier for r in records}
        if exchange == "BSE":
            shared = IntradayLeverage.query.filter(
                IntradayLeverage.symbol.in_([s.upper() for s in uncached]),
                IntradayLeverage.exchange == "NSE",
            ).all()
            for row in shared:
                found.setdefault(row.symbol, row.multiplier)
        for symbol in uncached:
            value = found.get(symbol.upper())
            _leverage_cache[f"{exchange}:{symbol.upper()}"] = value
            results[symbol] = value

    return results
