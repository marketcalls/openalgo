"""Alerts on the event bus: raise one per order event, then deliver it.

This replaces the per-channel ``telegram_subscriber`` and
``whatsapp_subscriber`` modules, which each subscribed to every order topic
and repeated the same handlers. Now:

- ``raise_alert`` is subscribed to every order topic that has an alert group.
  It publishes one ``AlertRaisedEvent``, and only when at least one channel is
  switched on and receives that group.
- ``deliver_alert`` is the one subscriber of ``alert.raised``. It hands the
  alert to each channel the group is routed to, each in its own ``try``, so a
  channel that fails never stops the others.

**One delivery callback, not one per channel.** A channel's ``deliver`` never
waits on the network: Telegram and WhatsApp queue on their own alert pools,
Slack and Discord on their own lanes. So a slow provider cannot hold this
callback, and an order event costs the bus two alert callbacks, the same two
the Telegram and WhatsApp subscribers took before. A callback per channel would
take a bus slot for every channel on every alert, switched off or not, under
the same cap that order logging and Socket.IO refreshes share.

Failures and validation errors raise no alert, as before: they have no group.
"""

from __future__ import annotations

from events.alert_events import ALERT_TOPIC, AlertRaisedEvent
from events.base import OrderEvent
from services.alerts import router
from services.alerts.categories import ALERT_TOPICS
from services.alerts.registry import CHANNELS
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)


def raise_alert(event: OrderEvent) -> None:
    """Publish the alert an order event raises, if any channel wants it."""
    alert = router.alert_for(event)
    if alert is not None and router.receivers(alert.category, CHANNELS):
        bus.publish(alert)


def deliver_alert(alert: AlertRaisedEvent) -> None:
    """Hand one alert to every channel its group is routed to."""
    for channel in router.receivers(alert.category, CHANNELS):
        try:
            channel.deliver(alert)
        except Exception:
            logger.exception(f"{channel.label} could not take a {alert.category} alert")


def register() -> None:
    """Subscribe alerts to the bus. Called once, from ``subscribers.register_all``."""
    for topic in ALERT_TOPICS:
        bus.subscribe(topic, raise_alert, f"alerts:raise:{topic}")
    bus.subscribe(ALERT_TOPIC, deliver_alert, "alerts:deliver")
