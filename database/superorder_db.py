import json
import os
from datetime import datetime

from sqlalchemy import (
    DECIMAL,
    Column,
    DateTime,
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

DATABASE_URL = os.getenv("DATABASE_URL")

# Conditionally create engine based on DB type
if DATABASE_URL and "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(
        DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10
    )

db_session = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=engine)
)
Base = declarative_base()
Base.query = db_session.query_property()


class SuperOrder(Base):
    __tablename__ = "super_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), nullable=False, index=True)

    # Order parameters
    symbol = Column(String(255), nullable=False)
    exchange = Column(String(50), nullable=False)
    product_type = Column(String(50), nullable=False)  # INTRADAY / NRML / CNC / MTF
    transaction_type = Column(String(20), nullable=False)  # BUY / SELL
    quantity = Column(Integer, nullable=False)

    # Pricing
    entry_price = Column(DECIMAL(15, 4), nullable=False)
    target_price = Column(DECIMAL(15, 4), nullable=False)
    stoploss_price = Column(DECIMAL(15, 4), nullable=False)
    trail_jump = Column(DECIMAL(15, 4), nullable=True)  # Optional trailing step

    # State tracking
    main_order_id = Column(String(255), nullable=True)
    target_order_id = Column(String(255), nullable=True)
    stoploss_order_id = Column(String(255), nullable=True)
    status = Column(
        String(20), default="PENDING", index=True
    )  # PENDING / ACTIVE / CLOSED / FAILED / CANCELLED

    # Metadata
    order_tag = Column(String(255), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now()
    )
    expires_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_user_superorder_status", "user_id", "status"),)


def init_db():
    """Initialize database tables"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Super Order DB", logger)
