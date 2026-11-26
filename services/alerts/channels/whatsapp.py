"""Order alerts to WhatsApp, through the existing WhatsApp alert service.

WhatsApp's own rules are unchanged and still decided by
``services/whatsapp_alert_service.py``: an alert goes to the paired device's
owner, and only while the device is paired and connected. This adapter adds
the /alerts page's switch and event routing in front of them.
"""

from __future__ import annotations

from events.alert_events import AlertRaisedEvent
from services.alerts.channels.base import TEST_MESSAGE, AlertChannel, ChannelStatus, DeliveryResult


class WhatsAppChannel(AlertChannel):
    """WhatsApp, through the paired OpenAlgo WhatsApp device."""

    name = "whatsapp"
    label = "WhatsApp"
    setup_path = "/whatsapp"

    def status(self) -> ChannelStatus:
        from database.whatsapp_db import get_bot_config
        from services.whatsapp_bot_service import whatsapp_bot_service

        if not (get_bot_config() or {}).get("is_paired"):
            return ChannelStatus(
                configured=False,
                ready=False,
                detail="No device is paired. Pair one on the WhatsApp page.",
            )
        if not whatsapp_bot_service.is_ready():
            reason = whatsapp_bot_service.unavailable_reason()
            return ChannelStatus(
                configured=True,
                ready=False,
                detail=reason or "The paired device is not connected. Open the WhatsApp page.",
            )
        return ChannelStatus(
            configured=True,
            ready=True,
            detail="Paired and connected. Alerts go to the paired number.",
        )

    def deliver(self, alert: AlertRaisedEvent) -> None:
        from services.whatsapp_alert_service import whatsapp_alert_service

        whatsapp_alert_service.send_order_alert(
            alert.api_type, alert.request_data, alert.response_data, alert.api_key
        )

    def send_test(self) -> DeliveryResult:
        from services.whatsapp_alert_service import whatsapp_alert_service

        state = self.status()
        if not state.ready:
            return DeliveryResult(delivered=False, message=state.detail)
        # An empty recipient sends to the paired device's own number, which is
        # where order alerts go.
        if whatsapp_alert_service.send_alert_sync("", TEST_MESSAGE):
            return DeliveryResult(delivered=True, message="Test message sent to WhatsApp.")
        return DeliveryResult(
            delivered=False,
            message="WhatsApp did not accept the test message. Open the WhatsApp page and "
            "check that the device is still connected.",
        )
