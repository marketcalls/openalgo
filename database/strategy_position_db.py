"""
Strategy Position Tracking Database Models

Models for strategy-level order tracking, position management,
trade audit trail, daily PnL snapshots, and position groups.

All tables stored in db/openalgo.db alongside existing strategy tables.
Uses WAL mode for safe concurrent access from risk engine, poller, and webhooks.
"""

import logging
import os
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

# Conditionally create engine based on DB type
if DATABASE_URL and "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)


# Set WAL mode for concurrent access (risk engine + poller + webhooks)
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Configure SQLite for safe multi-threaded access."""
    if DATABASE_URL and "sqlite" in DATABASE_URL:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA wal_autocheckpoint=1000")
        cursor.close()


db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class StrategyOrder(Base):
    """Tracks every order placed by a strategy."""

    __tablename__ = "strategy_order"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, nullable=False)
    strategy_type = Column(String(10), nullable=False)  # 'webhook' or 'chartink'
    user_id = Column(String(255), nullable=False)
    orderid = Column(String(50), nullable=False)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(10), nullable=False)
    action = Column(String(4), nullable=False)  # BUY or SELL
    quantity = Column(Integer, nullable=False)
    product_type = Column(String(10), nullable=False)  # MIS, CNC, NRML
    price_type = Column(String(10), nullable=False)  # MARKET, LIMIT, SL, SL-M
    price = Column(Float, default=0)
    trigger_price = Column(Float, default=0)
    order_status = Column(String(20), nullable=False)  # pending, open, complete, rejected, cancelled
    average_price = Column(Float, default=0)
    filled_quantity = Column(Integer, default=0)
    is_entry = Column(Boolean, default=True)
    exit_reason = Column(String(20))  # NULL for entries; stoploss/target/trailstop/manual/squareoff
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class StrategyPosition(Base):
    """Live + historical positions with risk columns.

    Each entry creates a new row. Active positions: WHERE quantity > 0.
    No UNIQUE constraint — allows re-entry after exit.
    """

    __tablename__ = "strategy_position"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, nullable=False)
    strategy_type = Column(String(10), nullable=False)
    user_id = Column(String(255), nullable=False)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(10), nullable=False)
    product_type = Column(String(10), nullable=False)
    action = Column(String(4), nullable=False)  # BUY (long) or SELL (short)
    quantity = Column(Integer, nullable=False)  # always positive; direction from action
    intended_quantity = Column(Integer, nullable=False)  # original intended qty
    average_entry_price = Column(Float, nullable=False)
    ltp = Column(Float, default=0)
    unrealized_pnl = Column(Float, default=0)
    unrealized_pnl_pct = Column(Float, default=0)
    peak_price = Column(Float, default=0)  # highest (long) or lowest (short)
    position_state = Column(String(15), default="active")  # active, exiting, pending_entry
    # Risk parameters (resolved effective values)
    stoploss_type = Column(String(10))
    stoploss_value = Column(Float)
    stoploss_price = Column(Float)
    target_type = Column(String(10))
    target_value = Column(Float)
    target_price = Column(Float)
    trailstop_type = Column(String(10))
    trailstop_value = Column(Float)
    trailstop_price = Column(Float)
    breakeven_type = Column(String(10))
    breakeven_threshold = Column(Float)
    breakeven_activated = Column(Boolean, default=False)
    tick_size = Column(Float, default=0.05)
    position_group_id = Column(String(36))  # UUID for combined P&L mode
    risk_mode = Column(String(10))  # 'per_leg' or 'combined'
    realized_pnl = Column(Float, default=0)
    exit_reason = Column(String(20))
    exit_detail = Column(String(30))
    exit_price = Column(Float)
    closed_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class StrategyTrade(Base):
    """Every filled trade for audit trail and PnL calculation."""

    __tablename__ = "strategy_trade"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, nullable=False)
    strategy_type = Column(String(10), nullable=False)
    user_id = Column(String(255), nullable=False)
    orderid = Column(String(50), nullable=False)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(10), nullable=False)
    action = Column(String(4), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)  # average_price from OrderStatus
    trade_type = Column(String(5), nullable=False)  # 'entry' or 'exit'
    exit_reason = Column(String(20))  # NULL for entries
    pnl = Column(Float, default=0)  # per-trade realized PnL (exit trades only)
    created_at = Column(DateTime, default=func.now())


class StrategyDailyPnL(Base):
    """End-of-day snapshots for analytics."""

    __tablename__ = "strategy_daily_pnl"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, nullable=False)
    strategy_type = Column(String(10), nullable=False)
    user_id = Column(String(255), nullable=False)
    date = Column(DateTime, nullable=False)
    realized_pnl = Column(Float, default=0)
    unrealized_pnl = Column(Float, default=0)
    total_pnl = Column(Float, default=0)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    gross_profit = Column(Float, default=0)
    gross_loss = Column(Float, default=0)
    max_trade_profit = Column(Float, default=0)
    max_trade_loss = Column(Float, default=0)
    cumulative_pnl = Column(Float, default=0)
    peak_cumulative_pnl = Column(Float, default=0)
    drawdown = Column(Float, default=0)
    drawdown_pct = Column(Float, default=0)
    max_drawdown = Column(Float, default=0)
    max_drawdown_pct = Column(Float, default=0)
    created_at = Column(DateTime, default=func.now())


class StrategyPositionGroup(Base):
    """Group-level state for combined P&L mode."""

    __tablename__ = "strategy_position_group"

    id = Column(String(36), primary_key=True)  # UUID
    strategy_id = Column(Integer, nullable=False)
    strategy_type = Column(String(10), nullable=False)
    user_id = Column(String(255), nullable=False)
    symbol_mapping_id = Column(Integer, nullable=False)
    expected_legs = Column(Integer, nullable=False)
    filled_legs = Column(Integer, default=0)
    group_status = Column(String(15), default="filling")  # filling, active, exiting, closed, failed_exit
    combined_peak_pnl = Column(Float, default=0)
    combined_pnl = Column(Float, default=0)
    # Options spread risk fields (AFL-style TSL)
    entry_value = Column(Float, default=0)  # abs(Σ signed_entry_price × qty) — capital at risk
    initial_stop = Column(Float)  # TSL initial level: -entry_value × trail%/100 or -trail_value
    current_stop = Column(Float)  # Ratcheting stop: only moves UP, never down
    exit_triggered = Column(Boolean, default=False)  # Duplicate exit prevention
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


# ---------- Database Initialization ----------


def init_db():
    """Initialize the database (safety net alongside migration script)."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Strategy Position DB", logger)


# ---------- CRUD Functions: StrategyOrder ----------


def create_strategy_order(
    strategy_id,
    strategy_type,
    user_id,
    orderid,
    symbol,
    exchange,
    action,
    quantity,
    product_type,
    price_type,
    order_status="pending",
    price=0,
    trigger_price=0,
    is_entry=True,
    exit_reason=None,
):
    """Create a new strategy order record."""
    try:
        order = StrategyOrder(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            user_id=user_id,
            orderid=orderid,
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            product_type=product_type,
            price_type=price_type,
            order_status=order_status,
            price=price,
            trigger_price=trigger_price,
            is_entry=is_entry,
            exit_reason=exit_reason,
        )
        db_session.add(order)
        db_session.commit()
        return order
    except Exception as e:
        logger.exception(f"Error creating strategy order: {e}")
        db_session.rollback()
        return None


def update_order_status(orderid, status, average_price=None, filled_quantity=None):
    """Update an order's status and optional fill data."""
    try:
        order = StrategyOrder.query.filter_by(orderid=orderid).first()
        if not order:
            return None
        order.order_status = status
        if average_price is not None:
            order.average_price = average_price
        if filled_quantity is not None:
            order.filled_quantity = filled_quantity
        order.updated_at = datetime.utcnow()
        db_session.commit()
        return order
    except Exception as e:
        logger.exception(f"Error updating order status for {orderid}: {e}")
        db_session.rollback()
        return None


def get_pending_orders():
    """Get all orders with pending or open status (for restart recovery)."""
    try:
        return StrategyOrder.query.filter(
            StrategyOrder.order_status.in_(["pending", "open"])
        ).all()
    except Exception as e:
        logger.exception(f"Error getting pending orders: {e}")
        return []


def get_strategy_orders(strategy_id, strategy_type):
    """Get all orders for a strategy."""
    try:
        return (
            StrategyOrder.query.filter_by(strategy_id=strategy_id, strategy_type=strategy_type)
            .order_by(StrategyOrder.created_at.desc())
            .all()
        )
    except Exception as e:
        logger.exception(f"Error getting strategy orders: {e}")
        return []


# ---------- CRUD Functions: StrategyPosition ----------


def create_strategy_position(
    strategy_id,
    strategy_type,
    user_id,
    symbol,
    exchange,
    product_type,
    action,
    quantity,
    intended_quantity,
    average_entry_price,
    position_state="active",
    stoploss_type=None,
    stoploss_value=None,
    stoploss_price=None,
    target_type=None,
    target_value=None,
    target_price=None,
    trailstop_type=None,
    trailstop_value=None,
    trailstop_price=None,
    breakeven_type=None,
    breakeven_threshold=None,
    tick_size=0.05,
    position_group_id=None,
    risk_mode=None,
):
    """Create a new strategy position."""
    try:
        position = StrategyPosition(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            user_id=user_id,
            symbol=symbol,
            exchange=exchange,
            product_type=product_type,
            action=action,
            quantity=quantity,
            intended_quantity=intended_quantity,
            average_entry_price=average_entry_price,
            ltp=average_entry_price,
            peak_price=average_entry_price,
            position_state=position_state,
            stoploss_type=stoploss_type,
            stoploss_value=stoploss_value,
            stoploss_price=stoploss_price,
            target_type=target_type,
            target_value=target_value,
            target_price=target_price,
            trailstop_type=trailstop_type,
            trailstop_value=trailstop_value,
            trailstop_price=trailstop_price,
            breakeven_type=breakeven_type,
            breakeven_threshold=breakeven_threshold,
            tick_size=tick_size,
            position_group_id=position_group_id,
            risk_mode=risk_mode,
        )
        db_session.add(position)
        db_session.commit()
        return position
    except Exception as e:
        logger.exception(f"Error creating strategy position: {e}")
        db_session.rollback()
        return None


def get_active_positions(strategy_id=None, symbol=None, exchange=None):
    """Get active positions (quantity > 0) with optional filters."""
    try:
        query = StrategyPosition.query.filter(StrategyPosition.quantity > 0)
        if strategy_id is not None:
            query = query.filter_by(strategy_id=strategy_id)
        if symbol is not None:
            query = query.filter_by(symbol=symbol)
        if exchange is not None:
            query = query.filter_by(exchange=exchange)
        return query.all()
    except Exception as e:
        logger.exception(f"Error getting active positions: {e}")
        return []


def get_active_positions_for_risk_engine():
    """Get all active positions where the parent strategy has risk_monitoring = 'active'.

    Joins with the strategies table (via strategy_db) to check risk_monitoring status.
    """
    try:
        return StrategyPosition.query.filter(
            StrategyPosition.quantity > 0,
            StrategyPosition.position_state == "active",
        ).all()
    except Exception as e:
        logger.exception(f"Error getting risk engine positions: {e}")
        return []


def update_position(position_id, **kwargs):
    """Update a position with arbitrary fields."""
    try:
        position = StrategyPosition.query.get(position_id)
        if not position:
            return None
        for key, value in kwargs.items():
            if hasattr(position, key):
                setattr(position, key, value)
        position.updated_at = datetime.utcnow()
        db_session.commit()
        return position
    except Exception as e:
        logger.exception(f"Error updating position {position_id}: {e}")
        db_session.rollback()
        return None


def get_position(position_id):
    """Get a position by ID."""
    try:
        return StrategyPosition.query.get(position_id)
    except Exception as e:
        logger.exception(f"Error getting position {position_id}: {e}")
        return None


def get_strategy_positions(strategy_id, strategy_type, include_closed=False):
    """Get all positions for a strategy."""
    try:
        query = StrategyPosition.query.filter_by(
            strategy_id=strategy_id, strategy_type=strategy_type
        )
        if not include_closed:
            query = query.filter(StrategyPosition.quantity > 0)
        return query.order_by(StrategyPosition.created_at.desc()).all()
    except Exception as e:
        logger.exception(f"Error getting strategy positions: {e}")
        return []


def get_active_position_for_symbol(strategy_id, strategy_type, symbol, exchange, product_type):
    """Get the active position for a specific symbol in a strategy (if any)."""
    try:
        return StrategyPosition.query.filter(
            StrategyPosition.strategy_id == strategy_id,
            StrategyPosition.strategy_type == strategy_type,
            StrategyPosition.symbol == symbol,
            StrategyPosition.exchange == exchange,
            StrategyPosition.product_type == product_type,
            StrategyPosition.quantity > 0,
        ).first()
    except Exception as e:
        logger.exception(f"Error getting active position for symbol: {e}")
        return None


def delete_position(position_id):
    """Delete a closed position record (only if quantity == 0)."""
    try:
        position = StrategyPosition.query.get(position_id)
        if not position:
            return False, "Position not found"
        if position.quantity > 0:
            return False, "Close position before deleting"
        db_session.delete(position)
        db_session.commit()
        return True, "Position record deleted"
    except Exception as e:
        logger.exception(f"Error deleting position {position_id}: {e}")
        db_session.rollback()
        return False, str(e)


# ---------- CRUD Functions: StrategyTrade ----------


def create_strategy_trade(
    strategy_id,
    strategy_type,
    user_id,
    orderid,
    symbol,
    exchange,
    action,
    quantity,
    price,
    trade_type,
    exit_reason=None,
    pnl=0,
):
    """Create a strategy trade record."""
    try:
        trade = StrategyTrade(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            user_id=user_id,
            orderid=orderid,
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            price=price,
            trade_type=trade_type,
            exit_reason=exit_reason,
            pnl=pnl,
        )
        db_session.add(trade)
        db_session.commit()
        return trade
    except Exception as e:
        logger.exception(f"Error creating strategy trade: {e}")
        db_session.rollback()
        return None


def get_strategy_trades(strategy_id, strategy_type):
    """Get all trades for a strategy."""
    try:
        return (
            StrategyTrade.query.filter_by(strategy_id=strategy_id, strategy_type=strategy_type)
            .order_by(StrategyTrade.created_at.desc())
            .all()
        )
    except Exception as e:
        logger.exception(f"Error getting strategy trades: {e}")
        return []


# ---------- CRUD Functions: StrategyDailyPnL ----------


def upsert_daily_pnl(strategy_id, strategy_type, user_id, date, **kwargs):
    """Insert or update a daily PnL snapshot."""
    try:
        existing = StrategyDailyPnL.query.filter_by(
            strategy_id=strategy_id, strategy_type=strategy_type, date=date
        ).first()
        if existing:
            for key, value in kwargs.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            db_session.commit()
            return existing
        else:
            snapshot = StrategyDailyPnL(
                strategy_id=strategy_id,
                strategy_type=strategy_type,
                user_id=user_id,
                date=date,
                **kwargs,
            )
            db_session.add(snapshot)
            db_session.commit()
            return snapshot
    except Exception as e:
        logger.exception(f"Error upserting daily PnL: {e}")
        db_session.rollback()
        return None


def get_daily_pnl(strategy_id, strategy_type):
    """Get all daily PnL records for a strategy."""
    try:
        return (
            StrategyDailyPnL.query.filter_by(
                strategy_id=strategy_id, strategy_type=strategy_type
            )
            .order_by(StrategyDailyPnL.date.asc())
            .all()
        )
    except Exception as e:
        logger.exception(f"Error getting daily PnL: {e}")
        return []


# ---------- CRUD Functions: StrategyPositionGroup ----------


def create_position_group(
    group_id, strategy_id, strategy_type, user_id, symbol_mapping_id, expected_legs
):
    """Create a new position group for combined P&L mode."""
    try:
        group = StrategyPositionGroup(
            id=group_id,
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            user_id=user_id,
            symbol_mapping_id=symbol_mapping_id,
            expected_legs=expected_legs,
        )
        db_session.add(group)
        db_session.commit()
        return group
    except Exception as e:
        logger.exception(f"Error creating position group: {e}")
        db_session.rollback()
        return None


def get_active_position_groups():
    """Get all active position groups (not closed/failed)."""
    try:
        return StrategyPositionGroup.query.filter(
            StrategyPositionGroup.group_status.in_(["filling", "active"])
        ).all()
    except Exception as e:
        logger.exception(f"Error getting active position groups: {e}")
        return []


def get_positions_by_group(group_id):
    """Get all positions belonging to a group."""
    try:
        return StrategyPosition.query.filter_by(position_group_id=group_id).all()
    except Exception as e:
        logger.exception(f"Error getting positions by group {group_id}: {e}")
        return []


def update_position_group(group_id, **kwargs):
    """Update a position group."""
    try:
        group = StrategyPositionGroup.query.get(group_id)
        if not group:
            return None
        for key, value in kwargs.items():
            if hasattr(group, key):
                setattr(group, key, value)
        group.updated_at = datetime.utcnow()
        db_session.commit()
        return group
    except Exception as e:
        logger.exception(f"Error updating position group {group_id}: {e}")
        db_session.rollback()
        return None
