# ai/agent_decisions.py
"""Decision logging and audit trail for AI agent operations.

Thin wrapper around database/ai_db.py that also publishes events
to the event bus for real-time subscriber notification.
"""

from database.ai_db import get_decisions, save_decision
from events.ai_events import AgentAnalysisEvent, AgentErrorEvent, AgentOrderEvent
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)


def log_analysis(
    user_id: str,
    symbol: str,
    exchange: str,
    interval: str,
    signal: str,
    confidence: float,
    score: float,
    regime: str,
    scores: dict | None = None,
    predicted_price: float | None = None,
    api_key: str = "",
) -> dict:
    """Log an AI analysis result to the database and publish an event.

    Args:
        user_id: The user who triggered the analysis.
        symbol: Trading symbol (e.g., "SBIN").
        exchange: Exchange code (e.g., "NSE").
        interval: Timeframe (e.g., "1d", "5m").
        signal: Signal output (e.g., "BUY", "SELL", "HOLD").
        confidence: Confidence percentage (0-100).
        score: Composite signal score.
        regime: Market regime (e.g., "TRENDING_UP", "RANGING").
        scores: Optional sub-score breakdown dict.
        predicted_price: Price at the time of prediction.
        api_key: API key for event context.

    Returns:
        The saved decision as a dict.
    """
    decision_data = {
        "user_id": user_id,
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "signal": signal,
        "confidence": confidence,
        "score": score,
        "regime": regime,
        "scores": scores or {},
        "predicted_price": predicted_price,
    }

    record = save_decision(decision_data)
    logger.info(f"AI decision logged: {symbol} ({exchange}) -> {signal} (confidence={confidence:.1f}%)")

    # Publish event for real-time subscribers
    bus.publish(
        AgentAnalysisEvent(
            symbol=symbol,
            exchange=exchange,
            signal=signal,
            confidence=confidence,
            score=score,
            regime=regime,
            api_key=api_key,
        )
    )

    return record.to_dict()


def log_order(
    user_id: str,
    symbol: str,
    exchange: str,
    interval: str,
    signal: str,
    confidence: float,
    score: float,
    regime: str,
    action_taken: str,
    order_id: str | None = None,
    reason: str = "",
    quantity: int = 0,
    scores: dict | None = None,
    api_key: str = "",
) -> dict:
    """Log an AI-driven order decision and publish an event.

    Args:
        user_id: The user who triggered the order.
        symbol: Trading symbol.
        exchange: Exchange code.
        interval: Timeframe.
        signal: Signal that triggered the order.
        confidence: Confidence percentage.
        score: Composite signal score.
        regime: Market regime.
        action_taken: Order action (e.g., "BUY", "SELL").
        order_id: Broker order ID (if placed).
        reason: Human-readable reason for the action.
        quantity: Order quantity.
        scores: Optional sub-score breakdown dict.
        api_key: API key for event context.

    Returns:
        The saved decision as a dict.
    """
    decision_data = {
        "user_id": user_id,
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "signal": signal,
        "confidence": confidence,
        "score": score,
        "regime": regime,
        "scores": scores or {},
        "action_taken": action_taken,
        "order_id": order_id,
        "reason": reason,
    }

    record = save_decision(decision_data)
    logger.info(f"AI order logged: {action_taken} {quantity}x {symbol} ({exchange}) order_id={order_id}")

    # Publish event for real-time subscribers
    bus.publish(
        AgentOrderEvent(
            symbol=symbol,
            exchange=exchange,
            action=action_taken,
            quantity=quantity,
            reason=reason,
            signal_score=score,
            api_key=api_key,
        )
    )

    return record.to_dict()


def log_error(
    symbol: str,
    operation: str,
    error_message: str,
    api_key: str = "",
) -> None:
    """Log an AI agent error and publish an event.

    Args:
        symbol: Trading symbol where the error occurred.
        operation: Operation that failed (e.g., "analysis", "order").
        error_message: Error description.
        api_key: API key for event context.
    """
    logger.error(f"AI error: {operation} on {symbol} - {error_message}")

    bus.publish(
        AgentErrorEvent(
            symbol=symbol,
            error_message=error_message,
            operation=operation,
            api_key=api_key,
        )
    )


def get_decision_history(user_id: str, symbol: str | None = None, limit: int = 50) -> list[dict]:
    """Get recent AI decisions for a user.

    Args:
        user_id: User identifier.
        symbol: Optional symbol filter.
        limit: Maximum number of records to return.

    Returns:
        List of decision dicts, newest first.
    """
    return get_decisions(user_id, symbol=symbol, limit=limit)
