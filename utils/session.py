from datetime import datetime, timedelta
import pytz
from functools import wraps
from flask import session, redirect, url_for
import logging
import os

logger = logging.getLogger(__name__)

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
    
    # Calculate expiry time
    expiry_time = login_time + get_session_expiry_time()
    
    # Check if current time is past expiry
    if now_ist > expiry_time:
        logger.info("Session expired")
        return False
    
    return True

def check_session_validity(f):
    """Decorator to check session validity before executing route"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_session_valid():
            logger.info("Invalid session detected - clearing session")
            clear_session()
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def invalidate_session_if_invalid(f):
    """Decorator to invalidate session if invalid without redirecting"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_session_valid():
            logger.info("Invalid session detected - clearing session")
            clear_session()
        return f(*args, **kwargs)
    return decorated_function

def clear_session():
    """Clear the current session"""
    session.pop('user', None)
    session.pop('broker', None)
    session.pop('logged_in', None)
    session.pop('login_time', None)
    logger.info("Session cleared")
