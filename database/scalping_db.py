# database/scalping_db.py
"""
Persistence for the /scalping terminal's stop-loss / trailing-SL configuration.

The trailing-SL engine itself runs in the browser (Phase 2). This module only
persists each active leg's SL config so it survives a page reload — keyed by
(symbol, exchange, product). Mirrors database/flow_db.py:
- SQLite via NullPool (one connection per op, closed immediately)
- scoped_session registered in app.py teardown_appcontext for FD hygiene
"""

import logging
import os

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

# Conditionally create engine based on DB type (mirrors flow_db.py)
if DATABASE_URL and "sqlite" in DATABASE_URL:
    # SQLite: NullPool prevents connection pool exhaustion / FD accumulation
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class ScalpingSLState(Base):
    """One row per active leg whose stop-loss is being tracked by the terminal."""

    __tablename__ = "scalping_sl_state"
    __table_args__ = (UniqueConstraint("symbol", "exchange", "product", name="uq_scalping_sl_leg"),)

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(60), nullable=False)
    exchange = Column(String(10), nullable=False)  # NFO | BFO
    product = Column(String(10), nullable=False)  # MIS | NRML
    side = Column(String(4), nullable=False, default="BUY")  # BUY | SELL

    entry_price = Column(Float, nullable=False, default=0.0)
    quantity = Column(Integer, nullable=False, default=0)

    initial_sl = Column(Float, nullable=True)
    trailing_enabled = Column(Boolean, nullable=False, default=False)
    trailing_step = Column(Float, nullable=True)
    highest_price = Column(Float, nullable=True)  # peak LTP seen since entry (long legs)
    current_sl = Column(Float, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


def init_db():
    """Create the scalping SL table if it doesn't exist."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Scalping DB", logger)


def _to_dict(row: "ScalpingSLState") -> dict:
    return {
        "symbol": row.symbol,
        "exchange": row.exchange,
        "product": row.product,
        "side": row.side,
        "entry_price": row.entry_price,
        "quantity": row.quantity,
        "initial_sl": row.initial_sl,
        "trailing_enabled": row.trailing_enabled,
        "trailing_step": row.trailing_step,
        "highest_price": row.highest_price,
        "current_sl": row.current_sl,
        "is_active": row.is_active,
    }


def upsert_sl_state(data: dict) -> dict | None:
    """Create or update the SL state for a (symbol, exchange, product) leg."""
    try:
        symbol = data["symbol"]
        exchange = data["exchange"]
        product = data["product"]
    except KeyError as e:
        logger.error(f"upsert_sl_state missing key: {e}")
        return None

    try:
        row = (
            db_session.query(ScalpingSLState)
            .filter_by(symbol=symbol, exchange=exchange, product=product)
            .first()
        )
        if row is None:
            row = ScalpingSLState(symbol=symbol, exchange=exchange, product=product)
            db_session.add(row)

        for field in (
            "side",
            "entry_price",
            "quantity",
            "initial_sl",
            "trailing_enabled",
            "trailing_step",
            "highest_price",
            "current_sl",
            "is_active",
        ):
            if field in data and data[field] is not None:
                setattr(row, field, data[field])

        db_session.commit()
        return _to_dict(row)
    except Exception as e:
        logger.exception(f"Error upserting scalping SL state: {e}")
        db_session.rollback()
        return None


def get_active_sl_states() -> list[dict]:
    """Return all active SL states for rehydrating the UI on load."""
    try:
        rows = db_session.query(ScalpingSLState).filter_by(is_active=True).all()
        return [_to_dict(r) for r in rows]
    except Exception as e:
        logger.exception(f"Error fetching scalping SL states: {e}")
        return []


def delete_sl_state(symbol: str, exchange: str, product: str) -> bool:
    """Remove the SL state for a leg (called when the position is closed/cleared)."""
    try:
        deleted = (
            db_session.query(ScalpingSLState)
            .filter_by(symbol=symbol, exchange=exchange, product=product)
            .delete()
        )
        db_session.commit()
        return deleted > 0
    except Exception as e:
        logger.exception(f"Error deleting scalping SL state: {e}")
        db_session.rollback()
        return False
