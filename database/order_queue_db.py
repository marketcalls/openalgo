"""
database/order_queue_db.py

Persistent, SQLite-backed order queue for the OpenAlgo Strategy Manager.

Replaces the ephemeral in-memory queue.Queue used in blueprints/strategy.py,
providing at-least-once delivery guarantees: orders survive app restarts, OOM
kills, and SIGTERM signals.

On startup, any order left in the 'processing' state (i.e. the process was
killed mid-flight) is automatically recovered and re-queued.

Order lifecycle:
    enqueue_order()  →  status = 'pending'
    fetch_next_pending() + mark_processing()  →  status = 'processing'
    mark_sent()     →  status = 'sent'      (terminal, success)
    mark_failed()   →  retry_count += 1
                       status = 'pending'   (if retry_count < MAX_RETRIES)
                       status = 'failed'    (dead-letter, if retry_count >= MAX_RETRIES)
"""

import json
import logging
import os
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, func
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
MAX_RETRIES = int(os.getenv("ORDER_QUEUE_MAX_RETRIES", "3"))

# ---------------------------------------------------------------------------
# Engine — follows the same pattern used in every other OpenAlgo database file
# ---------------------------------------------------------------------------
if DATABASE_URL and "sqlite" in DATABASE_URL:
    _engine = create_engine(
        DATABASE_URL,
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )
else:
    _engine = create_engine(
        DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_timeout=10,
    )

_db_session = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=_engine)
)
Base = declarative_base()
Base.query = _db_session.query_property()


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class PersistentOrder(Base):
    """Durable order queue entry — survives process restarts."""

    __tablename__ = "order_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    endpoint = Column(String(50), nullable=False)       # 'placeorder' | 'placesmartorder'
    payload_json = Column(Text, nullable=False)          # JSON-serialised order payload
    status = Column(String(20), nullable=False, default="pending")
    retry_count = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

    def get_payload(self) -> dict:
        try:
            return json.loads(self.payload_json)
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------
def init_db() -> None:
    """Create the order_queue table if it does not already exist."""
    try:
        Base.metadata.create_all(bind=_engine)
        logger.info("Order queue DB initialised.")
    except Exception:
        logger.exception("Failed to initialise order queue DB.")


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------
def enqueue_order(endpoint: str, payload: dict) -> int | None:
    """
    Persist a new order with status='pending'.
    Returns the database row ID on success, None on failure.
    """
    try:
        entry = PersistentOrder(
            endpoint=endpoint,
            payload_json=json.dumps(payload),
            status="pending",
        )
        _db_session.add(entry)
        _db_session.commit()
        logger.debug(
            "Enqueued order id=%d endpoint=%s symbol=%s",
            entry.id,
            endpoint,
            payload.get("symbol", "?"),
        )
        return entry.id
    except Exception:
        logger.exception("Failed to enqueue order.")
        _db_session.rollback()
        return None


def mark_processing(order_id: int) -> None:
    """Mark an order as actively being processed (prevents duplicate pick-up)."""
    try:
        entry = _db_session.get(PersistentOrder, order_id)
        if entry:
            entry.status = "processing"
            entry.updated_at = datetime.utcnow()
            _db_session.commit()
    except Exception:
        logger.exception("Failed to mark order %d as processing.", order_id)
        _db_session.rollback()


def mark_sent(order_id: int) -> None:
    """Mark an order as successfully delivered to the broker API."""
    try:
        entry = _db_session.get(PersistentOrder, order_id)
        if entry:
            entry.status = "sent"
            entry.sent_at = datetime.utcnow()
            entry.updated_at = datetime.utcnow()
            _db_session.commit()
    except Exception:
        logger.exception("Failed to mark order %d as sent.", order_id)
        _db_session.rollback()


def mark_failed(order_id: int, error: str = "") -> None:
    """
    Record a delivery failure.
    - If retry_count < MAX_RETRIES: reset to 'pending' for retry.
    - If retry_count >= MAX_RETRIES: move to 'failed' (dead-letter).
    """
    try:
        entry = _db_session.get(PersistentOrder, order_id)
        if entry:
            entry.retry_count += 1
            entry.error_message = error[:500]
            entry.updated_at = datetime.utcnow()
            if entry.retry_count >= MAX_RETRIES:
                entry.status = "failed"
                payload = entry.get_payload()
                logger.warning(
                    "Order id=%d symbol=%s moved to dead-letter after %d attempts. "
                    "Last error: %s",
                    order_id,
                    payload.get("symbol", "?"),
                    MAX_RETRIES,
                    error[:200],
                )
            else:
                entry.status = "pending"
            _db_session.commit()
    except Exception:
        logger.exception("Failed to update failure status for order %d.", order_id)
        _db_session.rollback()


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------
def fetch_next_pending(endpoint: str) -> PersistentOrder | None:
    """Fetch the oldest pending order for the given endpoint, or None if empty."""
    try:
        return (
            PersistentOrder.query.filter_by(endpoint=endpoint, status="pending")
            .order_by(PersistentOrder.created_at.asc())
            .first()
        )
    except Exception:
        logger.exception("Failed to fetch next pending order for endpoint=%s.", endpoint)
        return None


def recover_stale_processing_orders() -> int:
    """
    On startup, reset any orders stuck in 'processing' back to 'pending'.
    These are orders that were mid-flight when the process was killed last time.
    Returns the number of orders recovered.
    """
    try:
        stale = PersistentOrder.query.filter_by(status="processing").all()
        count = len(stale)
        for entry in stale:
            entry.status = "pending"
            entry.updated_at = datetime.utcnow()
        _db_session.commit()
        if count:
            logger.warning(
                "Recovered %d stale 'processing' order(s) from the previous session.", count
            )
        return count
    except Exception:
        logger.exception("Failed to recover stale processing orders.")
        _db_session.rollback()
        return 0


def get_failed_orders(limit: int = 50) -> list[dict]:
    """Return the most recent dead-letter (failed) orders — for display in the UI/logs."""
    try:
        rows = (
            PersistentOrder.query.filter_by(status="failed")
            .order_by(PersistentOrder.updated_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "endpoint": r.endpoint,
                "symbol": r.get_payload().get("symbol", "?"),
                "strategy": r.get_payload().get("strategy", "?"),
                "retry_count": r.retry_count,
                "error": r.error_message,
                "created_at": str(r.created_at),
            }
            for r in rows
        ]
    except Exception:
        logger.exception("Failed to fetch failed orders.")
        return []


def queue_depth() -> dict:
    """Return per-status order counts — useful for monitoring dashboards."""
    try:
        rows = (
            _db_session.query(PersistentOrder.status, func.count(PersistentOrder.id))
            .group_by(PersistentOrder.status)
            .all()
        )
        return {status: count for status, count in rows}
    except Exception:
        logger.exception("Failed to get queue depth.")
        return {}
