import asyncio
import concurrent.futures
import json
import os

from flask import Blueprint, Response, jsonify, redirect, render_template, request, session, url_for

from database.auth_db import get_auth_token
from database.telegram_db import (
    delete_telegram_user,
    get_all_telegram_users,
    get_bot_config,
    get_command_stats,
    get_telegram_user_by_username,
    update_bot_config,
)
from limiter import limiter
from services.telegram_bot_service import telegram_bot_service
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

# Rate limiting configuration from environment
TELEGRAM_MESSAGE_RATE_LIMIT = os.getenv("TELEGRAM_MESSAGE_RATE_LIMIT", "10 per minute")

# Define the blueprint
telegram_bp = Blueprint("telegram_bp", __name__, url_prefix="/telegram")


# No longer need run_async since we use the sync wrapper


# ============================================================================
# Legacy Jinja Template Routes (Commented out - React handles these now)
# ============================================================================
# Note: The following routes have been migrated to React frontend.
# They are kept commented for reference during the migration period.
# React routes are defined in react_app.py

# @telegram_bp.route('/')
# @check_session_validity
# def index():
#     """Main Telegram bot control panel"""
#     ... (migrated to React /telegram)

# @telegram_bp.route('/users')
# ... (migrated to React /telegram/users)

# @telegram_bp.route('/analytics')
# ... (migrated to React /telegram/analytics)


# Config POST endpoint - kept for React API usage
@telegram_bp.route("/config", methods=["POST"])
@check_session_validity
def configuration():
    """Update bot configuration (JSON API)"""
    try:
        data = request.json

        # Update configuration
        config_update = {}
        if "token" in data:
            config_update["bot_token"] = data["token"]
        if "broadcast_enabled" in data:
            config_update["broadcast_enabled"] = bool(data["broadcast_enabled"])
        if "rate_limit_per_minute" in data:
            config_update["rate_limit_per_minute"] = int(data["rate_limit_per_minute"])

        # Log config save without exposing token
        safe_config = {k: "[REDACTED]" if k == "bot_token" else v for k, v in config_update.items()}
        logger.debug(f"Saving config: {safe_config}")
        success = update_bot_config(config_update)

        if success:
            # Verify what was saved
            saved_config = get_bot_config()
            logger.debug(
                f"Config after save: broadcast_enabled={saved_config.get('broadcast_enabled')}, bot_token={'[REDACTED]' if saved_config.get('bot_token') else 'absent'}"
            )
            return jsonify({"status": "success", "message": "Configuration updated"})
        else:
            return jsonify({"status": "error", "message": "Failed to update configuration"}), 500

    except Exception as e:
        logger.exception(f"Error updating config: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@telegram_bp.route("/bot/start", methods=["POST"])
@check_session_validity
def start_bot():
    """Start the telegram bot"""
    try:
        config = get_bot_config()

        if not config.get("bot_token"):
            return jsonify({"status": "error", "message": "Bot token not configured"}), 400

        # Initialize bot - detect environment and use appropriate method
        import sys

        if "eventlet" in sys.modules:
            logger.info("Eventlet environment detected - using synchronous initialization")
            # Use synchronous initialization for eventlet
            success, message = telegram_bot_service.initialize_bot_sync(token=config["bot_token"])
        else:
            # Non-eventlet environment - use threaded async initialization
            logger.info("Standard environment - using async initialization")

            def init_bot():
                try:
                    # Try to get the current event loop
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # If there's a running loop (e.g., in Docker),
                        # schedule the coroutine in that loop
                        future = asyncio.run_coroutine_threadsafe(
                            telegram_bot_service.initialize_bot(token=config["bot_token"]), loop
                        )
                        return future.result(timeout=10)
                    else:
                        # No running loop, create a new one
                        return asyncio.run(
                            telegram_bot_service.initialize_bot(token=config["bot_token"])
                        )
                except RuntimeError:
                    # No event loop exists, create one
                    return asyncio.run(
                        telegram_bot_service.initialize_bot(token=config["bot_token"])
                    )

            import threading

            result = [None]

            def run_init():
                result[0] = init_bot()

            thread = threading.Thread(target=run_init)
            thread.start()
            thread.join(timeout=10)
            success, message = result[0] if result[0] else (False, "Initialization failed")

        if not success:
            return jsonify({"status": "error", "message": message}), 500

        # Start bot (now synchronous)
        success, message = telegram_bot_service.start_bot()

        if success:
            return jsonify({"status": "success", "message": message})
        else:
            return jsonify({"status": "error", "message": message}), 500

    except Exception as e:
        logger.exception(f"Error starting bot: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@telegram_bp.route("/bot/stop", methods=["POST"])
@check_session_validity
def stop_bot():
    """Stop the telegram bot"""
    try:
        # Use the synchronous stop method
        success, message = telegram_bot_service.stop_bot()

        if success:
            return jsonify({"status": "success", "message": message})
        else:
            return jsonify({"status": "error", "message": message}), 500

    except Exception as e:
        logger.exception(f"Error stopping bot: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@telegram_bp.route("/bot/status", methods=["GET"])
@check_session_validity
def bot_status():
    """Get bot status"""
    try:
        config = get_bot_config()

        status = {
            "is_running": telegram_bot_service.is_running,
            "is_configured": bool(config.get("bot_token")),
            "bot_username": config.get("bot_username"),
            "is_active": config.get("is_active", False),
        }

        return jsonify({"status": "success", "data": status})

    except Exception as e:
        logger.exception(f"Error getting bot status: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@telegram_bp.route("/broadcast", methods=["POST"])
@check_session_validity
def broadcast():
    """Send broadcast message"""
    try:
        data = request.json
        message = data.get("message")
        filters = data.get("filters", {})

        if not message:
            return jsonify({"status": "error", "message": "Message is required"}), 400

        # Check if broadcast is enabled
        config = get_bot_config()
        if not config.get("broadcast_enabled", True):
            return jsonify({"status": "error", "message": "Broadcast is disabled"}), 403

        # Run broadcast using the bot's event loop
        if telegram_bot_service.bot_loop and telegram_bot_service.is_running:
            future = asyncio.run_coroutine_threadsafe(
                telegram_bot_service.broadcast_message(message, filters),
                telegram_bot_service.bot_loop,
            )
            success_count, fail_count = future.result(timeout=30)
        else:
            success_count, fail_count = 0, 0
            logger.error("Bot not running or loop not available")

        return jsonify(
            {
                "status": "success",
                "message": f"Sent to {success_count} users, failed for {fail_count}",
                "success_count": success_count,
                "fail_count": fail_count,
            }
        )

    except Exception as e:
        logger.exception(f"Error broadcasting: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@telegram_bp.route("/user/<int:telegram_id>/unlink", methods=["POST"])
@check_session_validity
def unlink_user(telegram_id):
    """Unlink a telegram user"""
    try:
        success = delete_telegram_user(telegram_id)

        if success:
            return jsonify({"status": "success", "message": "User unlinked"})
        else:
            return jsonify({"status": "error", "message": "Failed to unlink user"}), 500

    except Exception as e:
        logger.exception(f"Error unlinking user: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@telegram_bp.route("/test-message", methods=["POST"])
@check_session_validity
def send_test_message():
    """Send a test message to the current user or first available user"""
    try:
        username = session.get("user")
        if not username:
            return jsonify({"status": "error", "message": "User not found"}), 404

        # Get all telegram users
        all_users = get_all_telegram_users()

        # Try to find user by openalgo_username
        telegram_user = None
        for user in all_users:
            if user.get("openalgo_username") == username:
                telegram_user = user
                break

        # If no linked user found, try to send to the first available user (for admin testing)
        if not telegram_user and all_users:
            telegram_user = all_users[0]  # Use first available user for testing
            message = f"🔔 Test Message from OpenAlgo (Admin: {username})\n\nYour Telegram integration is working correctly!"
        elif telegram_user:
            message = (
                "🔔 Test Message from OpenAlgo\n\nYour Telegram integration is working correctly!"
            )
        else:
            return jsonify(
                {
                    "status": "error",
                    "message": "No Telegram users found. Please ensure at least one user has started the bot with /start",
                }
            ), 404

        # Run notification using the bot's event loop
        if telegram_bot_service.bot_loop and telegram_bot_service.is_running:
            future = asyncio.run_coroutine_threadsafe(
                telegram_bot_service.send_notification(telegram_user["telegram_id"], message),
                telegram_bot_service.bot_loop,
            )
            success = future.result(timeout=10)
        else:
            success = False
            logger.error("Bot not running or loop not available")

        if success:
            return jsonify({"status": "success", "message": "Test message sent"})
        else:
            return jsonify({"status": "error", "message": "Failed to send test message"}), 500

    except Exception as e:
        logger.exception(f"Error sending test message: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@telegram_bp.route("/send-message", methods=["POST"])
@check_session_validity
@limiter.limit(TELEGRAM_MESSAGE_RATE_LIMIT)
def send_message():
    """Send a message to a specific Telegram user (Admin only)"""
    try:
        # Admin-only check (you can customize this based on your admin logic)
        username = session.get("user")
        # Add your admin check here. For now, we'll add basic protections

        data = request.json
        telegram_id = data.get("telegram_id")
        message = data.get("message")

        if not telegram_id or not message:
            return jsonify({"status": "error", "message": "Missing telegram_id or message"}), 400

        # Validate telegram_id is an integer to prevent injection
        try:
            telegram_id = int(telegram_id)
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "Invalid telegram_id"}), 400

        # Check if the telegram_id belongs to a registered user
        from database.telegram_db import get_telegram_user

        user = get_telegram_user(telegram_id)
        if not user:
            return jsonify({"status": "error", "message": "User not found"}), 404

        # Limit message length to prevent abuse
        if len(message) > 4096:  # Telegram's max message length
            return jsonify(
                {"status": "error", "message": "Message too long (max 4096 characters)"}
            ), 400

        # Check if bot is running
        if not telegram_bot_service.is_running:
            return jsonify({"status": "error", "message": "Bot is not running"}), 503

        # Log who sent the message for audit trail
        logger.info(f"User {username} sending message to Telegram ID {telegram_id}")

        # Run notification using the bot's event loop
        if telegram_bot_service.bot_loop and telegram_bot_service.is_running:
            future = asyncio.run_coroutine_threadsafe(
                telegram_bot_service.send_notification(telegram_id, message),
                telegram_bot_service.bot_loop,
            )
            success = future.result(timeout=10)
        else:
            success = False
            logger.error("Bot not running or loop not available")

        if success:
            logger.info(f"Message sent to Telegram ID {telegram_id}")
            return jsonify({"status": "success", "message": "Message sent successfully"})
        else:
            return jsonify({"status": "error", "message": "Failed to send message"}), 500

    except Exception as e:
        logger.exception(f"Error sending message: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================================
# JSON API Endpoints for React Frontend
# ============================================================================


def _format_stats_for_react(stats_dict):
    """Convert get_command_stats dict to React-friendly format"""
    if not stats_dict:
        return {"stats": [], "total_commands": 0, "active_users": 0}

    commands_by_type = stats_dict.get("commands_by_type", {})
    stats_array = [{"command": cmd, "count": count} for cmd, count in commands_by_type.items()]
    # Sort by count descending
    stats_array.sort(key=lambda x: x["count"], reverse=True)

    return {
        "stats": stats_array,
        "total_commands": stats_dict.get("total_commands", 0),
        "active_users": stats_dict.get("active_users", 0),
    }


@telegram_bp.route("/api/index")
@check_session_validity
def api_index():
    """Get telegram index data for React frontend"""
    try:
        config = get_bot_config()

        bot_status = {
            "is_running": telegram_bot_service.is_running,
            "bot_username": config.get("bot_username"),
            "is_configured": bool(config.get("bot_token")),
            "is_active": config.get("is_active", False),
        }

        users = get_all_telegram_users()
        raw_stats = get_command_stats(days=7)
        formatted_stats = _format_stats_for_react(raw_stats)

        username = session.get("user")
        telegram_user = get_telegram_user_by_username(username) if username else None

        return jsonify(
            {
                "status": "success",
                "data": {
                    "bot_status": bot_status,
                    "config": {
                        "bot_username": config.get("bot_username"),
                        "broadcast_enabled": config.get("broadcast_enabled", True),
                        "rate_limit_per_minute": config.get("rate_limit_per_minute", 10),
                        "is_active": config.get("is_active", False),
                    },
                    "users": users,
                    "stats": formatted_stats["stats"],
                    "total_commands": formatted_stats["total_commands"],
                    "active_users_7d": formatted_stats["active_users"],
                    "telegram_user": telegram_user,
                },
            }
        )

    except Exception as e:
        logger.exception(f"Error in telegram api index: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@telegram_bp.route("/api/config")
@check_session_validity
def api_config():
    """Get bot configuration for React frontend"""
    try:
        config = get_bot_config()

        # Don't expose the full token, just indicate if it's set
        return jsonify(
            {
                "status": "success",
                "data": {
                    "has_token": bool(config.get("bot_token")),
                    "bot_username": config.get("bot_username"),
                    "broadcast_enabled": config.get("broadcast_enabled", True),
                    "rate_limit_per_minute": config.get("rate_limit_per_minute", 10),
                    "is_active": config.get("is_active", False),
                },
            }
        )

    except Exception as e:
        logger.exception(f"Error getting config: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@telegram_bp.route("/api/users")
@check_session_validity
def api_users():
    """Get all telegram users for React frontend"""
    try:
        users = get_all_telegram_users()
        raw_stats = get_command_stats(days=30)
        formatted_stats = _format_stats_for_react(raw_stats)

        return jsonify(
            {
                "status": "success",
                "data": {
                    "users": users,
                    "stats": formatted_stats["stats"],
                    "total_commands": formatted_stats["total_commands"],
                },
            }
        )

    except Exception as e:
        logger.exception(f"Error getting users: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@telegram_bp.route("/api/analytics")
@check_session_validity
def api_analytics():
    """Get analytics data for React frontend"""
    try:
        raw_stats_7d = get_command_stats(days=7)
        raw_stats_30d = get_command_stats(days=30)
        formatted_stats_7d = _format_stats_for_react(raw_stats_7d)
        formatted_stats_30d = _format_stats_for_react(raw_stats_30d)

        users = get_all_telegram_users()
        active_users_count = len([u for u in users if u.get("notifications_enabled")])
        total_users = len(users)

        return jsonify(
            {
                "status": "success",
                "data": {
                    "stats_7d": formatted_stats_7d["stats"],
                    "stats_30d": formatted_stats_30d["stats"],
                    "total_users": total_users,
                    "active_users": active_users_count,
                    "users": users,
                },
            }
        )

    except Exception as e:
        logger.exception(f"Error getting analytics: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
