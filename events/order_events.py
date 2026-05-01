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


# -----------------------------------------------------------------------------
# GTT (Good Till Triggered) events
# -----------------------------------------------------------------------------


@dataclass
class GTTPlacedEvent(OrderEvent):
    """Fired when a GTT trigger is successfully placed (live or analyze)."""

    topic: str = "gtt.placed"
    strategy: str = ""
    symbol: str = ""
    exchange: str = ""
    trigger_type: str = ""  # "single" or "two-leg"
    trigger_id: str = ""
    trigger_prices: list = field(default_factory=list)


@dataclass
class GTTFailedEvent(OrderEvent):
    """Fired when GTT placement fails (broker rejection, validation, module missing)."""

    topic: str = "gtt.failed"
    symbol: str = ""
    exchange: str = ""
    trigger_type: str = ""
    error_message: str = ""


@dataclass
class GTTModifiedEvent(OrderEvent):
    """Fired when an active GTT is successfully modified."""

    topic: str = "gtt.modified"
    symbol: str = ""
    exchange: str = ""
    trigger_id: str = ""


@dataclass
class GTTModifyFailedEvent(OrderEvent):
    """Fired when a GTT modification fails."""

    topic: str = "gtt.modify_failed"
    symbol: str = ""
    trigger_id: str = ""
    error_message: str = ""


@dataclass
class GTTCancelledEvent(OrderEvent):
    """Fired when an active GTT is successfully cancelled."""

    topic: str = "gtt.cancelled"
    trigger_id: str = ""
    status: str = ""


@dataclass
class GTTCancelFailedEvent(OrderEvent):
    """Fired when a GTT cancellation fails."""

    topic: str = "gtt.cancel_failed"
    trigger_id: str = ""
    error_message: str = ""


@dataclass
class GTTTriggeredEvent(OrderEvent):
    """Fired when a GTT trigger condition is met and the underlying order is placed."""

    topic: str = "gtt.triggered"
    symbol: str = ""
    exchange: str = ""
    trigger_id: str = ""
    triggered_order_id: str = ""


@dataclass
class GTTExpiredEvent(OrderEvent):
    """Fired when a GTT expires without firing (beyond expires_at)."""

    topic: str = "gtt.expired"
    symbol: str = ""
    exchange: str = ""
    trigger_id: str = ""
