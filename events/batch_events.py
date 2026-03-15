"""Events for batch/compound order operations: basket, split, options, multi-order."""

from dataclasses import dataclass, field

from events.base import OrderEvent


@dataclass
class BasketCompletedEvent(OrderEvent):
    """Fired once after all orders in a basket complete."""

    topic: str = "basket.completed"
    strategy: str = ""
    results: list = field(default_factory=list)
    successful: int = 0
    total: int = 0


@dataclass
class SplitCompletedEvent(OrderEvent):
    """Fired once after all split sub-orders complete."""

    topic: str = "split.completed"
    strategy: str = ""
    symbol: str = ""
    exchange: str = ""
    action: str = ""
    pricetype: str = ""
    product: str = ""
    total_quantity: int = 0
    split_size: int = 0
    results: list = field(default_factory=list)
    successful: int = 0
    total: int = 0


@dataclass
class OptionsOrderCompletedEvent(OrderEvent):
    """Fired once after an options order (split path) completes all sub-orders."""

    topic: str = "options.completed"
    strategy: str = ""
    symbol: str = ""
    exchange: str = ""
    action: str = ""
    pricetype: str = ""
    product: str = ""
    results: list = field(default_factory=list)
    successful: int = 0
    total: int = 0


@dataclass
class MultiOrderCompletedEvent(OrderEvent):
    """Fired once after all legs of a multi-order complete."""

    topic: str = "multiorder.completed"
    strategy: str = ""
    underlying: str = ""
    exchange: str = ""
    results: list = field(default_factory=list)
    successful_legs: int = 0
    failed_legs: int = 0
    total: int = 0
