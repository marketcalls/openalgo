from flask import Blueprint, jsonify, request, render_template, session, redirect, url_for, Response
from database.auth_db import get_auth_token
from utils.session import check_session_validity
from limiter import limiter
from database.telegram_db import (
    get_bot_config,
    update_bot_config,
    get_all_telegram_users,
    get_telegram_user_by_username,
    get_command_stats,
    delete_telegram_user
)
from services.telegram_bot_service import telegram_bot_service
from utils.logging import get_logger
import asyncio
import json
import os

logger = get_logger(__name__)

# Rate limiting configuration from environment
TELEGRAM_MESSAGE_RATE_LIMIT = os.getenv("TELEGRAM_MESSAGE_RATE_LIMIT", "10 per minute")

# Define the blueprint
telegram_bp = Blueprint('telegram_bp', __name__, url_prefix='/telegram')


def run_async(coro):
    """Helper to run async coroutine in sync context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@telegram_bp.route('/')
@check_session_validity
def index():
    """Main Telegram bot control panel"""
    try:
        # Get bot configuration
        config = get_bot_config()

        # Get bot status
        bot_status = {
            'is_running': telegram_bot_service.is_running,
            'bot_username': config.get('bot_username'),
            'is_configured': bool(config.get('bot_token'))
        }

        # Get user stats
        users = get_all_telegram_users()
        stats = get_command_stats(days=7)

        # Get current user's telegram link status
        username = session.get('user')
        telegram_user = get_telegram_user_by_username(username) if username else None

        return render_template('telegram/index.html',
                             bot_status=bot_status,
                             config=config,
                             users=users,
                             stats=stats,
                             telegram_user=telegram_user)

    except Exception as e:
        logger.error(f"Error in telegram index: {str(e)}")
        return "Error loading Telegram panel", 500


@telegram_bp.route('/config', methods=['GET', 'POST'])
@check_session_validity
def configuration():
    """Bot configuration page"""
    if request.method == 'GET':
        config = get_bot_config()
        logger.debug(f"Config loaded for display: broadcast_enabled={config.get('broadcast_enabled')}, bot_token={'[REDACTED]' if config.get('bot_token') else 'absent'}")
        return render_template('telegram/config.html', config=config)

    elif request.method == 'POST':
        try:
            data = request.json

            # Update configuration
            config_update = {}
            if 'token' in data:
                config_update['bot_token'] = data['token']
            if 'broadcast_enabled' in data:
                config_update['broadcast_enabled'] = bool(data['broadcast_enabled'])
            if 'rate_limit_per_minute' in data:
                config_update['rate_limit_per_minute'] = int(data['rate_limit_per_minute'])

            # Log config save without exposing token
            safe_config = {k: '[REDACTED]' if k == 'bot_token' else v for k, v in config_update.items()}
            logger.debug(f"Saving config: {safe_config}")
            success = update_bot_config(config_update)

            if success:
                # Verify what was saved
                saved_config = get_bot_config()
                logger.debug(f"Config after save: broadcast_enabled={saved_config.get('broadcast_enabled')}, bot_token={'[REDACTED]' if saved_config.get('bot_token') else 'absent'}")
                return jsonify({'status': 'success', 'message': 'Configuration updated'})
            else:
                return jsonify({'status': 'error', 'message': 'Failed to update configuration'}), 500

        except Exception as e:
            logger.error(f"Error updating config: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500


@telegram_bp.route('/users')
@check_session_validity
def users():
    """Telegram users management page"""
    users = get_all_telegram_users()
    stats = get_command_stats(days=30)

    return render_template('telegram/users.html',
                         users=users,
                         stats=stats)


@telegram_bp.route('/analytics')
@check_session_validity
def analytics():
    """Analytics and statistics page"""
    # Get stats for different periods
    stats_7d = get_command_stats(days=7)
    stats_30d = get_command_stats(days=30)

    # Get all users for additional analytics
    users = get_all_telegram_users()

    # Calculate additional metrics
    active_users_count = len([u for u in users if u.get('notifications_enabled')])
    total_users = len(users)

    analytics_data = {
        'stats_7d': stats_7d,
        'stats_30d': stats_30d,
        'total_users': total_users,
        'active_users': active_users_count,
        'users': users
    }

    return render_template('telegram/analytics.html',
                         analytics=analytics_data)


@telegram_bp.route('/bot/start', methods=['POST'])
@check_session_validity
def start_bot():
    """Start the telegram bot"""
    try:
        config = get_bot_config()

        if not config.get('bot_token'):
            return jsonify({
                'status': 'error',
                'message': 'Bot token not configured'
            }), 400

        # Initialize bot
        success, message = run_async(telegram_bot_service.initialize_bot(
            token=config['bot_token']
        ))

        if not success:
            return jsonify({'status': 'error', 'message': message}), 500

        # Start bot
        success, message = run_async(telegram_bot_service.start_bot())

        if success:
            return jsonify({'status': 'success', 'message': message})
        else:
            return jsonify({'status': 'error', 'message': message}), 500

    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@telegram_bp.route('/bot/stop', methods=['POST'])
@check_session_validity
def stop_bot():
    """Stop the telegram bot"""
    try:
        # Use the synchronous stop method
        success, message = telegram_bot_service.stop_bot_sync()

        if success:
            return jsonify({'status': 'success', 'message': message})
        else:
            return jsonify({'status': 'error', 'message': message}), 500

    except Exception as e:
        logger.error(f"Error stopping bot: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@telegram_bp.route('/bot/status', methods=['GET'])
@check_session_validity
def bot_status():
    """Get bot status"""
    try:
        config = get_bot_config()

        status = {
            'is_running': telegram_bot_service.is_running,
            'is_configured': bool(config.get('bot_token')),
            'bot_username': config.get('bot_username'),
            'is_active': config.get('is_active', False)
        }

        return jsonify({'status': 'success', 'data': status})

    except Exception as e:
        logger.error(f"Error getting bot status: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@telegram_bp.route('/broadcast', methods=['POST'])
@check_session_validity
def broadcast():
    """Send broadcast message"""
    try:
        data = request.json
        message = data.get('message')
        filters = data.get('filters', {})

        if not message:
            return jsonify({'status': 'error', 'message': 'Message is required'}), 400

        # Check if broadcast is enabled
        config = get_bot_config()
        if not config.get('broadcast_enabled', True):
            return jsonify({'status': 'error', 'message': 'Broadcast is disabled'}), 403

        # Use the bot's event loop for broadcast
        if telegram_bot_service.bot_loop and telegram_bot_service.bot_loop.is_running():
            # Schedule the coroutine in the bot's event loop
            future = asyncio.run_coroutine_threadsafe(
                telegram_bot_service.broadcast_message(message, filters),
                telegram_bot_service.bot_loop
            )
            success_count, fail_count = future.result(timeout=30)  # Wait up to 30 seconds
        else:
            # Fallback to creating new event loop
            success_count, fail_count = run_async(telegram_bot_service.broadcast_message(message, filters))

        return jsonify({
            'status': 'success',
            'message': f'Sent to {success_count} users, failed for {fail_count}',
            'success_count': success_count,
            'fail_count': fail_count
        })

    except Exception as e:
        logger.error(f"Error broadcasting: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@telegram_bp.route('/user/<int:telegram_id>/unlink', methods=['POST'])
@check_session_validity
def unlink_user(telegram_id):
    """Unlink a telegram user"""
    try:
        success = delete_telegram_user(telegram_id)

        if success:
            return jsonify({'status': 'success', 'message': 'User unlinked'})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to unlink user'}), 500

    except Exception as e:
        logger.error(f"Error unlinking user: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@telegram_bp.route('/test-message', methods=['POST'])
@check_session_validity
def send_test_message():
    """Send a test message to the current user or first available user"""
    try:
        username = session.get('user')
        if not username:
            return jsonify({'status': 'error', 'message': 'User not found'}), 404

        # Get all telegram users
        all_users = get_all_telegram_users()

        # Try to find user by openalgo_username
        telegram_user = None
        for user in all_users:
            if user.get('openalgo_username') == username:
                telegram_user = user
                break

        # If no linked user found, try to send to the first available user (for admin testing)
        if not telegram_user and all_users:
            telegram_user = all_users[0]  # Use first available user for testing
            message = f"🔔 Test Message from OpenAlgo (Admin: {username})\n\nYour Telegram integration is working correctly!"
        elif telegram_user:
            message = "🔔 Test Message from OpenAlgo\n\nYour Telegram integration is working correctly!"
        else:
            return jsonify({
                'status': 'error',
                'message': 'No Telegram users found. Please ensure at least one user has started the bot with /start'
            }), 404

        # Use the bot's event loop for sending notification
        if telegram_bot_service.bot_loop and telegram_bot_service.bot_loop.is_running():
            # Schedule the coroutine in the bot's event loop
            future = asyncio.run_coroutine_threadsafe(
                telegram_bot_service.send_notification(telegram_user['telegram_id'], message),
                telegram_bot_service.bot_loop
            )
            success = future.result(timeout=10)  # Wait up to 10 seconds
        else:
            # Fallback to creating new event loop
            success = run_async(telegram_bot_service.send_notification(telegram_user['telegram_id'], message))

        if success:
            return jsonify({'status': 'success', 'message': 'Test message sent'})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to send test message'}), 500

    except Exception as e:
        logger.error(f"Error sending test message: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@telegram_bp.route('/send-message', methods=['POST'])
@check_session_validity
@limiter.limit(TELEGRAM_MESSAGE_RATE_LIMIT)
def send_message():
    """Send a message to a specific Telegram user (Admin only)"""
    try:
        # Admin-only check (you can customize this based on your admin logic)
        username = session.get('user')
        # Add your admin check here. For now, we'll add basic protections

        data = request.json
        telegram_id = data.get('telegram_id')
        message = data.get('message')

        if not telegram_id or not message:
            return jsonify({'status': 'error', 'message': 'Missing telegram_id or message'}), 400

        # Validate telegram_id is an integer to prevent injection
        try:
            telegram_id = int(telegram_id)
        except (ValueError, TypeError):
            return jsonify({'status': 'error', 'message': 'Invalid telegram_id'}), 400

        # Check if the telegram_id belongs to a registered user
        from database.telegram_db import get_telegram_user
        user = get_telegram_user(telegram_id)
        if not user:
            return jsonify({'status': 'error', 'message': 'User not found'}), 404

        # Limit message length to prevent abuse
        if len(message) > 4096:  # Telegram's max message length
            return jsonify({'status': 'error', 'message': 'Message too long (max 4096 characters)'}), 400

        # Check if bot is running
        if not telegram_bot_service.is_running:
            return jsonify({'status': 'error', 'message': 'Bot is not running'}), 503

        # Log who sent the message for audit trail
        logger.info(f"User {username} sending message to Telegram ID {telegram_id}")

        # Use the bot's event loop for sending notification
        if telegram_bot_service.bot_loop and telegram_bot_service.bot_loop.is_running():
            # Schedule the coroutine in the bot's event loop
            future = asyncio.run_coroutine_threadsafe(
                telegram_bot_service.send_notification(telegram_id, message),
                telegram_bot_service.bot_loop
            )
            success = future.result(timeout=10)  # Wait up to 10 seconds
        else:
            # Fallback to creating new event loop
            success = run_async(telegram_bot_service.send_notification(telegram_id, message))

        if success:
            logger.info(f"Message sent to Telegram ID {telegram_id}")
            return jsonify({'status': 'success', 'message': 'Message sent successfully'})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to send message'}), 500

    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500