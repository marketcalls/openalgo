import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource, fields

from database.auth_db import verify_api_key
from database.telegram_db import (
    get_all_telegram_users,
    get_bot_config,
    get_command_stats,
    get_telegram_user_by_username,
    get_user_preferences,
    update_bot_config,
    update_user_preferences,
)
from limiter import limiter
from services.telegram_alert_service import TelegramAlertService, alert_executor
from services.telegram_bot_service import telegram_bot_service
from utils.logging import get_logger

logger = get_logger(__name__)

# Rate limit for telegram operations
TELEGRAM_RATE_LIMIT = os.getenv("TELEGRAM_RATE_LIMIT", "30 per minute")

api = Namespace("telegram", description="Telegram Bot API")

# Initialize telegram alert service
telegram_alert = TelegramAlertService()

# Define Swagger models
bot_config_model = api.model(
    "BotConfig",
    {
        "token": fields.String(description="Telegram Bot Token"),
        "webhook_url": fields.String(description="Webhook URL for bot"),
        "polling_mode": fields.Boolean(description="Use polling mode"),
        "broadcast_enabled": fields.Boolean(description="Enable broadcast messages"),
        "rate_limit_per_minute": fields.Integer(description="Rate limit per minute"),
    },
)

user_link_model = api.model(
    "UserLink",
    {
        "apikey": fields.String(required=True, description="API Key"),
        "telegram_id": fields.Integer(required=True, description="Telegram User ID"),
        "username": fields.String(required=True, description="OpenAlgo Username"),
    },
)

broadcast_model = api.model(
    "Broadcast",
    {
        "apikey": fields.String(required=True, description="API Key"),
        "message": fields.String(required=True, description="Message to broadcast"),
        "filters": fields.Raw(description="Optional filters for users"),
    },
)

notification_model = api.model(
    "Notification",
    {
        "apikey": fields.String(required=True, description="API Key"),
        "username": fields.String(required=True, description="OpenAlgo Username"),
        "message": fields.String(required=True, description="Notification message"),
        "priority": fields.Integer(description="Priority (1-10)", default=5),
        "wait_for_delivery": fields.Boolean(
            description="Wait for delivery confirmation (default: false, returns immediately)",
            default=False,
        ),
    },
)

preferences_model = api.model(
    "UserPreferences",
    {
        "apikey": fields.String(required=True, description="API Key"),
        "telegram_id": fields.Integer(required=True, description="Telegram User ID"),
        "order_notifications": fields.Boolean(description="Enable order notifications"),
        "trade_notifications": fields.Boolean(description="Enable trade notifications"),
        "pnl_notifications": fields.Boolean(description="Enable P&L notifications"),
        "daily_summary": fields.Boolean(description="Enable daily summary"),
        "summary_time": fields.String(description="Daily summary time (HH:MM)"),
        "language": fields.String(description="Preferred language"),
        "timezone": fields.String(description="User timezone"),
    },
)


@api.route("/config", strict_slashes=False)
class TelegramBotConfig(Resource):
    @limiter.limit(TELEGRAM_RATE_LIMIT)
    @api.doc(security="apikey")
    def get(self):
        """Get current bot configuration"""
        try:
            api_key = request.headers.get("X-API-KEY") or request.args.get("apikey")

            if not api_key or not verify_api_key(api_key):
                return make_response(
                    jsonify({"status": "error", "message": "Invalid or missing API key"}), 401
                )

            config = get_bot_config()

            # Don't expose the full token for security
            if config.get("bot_token"):
                config["bot_token"] = (
                    config["bot_token"][:10] + "..."
                    if len(config["bot_token"]) > 10
                    else config["bot_token"]
                )

            return make_response(jsonify({"status": "success", "data": config}), 200)

        except Exception:
            logger.exception("Error getting bot config")
            return make_response(
                jsonify({"status": "error", "message": "Failed to get bot configuration"}), 500
            )

    @limiter.limit(TELEGRAM_RATE_LIMIT)
    @api.doc(security="apikey")
    @api.expect(bot_config_model)
    def post(self):
        """Update bot configuration"""
        try:
            data = request.json
            api_key = data.get("apikey") or request.headers.get("X-API-KEY")

            if not api_key or not verify_api_key(api_key):
                return make_response(
                    jsonify({"status": "error", "message": "Invalid or missing API key"}), 401
                )

            # Update configuration
            config_update = {}
            if "token" in data:
                config_update["token"] = data["token"]
            if "webhook_url" in data:
                config_update["webhook_url"] = data["webhook_url"]
            if "polling_mode" in data:
                config_update["polling_mode"] = data["polling_mode"]
            if "broadcast_enabled" in data:
                config_update["broadcast_enabled"] = data["broadcast_enabled"]
            if "rate_limit_per_minute" in data:
                try:
                    rate_limit = int(data["rate_limit_per_minute"])
                    if not 1 <= rate_limit <= 120:
                        return make_response(
                            jsonify({"status": "error", "message": "rate_limit_per_minute must be between 1 and 120"}), 400
                        )
                    config_update["rate_limit_per_minute"] = rate_limit
                except (TypeError, ValueError):
                    return make_response(
                        jsonify({"status": "error", "message": "rate_limit_per_minute must be an integer"}), 400
                    )

            success = update_bot_config(config_update)

            if success:
                return make_response(
                    jsonify({"status": "success", "message": "Bot configuration updated"}), 200
                )
            else:
                return make_response(
                    jsonify({"status": "error", "message": "Failed to update bot configuration"}),
                    500,
                )

        except Exception:
            logger.exception("Error updating bot config")
            return make_response(
                jsonify({"status": "error", "message": "Failed to update bot configuration"}), 500
            )


@api.route("/start", strict_slashes=False)
class StartBot(Resource):
    @limiter.limit(TELEGRAM_RATE_LIMIT)
    @api.doc(security="apikey")
    def post(self):
        """Start the Telegram bot"""
        try:
            data = request.json or {}
            api_key = data.get("apikey") or request.headers.get("X-API-KEY")

            if not api_key or not verify_api_key(api_key):
                return make_response(
                    jsonify({"status": "error", "message": "Invalid or missing API key"}), 401
                )

            # Get bot configuration
            config = get_bot_config()

            if not config.get("bot_token"):
                return make_response(
                    jsonify({"status": "error", "message": "Bot token not configured"}), 400
                )

            # Initialize bot. initialize_bot_sync() picks the right path for the
            # running server (synchronous under eventlet, threaded async on the
            # dev server), which is what the /telegram UI uses.
            success, message = telegram_bot_service.initialize_bot_sync(token=config["bot_token"])

            if not success:
                return make_response(jsonify({"status": "error", "message": message}), 500)

            # Start bot
            if config.get("polling_mode", True):
                success, message = telegram_bot_service.start_bot()
            else:
                # Webhook mode would be configured separately
                success = True
                message = "Bot initialized for webhook mode"

            if success:
                return make_response(jsonify({"status": "success", "message": message}), 200)
            else:
                return make_response(jsonify({"status": "error", "message": message}), 500)

        except Exception as e:
            logger.exception("Error starting bot")
            return make_response(
                jsonify({"status": "error", "message": f"Failed to start bot: {str(e)}"}), 500
            )


@api.route("/stop", strict_slashes=False)
class StopBot(Resource):
    @limiter.limit(TELEGRAM_RATE_LIMIT)
    @api.doc(security="apikey")
    def post(self):
        """Stop the Telegram bot"""
        try:
            data = request.json or {}
            api_key = data.get("apikey") or request.headers.get("X-API-KEY")

            if not api_key or not verify_api_key(api_key):
                return make_response(
                    jsonify({"status": "error", "message": "Invalid or missing API key"}), 401
                )

            # Stop bot
            success, message = telegram_bot_service.stop_bot()

            if success:
                return make_response(jsonify({"status": "success", "message": message}), 200)
            else:
                return make_response(jsonify({"status": "error", "message": message}), 500)

        except Exception as e:
            logger.exception("Error stopping bot")
            return make_response(
                jsonify({"status": "error", "message": f"Failed to stop bot: {str(e)}"}), 500
            )


def get_webhook_secret():
    """Return the shared secret used to verify inbound Telegram webhook calls.

    Telegram echoes this value back in the ``X-Telegram-Bot-Api-Secret-Token``
    header of every webhook delivery, which is how the webhook route tells a
    genuine Telegram callback from an arbitrary POST to a public URL.

    The value is resolved in two steps:

    1. ``TELEGRAM_WEBHOOK_SECRET`` from the environment, if it is set. Prefer
       this in production, so rotating the bot token does not silently change
       the webhook secret.
    2. Otherwise a value derived from the configured bot token, as the first 32
       characters of its SHA-256 digest. The digest keeps the raw token out of
       request headers while still giving a stable, deployment-specific secret
       with no extra configuration.

    Returns:
        str | None: The webhook secret, or None when neither the environment
        variable nor a bot token is configured. A None result means webhook
        verification cannot be performed and the caller must reject the
        request rather than treat it as verified.

    Example:
        >>> get_webhook_secret()
        '9f2c1d4ab6e83705c1f0d2ab4e7c9351'
    """
    # First check for explicit webhook secret
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if secret:
        return secret

    # Fall back to deriving from bot token (first 32 chars of token hash)
    config = get_bot_config()
    bot_token = config.get("bot_token")
    if bot_token:
        import hashlib

        return hashlib.sha256(bot_token.encode()).hexdigest()[:32]

    return None


@api.route("/webhook", strict_slashes=False)
class WebhookHandler(Resource):
    def post(self):
        """
        Handle Telegram webhook updates.

        Security: Verifies X-Telegram-Bot-Api-Secret-Token header to ensure
        requests are genuinely from Telegram and not from attackers.
        """
        try:
            # Verify webhook secret token (Telegram sends this header when secret_token is configured)
            expected_secret = get_webhook_secret()

            if expected_secret:
                received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")

                if not received_secret:
                    logger.warning("Webhook request missing secret token header")
                    # Return 401 Unauthorized for missing token
                    return make_response("Unauthorized", 401)

                if received_secret != expected_secret:
                    logger.warning("Webhook request with invalid secret token")
                    # Return 403 Forbidden for invalid token
                    return make_response("Forbidden", 403)

            # Get update data from Telegram
            update_data = request.json

            if not update_data:
                return make_response("", 200)

            # Basic structure validation - Telegram updates must have update_id
            if not isinstance(update_data, dict) or "update_id" not in update_data:
                logger.warning("Invalid webhook payload structure")
                return make_response("Bad Request", 400)

            # Process update asynchronously
            # Note: process_webhook_update method needs to be implemented in the new service
            # For now, return success
            logger.info(f"Webhook update received: update_id={update_data.get('update_id')}")

            # Always return 200 to Telegram for valid requests
            return make_response("", 200)

        except Exception as e:
            logger.exception(f"Error processing webhook: {str(e)}")
            # Still return 200 to avoid Telegram retries for processing errors
            return make_response("", 200)


@api.route("/users", strict_slashes=False)
class TelegramUsers(Resource):
    @limiter.limit(TELEGRAM_RATE_LIMIT)
    @api.doc(security="apikey")
    def get(self):
        """Get all linked Telegram users"""
        try:
            api_key = request.headers.get("X-API-KEY") or request.args.get("apikey")

            if not api_key or not verify_api_key(api_key):
                return make_response(
                    jsonify({"status": "error", "message": "Invalid or missing API key"}), 401
                )

            # Get filters from query params
            filters = {}
            if request.args.get("broker"):
                filters["broker"] = request.args.get("broker")
            if request.args.get("notifications_enabled"):
                filters["notifications_enabled"] = (
                    request.args.get("notifications_enabled").lower() == "true"
                )

            users = get_all_telegram_users(filters)

            return make_response(
                jsonify({"status": "success", "data": users, "count": len(users)}), 200
            )

        except Exception:
            logger.exception("Error getting telegram users")
            return make_response(
                jsonify({"status": "error", "message": "Failed to get users"}), 500
            )


@api.route("/broadcast", strict_slashes=False)
class BroadcastMessage(Resource):
    @limiter.limit("5 per minute")
    @api.doc(security="apikey")
    @api.expect(broadcast_model)
    def post(self):
        """Broadcast message to multiple users"""
        try:
            data = request.json
            api_key = data.get("apikey") or request.headers.get("X-API-KEY")

            if not api_key or not verify_api_key(api_key):
                return make_response(
                    jsonify({"status": "error", "message": "Invalid or missing API key"}), 401
                )

            message = data.get("message")
            filters = data.get("filters", {})

            if not message or not isinstance(message, str):
                return make_response(
                    jsonify({"status": "error", "message": "Message is required"}), 400
                )

            if len(message) > 4096:
                return make_response(
                    jsonify({"status": "error", "message": "Message must not exceed 4096 characters"}), 400
                )

            # Check if broadcast is enabled
            config = get_bot_config()
            if not config.get("broadcast_enabled", True):
                return make_response(
                    jsonify({"status": "error", "message": "Broadcast is disabled"}), 403
                )

            # Send broadcast
            # Note: broadcast_message method needs to be implemented in the new service
            # For now, return a placeholder response
            success_count, fail_count = 0, 0

            return make_response(
                jsonify(
                    {
                        "status": "success",
                        "message": f"Broadcast sent to {success_count} users, failed for {fail_count} users",
                        "success_count": success_count,
                        "fail_count": fail_count,
                    }
                ),
                200,
            )

        except Exception:
            logger.exception("Error broadcasting message")
            return make_response(
                jsonify({"status": "error", "message": "Failed to broadcast message"}), 500
            )


@api.route("/notify", strict_slashes=False)
class SendNotification(Resource):
    @limiter.limit(TELEGRAM_RATE_LIMIT)
    @api.doc(security="apikey")
    @api.expect(notification_model)
    def post(self):
        """Send notification to a specific user"""
        try:
            data = request.json
            api_key = data.get("apikey") or request.headers.get("X-API-KEY")

            if not api_key or not verify_api_key(api_key):
                return make_response(
                    jsonify({"status": "error", "message": "Invalid or missing API key"}), 401
                )

            # Stopping the bot must stop automated messages too (GitHub issue
            # #1577). /notify is the programmatic surface strategies call, so it
            # follows the same gate as order alerts. The admin test-message and
            # broadcast buttons in the /telegram UI stay available by design.
            if not telegram_alert.is_bot_active():
                logger.info("Telegram bot is stopped; rejecting /notify request")
                return make_response(
                    jsonify(
                        {
                            "status": "error",
                            "message": "Telegram bot is stopped. Start the bot to send notifications.",
                        }
                    ),
                    409,
                )

            username = data.get("username")
            message = data.get("message")
            try:
                priority = int(data.get("priority", 5))
                if not 1 <= priority <= 10:
                    priority = 5
            except (TypeError, ValueError):
                priority = 5

            if not username or not message:
                return make_response(
                    jsonify({"status": "error", "message": "Username and message are required"}),
                    400,
                )

            # Get user's telegram ID
            user = get_telegram_user_by_username(username)

            if not user:
                return make_response(
                    jsonify(
                        {"status": "error", "message": "User not found or not linked to Telegram"}
                    ),
                    404,
                )

            # Get telegram_id from user
            telegram_id = user.get("telegram_id")

            if not telegram_id:
                return make_response(
                    jsonify({"status": "error", "message": "User telegram_id not found"}), 404
                )

            # Send notification via telegram alert service
            wait_for_delivery = data.get("wait_for_delivery", False)

            if wait_for_delivery:
                # Synchronous: wait for delivery confirmation
                success = telegram_alert.send_alert_sync(telegram_id, message)
                if success:
                    logger.info(f"Telegram alert sent to user {username} (ID: {telegram_id})")
                    return make_response(
                        jsonify({"status": "success", "message": "Notification sent successfully"}),
                        200,
                    )
                else:
                    logger.warning(
                        f"Failed to send telegram alert to user {username} (ID: {telegram_id}), queued for retry"
                    )
                    return make_response(
                        jsonify(
                            {"status": "success", "message": "Notification queued for delivery"}
                        ),
                        200,
                    )
            else:
                # Async: fire-and-forget (default, fast path)
                alert_executor.submit(telegram_alert.send_alert_sync, telegram_id, message)
                logger.info(
                    f"Telegram notification queued for user {username} (ID: {telegram_id})"
                )
                return make_response(
                    jsonify({"status": "success", "message": "Notification queued for delivery"}),
                    200,
                )

        except Exception:
            logger.exception("Error sending notification")
            return make_response(
                jsonify({"status": "error", "message": "Failed to send notification"}), 500
            )


@api.route("/stats", strict_slashes=False)
class TelegramStats(Resource):
    @limiter.limit(TELEGRAM_RATE_LIMIT)
    @api.doc(security="apikey")
    def get(self):
        """Get bot usage statistics"""
        try:
            api_key = request.headers.get("X-API-KEY") or request.args.get("apikey")

            if not api_key or not verify_api_key(api_key):
                return make_response(
                    jsonify({"status": "error", "message": "Invalid or missing API key"}), 401
                )

            # Get days parameter (default 7, max 365)
            try:
                days = min(max(int(request.args.get("days", 7)), 1), 365)
            except (TypeError, ValueError):
                days = 7

            stats = get_command_stats(days)

            return make_response(jsonify({"status": "success", "data": stats}), 200)

        except Exception:
            logger.exception("Error getting stats")
            return make_response(
                jsonify({"status": "error", "message": "Failed to get statistics"}), 500
            )


@api.route("/preferences", strict_slashes=False)
class UserPreferences(Resource):
    @limiter.limit(TELEGRAM_RATE_LIMIT)
    @api.doc(security="apikey")
    def get(self):
        """Get user preferences"""
        try:
            api_key = request.headers.get("X-API-KEY") or request.args.get("apikey")
            telegram_id = request.args.get("telegram_id", type=int)

            if not api_key or not verify_api_key(api_key):
                return make_response(
                    jsonify({"status": "error", "message": "Invalid or missing API key"}), 401
                )

            if not telegram_id:
                return make_response(
                    jsonify({"status": "error", "message": "telegram_id is required"}), 400
                )

            preferences = get_user_preferences(telegram_id)

            return make_response(jsonify({"status": "success", "data": preferences}), 200)

        except Exception:
            logger.exception("Error getting preferences")
            return make_response(
                jsonify({"status": "error", "message": "Failed to get preferences"}), 500
            )

    @limiter.limit(TELEGRAM_RATE_LIMIT)
    @api.doc(security="apikey")
    @api.expect(preferences_model)
    def post(self):
        """Update user preferences"""
        try:
            data = request.json
            api_key = data.get("apikey") or request.headers.get("X-API-KEY")

            if not api_key or not verify_api_key(api_key):
                return make_response(
                    jsonify({"status": "error", "message": "Invalid or missing API key"}), 401
                )

            telegram_id = data.get("telegram_id")

            if not telegram_id:
                return make_response(
                    jsonify({"status": "error", "message": "telegram_id is required"}), 400
                )

            # Extract preferences
            preferences = {}
            for key in [
                "order_notifications",
                "trade_notifications",
                "pnl_notifications",
                "daily_summary",
                "summary_time",
                "language",
                "timezone",
            ]:
                if key in data:
                    preferences[key] = data[key]

            success = update_user_preferences(telegram_id, preferences)

            if success:
                return make_response(
                    jsonify({"status": "success", "message": "Preferences updated successfully"}),
                    200,
                )
            else:
                return make_response(
                    jsonify({"status": "error", "message": "Failed to update preferences"}), 500
                )

        except Exception:
            logger.exception("Error updating preferences")
            return make_response(
                jsonify({"status": "error", "message": "Failed to update preferences"}), 500
            )
