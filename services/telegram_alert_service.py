"""
Telegram Alert Service for Order Notifications
Handles sending of order-related alerts to users via Telegram.

Uses httpx.Client (synchronous) to call the Telegram Bot API directly,
avoiding asyncio entirely. This prevents greenlet/eventlet conflicts
under Gunicorn + eventlet deployments.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from database.auth_db import get_username_by_apikey
from database.telegram_db import (
    add_notification,
    get_all_telegram_users,
    get_bot_config,
    get_telegram_user_by_username,
)
from utils.logging import get_logger

logger = get_logger(__name__)

# Thread pool for non-blocking dispatch
alert_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="telegram_alert")

# Synchronous HTTP client for Telegram Bot API calls (thread-safe)
_http_client = httpx.Client(timeout=30.0)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramAlertService:
    """Service for sending order-related alerts via Telegram"""

    def __init__(self):
        self.enabled = True
        self.alert_templates = {
            "placeorder": "📈 *Order Placed*\n{details}",
            "placesmartorder": "🎯 *Smart Order Placed*\n{details}",
            "basketorder": "🛒 *Basket Order Executed*\n{details}",
            "splitorder": "✂️ *Split Order Executed*\n{details}",
            "optionsorder": "📊 *Options Order Executed*\n{details}",
            "optionsmultiorder": "📊 *Options Multi-Order Executed*\n{details}",
            "modifyorder": "✏️ *Order Modified*\n{details}",
            "cancelorder": "❌ *Order Cancelled*\n{details}",
            "cancelallorder": "🚫 *All Orders Cancelled*\n{details}",
            "closeposition": "🔒 *Position Closed*\n{details}",
        }

    def format_order_details(
        self, order_type: str, order_data: dict[str, Any], response: dict[str, Any]
    ) -> str:
        """Format order details for Telegram message"""
        try:
            details = []
            timestamp = datetime.now().strftime("%H:%M:%S")

            # Add mode indicator at the top
            mode = response.get("mode", "live")
            if mode == "analyze":
                details.append("🔬 *ANALYZE MODE - No Real Order*")
                details.append("─────────────────────")
            else:
                details.append("💰 *LIVE MODE - Real Order*")
                details.append("─────────────────────")

            if order_type == "placeorder":
                details.extend(
                    [
                        f"Symbol: `{order_data.get('symbol', 'N/A')}`",
                        f"Action: {order_data.get('action', 'N/A')}",
                        f"Quantity: {order_data.get('quantity', 'N/A')}",
                        f"Price Type: {order_data.get('pricetype', 'N/A')}",
                        f"Exchange: {order_data.get('exchange', 'N/A')}",
                        f"Product: {order_data.get('product', 'N/A')}",
                    ]
                )
                if response.get("status") == "success":
                    details.append(f"Order ID: `{response.get('orderid', 'N/A')}`")
                else:
                    details.append(f"Error: {response.get('message', 'Failed')}")

            elif order_type == "placesmartorder":
                details.extend(
                    [
                        f"Symbol: `{order_data.get('symbol', 'N/A')}`",
                        f"Action: {order_data.get('action', 'N/A')}",
                        f"Quantity: {order_data.get('quantity', 'N/A')}",
                        f"Position Size: {order_data.get('position_size', 'N/A')}",
                        f"Exchange: {order_data.get('exchange', 'N/A')}",
                    ]
                )
                if response.get("status") == "success":
                    details.append(f"Order ID: `{response.get('orderid', 'N/A')}`")

            elif order_type == "basketorder":
                if response.get("status") == "success":
                    results = response.get("results", [])
                    success_count = len([r for r in results if r.get("status") == "success"])
                    failed_count = len([r for r in results if r.get("status") != "success"])
                    details.extend(
                        [
                            f"Total Orders: {len(results)}",
                            f"✅ Successful: {success_count}",
                            f"❌ Failed: {failed_count}",
                        ]
                    )
                    # Add first few order details
                    for result in results[:3]:  # Show first 3 orders
                        status_emoji = "✅" if result.get("status") == "success" else "❌"
                        details.append(
                            f"{status_emoji} {result.get('symbol', 'N/A')}: {result.get('orderid', result.get('message', 'N/A'))}"
                        )
                    if len(results) > 3:
                        details.append(f"... and {len(results) - 3} more")

            elif order_type == "splitorder":
                details.append(f"Symbol: `{order_data.get('symbol', 'N/A')}`")
                results = response.get("results", [])
                success_count = len([r for r in results if r.get("status") == "success"])
                failed_count = len([r for r in results if r.get("status") != "success"])
                details.extend(
                    [
                        f"Total Quantity: {response.get('total_quantity', 'N/A')}",
                        f"Split Size: {response.get('split_size', 'N/A')}",
                        f"Total Orders: {len(results)}",
                        f"✅ Successful: {success_count}",
                        f"❌ Failed: {failed_count}",
                    ]
                )
                if failed_count > 0 and success_count == 0:
                    details.append("⚠️ All orders rejected")
                elif failed_count > 0:
                    details.append("⚠️ Partial fill")
                    # Show first failure reason
                    first_fail = next((r for r in results if r.get("status") != "success"), None)
                    if first_fail and first_fail.get("message"):
                        details.append(f"Reason: {first_fail['message']}")

            elif order_type == "modifyorder":
                details.extend(
                    [
                        f"Order ID: `{order_data.get('orderid', 'N/A')}`",
                        f"Symbol: `{order_data.get('symbol', 'N/A')}`",
                        f"New Quantity: {order_data.get('quantity', 'N/A')}",
                        f"New Price: {order_data.get('price', 'N/A')}",
                    ]
                )
                if response.get("status") == "success":
                    details.append("✅ Modification Successful")
                else:
                    details.append(f"❌ Error: {response.get('message', 'Failed')}")

            elif order_type == "cancelorder":
                details.extend([f"Order ID: `{order_data.get('orderid', 'N/A')}`"])
                if response.get("status") == "success":
                    details.append("✅ Cancellation Successful")
                else:
                    details.append(f"❌ Error: {response.get('message', 'Failed')}")

            elif order_type == "cancelallorder":
                if response.get("status") == "success":
                    canceled = response.get("canceled_orders", [])
                    failed = response.get("failed_cancellations", [])
                    details.extend(
                        [
                            f"✅ Cancelled: {len(canceled)} orders",
                            f"❌ Failed: {len(failed)} orders",
                        ]
                    )
                    if canceled and len(canceled) <= 5:
                        details.append(f"Order IDs: {', '.join(canceled[:5])}")

            elif order_type == "closeposition":
                if response.get("status") == "success":
                    # Individual position close includes symbol details
                    if order_data.get("symbol"):
                        details.extend(
                            [
                                f"Symbol: `{order_data.get('symbol', 'N/A')}`",
                                f"Exchange: {order_data.get('exchange', 'N/A')}",
                                f"Product: {order_data.get('product', 'N/A')}",
                                f"Order ID: `{response.get('orderid', 'N/A')}`",
                            ]
                        )
                    else:
                        closed = response.get("closed_positions", 0)
                        failed = response.get("failed_closures", 0)
                        if closed or failed:
                            details.extend(
                                [
                                    f"✅ Closed: {closed} positions",
                                    f"❌ Failed: {failed} positions",
                                ]
                            )
                        else:
                            details.append("✅ All positions closed successfully")
                else:
                    details.append(f"❌ Error: {response.get('message', 'Failed')}")

            elif order_type == "optionsorder":
                details.append(f"Underlying: `{order_data.get('underlying', 'N/A')}`")
                if response.get("status") == "success":
                    results = response.get("results", [])
                    success_count = len([r for r in results if r.get("status") == "success"])
                    failed_count = len([r for r in results if r.get("status") != "success"])
                    if results:
                        details.extend(
                            [
                                f"Total Orders: {len(results)}",
                                f"✅ Successful: {success_count}",
                                f"❌ Failed: {failed_count}",
                            ]
                        )
                        for result in results[:5]:
                            status_emoji = "✅" if result.get("status") == "success" else "❌"
                            details.append(
                                f"{status_emoji} `{result.get('symbol', 'N/A')}` {result.get('action', '')} → {result.get('orderid', result.get('message', 'N/A'))}"
                            )
                    else:
                        # Single order (non-split)
                        details.extend(
                            [
                                f"Symbol: `{response.get('symbol', order_data.get('symbol', 'N/A'))}`",
                                f"Action: {order_data.get('action', 'N/A')}",
                                f"Quantity: {order_data.get('quantity', 'N/A')}",
                                f"Order ID: `{response.get('orderid', 'N/A')}`",
                            ]
                        )
                else:
                    details.append(f"❌ Error: {response.get('message', 'Failed')}")

            elif order_type == "optionsmultiorder":
                details.append(f"Underlying: `{order_data.get('underlying', 'N/A')}`")
                if response.get("status") == "success":
                    results = response.get("results", [])
                    success_count = len([r for r in results if r.get("status") == "success"])
                    failed_count = len([r for r in results if r.get("status") != "success"])
                    details.extend(
                        [
                            f"Total Legs: {len(results)}",
                            f"✅ Successful: {success_count}",
                            f"❌ Failed: {failed_count}",
                        ]
                    )
                    for result in results:
                        status_emoji = "✅" if result.get("status") == "success" else "❌"
                        symbol = result.get("symbol", "N/A")
                        action = result.get("action", "")
                        oid = result.get("orderid", result.get("message", "N/A"))
                        details.append(f"{status_emoji} `{symbol}` {action} → {oid}")
                    if response.get("underlying_ltp"):
                        details.append(f"Underlying LTP: {response.get('underlying_ltp')}")
                else:
                    details.append(f"❌ Error: {response.get('message', 'Failed')}")

            details.append(f"⏰ Time: {timestamp}")

            # Add strategy if available
            if order_data.get("strategy"):
                details.insert(0, f"Strategy: *{order_data.get('strategy')}*")

            return "\n".join(details)

        except Exception as e:
            logger.exception(f"Error formatting order details: {e}")
            return f"Order Type: {order_type}\nStatus: {response.get('status', 'unknown')}"

    def _get_bot_token(self) -> str | None:
        """Get bot token from database config."""
        try:
            config = get_bot_config()
            if config and config.get("bot_token"):
                return config["bot_token"]
        except Exception as e:
            logger.error(f"Failed to get bot token: {e}")
        return None

    def send_alert_sync(self, telegram_id: int, message: str) -> bool:
        """
        Send alert via synchronous HTTP call to Telegram Bot API.

        Uses httpx.Client directly — no asyncio, no greenlet boundary crossing.
        Safe under Gunicorn + eventlet.
        """
        try:
            bot_token = self._get_bot_token()
            if not bot_token:
                logger.error("No bot token configured, queueing notification")
                add_notification(telegram_id, message, priority=8)
                return False

            url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": telegram_id,
                "text": message,
                "parse_mode": "Markdown",
            }

            resp = _http_client.post(url, json=payload)

            if resp.status_code == 200:
                logger.info(f"Telegram notification sent to {telegram_id}")
                return True

            # If Markdown parsing fails (bad entities), retry as plain text
            if resp.status_code == 400 and "can't parse entities" in resp.text:
                logger.warning(
                    f"Telegram Markdown parse error, retrying as plain text: {resp.text}"
                )
                payload.pop("parse_mode")
                resp = _http_client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info(f"Telegram notification sent (plain text) to {telegram_id}")
                    return True

            logger.error(
                f"Telegram API error {resp.status_code}: {resp.text}"
            )
            add_notification(telegram_id, message, priority=8)
            return False

        except httpx.TimeoutException:
            logger.error("Timeout sending telegram notification")
            add_notification(telegram_id, message, priority=8)
            return False
        except Exception as e:
            logger.exception(f"Error sending telegram alert: {e}")
            add_notification(telegram_id, message, priority=8)
            return False

    def send_order_alert(
        self,
        order_type: str,
        order_data: dict[str, Any],
        response: dict[str, Any],
        api_key: str | None = None,
    ):
        """
        Send order alert to telegram user (non-blocking)

        Args:
            order_type: Type of order (placeorder, basketorder, etc.)
            order_data: Original order data
            response: Order response
            api_key: API key to identify user
        """
        try:
            logger.info(
                f"Telegram alert triggered for {order_type}, response: {response.get('status', 'unknown')}"
            )

            # Skip if alerts are disabled
            if not self.enabled:
                logger.debug("Telegram alerts are disabled globally")
                return

            # Get username from API key
            username = None
            api_key_used = api_key or order_data.get("apikey")

            if api_key_used:
                logger.debug(
                    f"Looking up username for API key (first 10 chars): {api_key_used[:10] if api_key_used else 'None'}..."
                )
                username = get_username_by_apikey(api_key_used)
                logger.debug(f"Username lookup result: {username}")
            else:
                logger.warning("No API key provided for telegram alert")

            if not username:
                logger.warning(
                    f"No username found for telegram alert - api_key present: {bool(api_key_used)}, api_key_length: {len(api_key_used) if api_key_used else 0}"
                )
                # Try to get username from session if available
                try:
                    from flask import has_request_context, session

                    if has_request_context() and session.get("user"):
                        username = session.get("user")
                        logger.info(f"Using username from session: {username}")
                except:
                    pass

                if not username:
                    return

            # Get telegram user
            telegram_user = get_telegram_user_by_username(username)
            if not telegram_user:
                logger.info(f"No telegram user linked for username: {username}")
                return
            if not telegram_user.get("notifications_enabled"):
                logger.info(f"Notifications disabled for telegram user: {username}")
                return

            logger.info(
                f"Sending telegram alert to user {username} (telegram_id: {telegram_user['telegram_id']})"
            )

            # Format message
            template = self.alert_templates.get(order_type, "📊 *Order Update*\n{details}")
            details = self.format_order_details(order_type, order_data, response)
            message = template.format(details=details)

            # Send alert in thread pool (non-blocking)
            telegram_id = telegram_user["telegram_id"]
            logger.info(f"Queueing alert via thread pool for telegram_id: {telegram_id}")
            alert_executor.submit(self.send_alert_sync, telegram_id, message)

            logger.info(f"Telegram alert queued successfully for {order_type}")

        except Exception as e:
            # Log error but don't raise - we don't want to affect order processing
            logger.error(f"Error queuing telegram alert: {e}", exc_info=True)

    # Backward compatibility wrapper
    _send_alert_sync_wrapper = send_alert_sync

    def send_broadcast_alert(self, message: str, filters: dict | None = None):
        """Send broadcast alert to multiple users"""
        try:
            users = get_all_telegram_users(filters)

            for user in users:
                if user.get("notifications_enabled"):
                    telegram_id = user["telegram_id"]
                    alert_executor.submit(self._send_alert_sync_wrapper, telegram_id, message)

        except Exception as e:
            logger.exception(f"Error sending broadcast alert: {e}")

    def toggle_alerts(self, enabled: bool):
        """Enable or disable telegram alerts"""
        self.enabled = enabled
        logger.info(f"Telegram alerts {'enabled' if enabled else 'disabled'}")


# Initialize global instance
telegram_alert_service = TelegramAlertService()
