# subscribers/ai_subscriber.py
"""Subscribe to AI agent events for logging."""

from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)


def on_agent_analysis(event):
    """Log analysis events."""
    logger.info(
        f"AI Analysis: {event.symbol} ({event.exchange}) -> "
        f"{event.signal} (confidence={event.confidence:.1f}%, score={event.score:.4f}, regime={event.regime})"
    )


def on_agent_order(event):
    """Log order events."""
    logger.info(
        f"AI Order: {event.action} {event.quantity}x {event.symbol} ({event.exchange}) "
        f"-- reason: {event.reason}"
    )


def on_agent_error(event):
    """Log error events."""
    logger.error(f"AI Error: {event.operation} on {event.symbol} -- {event.error_message}")


def register_ai_subscribers():
    """Register all AI event subscribers."""
    bus.subscribe("agent.analysis", on_agent_analysis, name="ai_analysis_logger")
    bus.subscribe("agent.order", on_agent_order, name="ai_order_logger")
    bus.subscribe("agent.error", on_agent_error, name="ai_error_logger")
