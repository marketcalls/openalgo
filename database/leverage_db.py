# database/leverage_db.py
# Single-row leverage configuration for crypto brokers.
# Stores one common leverage value applied to all crypto futures orders.

import os

from sqlalchemy import Column, DateTime, Float, Integer, create_engine, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from utils.logging import get_logger
from utils.thread_safe_cache import MISSING, LockedTTLCache

logger = get_logger(__name__)

_leverage_cache = LockedTTLCache(maxsize=1, ttl=3600)

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL and "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class LeverageConfig(Base):
    __tablename__ = "leverage_config"

    id = Column(Integer, primary_key=True, default=1)
    leverage = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


def init_db():
    """Initialize the leverage config table and ensure a default row exists."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Leverage DB", logger)

    try:
        if not LeverageConfig.query.first():
            db_session.add(LeverageConfig(id=1, leverage=0.0))
            db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.debug(f"Leverage DB: default row may already exist: {e}")


def get_leverage():
    """Get the common leverage value (cached)."""
    cache_key = "leverage"

    cached = _leverage_cache.get(cache_key, MISSING)
    if cached is not MISSING:
        return cached
    # Read before the query, so a write that commits while this
    # read is in flight keeps its invalidation (see LockedTTLCache).
    generation = _leverage_cache.generation

    config = LeverageConfig.query.first()
    value = config.leverage if config else 0.0

    _leverage_cache.fill(cache_key, value, generation)
    return value


def set_leverage(leverage):
    """Set the common leverage value. Must be a non-negative integer."""
    import math
    leverage = float(leverage)
    if math.isnan(leverage) or math.isinf(leverage) or leverage < 0:
        raise ValueError(f"Invalid leverage: {leverage}")
    if not leverage.is_integer():
        raise ValueError(f"Leverage must be a whole number, got: {leverage}")
    leverage = int(leverage)

    config = LeverageConfig.query.first()
    if config:
        config.leverage = leverage
    else:
        config = LeverageConfig(id=1, leverage=leverage)
        db_session.add(config)
    db_session.commit()

    # Invalidate first, so a read that loaded the old value before this commit
    # cannot store it over the new one, then write the new value through.
    _leverage_cache.invalidate("leverage")
    _leverage_cache["leverage"] = leverage
    logger.info(f"Leverage set to {leverage}")
