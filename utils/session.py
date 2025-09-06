from datetime import datetime, timedelta
import pytz
from functools import wraps
from flask import session, redirect, url_for
from utils.logging import get_logger
import os

logger = get_logger(__name__)

def get_session_expiry_time():
    """Get session expiry time set to 3 AM IST next day"""
    now_utc = datetime.now(pytz.timezone('UTC'))
    now_ist = now_utc.astimezone(pytz.timezone('Asia/Kolkata'))
    
    # Get configured expiry time or default to 3 AM
    expiry_time = os.getenv('SESSION_EXPIRY_TIME', '03:00')
    hour, minute = map(int, expiry_time.split(':'))
    
    target_time_ist = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    # If current time is past target time, set expiry to next day
    if now_ist > target_time_ist:
        target_time_ist += timedelta(days=1)
    
    remaining_time = target_time_ist - now_ist
    logger.debug(f"Session expiry time set to: {target_time_ist}")
    return remaining_time

def set_session_login_time():
    """Set the session login time in IST"""
    now_utc = datetime.now(pytz.timezone('UTC'))
    now_ist = now_utc.astimezone(pytz.timezone('Asia/Kolkata'))
    session['login_time'] = now_ist.isoformat()
    logger.info(f"Session login time set to: {now_ist}")

def is_session_valid():
    """Check if the current session is valid"""
    if not session.get('logged_in'):
        logger.debug("Session invalid: 'logged_in' flag not set")
        return False
    
    # If no login time is set, consider session invalid
    if 'login_time' not in session:
        logger.debug("Session invalid: 'login_time' not in session")
        return False
        
    now_utc = datetime.now(pytz.timezone('UTC'))
    now_ist = now_utc.astimezone(pytz.timezone('Asia/Kolkata'))
    
    # Parse login time
    login_time = datetime.fromisoformat(session['login_time'])
    
    # Get configured expiry time
    expiry_time = os.getenv('SESSION_EXPIRY_TIME', '03:00')
    hour, minute = map(int, expiry_time.split(':'))
    
    # Get today's expiry time
    daily_expiry = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    # If current time is past expiry time and login was before expiry time
    if now_ist > daily_expiry and login_time < daily_expiry:
        logger.info(f"Session expired at {daily_expiry} IST")
        return False
    
    logger.debug(f"Session valid. Current time: {now_ist}, Login time: {login_time}, Daily expiry: {daily_expiry}")
    return True

def revoke_user_tokens():
    """Revoke auth tokens for the current user when session expires"""
    if 'user' in session:
        username = session.get('user')
        try:
            from database.auth_db import upsert_auth, auth_cache, feed_token_cache
            
            # Clear cache entries first to prevent stale data access
            cache_key_auth = f"auth-{username}"
            cache_key_feed = f"feed-{username}"
            if cache_key_auth in auth_cache:
                del auth_cache[cache_key_auth]
            if cache_key_feed in feed_token_cache:
                del feed_token_cache[cache_key_feed]
            
            # Clear symbol cache on logout/session expiry
            try:
                from database.master_contract_cache_hook import clear_cache_on_logout
                clear_cache_on_logout()
            except Exception as cache_error:
                logger.error(f"Error clearing symbol cache: {cache_error}")
            
            # Revoke the auth token in database
            inserted_id = upsert_auth(username, "", "", revoke=True)
            if inserted_id is not None:
                logger.info(f"Auto-expiry: Revoked auth tokens for user: {username}")
            else:
                logger.error(f"Auto-expiry: Failed to revoke auth tokens for user: {username}")
        except Exception as e:
            logger.error(f"Error revoking tokens during auto-expiry for user {username}: {e}")

def check_session_validity(f):
    """Decorator to check session validity before executing route"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_session_valid():
            # Revoke tokens before clearing session
            revoke_user_tokens()
            session.clear()
            logger.info("Invalid session detected - redirecting to login")
            return redirect(url_for('auth.login'))
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
