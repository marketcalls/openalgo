"""Order alerts to Telegram, through the existing Telegram alert service.

Telegram's own rules are unchanged and still decided by
``services/telegram_alert_service.py``: alerts go only while the bot is
running, and only to linked accounts with notifications on. This adapter adds
the /alerts page's switch and event routing in front of them.
"""

from __future__ import annotations

from events.alert_events import AlertRaisedEvent
from services.alerts.channels.base import TEST_MESSAGE, AlertChannel, ChannelStatus, DeliveryResult


class TelegramChannel(AlertChannel):
    """Telegram, through the OpenAlgo Telegram bot."""

    name = "telegram"
    label = "Telegram"
    setup_path = "/telegram"

    def status(self) -> ChannelStatus:
        from database.telegram_db import get_bot_config

        config = get_bot_config() or {}
        if not config.get("bot_token"):
            return ChannelStatus(
                configured=False,
                ready=False,
                detail="No bot token is saved. Add one on the Telegram page.",
            )
        if not config.get("is_active"):
            return ChannelStatus(
                configured=True,
                ready=False,
                detail="The bot is stopped. Start it on the Telegram page to receive alerts.",
            )
        recipients = len(_recipients())
        if recipients == 0:
            return ChannelStatus(
                configured=True,
                ready=False,
                detail="The bot is running, but no linked account has notifications on. "
                "Send /link to the bot from Telegram.",
            )
        accounts = "account receives" if recipients == 1 else "accounts receive"
        return ChannelStatus(
            configured=True,
            ready=True,
            detail=f"The bot is running. {recipients} linked {accounts} alerts.",
        )

    def deliver(self, alert: AlertRaisedEvent) -> None:
        from services.telegram_alert_service import telegram_alert_service

        telegram_alert_service.send_order_alert(
            alert.api_type, alert.request_data, alert.response_data, alert.api_key
        )

    def send_test(self) -> DeliveryResult:
        from services.telegram_alert_service import telegram_alert_service

        state = self.status()
        if not state.ready:
            return DeliveryResult(delivered=False, message=state.detail)
        sent = sum(
            1
            for user in _recipients()
            if telegram_alert_service.send_alert_sync(user["telegram_id"], TEST_MESSAGE)
        )
        if sent == 0:
            return DeliveryResult(
                delivered=False,
                message="Telegram did not accept the test message. Check that the bot token "
                "on the Telegram page is still valid.",
            )
        return DeliveryResult(delivered=True, message="Test message sent to Telegram.")


def _recipients() -> list[dict]:
    """Linked Telegram accounts that receive alerts."""
    from database.telegram_db import get_all_telegram_users

    return [user for user in get_all_telegram_users() if user.get("notifications_enabled")]
