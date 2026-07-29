# database/strategy_book_db.py
"""
Per-strategy position book and P&L ledger.

The broker nets positions per `(symbol, exchange, product)` and knows nothing
about which strategy opened them, so two strategies trading the same contract
are indistinguishable downstream. This module keeps a parallel book keyed by
strategy so a workflow can ask "how is *this* strategy doing?" and exit on
its own P&L rather than the account's.

Design notes:

* **Fed entirely from the event bus.** `order.placed` supplies the
  orderid -> strategy mapping (the only place the tag is known) and
  `order.update` supplies fills. Nothing in the order execution path is
  modified, so live trading is untouched by this feature.
* **Idempotent.** Order updates can arrive more than once - a broker feed and
  a postback may both report the same fill - so applied quantity is tracked
  per order and only the unseen delta is booked. This also makes partial
  fills fall out naturally.
* **Weighted-average cost**, matching how OpenAlgo and Indian brokers report
  `average_price`. A position flipping through zero realizes the closed leg
  and reopens the remainder at the fill price.
* **Realized P&L accumulates**; `today_realized` resets on the first fill of
  a new trading date, which keeps it aligned with the ~3 AM IST session
  rollover without needing a scheduler.

Unrealized P&L is deliberately *not* stored. It is a function of the last
traded price and would be stale the moment it was written; it is computed at
read time in `services/strategy_pnl_service.py`.
"""

import os
from datetime import date, datetime

from sqlalchemy import (
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

from utils.logging import get_logger

logger = get_logger(__name__)

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


class StrategyOrderTag(Base):
    """orderid -> strategy, captured when the order is placed.

    Fills arrive later carrying only an orderid, so without this the strategy
    that produced a trade cannot be recovered.
    """

    __tablename__ = "strategy_order_tags"

    id = Column(Integer, primary_key=True)
    orderid = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    strategy = Column(String(120), nullable=False, index=True)
    symbol = Column(String(64), nullable=False)
    exchange = Column(String(20), nullable=False)
    product = Column(String(20), nullable=False)
    # Cumulative quantity already booked for this order, so a repeated or
    # partial-fill update only contributes its unseen delta.
    applied_quantity = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class StrategyPosition(Base):
    """Open position and accumulated realized P&L for one strategy leg."""

    __tablename__ = "strategy_positions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "strategy", "symbol", "exchange", "product", name="uq_strategy_leg"
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    strategy = Column(String(120), nullable=False, index=True)
    symbol = Column(String(64), nullable=False, index=True)
    exchange = Column(String(20), nullable=False)
    product = Column(String(20), nullable=False)
    # Signed: positive long, negative short.
    quantity = Column(Float, nullable=False, default=0.0)
    average_price = Column(Float, nullable=False, default=0.0)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    today_realized_pnl = Column(Float, nullable=False, default=0.0)
    trade_date = Column(String(10), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


def init_strategy_book_db() -> None:
    """Create tables if absent. Safe to call repeatedly."""
    Base.metadata.create_all(bind=engine)
    logger.info("Strategy book DB initialized")


def record_order_tag(
    orderid: str, user_id: str, strategy: str, symbol: str, exchange: str, product: str
) -> bool:
    """Remember which strategy placed an order. Ignores duplicates."""
    if not orderid or not strategy:
        return False
    try:
        existing = db_session.query(StrategyOrderTag).filter_by(orderid=str(orderid)).one_or_none()
        if existing:
            return True
        db_session.add(
            StrategyOrderTag(
                orderid=str(orderid),
                user_id=user_id or "",
                strategy=strategy,
                symbol=symbol or "",
                exchange=exchange or "",
                product=product or "",
            )
        )
        db_session.commit()
        return True
    except Exception:
        db_session.rollback()
        logger.exception(f"Could not tag order {orderid} with strategy {strategy}")
        return False


def get_order_tag(orderid: str) -> StrategyOrderTag | None:
    try:
        return db_session.query(StrategyOrderTag).filter_by(orderid=str(orderid)).one_or_none()
    except Exception:
        db_session.rollback()
        logger.exception(f"Could not read order tag for {orderid}")
        return None


def apply_fill(
    orderid: str,
    filled_quantity: float,
    average_price: float,
    action: str,
) -> dict | None:
    """Book the unseen portion of a fill against its strategy's position.

    Returns a summary of the affected leg, or None when the order is unknown
    (not placed with a strategy tag) or the fill adds nothing new.
    """
    tag = get_order_tag(orderid)
    if tag is None:
        return None

    filled_quantity = abs(float(filled_quantity or 0))
    delta = filled_quantity - float(tag.applied_quantity or 0)
    if delta <= 0:
        return None  # already booked; duplicate or out-of-order event

    price = float(average_price or 0)
    signed = delta if str(action).upper() == "BUY" else -delta
    today = date.today().isoformat()

    try:
        leg = (
            db_session.query(StrategyPosition)
            .filter_by(
                user_id=tag.user_id,
                strategy=tag.strategy,
                symbol=tag.symbol,
                exchange=tag.exchange,
                product=tag.product,
            )
            .one_or_none()
        )
        if leg is None:
            leg = StrategyPosition(
                user_id=tag.user_id,
                strategy=tag.strategy,
                symbol=tag.symbol,
                exchange=tag.exchange,
                product=tag.product,
                trade_date=today,
            )
            db_session.add(leg)

        if leg.trade_date != today:
            leg.today_realized_pnl = 0.0
            leg.trade_date = today

        qty = float(leg.quantity or 0)
        avg = float(leg.average_price or 0)

        if qty == 0 or (qty > 0) == (signed > 0):
            total = abs(qty) + abs(signed)
            leg.average_price = ((avg * abs(qty)) + (price * abs(signed))) / total
            leg.quantity = qty + signed
        else:
            closing = min(abs(signed), abs(qty))
            direction = 1.0 if qty > 0 else -1.0
            realized = closing * (price - avg) * direction
            leg.realized_pnl = float(leg.realized_pnl or 0) + realized
            leg.today_realized_pnl = float(leg.today_realized_pnl or 0) + realized
            remaining = abs(signed) - closing
            leg.quantity = qty + signed
            if abs(leg.quantity) < 1e-9:
                leg.quantity = 0.0
                leg.average_price = 0.0
            elif remaining > 0:
                leg.average_price = price

        tag.applied_quantity = filled_quantity
        db_session.commit()
        return {
            "strategy": leg.strategy,
            "symbol": leg.symbol,
            "exchange": leg.exchange,
            "product": leg.product,
            "quantity": round(float(leg.quantity), 4),
            "average_price": round(float(leg.average_price), 4),
            "realized_pnl": round(float(leg.realized_pnl), 4),
            "today_realized_pnl": round(float(leg.today_realized_pnl), 4),
            "booked_quantity": round(delta, 4),
        }
    except Exception:
        db_session.rollback()
        logger.exception(f"Could not apply fill for order {orderid}")
        return None


def get_strategy_legs(user_id: str | None = None, strategy: str | None = None) -> list[dict]:
    """Every tracked leg, optionally narrowed to one user and/or strategy."""
    try:
        query = db_session.query(StrategyPosition)
        if user_id:
            query = query.filter_by(user_id=user_id)
        if strategy:
            query = query.filter_by(strategy=strategy)
        return [
            {
                "strategy": r.strategy,
                "symbol": r.symbol,
                "exchange": r.exchange,
                "product": r.product,
                "quantity": float(r.quantity or 0),
                "average_price": float(r.average_price or 0),
                "realized_pnl": float(r.realized_pnl or 0),
                "today_realized_pnl": float(r.today_realized_pnl or 0),
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in query.all()
        ]
    except Exception:
        db_session.rollback()
        logger.exception("Could not read strategy legs")
        return []


def list_strategies(user_id: str | None = None) -> list[str]:
    try:
        query = db_session.query(StrategyPosition.strategy).distinct()
        if user_id:
            query = query.filter(StrategyPosition.user_id == user_id)
        return sorted(r[0] for r in query.all())
    except Exception:
        db_session.rollback()
        logger.exception("Could not list strategies")
        return []


def reset_strategy(user_id: str, strategy: str) -> int:
    """Delete a strategy's legs. Administrative / test helper."""
    try:
        n = (
            db_session.query(StrategyPosition)
            .filter_by(user_id=user_id, strategy=strategy)
            .delete()
        )
        db_session.commit()
        return n
    except Exception:
        db_session.rollback()
        logger.exception(f"Could not reset strategy {strategy}")
        return 0
