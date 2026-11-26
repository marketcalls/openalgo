"""Every alert channel, in the order the /alerts page shows them.

Adding a channel is one line here and one class under ``channels/``. The alert
subscriber, the /alerts API and the page all read this tuple, so nothing else
changes.
"""

from __future__ import annotations

from services.alerts.channels.base import AlertChannel
from services.alerts.channels.discord import DiscordChannel
from services.alerts.channels.slack import SlackChannel
from services.alerts.channels.telegram import TelegramChannel
from services.alerts.channels.webhook import WebhookChannel
from services.alerts.channels.whatsapp import WhatsAppChannel

CHANNELS: tuple[AlertChannel, ...] = (
    TelegramChannel(),
    WhatsAppChannel(),
    SlackChannel(),
    DiscordChannel(),
)

_BY_NAME: dict[str, AlertChannel] = {channel.name: channel for channel in CHANNELS}


def get_channel(name: str) -> AlertChannel | None:
    """The channel called ``name``, or None."""
    return _BY_NAME.get(name)


def get_webhook_channel(name: str) -> WebhookChannel | None:
    """The webhook channel called ``name``, or None for any other name."""
    channel = _BY_NAME.get(name)
    return channel if isinstance(channel, WebhookChannel) else None
