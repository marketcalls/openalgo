"""Events for position operations."""

from dataclasses import dataclass, field

from events.base import OrderEvent


@dataclass
class PositionClosedEvent(OrderEvent):
    """Fired when positions are closed (single or all)."""

    topic: str = "position.closed"
    symbol: str = ""
    exchange: str = ""
    product: str = ""
    orderid: str = ""
    message: str = ""


@dataclass
class AllOrdersCancelledEvent(OrderEvent):
    """Fired when cancel-all-orders completes."""

    topic: str = "orders.all_cancelled"
    canceled_count: int = 0
    failed_count: int = 0
    canceled_orders: list = field(default_factory=list)
    failed_cancellations: list = field(default_factory=list)
