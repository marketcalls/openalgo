# database/traffic_db.py - FIXED CONNECTION POOLING

import json
import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql import func

logger = logging.getLogger(__name__)

# Use a separate database for logs
LOGS_DATABASE_URL = os.getenv("LOGS_DATABASE_URL", "sqlite:///db/logs.db")

# FIXED: Use StaticPool instead of NullPool for better connection management
# StaticPool maintains a single connection per thread, which is perfect for SQLite
if LOGS_DATABASE_URL and "sqlite" in LOGS_DATABASE_URL:
    logs_engine = create_engine(
        LOGS_DATABASE_URL,
        poolclass=StaticPool,  # Changed from NullPool
        connect_args={
            "check_same_thread": False,
            "timeout": 20.0,  # Wait up to 20 seconds for locks
        },
        pool_pre_ping=True,  # Verify connections before use
        echo=False,
    )
else:
    # For PostgreSQL: strict connection limits
    logs_engine = create_engine(
        LOGS_DATABASE_URL,
        pool_size=10,  # Reduced from 50
        max_overflow=20,  # Reduced from 100
        pool_timeout=30,
        pool_recycle=3600,  # Recycle connections after 1 hour
        pool_pre_ping=True,
    )

logs_session = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=logs_engine)
)
LogBase = declarative_base()
LogBase.query = logs_session.query_property()

# Rest of the code remains the same...
