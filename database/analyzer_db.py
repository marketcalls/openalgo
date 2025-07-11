# database/analyzer_db.py

import os
import json
from sqlalchemy import create_engine, Column, Integer, DateTime, Text, String
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import pytz
from utils.logging import get_logger

logger = get_logger(__name__)

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

class AnalyzerLog(Base):
    __tablename__ = 'analyzer_logs'
    id = Column(Integer, primary_key=True)
    api_type = Column(String(50), nullable=False)  # placeorder, cancelorder, etc.
    request_data = Column(Text, nullable=False)
    response_data = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())

    def to_dict(self):
        """Convert log entry to dictionary"""
        try:
            request_data = json.loads(self.request_data) if isinstance(self.request_data, str) else self.request_data
            response_data = json.loads(self.response_data) if isinstance(self.response_data, str) else self.response_data
        except json.JSONDecodeError:
            request_data = self.request_data
            response_data = self.response_data

        return {
            'id': self.id,
            'api_type': self.api_type,
            'request_data': request_data,
            'response_data': response_data,
            'created_at': self.created_at.astimezone(pytz.UTC).isoformat()
        }

def init_db():
    """Initialize the analyzer table"""
    logger.info("Initializing Analyzer Table")
    Base.metadata.create_all(bind=engine)

# Executor for asynchronous tasks
executor = ThreadPoolExecutor(10)  # Increased from 2 to 10 for better concurrency

def async_log_analyzer(request_data, response_data, api_type='placeorder'):
    """Asynchronously log analyzer request"""
    try:
        # Serialize JSON data for storage
        request_json = json.dumps(request_data)
        response_json = json.dumps(response_data)

        # Get current time in IST
        ist = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist)

        analyzer_log = AnalyzerLog(
            api_type=api_type,
            request_data=request_json,
            response_data=response_json,
            created_at=now_ist
        )
        db_session.add(analyzer_log)
        db_session.commit()
    except Exception as e:
        logger.error(f"Error saving analyzer log: {e}")
        db_session.rollback()
    finally:
        db_session.remove()
