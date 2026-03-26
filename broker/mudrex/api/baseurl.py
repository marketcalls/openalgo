"""
Mudrex API base URL and authentication header helpers.

All Mudrex REST endpoints live under https://trade.mudrex.com/fapi/v1.
Authentication is a single ``X-Authentication`` header carrying the API secret.
"""

import os

BASE_URL: str = os.getenv("MUDREX_BASE_URL", "https://trade.mudrex.com/fapi/v1")


def get_url(endpoint: str) -> str:
    """Build a full Mudrex API URL from a relative path."""
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return BASE_URL + endpoint


def get_auth_headers(api_secret: str | None = None) -> dict[str, str]:
    """Return headers required for every authenticated Mudrex request.

    Args:
        api_secret: The user's API secret.  Falls back to BROKER_API_SECRET env var.
    """
    secret = api_secret or os.getenv("BROKER_API_SECRET", "")
    return {
        "X-Authentication": secret,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "openalgo-python-client",
    }
