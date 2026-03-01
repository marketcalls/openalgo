# database/backtest_db.py
"""
Backtest Database Module

Separate SQLite database for backtesting engine results.
Stores backtest run configurations, metrics, trades, and equity curves.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import (
    DECIMAL,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Load environment variables
load_dotenv()

# Backtest database URL - separate database for isolation
BACKTEST_DATABASE_URL = os.getenv("BACKTEST_DATABASE_URL", "sqlite:///db/backtest.db")

# Create engine with NullPool for SQLite thread safety
if BACKTEST_DATABASE_URL and "sqlite" in BACKTEST_DATABASE_URL:
    engine = create_engine(
        BACKTEST_DATABASE_URL,
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        BACKTEST_DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_timeout=10,
    )

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class BacktestRun(Base):
    """Backtest run configuration and results."""

    __tablename__ = "backtest_runs"

    id = Column(String(50), primary_key=True)  # BT-YYYYMMDD-HHMMSS-{uuid8}
    user_id = Column(String(50), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    strategy_id = Column(String(50), nullable=True)  # link to python_strategy
    strategy_code = Column(Text, nullable=False)  # snapshot of code at run time

    # Configuration
    symbols = Column(Text, nullable=False)  # JSON array
    start_date = Column(String(10), nullable=False)  # YYYY-MM-DD
    end_date = Column(String(10), nullable=False)
    interval = Column(String(10), nullable=False)  # 1m, 5m, 15m, 1h, D
    initial_capital = Column(DECIMAL(15, 2), nullable=False)
    slippage_pct = Column(DECIMAL(6, 4), nullable=False, default=0.05)
    commission_per_order = Column(DECIMAL(10, 2), nullable=False, default=20.00)
    commission_pct = Column(DECIMAL(6, 4), nullable=False, default=0.00)
    data_source = Column(String(10), nullable=False, default="db")

    # Status
    status = Column(String(20), nullable=False, default="pending", index=True)
    # pending / running / completed / failed / cancelled

    # Results - populated after completion
    final_capital = Column(DECIMAL(15, 2), nullable=True)
    total_return_pct = Column(DECIMAL(10, 4), nullable=True)
    cagr = Column(DECIMAL(10, 4), nullable=True)
    sharpe_ratio = Column(DECIMAL(10, 4), nullable=True)
    sortino_ratio = Column(DECIMAL(10, 4), nullable=True)
    max_drawdown_pct = Column(DECIMAL(10, 4), nullable=True)
    calmar_ratio = Column(DECIMAL(10, 4), nullable=True)
    win_rate = Column(DECIMAL(10, 4), nullable=True)
    profit_factor = Column(DECIMAL(10, 4), nullable=True)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    avg_win = Column(DECIMAL(15, 2), nullable=True)
    avg_loss = Column(DECIMAL(15, 2), nullable=True)
    max_win = Column(DECIMAL(15, 2), nullable=True)
    max_loss = Column(DECIMAL(15, 2), nullable=True)
    expectancy = Column(DECIMAL(15, 2), nullable=True)
    avg_holding_bars = Column(Integer, nullable=True)
    total_commission = Column(DECIMAL(15, 2), nullable=True)
    total_slippage = Column(DECIMAL(15, 2), nullable=True)

    # Serialized large data
    equity_curve_json = Column(Text, nullable=True)
    monthly_returns_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_backtest_user_status", "user_id", "status"),
        Index("idx_backtest_created", "created_at"),
    )


class BacktestTrade(Base):
    """Individual trade within a backtest run."""

    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    backtest_id = Column(
        String(50),
        ForeignKey("backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trade_num = Column(Integer, nullable=False)

    symbol = Column(String(50), nullable=False)
    exchange = Column(String(20), nullable=False)
    action = Column(String(10), nullable=False)  # LONG / SHORT
    quantity = Column(Integer, nullable=False)
    entry_price = Column(DECIMAL(10, 2), nullable=False)
    exit_price = Column(DECIMAL(10, 2), nullable=True)  # null if still open at end
    entry_time = Column(String(30), nullable=True)  # ISO timestamp string
    exit_time = Column(String(30), nullable=True)

    pnl = Column(DECIMAL(15, 2), default=0)
    pnl_pct = Column(DECIMAL(10, 4), default=0)
    commission = Column(DECIMAL(10, 2), default=0)
    slippage_cost = Column(DECIMAL(10, 2), default=0)
    net_pnl = Column(DECIMAL(15, 2), default=0)

    bars_held = Column(Integer, default=0)
    product = Column(String(20), nullable=True)
    strategy_tag = Column(String(100), nullable=True)

    __table_args__ = (
        Index("idx_bt_trade_backtest_num", "backtest_id", "trade_num"),
    )


def init_db():
    """Initialize backtest database and tables."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Backtest DB", logger)


def get_backtest_run(backtest_id):
    """Get a backtest run by ID."""
    try:
        return BacktestRun.query.filter_by(id=backtest_id).first()
    except Exception as e:
        logger.exception(f"Error fetching backtest run {backtest_id}: {e}")
        return None


def get_user_backtests(user_id, limit=50):
    """Get all backtests for a user, ordered by creation date descending."""
    try:
        return (
            BacktestRun.query.filter_by(user_id=user_id)
            .order_by(BacktestRun.created_at.desc())
            .limit(limit)
            .all()
        )
    except Exception as e:
        logger.exception(f"Error fetching backtests for user {user_id}: {e}")
        return []


def get_backtest_trades(backtest_id):
    """Get all trades for a backtest run."""
    try:
        return (
            BacktestTrade.query.filter_by(backtest_id=backtest_id)
            .order_by(BacktestTrade.trade_num)
            .all()
        )
    except Exception as e:
        logger.exception(f"Error fetching trades for backtest {backtest_id}: {e}")
        return []


def delete_backtest(backtest_id):
    """Delete a backtest run and all its trades."""
    try:
        BacktestTrade.query.filter_by(backtest_id=backtest_id).delete()
        BacktestRun.query.filter_by(id=backtest_id).delete()
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error deleting backtest {backtest_id}: {e}")
        return False
