from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, DateTime, Time
from sqlalchemy.orm import scoped_session, sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.pool import NullPool
from cachetools import TTLCache
import os
import logging

logger = logging.getLogger(__name__)

# Strategy caches - 5 minute TTL for webhook lookups (high frequency)
# Webhook lookups happen on every webhook trigger, caching significantly reduces DB load
_strategy_webhook_cache = TTLCache(maxsize=5000, ttl=300)  # 5 minutes TTL
_user_strategies_cache = TTLCache(maxsize=1000, ttl=600)   # 10 minutes TTL

DATABASE_URL = os.getenv('DATABASE_URL')

# Conditionally create engine based on DB type
if DATABASE_URL and 'sqlite' in DATABASE_URL:
    # SQLite: Use NullPool to prevent connection pool exhaustion
    engine = create_engine(
        DATABASE_URL,
        poolclass=NullPool,
        connect_args={'check_same_thread': False}
    )
else:
    # For other databases like PostgreSQL, use connection pooling
    engine = create_engine(
        DATABASE_URL,
        pool_size=50,
        max_overflow=100,
        pool_timeout=10
    )

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class Strategy(Base):
    """Model for trading strategies"""
    __tablename__ = 'strategies'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    webhook_id = Column(String(36), unique=True, nullable=False)  # UUID
    user_id = Column(String(255), nullable=False)
    platform = Column(String(50), nullable=False, default='tradingview')  # Platform type (tradingview, chartink, etc)
    is_active = Column(Boolean, default=True)
    is_intraday = Column(Boolean, default=True)
    trading_mode = Column(String(10), nullable=False, default='LONG')  # LONG, SHORT, or BOTH
    start_time = Column(String(5))  # HH:MM format
    end_time = Column(String(5))  # HH:MM format
    squareoff_time = Column(String(5))  # HH:MM format
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    symbol_mappings = relationship("StrategySymbolMapping", back_populates="strategy", cascade="all, delete-orphan")

class StrategySymbolMapping(Base):
    """Model for symbol mappings in strategies"""
    __tablename__ = 'strategy_symbol_mappings'
    
    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey('strategies.id'), nullable=False)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False)
    product_type = Column(String(10), nullable=False)  # MIS/CNC
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    strategy = relationship("Strategy", back_populates="symbol_mappings")

def init_db():
    """Initialize the database"""
    from database.db_init_helper import init_db_with_logging
    init_db_with_logging(Base, engine, "Strategy DB", logger)

def create_strategy(name, webhook_id, user_id, is_intraday=True, trading_mode='LONG', start_time=None, end_time=None, squareoff_time=None, platform='tradingview'):
    """Create a new strategy"""
    try:
        strategy = Strategy(
            name=name,
            webhook_id=webhook_id,
            user_id=user_id,
            is_intraday=is_intraday,
            trading_mode=trading_mode,
            start_time=start_time,
            end_time=end_time,
            squareoff_time=squareoff_time,
            platform=platform
        )
        db_session.add(strategy)
        db_session.commit()

        # Invalidate user strategies cache
        user_cache_key = f"user_{user_id}"
        if user_cache_key in _user_strategies_cache:
            del _user_strategies_cache[user_cache_key]

        return strategy
    except Exception as e:
        logger.error(f"Error creating strategy: {str(e)}")
        db_session.rollback()
        return None

def get_strategy(strategy_id):
    """Get strategy by ID"""
    try:
        return Strategy.query.get(strategy_id)
    except Exception as e:
        logger.error(f"Error getting strategy {strategy_id}: {str(e)}")
        return None

def get_strategy_by_webhook_id(webhook_id):
    """Get strategy by webhook ID (cached for 5 minutes)"""
    # Check cache first
    if webhook_id in _strategy_webhook_cache:
        return _strategy_webhook_cache[webhook_id]

    try:
        strategy = Strategy.query.filter_by(webhook_id=webhook_id).first()
        # Cache the result (including None for not found)
        if strategy:
            _strategy_webhook_cache[webhook_id] = strategy
        return strategy
    except Exception as e:
        logger.error(f"Error getting strategy by webhook ID {webhook_id}: {str(e)}")
        return None

def get_all_strategies():
    """Get all strategies"""
    try:
        return Strategy.query.all()
    except Exception as e:
        logger.error(f"Error getting all strategies: {str(e)}")
        return []

def get_user_strategies(user_id):
    """Get all strategies for a user (cached for 10 minutes)"""
    cache_key = f"user_{user_id}"

    # Check cache first
    if cache_key in _user_strategies_cache:
        return _user_strategies_cache[cache_key]

    try:
        logger.info(f"Fetching strategies for user: {user_id}")
        strategies = Strategy.query.filter_by(user_id=user_id).all()
        logger.info(f"Found {len(strategies)} strategies")
        # Cache the result
        _user_strategies_cache[cache_key] = strategies
        return strategies
    except Exception as e:
        logger.error(f"Error getting user strategies for {user_id}: {str(e)}")
        return []

def delete_strategy(strategy_id):
    """Delete strategy and its symbol mappings"""
    try:
        strategy = get_strategy(strategy_id)
        if not strategy:
            return False

        # Invalidate caches before deletion
        webhook_id = strategy.webhook_id
        user_id = strategy.user_id

        db_session.delete(strategy)
        db_session.commit()

        # Clear from caches
        if webhook_id in _strategy_webhook_cache:
            del _strategy_webhook_cache[webhook_id]
        user_cache_key = f"user_{user_id}"
        if user_cache_key in _user_strategies_cache:
            del _user_strategies_cache[user_cache_key]

        return True
    except Exception as e:
        logger.error(f"Error deleting strategy {strategy_id}: {str(e)}")
        db_session.rollback()
        return False

def toggle_strategy(strategy_id):
    """Toggle strategy active status"""
    try:
        strategy = get_strategy(strategy_id)
        if not strategy:
            return None
        
        strategy.is_active = not strategy.is_active
        db_session.commit()
        return strategy
    except Exception as e:
        logger.error(f"Error toggling strategy {strategy_id}: {str(e)}")
        db_session.rollback()
        return None

def update_strategy_times(strategy_id, start_time=None, end_time=None, squareoff_time=None):
    """Update strategy trading times"""
    try:
        strategy = Strategy.query.get(strategy_id)
        if strategy:
            if start_time is not None:
                strategy.start_time = start_time
            if end_time is not None:
                strategy.end_time = end_time
            if squareoff_time is not None:
                strategy.squareoff_time = squareoff_time
            db_session.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"Error updating strategy times {strategy_id}: {str(e)}")
        db_session.rollback()
        return False

def add_symbol_mapping(strategy_id, symbol, exchange, quantity, product_type):
    """Add symbol mapping to strategy"""
    try:
        mapping = StrategySymbolMapping(
            strategy_id=strategy_id,
            symbol=symbol,
            exchange=exchange,
            quantity=quantity,
            product_type=product_type
        )
        db_session.add(mapping)
        db_session.commit()
        return mapping
    except Exception as e:
        logger.error(f"Error adding symbol mapping: {str(e)}")
        db_session.rollback()
        return None

def bulk_add_symbol_mappings(strategy_id, mappings):
    """Add multiple symbol mappings at once"""
    try:
        for mapping_data in mappings:
            mapping = StrategySymbolMapping(
                strategy_id=strategy_id,
                **mapping_data
            )
            db_session.add(mapping)
        db_session.commit()
        return True
    except Exception as e:
        logger.error(f"Error bulk adding symbol mappings: {str(e)}")
        db_session.rollback()
        return False

def get_symbol_mappings(strategy_id):
    """Get all symbol mappings for a strategy"""
    try:
        return StrategySymbolMapping.query.filter_by(strategy_id=strategy_id).all()
    except Exception as e:
        logger.error(f"Error getting symbol mappings: {str(e)}")
        return []

def delete_symbol_mapping(mapping_id):
    """Delete a symbol mapping"""
    try:
        mapping = StrategySymbolMapping.query.get(mapping_id)
        if mapping:
            db_session.delete(mapping)
            db_session.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"Error deleting symbol mapping {mapping_id}: {str(e)}")
        db_session.rollback()
        return False


def clear_strategy_cache():
    """
    Clear all strategy caches.
    Called on logout/session expiry to ensure fresh data on next login.
    """
    _strategy_webhook_cache.clear()
    _user_strategies_cache.clear()
    logger.info("Strategy cache cleared")
