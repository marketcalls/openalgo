# database/chart_prefs_db.py

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import NullPool
import os
from datetime import datetime
from utils.logging import get_logger
from database.auth_db import verify_api_key

logger = get_logger(__name__)

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

class ChartPreferences(Base):
    __tablename__ = 'chart_preferences'
    user_id = Column(String(80), primary_key=True)  # Using String to match 'name' in Auth/User logic
    key = Column(String(50), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

def init_db():
    """Initialize the chart preferences database"""
    from database.db_init_helper import init_db_with_logging
    init_db_with_logging(Base, engine, "Chart Prefs DB", logger)

def get_chart_prefs(api_key):
    """
    Get all chart preferences for the user associated with the API key.
    Returns a dictionary of key-value pairs.
    """
    user_id = verify_api_key(api_key)
    logger.debug(f"[ChartPrefsDB] get_chart_prefs: user_id={user_id}")
    
    if not user_id:
        logger.warning("[ChartPrefsDB] get_chart_prefs: Invalid API Key")
        return None

    try:
        prefs = ChartPreferences.query.filter_by(user_id=user_id).all()
        result = {pref.key: pref.value for pref in prefs}
        logger.debug(f"[ChartPrefsDB] get_chart_prefs: Found {len(result)} preferences")
        return result
    except Exception as e:
        logger.error(f"[ChartPrefsDB] Error getting chart preferences: {e}")
        return None

def update_chart_prefs(api_key, data):
    """
    Update chart preferences for the user associated with the API key.
    'data' should be a dictionary of {key: value}.
    """
    user_id = verify_api_key(api_key)
    logger.debug(f"[ChartPrefsDB] update_chart_prefs: user_id={user_id}, keys={list(data.keys()) if data else 'None'}")
    
    if not user_id:
        logger.warning("[ChartPrefsDB] update_chart_prefs: Invalid API Key")
        return False

    try:
        for key, value in data.items():
            pref = ChartPreferences.query.filter_by(user_id=user_id, key=key).first()
            if pref:
                pref.value = value
                logger.debug(f"[ChartPrefsDB] Updated existing key: {key}")
            else:
                pref = ChartPreferences(user_id=user_id, key=key, value=value)
                db_session.add(pref)
                logger.debug(f"[ChartPrefsDB] Created new key: {key}")
        
        db_session.commit()
        logger.info(f"[ChartPrefsDB] Successfully saved {len(data)} preferences for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"[ChartPrefsDB] Error updating chart preferences: {e}")
        db_session.rollback()
        return False

def ensure_chart_prefs_tables_exists():
    """Ensure tables exist (alias for init_db to match app.py pattern)"""
    init_db()
