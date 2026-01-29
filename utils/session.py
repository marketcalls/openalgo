import os
from datetime import datetime, timedelta
from functools import wraps

import pytz
from flask import redirect, session, url_for

from utils.logging import get_logger

logger = get_logger(__name__)


def get_session_expiry_time():
    """Get session expiry time set to 3 AM IST next day"""
    now_utc = datetime.now(pytz.timezone("UTC"))
    now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))

    # Get configured expiry time or default to 3 AM
    expiry_time = os.getenv("SESSION_EXPIRY_TIME", "03:00")
    hour, minute = map(int, expiry_time.split(":"))

    target_time_ist = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # If current time is past target time, set expiry to next day
    if now_ist > target_time_ist:
        target_time_ist += timedelta(days=1)

    remaining_time = target_time_ist - now_ist
    logger.debug(f"Session expiry time set to: {target_time_ist}")
    return remaining_time


def set_session_login_time():
    """Set the session login time in IST"""
    now_utc = datetime.now(pytz.timezone("UTC"))
    now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))
    session["login_time"] = now_ist.isoformat()
    logger.info(f"Session login time set to: {now_ist}")


def is_session_valid():
    """Check if the current session is valid"""
    if not session.get("logged_in"):
        logger.debug("Session invalid: 'logged_in' flag not set")
        return False

    # If no login time is set, consider session invalid
    if "login_time" not in session:
        logger.debug("Session invalid: 'login_time' not in session")
        return False

    now_utc = datetime.now(pytz.timezone("UTC"))
    now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))

    # Parse login time
    login_time = datetime.fromisoformat(session["login_time"])

    # Get configured expiry time
    expiry_time = os.getenv("SESSION_EXPIRY_TIME", "03:00")
    hour, minute = map(int, expiry_time.split(":"))

    # Get today's expiry time
    daily_expiry = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # If current time is past expiry time and login was before expiry time
    if now_ist > daily_expiry and login_time < daily_expiry:
        logger.info(f"Session expired at {daily_expiry} IST")
        return False

    logger.debug(
        f"Session valid. Current time: {now_ist}, Login time: {login_time}, Daily expiry: {daily_expiry}"
    )
    return True


def revoke_user_tokens(revoke_db_tokens=True):
    """
    Revoke auth tokens for the current user when session expires.

    Also publishes cache invalidation events via ZeroMQ for multi-process deployments.
    This ensures WebSocket proxy and other processes clear their stale cached tokens.
    See GitHub issue #765 for details on the cross-process cache synchronization problem.

    Args:
        revoke_db_tokens (bool): If True, revokes the token in the database (Invalidates API Key).
                                 If False, only clears local caches (Preserves API Key).
    """
    if "user" in session:
        username = session.get("user")
        try:
            from database.auth_db import auth_cache, feed_token_cache, upsert_auth

            # Clear cache entries first to prevent stale data access
            cache_key_auth = f"auth-{username}"
            cache_key_feed = f"feed-{username}"
            if cache_key_auth in auth_cache:
                del auth_cache[cache_key_auth]
            if cache_key_feed in feed_token_cache:
                del feed_token_cache[cache_key_feed]

            # Publish cache invalidation event via ZeroMQ for other processes
            # This notifies WebSocket proxy and other processes to clear their stale caches
            try:
                from database.cache_invalidation import publish_all_cache_invalidation
                publish_all_cache_invalidation(username)
                logger.debug(f"Published cache invalidation for user: {username}")
            except Exception as invalidation_error:
                # Don't fail logout if cache invalidation fails
                logger.warning(f"Failed to publish cache invalidation for user {username}: {invalidation_error}")

            # Clear symbol cache on logout/session expiry
            try:
                from database.master_contract_cache_hook import clear_cache_on_logout

                clear_cache_on_logout()
            except Exception as cache_error:
                logger.exception(f"Error clearing symbol cache: {cache_error}")

            # Clear settings cache on logout/session expiry
            try:
                from database.settings_db import clear_settings_cache

                clear_settings_cache()
            except Exception as cache_error:
                logger.exception(f"Error clearing settings cache: {cache_error}")

            # Clear strategy cache on logout/session expiry
            try:
                from database.strategy_db import clear_strategy_cache

                clear_strategy_cache()
            except Exception as cache_error:
                logger.exception(f"Error clearing strategy cache: {cache_error}")

            # Clear telegram cache on logout/session expiry
            try:
                from database.telegram_db import clear_telegram_cache

                clear_telegram_cache()
            except Exception as cache_error:
                logger.exception(f"Error clearing telegram cache: {cache_error}")

            if revoke_db_tokens:
                # Revoke the auth token in database
                inserted_id = upsert_auth(username, "", "", revoke=True)
                if inserted_id is not None:
                    logger.info(f"Auto-expiry: Revoked auth tokens for user: {username}")
                else:
                    logger.error(f"Auto-expiry: Failed to revoke auth tokens for user: {username}")
            else:
                logger.info(
                    f"Auto-expiry: Skipped DB revocation for user: {username} (Preserving API access)"
                )

        except Exception as e:
            logger.exception(f"Error revoking tokens during auto-expiry for user {username}: {e}")


def check_session_validity(f):
    """Decorator to check session validity before executing route"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_session_valid():
            # Revoke tokens before clearing session
            revoke_user_tokens()
            session.clear()

            # Check if this is an AJAX/fetch request
            from flask import jsonify, request

            is_ajax = (
                request.headers.get("X-Requested-With") == "XMLHttpRequest"
                or request.headers.get("Accept", "").startswith("application/json")
                or request.content_type == "application/json"
                or request.is_json
            )

            if is_ajax:
                # Return JSON response for AJAX requests instead of redirect
                # This prevents consuming rate limits on the login endpoint
                logger.info("Invalid session detected - returning 401 for AJAX request")
                return jsonify(
                    {
                        "status": "error",
                        "error": "session_expired",
                        "message": "Your session has expired. Please log in again.",
                    }
                ), 401

            logger.info("Invalid session detected - redirecting to login")
            return redirect(url_for("auth.login"))
        logger.debug("Session validated successfully")
        return f(*args, **kwargs)

    return decorated_function


def invalidate_session_if_invalid(f):
    """Decorator to invalidate session if invalid without redirecting"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_session_valid():
            logger.info("Invalid session detected - clearing session")
            # Revoke tokens before clearing session
            revoke_user_tokens()
            session.clear()
        return f(*args, **kwargs)

    return decorated_function
