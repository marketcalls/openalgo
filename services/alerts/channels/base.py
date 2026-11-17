"""What every alert channel provides.

A channel is one way of telling a trader something happened: Telegram,
WhatsApp, Slack, Discord. The alert subscriber hands each channel every alert
it is routed (``deliver``); the /alerts page asks each one how it stands
(``status``) and for a test message (``send_test``). Nothing outside a channel
knows how it sends.

Adding a channel is a subclass of ``AlertChannel`` (or ``WebhookChannel`` for
one that posts to a URL) and one line in ``services/alerts/registry.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from events.alert_events import AlertRaisedEvent

#: The text of every test message, whichever channel sends it.
TEST_MESSAGE = (
    "OpenAlgo test alert. If you can read this, alerts from your OpenAlgo reach this channel."
)


@dataclass(frozen=True)
class ChannelStatus:
    """How a channel stands, for the /alerts page.

    Attributes:
        configured: Set up enough to send at all: a bot token saved, a device
            paired, a webhook saved.
        ready: Would deliver an alert raised right now.
        detail: One sentence for the trader saying why, and what to do if not.
    """

    configured: bool
    ready: bool
    detail: str


@dataclass(frozen=True)
class DeliveryResult:
    """What came of one send the trader is waiting on.

    Attributes:
        delivered: Whether the channel accepted the message.
        message: One sentence for the trader. On failure it names the cause and
            the next step, never a status code.
    """

    delivered: bool
    message: str


class AlertChannel(ABC):
    """One alert channel.

    Attributes:
        name: Stable identifier, used in URLs and stored settings.
        label: The name a trader reads.
        setup_path: The page where the channel is set up.
        uses_webhook: Whether the channel posts to a saved webhook URL.
        enabled_by_default: Whether a channel nobody has changed is on.
            Telegram and WhatsApp are, so alerts keep flowing exactly as they
            did before the /alerts page existed. A webhook channel starts off
            and is turned on when its webhook is saved.
    """

    name: ClassVar[str]
    label: ClassVar[str]
    setup_path: ClassVar[str]
    uses_webhook: ClassVar[bool] = False
    enabled_by_default: ClassVar[bool] = True

    @abstractmethod
    def status(self) -> ChannelStatus:
        """How the channel stands right now."""

    @abstractmethod
    def deliver(self, alert: AlertRaisedEvent) -> None:
        """Send one alert, without waiting for it to arrive.

        Called on an event-bus thread for every alert routed to this channel.
        Must not block on the network: hand the send to the channel's own
        worker pool and return.
        """

    @abstractmethod
    def send_test(self) -> DeliveryResult:
        """Send a test message now and say whether it arrived."""
