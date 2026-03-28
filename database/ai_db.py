# database/ai_db.py
"""AI agent decision persistence.

Stores analysis results and agent decisions for audit trail.
Uses raw SQLAlchemy (same pattern as auth_db.py, NOT Flask-SQLAlchemy).
Separate DB file: db/ai.db (follows OpenAlgo's multi-DB isolation pattern).
"""

import json
import os
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)

# AI database path (separate DB, follows OpenAlgo's 5-DB pattern)
AI_DATABASE_URL = os.getenv("AI_DATABASE_URL", "sqlite:///db/ai.db")
ai_engine = create_engine(AI_DATABASE_URL, poolclass=NullPool)
ai_session_factory = sessionmaker(bind=ai_engine)
AiSession = scoped_session(ai_session_factory)
AiBase = declarative_base()


class AiDecision(AiBase):
    """Stores every AI analysis + decision for audit."""

    __tablename__ = "ai_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    user_id = Column(String(100), nullable=False)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(10), nullable=False, default="NSE")
    interval = Column(String(10), nullable=False, default="1d")

    # Signal output
    signal = Column(String(20), nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)
    score = Column(Float, nullable=False, default=0.0)
    regime = Column(String(20), nullable=False, default="RANGING")
    sub_scores_json = Column(Text, nullable=True)

    # Action taken (if any)
    action_taken = Column(String(20), nullable=True)
    order_id = Column(String(50), nullable=True)
    reason = Column(Text, nullable=True)

    # Outcome tracking (Self-Learning / Option 2)
    predicted_price = Column(Float, nullable=True)
    actual_price = Column(Float, nullable=True)
    outcome = Column(String(20), nullable=False, default="PENDING")  # PENDING, CORRECT, INCORRECT
    accuracy_score = Column(Float, nullable=True)
    actual_direction = Column(String(10), nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "interval": self.interval,
            "signal": self.signal,
            "confidence": self.confidence,
            "score": self.score,
            "regime": self.regime,
            "sub_scores": json.loads(self.sub_scores_json) if self.sub_scores_json else {},
            "action_taken": self.action_taken,
            "order_id": self.order_id,
            "reason": self.reason,
            "predicted_price": self.predicted_price,
            "actual_price": self.actual_price,
            "outcome": self.outcome,
            "accuracy_score": self.accuracy_score,
            "actual_direction": self.actual_direction,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


def init_ai_db():
    """Create AI tables if they don't exist."""
    AiBase.metadata.create_all(ai_engine)
    logger.info("AI database initialized")


def save_decision(decision_data: dict) -> AiDecision:
    """Save an AI decision record."""
    session = AiSession()
    try:
        record = AiDecision(
            user_id=decision_data.get("user_id", "system"),
            symbol=decision_data["symbol"],
            exchange=decision_data.get("exchange", "NSE"),
            interval=decision_data.get("interval", "1d"),
            signal=decision_data["signal"],
            confidence=decision_data.get("confidence", 0.0),
            score=decision_data.get("score", 0.0),
            regime=decision_data.get("regime", "RANGING"),
            sub_scores_json=json.dumps(decision_data.get("scores", {})),
            action_taken=decision_data.get("action_taken"),
            order_id=decision_data.get("order_id"),
            reason=decision_data.get("reason"),
        )
        session.add(record)
        session.commit()
        return record
    except Exception:
        session.rollback()
        raise
    finally:
        AiSession.remove()


def update_outcome(decision_id: int, outcome_data: dict) -> AiDecision | None:
    """Update an AI decision with the actual outcome."""
    session = AiSession()
    try:
        record = session.query(AiDecision).filter_by(id=decision_id).first()
        if not record:
            return None

        if "actual_price" in outcome_data:
            record.actual_price = outcome_data["actual_price"]
        if "outcome" in outcome_data:
            record.outcome = outcome_data["outcome"]
        if "accuracy_score" in outcome_data:
            record.accuracy_score = outcome_data["accuracy_score"]
        if "actual_direction" in outcome_data:
            record.actual_direction = outcome_data["actual_direction"]
        if "predicted_price" in outcome_data:
            record.predicted_price = outcome_data["predicted_price"]

        record.resolved_at = datetime.now(timezone.utc)
        session.commit()
        return record
    except Exception:
        session.rollback()
        raise
    finally:
        AiSession.remove()


def get_pending_decisions(limit: int = 100) -> list[AiDecision]:
    """Get AI decisions that are still PENDING outcome verification."""
    session = AiSession()
    try:
        return session.query(AiDecision).filter_by(outcome="PENDING").limit(limit).all()
    finally:
        AiSession.remove()


def get_decisions(user_id: str, symbol: str | None = None, limit: int = 50) -> list[dict]:
    """Get recent AI decisions for a user."""
    session = AiSession()
    try:
        query = session.query(AiDecision).filter_by(user_id=user_id)
        if symbol:
            query = query.filter_by(symbol=symbol)
        query = query.order_by(AiDecision.timestamp.desc()).limit(limit)
        return [d.to_dict() for d in query.all()]
    finally:
        AiSession.remove()
