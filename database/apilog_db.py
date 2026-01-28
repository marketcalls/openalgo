# database/apilog_db.py

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytz
from sqlalchemy import Column, DateTime, Integer, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

from utils.logging import get_logger

logger = get_logger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL")  # Replace with your SQLite path

# Conditionally create engine based on DB type
if DATABASE_URL and "sqlite" in DATABASE_URL:
    # SQLite: Use NullPool to prevent connection pool exhaustion
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    # For other databases like PostgreSQL, use connection pooling
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class OrderLog(Base):
    __tablename__ = "order_logs"
    id = Column(Integer, primary_key=True)
    api_type = Column(Text, nullable=False)
    request_data = Column(Text, nullable=False)
    response_data = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())


def init_db():
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "API Log DB", logger)


# Executor for asynchronous tasks
executor = ThreadPoolExecutor(10)  # Increased from 2 to 10 for better concurrency


def async_log_order(api_type, request_data, response_data):
    try:
        # Serialize JSON data for storage
        request_json = json.dumps(request_data)
        response_json = json.dumps(response_data)

        # Get current time in IST
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)

        order_log = OrderLog(
            api_type=api_type,
            request_data=request_json,
            response_data=response_json,
            created_at=now_ist,
        )
        db_session.add(order_log)
        db_session.commit()
    except Exception as e:
        logger.exception(f"Error saving order log: {e}")
    finally:
        db_session.remove()
