import logging
import os
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
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

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


# ─── Models ────────────────────────────────────────────────────────────────


class StrategyOrder(Base):
    """Tracks every order placed by a strategy (PRD §5.3)"""

    __tablename__ = "strategy_order"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, nullable=False)
    strategy_type = Column(String(10), nullable=False)  # 'webhook' or 'chartink'
    user_id = Column(String(255), nullable=False)
    orderid = Column(String(50), nullable=False)  # broker order ID
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(10), nullable=False)
    action = Column(String(4), nullable=False)  # BUY or SELL
    quantity = Column(Integer, nullable=False)
    product_type = Column(String(10), nullable=False)  # MIS, CNC, NRML
    price_type = Column(String(10), nullable=False)  # MARKET, LIMIT, SL, SL-M
    price = Column(Float, default=0)
    trigger_price = Column(Float, default=0)
    order_status = Column(String(20), nullable=False)  # pending, open, complete, rejected, cancelled
    average_price = Column(Float, default=0)  # fill price from OrderStatus
    filled_quantity = Column(Integer, default=0)
    is_entry = Column(Boolean, default=True)
    exit_reason = Column(String(20))  # NULL for entries; stoploss/target/trailstop/manual/squareoff
    position_id = Column(Integer)  # link back to StrategyPosition
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class StrategyPosition(Base):
    """Per-entry position row — active when quantity > 0 (PRD §5.4)"""

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
    ltp = Column(Float, default=0)  # last traded price (live updated)
    unrealized_pnl = Column(Float, default=0)
    unrealized_pnl_pct = Column(Float, default=0)
    peak_price = Column(Float, default=0)  # highest (long) or lowest (short)
    position_state = Column(String(15), default="pending_entry")  # pending_entry, active, exiting, closed
    # Resolved risk parameters
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
    # Multi-leg grouping
    position_group_id = Column(String(36))  # UUID, links legs in combined P&L mode
    risk_mode = Column(String(10))  # 'per_leg' or 'combined'
    realized_pnl = Column(Float, default=0)  # accumulated from partial exits
    exit_reason = Column(String(20))  # stoploss/target/trailstop/breakeven_sl/manual/squareoff
    exit_detail = Column(String(30))  # granular: leg_sl/combined_sl/manual etc.
    exit_price = Column(Float)
    closed_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "idx_strategy_position_active",
            "strategy_id",
            "strategy_type",
            "symbol",
            "exchange",
            "product_type",
        ),
        Index("idx_strategy_position_state", "position_state"),
        Index("idx_strategy_position_group", "position_group_id"),
    )


class StrategyTrade(Base):
    """Every filled trade for audit trail and PnL calculation (PRD §5.5)"""

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
    position_id = Column(Integer)  # link back to StrategyPosition
    created_at = Column(DateTime, default=func.now())


class StrategyDailyPnL(Base):
    """End-of-day snapshots for analytics (PRD §5.6)"""

    __tablename__ = "strategy_daily_pnl"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, nullable=False)
    strategy_type = Column(String(10), nullable=False)
    user_id = Column(String(255), nullable=False)
    date = Column(Date, nullable=False)
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

    __table_args__ = (
        UniqueConstraint("strategy_id", "strategy_type", "date", name="uq_daily_pnl"),
    )


class StrategyPositionGroup(Base):
    """Group-level state for combined P&L mode (PRD §5.7)"""

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
    entry_value = Column(Float, default=0)
    initial_stop = Column(Float)
    current_stop = Column(Float)
    exit_triggered = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class AlertLog(Base):
    """Centralized log for all alert deliveries (PRD §5.8)"""

    __tablename__ = "alert_log"

    id = Column(Integer, primary_key=True)
    alert_id = Column(String(50), nullable=False)
    alert_type = Column(String(20), nullable=False)  # strategy_risk, circuit_breaker, order_status, etc.
    symbol = Column(String(50))
    exchange = Column(String(10))
    strategy_id = Column(Integer)
    strategy_type = Column(String(10))
    trigger_reason = Column(String(30))
    trigger_price = Column(Float)
    ltp_at_trigger = Column(Float)
    pnl = Column(Float)
    message = Column(Text)
    channels_attempted = Column(Text)  # JSON
    channels_delivered = Column(Text)  # JSON
    errors = Column(Text)  # JSON
    priority = Column(String(10), default="normal")
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index("idx_alert_log_symbol", "symbol", "exchange"),
        Index("idx_alert_log_strategy", "strategy_id", "strategy_type"),
        Index("idx_alert_log_type", "alert_type", "created_at"),
    )


# ─── Database Initialization ──────────────────────────────────────────────


def init_db():
    """Initialize the database tables"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Strategy Position DB", logger)


# ─── StrategyOrder CRUD ───────────────────────────────────────────────────


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
    price_type="MARKET",
    price=0,
    trigger_price=0,
    is_entry=True,
    exit_reason=None,
    position_id=None,
):
    """Create a new strategy order record"""
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
            price=price,
            trigger_price=trigger_price,
            order_status="pending",
            is_entry=is_entry,
            exit_reason=exit_reason,
            position_id=position_id,
        )
        db_session.add(order)
        db_session.commit()
        return order
    except Exception as e:
        logger.exception(f"Error creating strategy order: {e}")
        db_session.rollback()
        return None


def update_order_status(orderid, status, average_price=None, filled_quantity=None):
    """Update order status after broker callback"""
    try:
        order = StrategyOrder.query.filter_by(orderid=orderid).first()
        if not order:
            return None
        order.order_status = status
        if average_price is not None:
            order.average_price = average_price
        if filled_quantity is not None:
            order.filled_quantity = filled_quantity
        db_session.commit()
        return order
    except Exception as e:
        logger.exception(f"Error updating order status for {orderid}: {e}")
        db_session.rollback()
        return None


def get_strategy_orders(strategy_id, strategy_type, limit=50, offset=0):
    """Get orders for a strategy with pagination"""
    try:
        return (
            StrategyOrder.query.filter_by(strategy_id=strategy_id, strategy_type=strategy_type)
            .order_by(StrategyOrder.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
    except Exception as e:
        logger.exception(f"Error getting strategy orders: {e}")
        return []


def get_pending_orders(strategy_id=None, strategy_type=None):
    """Get orders in pending/open status (for polling)"""
    try:
        query = StrategyOrder.query.filter(StrategyOrder.order_status.in_(["pending", "open"]))
        if strategy_id is not None:
            query = query.filter_by(strategy_id=strategy_id)
        if strategy_type is not None:
            query = query.filter_by(strategy_type=strategy_type)
        return query.all()
    except Exception as e:
        logger.exception(f"Error getting pending orders: {e}")
        return []


# ─── StrategyPosition CRUD ────────────────────────────────────────────────


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
    position_state="pending_entry",
):
    """Create a new strategy position"""
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


def get_active_positions(strategy_id=None, strategy_type=None, user_id=None):
    """Get active positions (quantity > 0)"""
    try:
        query = StrategyPosition.query.filter(StrategyPosition.quantity > 0)
        if strategy_id is not None:
            query = query.filter_by(strategy_id=strategy_id)
        if strategy_type is not None:
            query = query.filter_by(strategy_type=strategy_type)
        if user_id is not None:
            query = query.filter_by(user_id=user_id)
        return query.order_by(StrategyPosition.created_at.desc()).all()
    except Exception as e:
        logger.exception(f"Error getting active positions: {e}")
        return []


def get_position(position_id):
    """Get a single position by ID"""
    try:
        return StrategyPosition.query.get(position_id)
    except Exception as e:
        logger.exception(f"Error getting position {position_id}: {e}")
        return None


def update_position_state(position_id, state):
    """Update position state (pending_entry, active, exiting, closed)"""
    try:
        position = StrategyPosition.query.get(position_id)
        if not position:
            return None
        position.position_state = state
        if state == "closed":
            position.closed_at = datetime.utcnow()
        db_session.commit()
        return position
    except Exception as e:
        logger.exception(f"Error updating position state: {e}")
        db_session.rollback()
        return None


def update_position_ltp(position_id, ltp, unrealized_pnl=None, unrealized_pnl_pct=None, peak_price=None):
    """Update position with live market data"""
    try:
        position = StrategyPosition.query.get(position_id)
        if not position:
            return None
        position.ltp = ltp
        if unrealized_pnl is not None:
            position.unrealized_pnl = unrealized_pnl
        if unrealized_pnl_pct is not None:
            position.unrealized_pnl_pct = unrealized_pnl_pct
        if peak_price is not None:
            position.peak_price = peak_price
        db_session.commit()
        return position
    except Exception as e:
        logger.exception(f"Error updating position LTP: {e}")
        db_session.rollback()
        return None


def close_position(position_id, exit_reason, exit_detail=None, exit_price=None, realized_pnl=None):
    """Close a position (set quantity to 0)"""
    try:
        position = StrategyPosition.query.get(position_id)
        if not position:
            return None
        position.quantity = 0
        position.position_state = "closed"
        position.exit_reason = exit_reason
        position.exit_detail = exit_detail
        position.exit_price = exit_price
        position.closed_at = datetime.utcnow()
        if realized_pnl is not None:
            position.realized_pnl = realized_pnl
        db_session.commit()
        return position
    except Exception as e:
        logger.exception(f"Error closing position {position_id}: {e}")
        db_session.rollback()
        return None


def get_all_positions(strategy_id, strategy_type, include_closed=False, limit=50, offset=0):
    """Get all positions for a strategy (active and optionally closed)"""
    try:
        query = StrategyPosition.query.filter_by(strategy_id=strategy_id, strategy_type=strategy_type)
        if not include_closed:
            query = query.filter(StrategyPosition.quantity > 0)
        return query.order_by(StrategyPosition.created_at.desc()).offset(offset).limit(limit).all()
    except Exception as e:
        logger.exception(f"Error getting positions: {e}")
        return []


def delete_closed_position(position_id):
    """Delete a closed position record"""
    try:
        position = StrategyPosition.query.get(position_id)
        if not position or position.quantity > 0:
            return False
        db_session.delete(position)
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error deleting position {position_id}: {e}")
        db_session.rollback()
        return False


# ─── StrategyTrade CRUD ───────────────────────────────────────────────────


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
    position_id=None,
):
    """Create a trade record"""
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
            position_id=position_id,
        )
        db_session.add(trade)
        db_session.commit()
        return trade
    except Exception as e:
        logger.exception(f"Error creating strategy trade: {e}")
        db_session.rollback()
        return None


def get_strategy_trades(strategy_id, strategy_type, limit=50, offset=0):
    """Get trades for a strategy with pagination"""
    try:
        return (
            StrategyTrade.query.filter_by(strategy_id=strategy_id, strategy_type=strategy_type)
            .order_by(StrategyTrade.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
    except Exception as e:
        logger.exception(f"Error getting strategy trades: {e}")
        return []


# ─── StrategyDailyPnL CRUD ────────────────────────────────────────────────


def upsert_daily_pnl(strategy_id, strategy_type, user_id, pnl_date, **kwargs):
    """Create or update daily PnL snapshot"""
    try:
        existing = StrategyDailyPnL.query.filter_by(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            date=pnl_date,
        ).first()

        if existing:
            for key, value in kwargs.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            db_session.commit()
            return existing

        daily_pnl = StrategyDailyPnL(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            user_id=user_id,
            date=pnl_date,
            **kwargs,
        )
        db_session.add(daily_pnl)
        db_session.commit()
        return daily_pnl
    except Exception as e:
        logger.exception(f"Error upserting daily PnL: {e}")
        db_session.rollback()
        return None


def get_daily_pnl_range(strategy_id, strategy_type, start_date=None, end_date=None):
    """Get daily PnL records for a date range"""
    try:
        query = StrategyDailyPnL.query.filter_by(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
        )
        if start_date:
            query = query.filter(StrategyDailyPnL.date >= start_date)
        if end_date:
            query = query.filter(StrategyDailyPnL.date <= end_date)
        return query.order_by(StrategyDailyPnL.date.asc()).all()
    except Exception as e:
        logger.exception(f"Error getting daily PnL range: {e}")
        return []


# ─── StrategyPositionGroup CRUD ───────────────────────────────────────────


def create_position_group(
    group_id,
    strategy_id,
    strategy_type,
    user_id,
    symbol_mapping_id,
    expected_legs,
):
    """Create a new position group for combined P&L mode"""
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


def get_position_group(group_id):
    """Get a position group by ID"""
    try:
        return StrategyPositionGroup.query.get(group_id)
    except Exception as e:
        logger.exception(f"Error getting position group {group_id}: {e}")
        return None


def update_group_status(group_id, **kwargs):
    """Update position group fields"""
    try:
        group = StrategyPositionGroup.query.get(group_id)
        if not group:
            return None
        for key, value in kwargs.items():
            if hasattr(group, key):
                setattr(group, key, value)
        db_session.commit()
        return group
    except Exception as e:
        logger.exception(f"Error updating position group {group_id}: {e}")
        db_session.rollback()
        return None


def get_active_groups(strategy_id=None, strategy_type=None):
    """Get groups that are not closed"""
    try:
        query = StrategyPositionGroup.query.filter(
            StrategyPositionGroup.group_status.notin_(["closed"])
        )
        if strategy_id is not None:
            query = query.filter_by(strategy_id=strategy_id)
        if strategy_type is not None:
            query = query.filter_by(strategy_type=strategy_type)
        return query.all()
    except Exception as e:
        logger.exception(f"Error getting active groups: {e}")
        return []


# ─── AlertLog CRUD ────────────────────────────────────────────────────────


def create_alert_log(
    alert_id,
    alert_type,
    message,
    symbol=None,
    exchange=None,
    strategy_id=None,
    strategy_type=None,
    trigger_reason=None,
    trigger_price=None,
    ltp_at_trigger=None,
    pnl=None,
    channels_attempted=None,
    channels_delivered=None,
    errors=None,
    priority="normal",
):
    """Create an alert log entry"""
    try:
        alert = AlertLog(
            alert_id=alert_id,
            alert_type=alert_type,
            symbol=symbol,
            exchange=exchange,
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            trigger_reason=trigger_reason,
            trigger_price=trigger_price,
            ltp_at_trigger=ltp_at_trigger,
            pnl=pnl,
            message=message,
            channels_attempted=channels_attempted,
            channels_delivered=channels_delivered,
            errors=errors,
            priority=priority,
        )
        db_session.add(alert)
        db_session.commit()
        return alert
    except Exception as e:
        logger.exception(f"Error creating alert log: {e}")
        db_session.rollback()
        return None


def get_alert_logs(strategy_id=None, strategy_type=None, limit=20, offset=0):
    """Get alert log entries with pagination"""
    try:
        query = AlertLog.query
        if strategy_id is not None:
            query = query.filter_by(strategy_id=strategy_id)
        if strategy_type is not None:
            query = query.filter_by(strategy_type=strategy_type)
        return query.order_by(AlertLog.created_at.desc()).offset(offset).limit(limit).all()
    except Exception as e:
        logger.exception(f"Error getting alert logs: {e}")
        return []
