"""The groups of order events a trader can route to each alert channel.

The /alerts page shows one row per group and one column per channel. A group
is the smallest thing a trader decides about: "tell me on Slack when a GTT
fires" is a sensible choice, "tell me about gtt.modified but not gtt.placed"
is not one anybody makes.

Only events that report something that happened are here. Failures and
validation errors (``order.failed``, ``analyzer.error`` and the like) have
never been sent to Telegram or WhatsApp, because a script retrying a bad order
turns every chat into a stream of rejections. They stay off every channel.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertCategory:
    """One group of order events, as the /alerts page shows it.

    Attributes:
        id: Stable identifier stored with each channel's settings.
        label: What the trader reads.
        description: One sentence on what the group covers.
        topics: The event-bus topics that belong to the group.
    """

    id: str
    label: str
    description: str
    topics: tuple[str, ...]


CATEGORIES: tuple[AlertCategory, ...] = (
    AlertCategory(
        id="orders_placed",
        label="Orders placed",
        description="New orders, and smart orders that found nothing to change.",
        topics=("order.placed", "order.no_action"),
    ),
    AlertCategory(
        id="orders_modified",
        label="Orders modified",
        description="A change to the price or quantity of an open order.",
        topics=("order.modified",),
    ),
    AlertCategory(
        id="orders_cancelled",
        label="Orders cancelled",
        description="One order cancelled, or every open order cancelled at once.",
        topics=("order.cancelled", "orders.all_cancelled"),
    ),
    AlertCategory(
        id="positions_closed",
        label="Positions closed",
        description="One position or every open position squared off.",
        topics=("position.closed",),
    ),
    AlertCategory(
        id="batch_orders",
        label="Basket, split and options orders",
        description="Orders sent together, with how many went through.",
        topics=(
            "basket.completed",
            "split.completed",
            "options.completed",
            "multiorder.completed",
        ),
    ),
    AlertCategory(
        id="gtt_orders",
        label="GTT orders",
        description="GTT orders placed, modified, cancelled, triggered or expired.",
        topics=("gtt.placed", "gtt.modified", "gtt.cancelled", "gtt.triggered", "gtt.expired"),
    ),
)

#: Every group id, in the order the page shows them.
CATEGORY_IDS: tuple[str, ...] = tuple(category.id for category in CATEGORIES)

#: Which group an order topic belongs to. A topic missing here raises no alert.
CATEGORY_BY_TOPIC: dict[str, str] = {
    topic: category.id for category in CATEGORIES for topic in category.topics
}

#: The order topics that raise an alert, for the subscriber to register.
ALERT_TOPICS: tuple[str, ...] = tuple(CATEGORY_BY_TOPIC)
