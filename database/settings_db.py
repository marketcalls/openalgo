# database/settings_db.py

from sqlalchemy import create_engine, Column, Integer, String, Boolean, MetaData
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

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

class Settings(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True)
    analyze_mode = Column(Boolean, default=False)  # Default to Live Mode

def init_db():
    """Initialize the settings database"""
    print("Initializing Settings DB")
    
    # Drop existing settings table if it exists
    metadata = MetaData()
    metadata.reflect(bind=engine)
    if 'settings' in metadata.tables:
        Settings.__table__.drop(engine)
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    # Create default settings
    if not Settings.query.first():
        default_settings = Settings(analyze_mode=False)  # Default to Live Mode
        db_session.add(default_settings)
        db_session.commit()

def get_analyze_mode():
    """Get current analyze mode setting"""
    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=False)  # Default to Live Mode
        db_session.add(settings)
        db_session.commit()
    return settings.analyze_mode

def set_analyze_mode(mode: bool):
    """Set analyze mode setting"""
    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=mode)
        db_session.add(settings)
    else:
        settings.analyze_mode = mode
    db_session.commit()
