# database/action_center_db.py

import json
import os
from datetime import datetime

import pytz
from sqlalchemy import Column, DateTime, Index, Integer, String, Text, create_engine
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
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


def get_ist_timestamp():
    """Get current timestamp in IST format"""
    try:
        utc_now = datetime.now(pytz.UTC)
        ist = pytz.timezone("Asia/Kolkata")
        ist_now = utc_now.astimezone(ist)
        return ist_now.strftime("%Y-%m-%d %H:%M:%S IST")
    except Exception as e:
        logger.exception(f"Error getting IST timestamp: {e}")
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")


class PendingOrder(Base):
    __tablename__ = "pending_orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    api_type = Column(String(50), nullable=False)
    order_data = Column(Text, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=func.now())
    created_at_ist = Column(String(50))

    # Status tracking
    status = Column(String(20), default="pending")

    # Approval tracking
    approved_at = Column(DateTime(timezone=True))
    approved_at_ist = Column(String(50))
    approved_by = Column(String(255))

    # Rejection tracking
    rejected_at = Column(DateTime(timezone=True))
    rejected_at_ist = Column(String(50))
    rejected_by = Column(String(255))
    rejected_reason = Column(Text)

    # Broker execution tracking
    broker_order_id = Column(String(255))
    broker_status = Column(String(20))

    __table_args__ = (
        Index("idx_user_status", "user_id", "status"),
        Index("idx_created_at", "created_at"),
    )


def init_db():
    """Initialize database tables"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Action Center DB", logger)


def create_pending_order(user_id, api_type, order_data):
    """
    Create a new pending order with IST timestamp

    Args:
        user_id: User identifier
        api_type: Type of order (placeorder, smartorder, basketorder, splitorder)
        order_data: Order data dictionary

    Returns:
        int: Pending order ID or None if failed
    """
    try:
        # Convert order_data to JSON string
        order_data_json = json.dumps(order_data)

        pending_order = PendingOrder(
            user_id=user_id,
            api_type=api_type,
            order_data=order_data_json,
            created_at_ist=get_ist_timestamp(),
            status="pending",
        )

        db_session.add(pending_order)
        db_session.commit()

        logger.info(
            f"Pending order created: ID={pending_order.id}, user={user_id}, type={api_type}, time={pending_order.created_at_ist}"
        )
        return pending_order.id

    except Exception as e:
        logger.exception(f"Error creating pending order: {e}")
        db_session.rollback()
        return None


def get_pending_orders(user_id, status=None):
    """
    Get pending orders for a user, optionally filtered by status

    Args:
        user_id: User identifier
        status: Optional status filter ('pending', 'approved', 'rejected')

    Returns:
        list: List of PendingOrder objects
    """
    try:
        query = PendingOrder.query.filter_by(user_id=user_id)

        if status:
            query = query.filter_by(status=status)

        orders = query.order_by(PendingOrder.created_at.desc()).all()
        return orders

    except Exception as e:
        logger.exception(f"Error getting pending orders: {e}")
        return []


def get_pending_order_by_id(order_id):
    """
    Get a single pending order by ID

    Args:
        order_id: Order ID

    Returns:
        PendingOrder or None
    """
    try:
        return PendingOrder.query.filter_by(id=order_id).first()
    except Exception as e:
        logger.exception(f"Error getting pending order by ID: {e}")
        return None


def approve_pending_order(order_id, approved_by, user_id):
    """
    Approve a pending order with IST timestamp

    Args:
        order_id: Order ID
        approved_by: Username of approver
        user_id: ID of the user who owns the order (for security)

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        pending_order = PendingOrder.query.filter_by(
            id=order_id, user_id=user_id, status="pending"
        ).first()

        if pending_order:
            pending_order.status = "approved"
            pending_order.approved_by = approved_by
            pending_order.approved_at = datetime.utcnow()
            pending_order.approved_at_ist = get_ist_timestamp()
            db_session.commit()

            logger.info(
                f"Order approved: ID={order_id}, by={approved_by}, time={pending_order.approved_at_ist}"
            )
            return True
        else:
            logger.warning(f"Cannot approve order {order_id}: not found or not pending")
            return False

    except Exception as e:
        logger.exception(f"Error approving order: {e}")
        db_session.rollback()
        return False


def reject_pending_order(order_id, reason, rejected_by, user_id):
    """
    Reject a pending order with IST timestamp

    Args:
        order_id: Order ID
        reason: Rejection reason
        rejected_by: Username of rejector
        user_id: ID of the user who owns the order (for security)

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        pending_order = PendingOrder.query.filter_by(
            id=order_id, user_id=user_id, status="pending"
        ).first()

        if pending_order:
            pending_order.status = "rejected"
            pending_order.rejected_reason = reason
            pending_order.rejected_by = rejected_by
            pending_order.rejected_at = datetime.utcnow()
            pending_order.rejected_at_ist = get_ist_timestamp()
            db_session.commit()

            logger.info(
                f"Order rejected: ID={order_id}, by={rejected_by}, time={pending_order.rejected_at_ist}, reason={reason}"
            )
            return True
        else:
            logger.warning(f"Cannot reject order {order_id}: not found or not pending")
            return False

    except Exception as e:
        logger.exception(f"Error rejecting order: {e}")
        db_session.rollback()
        return False


def delete_pending_order(order_id, user_id):
    """
    Delete a pending order (only if not in pending status)

    Args:
        order_id: Order ID
        user_id: ID of the user who owns the order (for security)

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        pending_order = PendingOrder.query.filter_by(id=order_id, user_id=user_id).first()

        if pending_order:
            if pending_order.status == "pending":
                logger.warning(f"Cannot delete order {order_id}: still in pending status")
                return False

            db_session.delete(pending_order)
            db_session.commit()

            logger.info(f"Order deleted: ID={order_id}")
            return True
        else:
            logger.warning(f"Cannot delete order {order_id}: not found")
            return False

    except Exception as e:
        logger.exception(f"Error deleting order: {e}")
        db_session.rollback()
        return False


def update_broker_status(pending_order_id, broker_order_id, broker_status):
    """
    Update the broker order ID and status after execution

    Args:
        pending_order_id: Pending order ID
        broker_order_id: Broker's order ID
        broker_status: Broker status ('complete', 'open', 'rejected', 'cancelled')

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        pending_order = PendingOrder.query.filter_by(id=pending_order_id).first()

        if pending_order:
            pending_order.broker_order_id = broker_order_id
            pending_order.broker_status = broker_status
            db_session.commit()

            logger.info(
                f"Broker status updated: pending_order={pending_order_id}, broker_order={broker_order_id}, status={broker_status}"
            )
            return True
        else:
            logger.warning(f"Cannot update broker status: order {pending_order_id} not found")
            return False

    except Exception as e:
        logger.exception(f"Error updating broker status: {e}")
        db_session.rollback()
        return False


def get_pending_count(user_id):
    """
    Get count of pending orders for a user

    Args:
        user_id: User identifier

    Returns:
        int: Count of pending orders
    """
    try:
        count = PendingOrder.query.filter_by(user_id=user_id, status="pending").count()
        return count
    except Exception as e:
        logger.exception(f"Error getting pending count: {e}")
        return 0
