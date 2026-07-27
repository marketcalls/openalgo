"""Events for analyzer/validation errors."""

from dataclasses import dataclass

from events.base import OrderEvent


@dataclass
class AnalyzerErrorEvent(OrderEvent):
    """Fired on validation errors or unexpected exceptions (both live and analyze mode)."""

    topic: str = "analyzer.error"
    error_message: str = ""
