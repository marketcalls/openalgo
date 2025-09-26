"""
Telegram Alert Service for Order Notifications
Handles asynchronous sending of order-related alerts to users via Telegram
"""

import asyncio
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from database.telegram_db import (
    get_telegram_user_by_username,
    get_all_telegram_users,
    get_bot_config,
    add_notification
)
from utils.logging import get_logger
from database.auth_db import get_username_by_apikey

# Lazy import telegram bot service to avoid import errors if telegram package not installed properly
telegram_bot_service = None

def _get_telegram_bot_service():
    """Lazy load telegram bot service"""
    global telegram_bot_service
    if telegram_bot_service is None:
        try:
            from services.telegram_bot_service import telegram_bot_service as tbs
            telegram_bot_service = tbs
        except ImportError as e:
            logger.warning(f"Telegram bot service not available: {e}")
            # Create a mock object with minimal interface
            class MockTelegramBotService:
                is_running = False
                bot_loop = None
                async def send_notification(self, *args, **kwargs):
                    return False
            telegram_bot_service = MockTelegramBotService()
    return telegram_bot_service

logger = get_logger(__name__)

# Thread pool for async operations
alert_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="telegram_alert")

class TelegramAlertService:
    """Service for sending order-related alerts via Telegram"""

    def __init__(self):
        self.enabled = True
        self.alert_templates = {
            'placeorder': '📈 *Order Placed*\n{details}',
            'placesmartorder': '🎯 *Smart Order Placed*\n{details}',
            'basketorder': '🛒 *Basket Order Executed*\n{details}',
            'splitorder': '✂️ *Split Order Executed*\n{details}',
            'modifyorder': '✏️ *Order Modified*\n{details}',
            'cancelorder': '❌ *Order Cancelled*\n{details}',
            'cancelallorder': '🚫 *All Orders Cancelled*\n{details}',
            'closeposition': '🔒 *Position Closed*\n{details}'
        }

    def format_order_details(self, order_type: str, order_data: Dict[str, Any], response: Dict[str, Any]) -> str:
        """Format order details for Telegram message"""
        try:
            details = []
            timestamp = datetime.now().strftime('%H:%M:%S')

            # Add mode indicator at the top
            mode = response.get('mode', 'live')
            if mode == 'analyze':
                details.append("🔬 **ANALYZE MODE - No Real Order**")
                details.append("─────────────────────")
            else:
                details.append("💰 **LIVE MODE - Real Order**")
                details.append("─────────────────────")

            if order_type == 'placeorder':
                details.extend([
                    f"Symbol: `{order_data.get('symbol', 'N/A')}`",
                    f"Action: {order_data.get('action', 'N/A')}",
                    f"Quantity: {order_data.get('quantity', 'N/A')}",
                    f"Price Type: {order_data.get('pricetype', 'N/A')}",
                    f"Exchange: {order_data.get('exchange', 'N/A')}",
                    f"Product: {order_data.get('product', 'N/A')}"
                ])
                if response.get('status') == 'success':
                    details.append(f"Order ID: `{response.get('orderid', 'N/A')}`")
                else:
                    details.append(f"Error: {response.get('message', 'Failed')}")

            elif order_type == 'placesmartorder':
                details.extend([
                    f"Symbol: `{order_data.get('symbol', 'N/A')}`",
                    f"Action: {order_data.get('action', 'N/A')}",
                    f"Quantity: {order_data.get('quantity', 'N/A')}",
                    f"Position Size: {order_data.get('position_size', 'N/A')}",
                    f"Exchange: {order_data.get('exchange', 'N/A')}"
                ])
                if response.get('status') == 'success':
                    details.append(f"Order ID: `{response.get('orderid', 'N/A')}`")

            elif order_type == 'basketorder':
                if response.get('status') == 'success':
                    results = response.get('results', [])
                    success_count = len([r for r in results if r.get('status') == 'success'])
                    failed_count = len([r for r in results if r.get('status') != 'success'])
                    details.extend([
                        f"Total Orders: {len(results)}",
                        f"✅ Successful: {success_count}",
                        f"❌ Failed: {failed_count}"
                    ])
                    # Add first few order details
                    for result in results[:3]:  # Show first 3 orders
                        status_emoji = "✅" if result.get('status') == 'success' else "❌"
                        details.append(f"{status_emoji} {result.get('symbol', 'N/A')}: {result.get('orderid', result.get('message', 'N/A'))}")
                    if len(results) > 3:
                        details.append(f"... and {len(results) - 3} more")

            elif order_type == 'splitorder':
                if response.get('status') == 'success':
                    details.extend([
                        f"Symbol: `{order_data.get('symbol', 'N/A')}`",
                        f"Total Quantity: {response.get('total_quantity', 'N/A')}",
                        f"Split Size: {response.get('split_size', 'N/A')}",
                        f"Orders Created: {len(response.get('results', []))}"
                    ])

            elif order_type == 'modifyorder':
                details.extend([
                    f"Order ID: `{order_data.get('orderid', 'N/A')}`",
                    f"Symbol: `{order_data.get('symbol', 'N/A')}`",
                    f"New Quantity: {order_data.get('quantity', 'N/A')}",
                    f"New Price: {order_data.get('price', 'N/A')}"
                ])
                if response.get('status') == 'success':
                    details.append("✅ Modification Successful")
                else:
                    details.append(f"❌ Error: {response.get('message', 'Failed')}")

            elif order_type == 'cancelorder':
                details.extend([
                    f"Order ID: `{order_data.get('orderid', 'N/A')}`"
                ])
                if response.get('status') == 'success':
                    details.append("✅ Cancellation Successful")
                else:
                    details.append(f"❌ Error: {response.get('message', 'Failed')}")

            elif order_type == 'cancelallorder':
                if response.get('status') == 'success':
                    canceled = response.get('canceled_orders', [])
                    failed = response.get('failed_cancellations', [])
                    details.extend([
                        f"✅ Cancelled: {len(canceled)} orders",
                        f"❌ Failed: {len(failed)} orders"
                    ])
                    if canceled and len(canceled) <= 5:
                        details.append(f"Order IDs: {', '.join(canceled[:5])}")

            elif order_type == 'closeposition':
                if response.get('status') == 'success':
                    details.append("✅ All positions closed successfully")
                else:
                    details.append(f"❌ Error: {response.get('message', 'Failed')}")

            details.append(f"⏰ Time: {timestamp}")

            # Add strategy if available
            if order_data.get('strategy'):
                details.insert(0, f"Strategy: *{order_data.get('strategy')}*")

            return '\n'.join(details)

        except Exception as e:
            logger.error(f"Error formatting order details: {e}")
            return f"Order Type: {order_type}\nStatus: {response.get('status', 'unknown')}"

    async def send_alert_async(self, telegram_id: int, message: str) -> bool:
        """Send alert message asynchronously"""
        try:
            # Get telegram bot service
            bot_service = _get_telegram_bot_service()

            # Check if bot is running
            if not bot_service.is_running:
                logger.debug("Telegram bot is not running, queueing notification")
                # Queue the notification for later delivery
                add_notification(telegram_id, message, priority=8)
                return True

            # Send notification directly
            success = await bot_service.send_notification(telegram_id, message)

            if not success:
                # If failed, add to queue for retry
                add_notification(telegram_id, message, priority=8)

            return success

        except Exception as e:
            logger.error(f"Error sending telegram alert: {e}")
            # Add to queue on error
            add_notification(telegram_id, message, priority=8)
            return False

    def send_order_alert(self, order_type: str, order_data: Dict[str, Any],
                        response: Dict[str, Any], api_key: Optional[str] = None):
        """
        Send order alert to telegram user (non-blocking)

        Args:
            order_type: Type of order (placeorder, basketorder, etc.)
            order_data: Original order data
            response: Order response
            api_key: API key to identify user
        """
        try:
            logger.info(f"Telegram alert triggered for {order_type}, response: {response.get('status', 'unknown')}")

            # Skip if alerts are disabled
            if not self.enabled:
                logger.debug("Telegram alerts are disabled globally")
                return

            # Get username from API key
            username = None
            if api_key:
                username = get_username_by_apikey(api_key)
                logger.debug(f"Username from api_key: {username}")
            elif order_data.get('apikey'):
                username = get_username_by_apikey(order_data.get('apikey'))
                logger.debug(f"Username from order_data: {username}")

            if not username:
                logger.warning(f"No username found for telegram alert - api_key present: {bool(api_key or order_data.get('apikey'))}")
                return

            # Get telegram user
            telegram_user = get_telegram_user_by_username(username)
            if not telegram_user:
                logger.info(f"No telegram user linked for username: {username}")
                return
            if not telegram_user.get('notifications_enabled'):
                logger.info(f"Notifications disabled for telegram user: {username}")
                return

            logger.info(f"Sending telegram alert to user {username} (telegram_id: {telegram_user['telegram_id']})")

            # Format message
            template = self.alert_templates.get(order_type, '📊 *Order Update*\n{details}')
            details = self.format_order_details(order_type, order_data, response)
            message = template.format(details=details)

            # Send alert asynchronously (non-blocking)
            telegram_id = telegram_user['telegram_id']

            # Get telegram bot service
            bot_service = _get_telegram_bot_service()

            # Use the bot's event loop if available
            if bot_service.bot_loop and bot_service.bot_loop.is_running():
                # Schedule in bot's event loop
                asyncio.run_coroutine_threadsafe(
                    self.send_alert_async(telegram_id, message),
                    bot_service.bot_loop
                )
            else:
                # Use thread pool executor for truly async execution
                logger.info(f"Queueing alert via thread pool for telegram_id: {telegram_id}")
                alert_executor.submit(self._send_alert_sync_wrapper, telegram_id, message)

            logger.info(f"Telegram alert queued successfully for {order_type}")

        except Exception as e:
            # Log error but don't raise - we don't want to affect order processing
            logger.error(f"Error queuing telegram alert: {e}", exc_info=True)

    def _send_alert_sync_wrapper(self, telegram_id: int, message: str):
        """Wrapper to run async function in sync context"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.send_alert_async(telegram_id, message))
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Error in sync wrapper: {e}")

    def send_broadcast_alert(self, message: str, filters: Optional[Dict] = None):
        """Send broadcast alert to multiple users"""
        try:
            users = get_all_telegram_users(filters)

            for user in users:
                if user.get('notifications_enabled'):
                    telegram_id = user['telegram_id']
                    alert_executor.submit(self._send_alert_sync_wrapper, telegram_id, message)

        except Exception as e:
            logger.error(f"Error sending broadcast alert: {e}")

    def toggle_alerts(self, enabled: bool):
        """Enable or disable telegram alerts"""
        self.enabled = enabled
        logger.info(f"Telegram alerts {'enabled' if enabled else 'disabled'}")

# Initialize global instance
telegram_alert_service = TelegramAlertService()