# utils/config.py

import os

from dotenv import load_dotenv

# Load environment variables from .env file with override=True to ensure values are updated
load_dotenv(override=True)


def get_broker_api_key() -> str | None:
    """
    Retrieve the configured broker API key.

    Returns:
        str | None: The broker API key from environment variables, or None if not set.
    """
    return os.getenv("BROKER_API_KEY")


def get_broker_api_secret() -> str | None:
    """
    Retrieve the configured broker API secret.

    Returns:
        str | None: The broker API secret from environment variables, or None if not set.
    """
    return os.getenv("BROKER_API_SECRET")


def get_login_rate_limit_min() -> str:
    """
    Retrieve the rate limit for logins per minute.

    Returns:
        str: The rate limit string (e.g., '5 per minute').
    """
    return os.getenv("LOGIN_RATE_LIMIT_MIN", "5 per minute")


def get_login_rate_limit_hour() -> str:
    """
    Retrieve the rate limit for logins per hour.

    Returns:
        str: The rate limit string (e.g., '25 per hour').
    """
    return os.getenv("LOGIN_RATE_LIMIT_HOUR", "25 per hour")


def get_host_server() -> str:
    """
    Retrieve the host server URL.

    Returns:
        str: The host server URL string.
    """
    return os.getenv("HOST_SERVER", "http://127.0.0.1:5000")


def build_external_url(path: str) -> str:
    """
    Build an absolute URL for an outbound link, rooted at the configured HOST_SERVER.

    Use this instead of ``url_for(..., _external=True)`` for any URL that leaves
    the server - password reset emails, broker OAuth callbacks. Flask derives the
    scheme and host for ``_external=True`` from the incoming request's ``Host``
    header, which is attacker-controlled: a poisoned header rewrites the link to
    an origin of the attacker's choosing, and whoever follows it (the account
    owner reading their email, or the broker redirecting after OAuth) hands over
    the token in the URL. HOST_SERVER is set by every official install script and
    is not influenced by the request, so it cannot be poisoned this way.

    Args:
        path: Root-relative path, normally the return value of ``url_for()``
            called without ``_external``. A leading slash is optional.

    Returns:
        str: Absolute URL rooted at HOST_SERVER.
    """
    base = get_host_server().strip().rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"
