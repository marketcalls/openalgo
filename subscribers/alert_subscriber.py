"""Alerts on the event bus: raise one per order event, deliver it per channel.

This replaces the per-channel ``telegram_subscriber`` and
``whatsapp_subscriber`` modules, which each subscribed to every order topic
and repeated the same handlers. Now:

- ``raise_alert`` is subscribed to every order topic that has an alert group
  and publishes one ``AlertRaisedEvent`` for it.
- Each channel in ``services/alerts/registry.py`` gets its own subscription to
  that one event. The bus runs each in its own callback, so channels are
  isolated from each other, and a new channel is registered here by the
  registry alone.

Failures and validation errors raise no alert, as before: they have no group.
"""

from __future__ import annotations

from collections.abc import Callable

from events.alert_events import ALERT_TOPIC, AlertRaisedEvent
from events.base import OrderEvent
from services.alerts import router
from services.alerts.categories import ALERT_TOPICS
from services.alerts.channels.base import AlertChannel
from services.alerts.registry import CHANNELS
from utils.event_bus import bus


def raise_alert(event: OrderEvent) -> None:
    """Publish the alert an order event raises."""
    alert = router.alert_for(event)
    if alert is not None:
        bus.publish(alert)


def delivery_to(channel: AlertChannel) -> Callable[[AlertRaisedEvent], None]:
    """The bus callback that delivers alerts to one channel."""

    def deliver(alert: AlertRaisedEvent) -> None:
        router.deliver(channel, alert)

    deliver.__name__ = f"deliver_to_{channel.name}"
    return deliver


def register() -> None:
    """Subscribe alerts to the bus. Called once, from ``subscribers.register_all``."""
    for topic in ALERT_TOPICS:
        bus.subscribe(topic, raise_alert, f"alerts:raise:{topic}")
    for channel in CHANNELS:
        bus.subscribe(ALERT_TOPIC, delivery_to(channel), f"alerts:{channel.name}")
