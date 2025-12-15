
import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')

# --- FIX 1: Validate Database URL ---
if not DATABASE_URL:
    # This stops the app immediately with a clear message if the config is missing
    raise ValueError("CRITICAL: DATABASE_URL is not set in environment variables.")

# Create engine (reuse existing connection pattern)
# If using SQLite, we need to be careful with threads
if DATABASE_URL and 'sqlite' in DATABASE_URL:
    from sqlalchemy.pool import NullPool
    engine = create_engine(
        DATABASE_URL,
        poolclass=NullPool,
        connect_args={'check_same_thread': False}
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=50,
        max_overflow=100,
        pool_timeout=10
    )

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class Alert(Base):
    __tablename__ = 'alerts'

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False)   # e.g. "INFY"
    condition = Column(String(10), nullable=False) # "ABOVE" or "BELOW"
    price = Column(Float, nullable=False)          # e.g. 1500.00
    status = Column(String(20), default="ACTIVE")  # ACTIVE, TRIGGERED
    created_at = Column(DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "condition": self.condition,
            "price": self.price,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

def init_db():
    from database.db_init_helper import init_db_with_logging
    init_db_with_logging(Base, engine, "Alerts DB", logger)
