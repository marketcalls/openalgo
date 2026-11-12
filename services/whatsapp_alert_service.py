"""
WhatsApp Alert Service — outbound notifier.

Mirrors services/telegram_alert_service.py one-for-one: a small ThreadPoolExecutor
dispatches send calls asynchronously so the publisher (eventbus worker, REST
handler) is never blocked. send_order_alert() is the single entry point that
the WhatsApp alert channel (services/alerts/channels/whatsapp.py) calls; it
formats the order/position/batch payload with the shared alert formatter
(services/alerts/formatting.py), prefixes LIVE/ANALYZE mode, and hands it to
the bot service for transmission.

The actual WhatsApp protocol work happens inside wars (Rust). This module
never touches sockets, keys, or the Signal Protocol — it only formats text
and asks the bot service to send it.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from database.auth_db import get_username_by_apikey
from database.whatsapp_db import (
    add_notification,
    get_all_whatsapp_users,
    get_bot_config,
    get_whatsapp_user_by_username,
)
from services.alerts.formatting import SEPARATOR, AlertMessage, build_message
from utils.logging import get_logger

logger = get_logger(__name__)

# Non-blocking dispatch pool. Bounded so a flood of orders can't spawn
# unbounded threads. Matches the size of the Telegram alert pool.
alert_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="whatsapp_alert")


class WhatsAppAlertService:
    """Format order events and dispatch them to linked WhatsApp users."""

    def __init__(self) -> None:
        self.enabled = True

    # ------------------------------------------------------------------
    # Formatting. The fields come from services/alerts/formatting.py, which
    # Slack and Discord alerts share; WhatsApp bolds with single asterisks.
    # ------------------------------------------------------------------

    @staticmethod
    def render(message: AlertMessage) -> str:
        """An alert as WhatsApp text: bold title and banner, then the lines."""
        parts = [f"*{message.title}*"]
        if message.strategy:
            parts.append(f"Strategy: {message.strategy}")
        if message.banner:
            parts.extend([f"*{message.banner}*", SEPARATOR])
        parts.extend(message.lines)
        return "\n".join(parts)

    def format_order_alert(
        self,
        order_type: str,
        order_data: dict[str, Any],
        response: dict[str, Any],
    ) -> str:
        """The full WhatsApp message for one order event."""
        return self.render(build_message(order_type, order_data, response))

    # ------------------------------------------------------------------
    # Transmission — delegates to the bot service (which holds the wars
    # client). The bot service does its own input validation; if it's not
    # connected, send_message_sync returns False and we queue for retry.
    # ------------------------------------------------------------------

    def send_alert_sync(
        self,
        whatsapp_jid: str | list[str],
        message: str,
        image_path: str | None = None,
        document_path: str | None = None,
    ) -> bool:
        """Dispatch a single alert via the bot's unified send_sync(). Returns
        True if at least one recipient received the message.

        If WhatsApp isn't paired/connected, we silently drop the alert — we
        do NOT queue. Queueing was misleading: a trader expects order alerts
        to arrive in real time, not days later. Pair from the /whatsapp page
        first, and incoming order events will flow from then on.
        """
        from services.whatsapp_bot_service import whatsapp_bot_service

        if not whatsapp_bot_service.is_ready():
            logger.debug(
                "WhatsApp alert dropped: %s",
                whatsapp_bot_service.unavailable_reason() or "bot not paired/connected",
            )
            return False

        try:
            report = whatsapp_bot_service.send_sync(
                to=whatsapp_jid,
                text=message,
                image=image_path,
                document=document_path,
            )
            return bool(report.get("sent"))
        except Exception:
            logger.exception("Error sending WhatsApp alert")
            return False

    def send_order_alert(
        self,
        order_type: str,
        order_data: dict[str, Any],
        response: dict[str, Any],
        api_key: str | None = None,
    ) -> None:
        """Format the order/position/batch event and dispatch a self-send
        WhatsApp alert to the paired device's owner.

        Single-user OpenAlgo: every order placed via this instance is by the
        operator who paired the WhatsApp device. We confirm that by matching
        the order's api_key→username against `whatsapp_config.owner_username`
        captured at pair time, then fire a self-send through wars's single-
        arg `send("text")` form. We do NOT look up `whatsapp_users` here —
        that table is leftover from a multi-user design and stays empty
        because the `/link` command was removed.

        Legacy fallback (still useful for any explicit /notify usage): if
        the username happens to have a row in `whatsapp_users` (e.g. a
        future multi-recipient deployment), honour it too.
        """
        try:
            if not self.enabled:
                return

            api_key_used = api_key or order_data.get("apikey")
            if not api_key_used:
                logger.debug("WhatsApp alert: no api_key in event, skipping")
                return

            username = get_username_by_apikey(api_key_used)
            if not username:
                try:
                    from flask import has_request_context, session

                    if has_request_context() and session.get("user"):
                        username = session.get("user")
                except Exception:
                    pass

            if not username:
                logger.debug("WhatsApp alert: api_key did not resolve to any user")
                return

            message = self.format_order_alert(order_type, order_data, response)

            # Primary path: send to the paired-device owner. This is the
            # only path that actually fires in the current single-user
            # design — see the class docstring above.
            cfg = get_bot_config()
            owner_username = cfg.get("owner_username")
            if cfg.get("is_paired") and owner_username and username == owner_username:
                # `to=None` triggers wars's single-arg send() → owner. We
                # don't need own_jid (wars 0.1.3 doesn't expose it anyway).
                alert_executor.submit(self.send_alert_sync, "", message)
                logger.info(
                    f"WhatsApp alert queued for owner user={username} type={order_type}"
                )

            # Legacy fan-out for explicit multi-recipient deployments.
            # Empty in the standard single-user setup.
            wa_user = get_whatsapp_user_by_username(username)
            if wa_user and wa_user.get("notifications_enabled"):
                whatsapp_jid = wa_user["whatsapp_jid"]
                alert_executor.submit(self.send_alert_sync, whatsapp_jid, message)
                logger.info(
                    f"WhatsApp alert queued for linked user={username} jid={whatsapp_jid} type={order_type}"
                )

        except Exception:
            # Never let a notification failure bubble back into order placement.
            logger.exception("Error queuing WhatsApp alert")

    def send_broadcast_alert(
        self,
        message: str,
        filters: dict | None = None,
    ) -> tuple[int, int]:
        """Fan out `message` to every linked user matching `filters`.
        Returns (queued_count, skipped_count)."""
        queued = 0
        skipped = 0
        try:
            users = get_all_whatsapp_users(filters)
            for user in users:
                if user.get("notifications_enabled"):
                    alert_executor.submit(
                        self.send_alert_sync, user["whatsapp_jid"], message
                    )
                    queued += 1
                else:
                    skipped += 1
        except Exception:
            logger.exception("Error broadcasting WhatsApp alert")
        return queued, skipped

    def toggle_alerts(self, enabled: bool) -> None:
        self.enabled = enabled
        logger.info(f"WhatsApp alerts {'enabled' if enabled else 'disabled'}")


# Module-level singleton used by the event-bus subscriber.
whatsapp_alert_service = WhatsAppAlertService()
