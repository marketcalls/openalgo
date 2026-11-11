"""Turning order events into alerts, and alerts into deliveries.

Two steps, both run by ``subscribers/alert_subscriber.py`` on the event bus:

1. ``alert_for`` reads an order event and, if it belongs to an alert group,
   returns the ``AlertRaisedEvent`` to publish.
2. ``deliver`` runs once per channel for every published alert, and hands the
   alert to the channel if the trader routed that group to it.

Each channel's delivery is its own bus callback, so a channel that is slow or
failing never delays or stops another.
"""

from __future__ import annotations

from events.alert_events import AlertRaisedEvent
from events.base import OrderEvent
from services.alerts.categories import CATEGORY_BY_TOPIC
from services.alerts.channels.base import AlertChannel
from services.alerts.settings import settings_for


def alert_for(event: OrderEvent) -> AlertRaisedEvent | None:
    """The alert an order event raises, or None when it raises none."""
    category = CATEGORY_BY_TOPIC.get(event.topic)
    if category is None:
        return None
    return AlertRaisedEvent(
        mode=event.mode,
        api_type=event.api_type,
        request_data=event.request_data,
        response_data=event.response_data,
        api_key=event.api_key,
        category=category,
        source_topic=event.topic,
    )


def deliver(channel: AlertChannel, alert: AlertRaisedEvent) -> bool:
    """Hand ``alert`` to ``channel`` if the trader routed its group there.

    Returns:
        Whether the channel was given the alert. The channel may still decline
        it by its own rules (a stopped Telegram bot, say).
    """
    if not settings_for(channel).receives(alert.category):
        return False
    channel.deliver(alert)
    return True
