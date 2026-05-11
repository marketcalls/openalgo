import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from sqlalchemy.pool import NullPool, QueuePool

from database.db_init_helper import init_db_with_logging
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///openalgo.db")

# Choose pool class based on database URI
pool_class = QueuePool if DATABASE_URL.startswith("postgresql") else NullPool

# Setup engine with pooling
engine = create_engine(
    DATABASE_URL,
    poolclass=pool_class,
    pool_pre_ping=True,  # Test connections before handing them out
    pool_recycle=3600,   # Recycle connections after an hour
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

# Setup scoped session
session_factory = sessionmaker(bind=engine)
db_session = scoped_session(session_factory)

# Declarative base
Base = declarative_base()


class BracketOrder(Base):
    __tablename__ = "bracket_orders"

    id = Column(Integer, primary_key=True)
    bo_id = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    api_key = Column(String(256), nullable=False)
    strategy = Column(String(255), nullable=False)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(20), nullable=False)
    action = Column(String(4), nullable=False)
    product = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False)
    price_type = Column(String(10), nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    target_type = Column(String(20), nullable=False)
    target_value = Column(Float, nullable=False)
    sl_type = Column(String(20), nullable=False)
    sl_value = Column(Float, nullable=False)
    
    status = Column(String(20), nullable=False, default="CREATED")
    entry_order_id = Column(String(50), nullable=True)
    target_order_id = Column(String(50), nullable=True)
    sl_order_id = Column(String(50), nullable=True)
    
    entry_price = Column(Float, nullable=True)
    target_price = Column(Float, nullable=True)
    sl_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    exit_type = Column(String(10), nullable=True)
    
    error_message = Column(String(500), nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    filled_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "bo_id": self.bo_id,
            "api_key": self.api_key,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "action": self.action,
            "product": self.product,
            "quantity": self.quantity,
            "price_type": self.price_type,
            "price": self.price,
            "target_type": self.target_type,
            "target_value": self.target_value,
            "sl_type": self.sl_type,
            "sl_value": self.sl_value,
            "status": self.status,
            "entry_order_id": self.entry_order_id,
            "target_order_id": self.target_order_id,
            "sl_order_id": self.sl_order_id,
            "entry_price": self.entry_price,
            "target_price": self.target_price,
            "sl_price": self.sl_price,
            "exit_price": self.exit_price,
            "exit_type": self.exit_type,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


def init_db():
    """Initialize the database tables."""
    init_db_with_logging(Base, engine, "BracketOrder", logger)


def create_bracket_order(
    api_key: str,
    strategy: str,
    symbol: str,
    exchange: str,
    action: str,
    product: str,
    quantity: int,
    price_type: str,
    price: float,
    target_type: str,
    target_value: float,
    sl_type: str,
    sl_value: float,
) -> Optional[str]:
    """Create a new bracket order in the database."""
    session = db_session()
    try:
        new_bo = BracketOrder(
            api_key=api_key,
            strategy=strategy,
            symbol=symbol,
            exchange=exchange,
            action=action,
            product=product,
            quantity=quantity,
            price_type=price_type,
            price=price,
            target_type=target_type,
            target_value=target_value,
            sl_type=sl_type,
            sl_value=sl_value,
        )
        session.add(new_bo)
        session.commit()
        return new_bo.bo_id
    except Exception as e:
        session.rollback()
        logger.error(f"Error creating bracket order: {e}")
        return None


def get_bracket_order_by_bo_id(bo_id: str, api_key: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Retrieve a bracket order by its bo_id."""
    session = db_session()
    try:
        query = session.query(BracketOrder).filter(BracketOrder.bo_id == bo_id)
        if api_key:
            query = query.filter(BracketOrder.api_key == api_key)
            
        bo = query.first()
        return bo.to_dict() if bo else None
    except Exception as e:
        logger.error(f"Error retrieving bracket order {bo_id}: {e}")
        return None


def update_bracket_order(bo_id: str, updates: dict[str, Any]) -> bool:
    """Update a bracket order with new values."""
    session = db_session()
    try:
        bo = session.query(BracketOrder).filter(BracketOrder.bo_id == bo_id).first()
        if not bo:
            return False
            
        for key, value in updates.items():
            if hasattr(bo, key):
                setattr(bo, key, value)
                
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating bracket order {bo_id}: {e}")
        return False


def get_orders_by_status(statuses: list[str]) -> list[dict[str, Any]]:
    """Retrieve bracket orders with specific statuses."""
    session = db_session()
    try:
        bos = session.query(BracketOrder).filter(BracketOrder.status.in_(statuses)).all()
        return [bo.to_dict() for bo in bos]
    except Exception as e:
        logger.error(f"Error retrieving bracket orders by status: {e}")
        return []


def get_active_bo_for_symbol(api_key: str, symbol: str, exchange: str, action: str) -> Optional[dict[str, Any]]:
    """Check if there's already an active bracket order for this exact setup to prevent duplicates."""
    session = db_session()
    try:
        active_statuses = ["CREATED", "ENTRY_PENDING", "ENTRY_FILLED", "EXIT_PLACING", "ACTIVE"]
        bo = session.query(BracketOrder).filter(
            BracketOrder.api_key == api_key,
            BracketOrder.symbol == symbol,
            BracketOrder.exchange == exchange,
            BracketOrder.action == action,
            BracketOrder.status.in_(active_statuses)
        ).first()
        return bo.to_dict() if bo else None
    except Exception as e:
        logger.error(f"Error checking active BO for {symbol}: {e}")
        return None
