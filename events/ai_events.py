# events/ai_events.py
"""Event types for AI agent operations."""

from dataclasses import dataclass, field

from events.base import OrderEvent


@dataclass
class AgentAnalysisEvent(OrderEvent):
    """Fired when AI agent completes an analysis."""

    topic: str = "agent.analysis"
    symbol: str = ""
    exchange: str = ""
    signal: str = ""
    confidence: float = 0.0
    score: float = 0.0
    regime: str = ""


@dataclass
class AgentOrderEvent(OrderEvent):
    """Fired when AI agent places or recommends an order."""

    topic: str = "agent.order"
    symbol: str = ""
    exchange: str = ""
    action: str = ""
    quantity: int = 0
    reason: str = ""
    signal_score: float = 0.0


@dataclass
class AgentErrorEvent(OrderEvent):
    """Fired when AI agent encounters an error."""

    topic: str = "agent.error"
    symbol: str = ""
    error_message: str = ""
    operation: str = ""
