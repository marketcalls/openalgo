# sandbox/utils.py
"""
Sandbox Utility Functions

Shared utilities for the sandbox virtual trading environment.
"""

import os
from datetime import datetime, time as dt_time, timedelta
import pytz

from utils.logging import get_logger

logger = get_logger(__name__)


def get_sandbox_session_start():
    """
    Calculate the start time of the current sandbox trading session.

    The session boundary is determined by the SESSION_EXPIRY_TIME environment
    variable (default: '03:00' IST). Orders placed before this time are
    considered from a previous session.

    Returns:
        datetime: The session start time (timezone-naive for DB compatibility)
    """
    # Get session expiry time from config (e.g., '03:00')
    session_expiry_str = os.getenv('SESSION_EXPIRY_TIME', '03:00')
    expiry_hour, expiry_minute = map(int, session_expiry_str.split(':'))

    # Get current time in IST
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    today = now.date()

    # Calculate session start time
    # If current time is before session expiry (e.g., before 3 AM),
    # session started yesterday at expiry time
    session_expiry_time = dt_time(expiry_hour, expiry_minute)

    if now.time() < session_expiry_time:
        # We're in the early morning before session expiry
        # Session started yesterday at expiry time
        session_start = datetime.combine(today - timedelta(days=1), session_expiry_time)
    else:
        # We're after session expiry time
        # Session started today at expiry time
        session_start = datetime.combine(today, session_expiry_time)

    logger.debug(f"Sandbox session start: {session_start}")
    return session_start
