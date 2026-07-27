"""
WhatsApp Alert Service — outbound notifier.

Mirrors services/telegram_alert_service.py one-for-one: a small ThreadPoolExecutor
dispatches send calls asynchronously so the publisher (eventbus worker, REST
handler) is never blocked. send_order_alert() is the single entry point that
the event-bus subscriber wraps; it formats the order/position/batch payload
using the same templates as the Telegram service, prefixes LIVE/ANALYZE mode,
and hands it to the bot service for transmission.

The actual WhatsApp protocol work happens inside wars (Rust). This module
never touches sockets, keys, or the Signal Protocol — it only formats text
and asks the bot service to send it.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from database.auth_db import get_username_by_apikey
from database.whatsapp_db import (
    add_notification,
    get_all_whatsapp_users,
    get_bot_config,
    get_whatsapp_user_by_username,
)
from utils.logging import get_logger

logger = get_logger(__name__)

# Non-blocking dispatch pool. Bounded so a flood of orders can't spawn
# unbounded threads. Matches the size of the Telegram alert pool.
alert_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="whatsapp_alert")


class WhatsAppAlertService:
    """Format order events and dispatch them to linked WhatsApp users."""

    def __init__(self) -> None:
        self.enabled = True
        # Plain-text templates (no Markdown). WhatsApp's *bold*, _italic_,
        # ```mono``` markup is preserved as-is.
        self.alert_templates = {
            "placeorder": "*Order Placed*\n{details}",
            "placesmartorder": "*Smart Order Placed*\n{details}",
            "basketorder": "*Basket Order Executed*\n{details}",
            "splitorder": "*Split Order Executed*\n{details}",
            "optionsorder": "*Options Order Executed*\n{details}",
            "optionsmultiorder": "*Options Multi-Order Executed*\n{details}",
            "modifyorder": "*Order Modified*\n{details}",
            "cancelorder": "*Order Cancelled*\n{details}",
            "cancelallorder": "*All Orders Cancelled*\n{details}",
            "closeposition": "*Position Closed*\n{details}",
        }

    # ------------------------------------------------------------------
    # Formatting — kept symmetric with telegram_alert_service so users see
    # the same fields and tone on both channels.
    # ------------------------------------------------------------------

    def format_order_details(
        self,
        order_type: str,
        order_data: dict[str, Any],
        response: dict[str, Any],
    ) -> str:
        try:
            lines: list[str] = []
            timestamp = datetime.now().strftime("%H:%M:%S")

            mode = response.get("mode", "live")
            if mode == "analyze":
                lines.append("*ANALYZE MODE - No Real Order*")
            else:
                lines.append("*LIVE MODE - Real Order*")
            lines.append("---------------------")

            if order_type == "placeorder":
                lines.extend(
                    [
                        f"Symbol: {order_data.get('symbol', 'N/A')}",
                        f"Action: {order_data.get('action', 'N/A')}",
                        f"Quantity: {order_data.get('quantity', 'N/A')}",
                        f"Price Type: {order_data.get('pricetype', 'N/A')}",
                        f"Exchange: {order_data.get('exchange', 'N/A')}",
                        f"Product: {order_data.get('product', 'N/A')}",
                    ]
                )
                if response.get("status") == "success":
                    lines.append(f"Order ID: {response.get('orderid', 'N/A')}")
                else:
                    lines.append(f"Error: {response.get('message', 'Failed')}")

            elif order_type == "placesmartorder":
                lines.extend(
                    [
                        f"Symbol: {order_data.get('symbol', 'N/A')}",
                        f"Action: {order_data.get('action', 'N/A')}",
                        f"Quantity: {order_data.get('quantity', 'N/A')}",
                        f"Position Size: {order_data.get('position_size', 'N/A')}",
                        f"Exchange: {order_data.get('exchange', 'N/A')}",
                    ]
                )
                if response.get("status") == "success":
                    lines.append(f"Order ID: {response.get('orderid', 'N/A')}")

            elif order_type == "basketorder":
                if response.get("status") == "success":
                    results = response.get("results", [])
                    success_count = len([r for r in results if r.get("status") == "success"])
                    failed_count = len(results) - success_count
                    lines.extend(
                        [
                            f"Total Orders: {len(results)}",
                            f"Successful: {success_count}",
                            f"Failed: {failed_count}",
                        ]
                    )
                    for r in results[:3]:
                        mark = "OK" if r.get("status") == "success" else "X"
                        lines.append(
                            f"[{mark}] {r.get('symbol', 'N/A')}: "
                            f"{r.get('orderid', r.get('message', 'N/A'))}"
                        )
                    if len(results) > 3:
                        lines.append(f"... and {len(results) - 3} more")

            elif order_type == "splitorder":
                results = response.get("results", [])
                success_count = len([r for r in results if r.get("status") == "success"])
                failed_count = len(results) - success_count
                lines.extend(
                    [
                        f"Symbol: {order_data.get('symbol', 'N/A')}",
                        f"Total Quantity: {response.get('total_quantity', 'N/A')}",
                        f"Split Size: {response.get('split_size', 'N/A')}",
                        f"Total Orders: {len(results)}",
                        f"Successful: {success_count}",
                        f"Failed: {failed_count}",
                    ]
                )
                if failed_count > 0 and success_count == 0:
                    lines.append("All orders rejected")
                elif failed_count > 0:
                    lines.append("Partial fill")
                    first_fail = next(
                        (r for r in results if r.get("status") != "success"), None
                    )
                    if first_fail and first_fail.get("message"):
                        lines.append(f"Reason: {first_fail['message']}")

            elif order_type == "modifyorder":
                lines.extend(
                    [
                        f"Order ID: {order_data.get('orderid', 'N/A')}",
                        f"Symbol: {order_data.get('symbol', 'N/A')}",
                        f"New Quantity: {order_data.get('quantity', 'N/A')}",
                        f"New Price: {order_data.get('price', 'N/A')}",
                    ]
                )
                lines.append(
                    "Modification Successful"
                    if response.get("status") == "success"
                    else f"Error: {response.get('message', 'Failed')}"
                )

            elif order_type == "cancelorder":
                lines.append(f"Order ID: {order_data.get('orderid', 'N/A')}")
                lines.append(
                    "Cancellation Successful"
                    if response.get("status") == "success"
                    else f"Error: {response.get('message', 'Failed')}"
                )

            elif order_type == "cancelallorder":
                if response.get("status") == "success":
                    canceled = response.get("canceled_orders", [])
                    failed = response.get("failed_cancellations", [])
                    lines.extend(
                        [
                            f"Cancelled: {len(canceled)} orders",
                            f"Failed: {len(failed)} orders",
                        ]
                    )
                    if canceled and len(canceled) <= 5:
                        lines.append(f"Order IDs: {', '.join(canceled[:5])}")

            elif order_type == "closeposition":
                if response.get("status") == "success":
                    if order_data.get("symbol"):
                        lines.extend(
                            [
                                f"Symbol: {order_data.get('symbol', 'N/A')}",
                                f"Exchange: {order_data.get('exchange', 'N/A')}",
                                f"Product: {order_data.get('product', 'N/A')}",
                                f"Order ID: {response.get('orderid', 'N/A')}",
                            ]
                        )
                    else:
                        closed = response.get("closed_positions", 0)
                        failed = response.get("failed_closures", 0)
                        if closed or failed:
                            lines.extend(
                                [
                                    f"Closed: {closed} positions",
                                    f"Failed: {failed} positions",
                                ]
                            )
                        else:
                            lines.append("All positions closed successfully")
                else:
                    lines.append(f"Error: {response.get('message', 'Failed')}")

            elif order_type in ("optionsorder", "optionsmultiorder"):
                lines.append(f"Underlying: {order_data.get('underlying', 'N/A')}")
                results = response.get("results", [])
                if response.get("status") == "success":
                    success_count = len([r for r in results if r.get("status") == "success"])
                    failed_count = len(results) - success_count
                    if results:
                        lines.extend(
                            [
                                f"Total Legs: {len(results)}",
                                f"Successful: {success_count}",
                                f"Failed: {failed_count}",
                            ]
                        )
                        for r in results[:5]:
                            mark = "OK" if r.get("status") == "success" else "X"
                            symbol = r.get("symbol", "N/A")
                            action = r.get("action", "")
                            oid = r.get("orderid", r.get("message", "N/A"))
                            lines.append(f"[{mark}] {symbol} {action} -> {oid}")
                    if response.get("underlying_ltp"):
                        lines.append(f"Underlying LTP: {response.get('underlying_ltp')}")
                else:
                    lines.append(f"Error: {response.get('message', 'Failed')}")

            lines.append(f"Time: {timestamp}")

            if order_data.get("strategy"):
                lines.insert(0, f"Strategy: {order_data.get('strategy')}")

            return "\n".join(lines)

        except Exception:
            logger.exception("Error formatting WhatsApp order details")
            return f"Order Type: {order_type}\nStatus: {response.get('status', 'unknown')}"

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
            logger.debug("WhatsApp alert dropped: bot not paired/connected")
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

            template = self.alert_templates.get(order_type, "*Order Update*\n{details}")
            details = self.format_order_details(order_type, order_data, response)
            message = template.format(details=details)

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
