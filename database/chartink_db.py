from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, DateTime, Time
from sqlalchemy.orm import scoped_session, sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')

engine = create_engine(
    DATABASE_URL,
    pool_size=50,
    max_overflow=100,
    pool_timeout=10
)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class ChartinkStrategy(Base):
    """Model for Chartink strategies"""
    __tablename__ = 'chartink_strategies'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    webhook_id = Column(String(36), unique=True, nullable=False)  # UUID
    user_id = Column(String(255), nullable=False)  # Added user_id field
    is_active = Column(Boolean, default=True)
    is_intraday = Column(Boolean, default=True)
    start_time = Column(String(5))  # HH:MM format
    end_time = Column(String(5))  # HH:MM format
    squareoff_time = Column(String(5))  # HH:MM format
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    symbol_mappings = relationship("ChartinkSymbolMapping", back_populates="strategy", cascade="all, delete-orphan")

class ChartinkSymbolMapping(Base):
    """Model for symbol mappings in Chartink strategies"""
    __tablename__ = 'chartink_symbol_mappings'
    
    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey('chartink_strategies.id'), nullable=False)
    chartink_symbol = Column(String(50), nullable=False)
    exchange = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False)
    product_type = Column(String(10), nullable=False)  # MIS/CNC
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    strategy = relationship("ChartinkStrategy", back_populates="symbol_mappings")

def init_db():
    """Initialize the database"""
    logger.info("Initializing Chartink DB")
    Base.metadata.create_all(bind=engine)

def create_strategy(name, webhook_id, user_id, is_intraday=True, start_time=None, end_time=None, squareoff_time=None):
    """Create a new strategy"""
    try:
        strategy = ChartinkStrategy(
            name=name,
            webhook_id=webhook_id,
            user_id=user_id,  # Added user_id
            is_intraday=is_intraday,
            start_time=start_time,
            end_time=end_time,
            squareoff_time=squareoff_time
        )
        db_session.add(strategy)
        db_session.commit()
        return strategy
    except Exception as e:
        logger.error(f"Error creating strategy: {str(e)}")
        db_session.rollback()
        return None

def get_strategy(strategy_id):
    """Get strategy by ID"""
    try:
        return ChartinkStrategy.query.get(strategy_id)
    except Exception as e:
        logger.error(f"Error getting strategy {strategy_id}: {str(e)}")
        return None

def get_strategy_by_webhook_id(webhook_id):
    """Get strategy by webhook ID"""
    try:
        return ChartinkStrategy.query.filter_by(webhook_id=webhook_id).first()
    except Exception as e:
        logger.error(f"Error getting strategy by webhook ID {webhook_id}: {str(e)}")
        return None

def get_all_strategies():
    """Get all strategies"""
    try:
        return ChartinkStrategy.query.all()
    except Exception as e:
        logger.error(f"Error getting all strategies: {str(e)}")
        return []

def get_user_strategies(user_id):
    """Get all strategies for a user"""
    try:
        return ChartinkStrategy.query.filter_by(user_id=user_id).all()
    except Exception as e:
        logger.error(f"Error getting strategies for user {user_id}: {str(e)}")
        return []

def delete_strategy(strategy_id):
    """Delete a strategy"""
    try:
        strategy = ChartinkStrategy.query.get(strategy_id)
        if strategy:
            db_session.delete(strategy)
            db_session.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"Error deleting strategy {strategy_id}: {str(e)}")
        db_session.rollback()
        return False

def toggle_strategy(strategy_id):
    """Toggle strategy active status"""
    try:
        strategy = ChartinkStrategy.query.get(strategy_id)
        if strategy:
            strategy.is_active = not strategy.is_active
            db_session.commit()
            return strategy
        return None
    except Exception as e:
        logger.error(f"Error toggling strategy {strategy_id}: {str(e)}")
        db_session.rollback()
        return None

def update_strategy_times(strategy_id, start_time=None, end_time=None, squareoff_time=None):
    """Update strategy trading times"""
    try:
        strategy = ChartinkStrategy.query.get(strategy_id)
        if strategy:
            if start_time is not None:
                strategy.start_time = start_time
            if end_time is not None:
                strategy.end_time = end_time
            if squareoff_time is not None:
                strategy.squareoff_time = squareoff_time
            db_session.commit()
            return strategy
        return None
    except Exception as e:
        logger.error(f"Error updating strategy times {strategy_id}: {str(e)}")
        db_session.rollback()
        return None

def add_symbol_mapping(strategy_id, chartink_symbol, exchange, quantity, product_type):
    """Add symbol mapping to strategy"""
    try:
        mapping = ChartinkSymbolMapping(
            strategy_id=strategy_id,
            chartink_symbol=chartink_symbol,
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
            mapping = ChartinkSymbolMapping(
                strategy_id=strategy_id,
                chartink_symbol=mapping_data['chartink_symbol'],
                exchange=mapping_data['exchange'],
                quantity=mapping_data['quantity'],
                product_type=mapping_data['product_type']
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
        return ChartinkSymbolMapping.query.filter_by(strategy_id=strategy_id).all()
    except Exception as e:
        logger.error(f"Error getting symbol mappings for strategy {strategy_id}: {str(e)}")
        return []

def delete_symbol_mapping(mapping_id):
    """Delete a symbol mapping"""
    try:
        mapping = ChartinkSymbolMapping.query.get(mapping_id)
        if mapping:
            db_session.delete(mapping)
            db_session.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"Error deleting symbol mapping {mapping_id}: {str(e)}")
        db_session.rollback()
        return False
