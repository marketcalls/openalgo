"""Base event with common fields shared by all order events."""

from dataclasses import dataclass, field

from utils.event_bus import Event


@dataclass
class OrderEvent(Event):
    """
    Base for all order-related events.

    Every order event carries:
    - mode: "live" or "analyze" — subscribers branch on this
    - api_type: the operation name used for logging and telegram templates
    - request_data / response_data: dicts for log subscribers
    - api_key: for telegram username resolution
    """

    mode: str = "live"  # "live" or "analyze"
    api_type: str = ""
    request_data: dict = field(default_factory=dict)
    response_data: dict = field(default_factory=dict)
    api_key: str = ""
