"""Sahi hosts and request headers.

Sahi serves its API from two hosts (docs.sahi.com, Authentication):

    auth host  https://apis.sahi.com    POST /api/v1/apikeys/token only
    API host   https://direct.sahi.com  everything under /v1, and both
                                        WebSocket streams (wss://)

The scrip master is a public static file on a third host and needs no token.
"""

AUTH_BASE_URL = "https://apis.sahi.com"
API_BASE_URL = "https://direct.sahi.com"
WS_BASE_URL = "wss://direct.sahi.com"
SCRIP_MASTER_URL = "https://assets.sahi.com/external/instruments.csv"

# Sahi's CloudFront refuses requests without a User-Agent (seen on the
# WebSocket upgrade, where it answers 403), so every call names itself.
USER_AGENT = "openalgo-sahi/1.0"


def get_url(path):
    """Full URL on the API host for a path such as ``/v1/orders``."""
    return f"{API_BASE_URL}{path}"


def get_headers(auth_token, json_body=False):
    """Headers for an API-host request carrying the access token."""
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers
