# database/risk_limits_db.py
# Per-user daily risk limits: profit target, loss limit, trade limit.
# Follows the same pattern as leverage_db.py / settings_db.py.

import os
from datetime import date, datetime

from cachetools import TTLCache
from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, String, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)

# Short TTL — limits are read on every order but rarely written
_risk_limits_cache = TTLCache(maxsize=50, ttl=300)  # 5 min

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


class RiskLimits(Base):
    __tablename__ = "risk_limits"

    id = Column(Integer, primary_key=True)
    user = Column(String(50), unique=True, nullable=False)
    enabled = Column(Boolean, default=False)
    daily_profit_target = Column(Float, nullable=True)  # None = no limit
    daily_loss_limit = Column(Float, nullable=True)  # Stored as positive number
    daily_trade_limit = Column(Integer, nullable=True)  # None = no limit
    breached = Column(Boolean, default=False)  # Latch: True once tripped today
    breached_reason = Column(String(100), nullable=True)
    breached_at = Column(DateTime, nullable=True)
    last_reset_date = Column(Date, nullable=True)  # Auto-reset on new trading day
    daily_trade_count = Column(Integer, default=0)  # DB-backed trade counter
    trade_count_date = Column(Date, nullable=True)  # Date of current trade count


def init_db():
    """Initialize the risk_limits table and migrate new columns if needed."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Risk Limits DB", logger)

    # Migrate: add trade count columns if table exists but columns are missing
    try:
        inspector = inspect(engine)
        if "risk_limits" in inspector.get_table_names():
            existing_cols = {c["name"] for c in inspector.get_columns("risk_limits")}
            with engine.connect() as conn:
                if "daily_trade_count" not in existing_cols:
                    conn.execute(text("ALTER TABLE risk_limits ADD COLUMN daily_trade_count INTEGER DEFAULT 0"))
                    conn.commit()
                    logger.info("Migration: Added 'daily_trade_count' column to risk_limits table")
                if "trade_count_date" not in existing_cols:
                    conn.execute(text("ALTER TABLE risk_limits ADD COLUMN trade_count_date DATE"))
                    conn.commit()
                    logger.info("Migration: Added 'trade_count_date' column to risk_limits table")
    except Exception as e:
        logger.error(f"Risk Limits migration FAILED — trade count columns may be missing: {e}")
        raise


def get_risk_limits(user: str) -> RiskLimits | None:
    """Get risk limits for a user (cached)."""
    cache_key = f"risk_limits:{user}"
    if cache_key in _risk_limits_cache:
        return _risk_limits_cache[cache_key]

    try:
        row = RiskLimits.query.filter_by(user=user).first()
        _risk_limits_cache[cache_key] = row
        return row
    except Exception as e:
        logger.exception(f"Error fetching risk limits for {user}: {e}")
        return None


def upsert_risk_limits(
    user: str,
    enabled: bool,
    daily_profit_target: float | None,
    daily_loss_limit: float | None,
    daily_trade_limit: int | None,
) -> bool:
    """Create or update risk limits for a user. Clears cache."""
    try:
        row = RiskLimits.query.filter_by(user=user).first()
        if row is None:
            row = RiskLimits(user=user)
            db_session.add(row)
            try:
                db_session.flush()
            except IntegrityError:
                # Concurrent insert — retry as update
                db_session.rollback()
                row = RiskLimits.query.filter_by(user=user).first()
                if row is None:
                    return False

        row.enabled = enabled
        row.daily_profit_target = daily_profit_target
        row.daily_loss_limit = daily_loss_limit
        row.daily_trade_limit = daily_trade_limit
        db_session.commit()

        # Invalidate cache
        _risk_limits_cache.pop(f"risk_limits:{user}", None)
        return True
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error upserting risk limits for {user}: {e}")
        return False


def set_breached(user: str, reason: str) -> None:
    """Set the breached latch for a user."""
    try:
        row = RiskLimits.query.filter_by(user=user).first()
        if row and not row.breached:
            row.breached = True
            row.breached_reason = reason
            row.breached_at = datetime.now()
            row.last_reset_date = date.today()
            db_session.commit()
            _risk_limits_cache.pop(f"risk_limits:{user}", None)
            logger.info(f"Risk limit breached for {user}: {reason}")
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error setting breached for {user}: {e}")


def reset_if_new_day(user: str) -> bool:
    """Reset breached latch and trade count if it's a new trading day. Returns True if reset happened."""
    try:
        row = RiskLimits.query.filter_by(user=user).first()
        if not row:
            return False
        today = date.today()
        reset_needed = False

        if row.breached and row.last_reset_date and row.last_reset_date < today:
            row.breached = False
            row.breached_reason = None
            row.breached_at = None
            reset_needed = True

        if row.trade_count_date and row.trade_count_date < today:
            row.daily_trade_count = 0
            row.trade_count_date = today
            reset_needed = True

        if reset_needed:
            db_session.commit()
            _risk_limits_cache.pop(f"risk_limits:{user}", None)
            logger.info(f"Risk limits auto-reset for {user} (new day)")
        return reset_needed
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error resetting risk limits for {user}: {e}")
        return False


def increment_and_get_trade_count(user: str) -> int:
    """Atomically increment trade count in DB using SQL and return the new value."""
    try:
        today = date.today()

        # Atomic UPDATE with SQL expression — no read-modify-write race
        result = db_session.execute(
            text(
                "UPDATE risk_limits "
                "SET daily_trade_count = CASE "
                "  WHEN trade_count_date IS NULL OR trade_count_date < :today THEN 1 "
                "  ELSE COALESCE(daily_trade_count, 0) + 1 "
                "END, "
                "trade_count_date = :today "
                "WHERE \"user\" = :user"
            ),
            {"today": today, "user": user},
        )
        db_session.commit()

        if result.rowcount == 0:
            return 0

        # Read back the new count
        row = RiskLimits.query.filter_by(user=user).first()
        _risk_limits_cache.pop(f"risk_limits:{user}", None)
        return row.daily_trade_count if row else 0
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error incrementing trade count for {user}: {e}")
        return 0


def get_db_trade_count(user: str) -> int:
    """Get the current day's trade count from DB."""
    try:
        today = date.today()
        row = RiskLimits.query.filter_by(user=user).first()
        if row is None or row.trade_count_date is None or row.trade_count_date < today:
            return 0
        return row.daily_trade_count or 0
    except Exception as e:
        logger.exception(f"Error getting trade count for {user}: {e}")
        return 0
