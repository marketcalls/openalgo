# utils/config.py

import os
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file with override=True to ensure values are updated
load_dotenv(override=True)


def get_broker_api_key() -> Optional[str]:
    """Get broker API key from BROKER_API_KEY environment variable."""
    return os.getenv("BROKER_API_KEY")


def get_broker_api_secret() -> Optional[str]:
    """Get broker API secret from BROKER_API_SECRET environment variable."""
    return os.getenv("BROKER_API_SECRET")


def get_login_rate_limit_min() -> str:
    """Get login rate limit per minute from LOGIN_RATE_LIMIT_MIN environment variable."""
    return os.getenv("LOGIN_RATE_LIMIT_MIN", "5 per minute")


def get_login_rate_limit_hour() -> str:
    """Get login rate limit per hour from LOGIN_RATE_LIMIT_HOUR environment variable."""
    return os.getenv("LOGIN_RATE_LIMIT_HOUR", "25 per hour")


def get_host_server() -> str:
    """Get host server URL from HOST_SERVER environment variable."""
    return os.getenv("HOST_SERVER", "http://127.0.0.1:5000")
