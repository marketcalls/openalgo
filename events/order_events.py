"""Events for single order operations: place, smart-order, modify, cancel."""

from dataclasses import dataclass, field

from events.base import OrderEvent


@dataclass
class OrderPlacedEvent(OrderEvent):
    """Fired when a single order is successfully placed (live or analyze)."""

    topic: str = "order.placed"
    strategy: str = ""
    symbol: str = ""
    exchange: str = ""
    action: str = ""
    quantity: int = 0
    pricetype: str = ""
    product: str = ""
    orderid: str = ""


@dataclass
class OrderFailedEvent(OrderEvent):
    """Fired when a single order fails (broker rejection, validation, module not found)."""

    topic: str = "order.failed"
    symbol: str = ""
    exchange: str = ""
    error_message: str = ""


@dataclass
class SmartOrderNoActionEvent(OrderEvent):
    """Fired when a smart order determines no action is needed."""

    topic: str = "order.no_action"
    symbol: str = ""
    exchange: str = ""
    message: str = ""


@dataclass
class OrderModifiedEvent(OrderEvent):
    """Fired when an order is successfully modified."""

    topic: str = "order.modified"
    symbol: str = ""
    exchange: str = ""
    orderid: str = ""


@dataclass
class OrderModifyFailedEvent(OrderEvent):
    """Fired when an order modification fails."""

    topic: str = "order.modify_failed"
    symbol: str = ""
    orderid: str = ""
    error_message: str = ""


@dataclass
class OrderCancelledEvent(OrderEvent):
    """Fired when a single order is successfully cancelled."""

    topic: str = "order.cancelled"
    orderid: str = ""
    status: str = ""


@dataclass
class OrderCancelFailedEvent(OrderEvent):
    """Fired when a single order cancellation fails."""

    topic: str = "order.cancel_failed"
    orderid: str = ""
    error_message: str = ""
