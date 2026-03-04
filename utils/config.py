# utils/config.py

import os
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file with override=True to ensure values are updated
load_dotenv(override=True)


def get_broker_api_key() -> Optional[str]:
    """Get the broker API key from environment variables.

    Returns:
        The broker API key, or None if not set.
    """
    return os.getenv("BROKER_API_KEY")


def get_broker_api_secret() -> Optional[str]:
    """Get the broker API secret from environment variables.

    Returns:
        The broker API secret, or None if not set.
    """
    return os.getenv("BROKER_API_SECRET")


def get_login_rate_limit_min() -> str:
    """Get the per-minute login rate limit from environment variables.

    Returns:
        The per-minute rate limit string, defaults to ``'5 per minute'``.
    """
    return os.getenv("LOGIN_RATE_LIMIT_MIN", "5 per minute")


def get_login_rate_limit_hour() -> str:
    """Get the per-hour login rate limit from environment variables.

    Returns:
        The per-hour rate limit string, defaults to ``'25 per hour'``.
    """
    return os.getenv("LOGIN_RATE_LIMIT_HOUR", "25 per hour")


def get_host_server() -> str:
    """Get the host server URL from environment variables.

    Returns:
        The host server URL, defaults to ``'http://127.0.0.1:5000'``.
    """
    return os.getenv("HOST_SERVER", "http://127.0.0.1:5000")
