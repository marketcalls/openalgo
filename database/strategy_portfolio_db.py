"""Persistent store for Strategy Builder portfolios.

Single-user deployment, so no user_id column — one OpenAlgo instance owns one
portfolio per fixed watchlist. Two watchlists are supported: `mytrades` (live
or intended-live trades) and `simulation` (paper scenarios). The legs array is
serialised as JSON; restoring is cheap and re-validation happens in the
builder UI.
"""

import json
import os
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL and "sqlite" in DATABASE_URL:
    # NullPool is the project-wide SQLite pattern (see CLAUDE.md).
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


WATCHLISTS = ("mytrades", "simulation")


class StrategyPortfolio(Base):
    __tablename__ = "strategy_portfolio"
    id = Column(Integer, primary_key=True)
    # 'mytrades' or 'simulation' — enforced at the service layer.
    watchlist = Column(String(20), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    underlying = Column(String(40), nullable=False)
    exchange = Column(String(20), nullable=False)
    expiry = Column(String(20), nullable=True)
    # JSON-encoded list[dict]; each entry follows the frontend StrategyLeg shape.
    legs_json = Column(Text, nullable=False, default="[]")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


def init_db():
    """Create the strategy_portfolio table if missing."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Strategy Portfolio DB", logger)


def ensure_strategy_portfolio_tables_exists():
    """Alias to match the app.py init pattern."""
    init_db()


def _serialize(row: StrategyPortfolio) -> dict[str, Any]:
    try:
        legs = json.loads(row.legs_json) if row.legs_json else []
    except json.JSONDecodeError:
        legs = []
    return {
        "id": row.id,
        "watchlist": row.watchlist,
        "name": row.name,
        "underlying": row.underlying,
        "exchange": row.exchange,
        "expiry": row.expiry,
        "legs": legs,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_portfolio(watchlist: str | None = None) -> list[dict[str, Any]]:
    """Return all saved strategies, optionally filtered by watchlist."""
    try:
        query = StrategyPortfolio.query
        if watchlist:
            query = query.filter_by(watchlist=watchlist)
        rows = query.order_by(StrategyPortfolio.updated_at.desc()).all()
        return [_serialize(r) for r in rows]
    except Exception as e:
        logger.exception(f"[StrategyPortfolio] list_portfolio failed: {e}")
        return []


def get_portfolio_entry(entry_id: int) -> dict[str, Any] | None:
    try:
        row = StrategyPortfolio.query.filter_by(id=entry_id).first()
        return _serialize(row) if row else None
    except Exception as e:
        logger.exception(f"[StrategyPortfolio] get_portfolio_entry failed: {e}")
        return None


def save_portfolio_entry(
    *,
    name: str,
    watchlist: str,
    underlying: str,
    exchange: str,
    expiry: str | None,
    legs: list[dict[str, Any]],
    notes: str | None = None,
    entry_id: int | None = None,
) -> dict[str, Any] | None:
    """Create or update a portfolio entry.

    Returns the serialised row on success, None on failure.
    """
    if watchlist not in WATCHLISTS:
        logger.warning(f"[StrategyPortfolio] invalid watchlist: {watchlist}")
        return None

    try:
        legs_json = json.dumps(legs, default=str)
        if entry_id is not None:
            row = StrategyPortfolio.query.filter_by(id=entry_id).first()
            if not row:
                return None
            row.name = name
            row.watchlist = watchlist
            row.underlying = underlying
            row.exchange = exchange
            row.expiry = expiry
            row.legs_json = legs_json
            row.notes = notes
        else:
            row = StrategyPortfolio(
                name=name,
                watchlist=watchlist,
                underlying=underlying,
                exchange=exchange,
                expiry=expiry,
                legs_json=legs_json,
                notes=notes,
            )
            db_session.add(row)
        db_session.commit()
        return _serialize(row)
    except Exception as e:
        logger.exception(f"[StrategyPortfolio] save_portfolio_entry failed: {e}")
        db_session.rollback()
        return None


def delete_portfolio_entry(entry_id: int) -> bool:
    try:
        row = StrategyPortfolio.query.filter_by(id=entry_id).first()
        if not row:
            return False
        db_session.delete(row)
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"[StrategyPortfolio] delete_portfolio_entry failed: {e}")
        db_session.rollback()
        return False
