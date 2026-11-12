"""The event every alert channel listens to."""

from dataclasses import dataclass

from events.base import OrderEvent

#: The topic alerts are published on.
ALERT_TOPIC = "alert.raised"


@dataclass
class AlertRaisedEvent(OrderEvent):
    """An order event that a trader should be told about.

    Published by ``subscribers.alert_subscriber`` once for each alertable
    order event. Every alert channel (Telegram, WhatsApp, Slack, Discord)
    subscribes to this one topic and decides for itself whether to deliver it,
    so a channel never needs to know which order topics exist, and adding a
    channel never touches the order code.

    It carries the source event's own fields unchanged (``mode``,
    ``api_type``, ``request_data``, ``response_data``, ``api_key``), because
    the Telegram and WhatsApp formatters read them directly.

    Attributes:
        category: The alert group this event belongs to, one of
            ``services.alerts.categories.CATEGORY_IDS``. The /alerts page routes
            groups, not individual topics, to each channel.
        source_topic: The order topic the alert was raised from, for logs.
    """

    topic: str = ALERT_TOPIC
    category: str = ""
    source_topic: str = ""
