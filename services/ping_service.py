from typing import Any, Dict, Optional, Tuple

from database.auth_db import get_broker_name, verify_api_key
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


def ping_with_auth(auth_token: str, broker: str) -> tuple[bool, dict[str, Any], int]:
    """
    Validate auth token and return pong response.

    Args:
        auth_token: Authentication token for the broker API
        broker: Name of the broker

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Since we've already validated the auth_token by getting here,
    # we can simply return a pong response
    return True, {"status": "success", "data": {"message": "pong", "broker": broker}}, 200


def get_ping(
    api_key: str | None = None, auth_token: str | None = None, broker: str | None = None
) -> tuple[bool, dict[str, Any], int]:
    """
    Ping endpoint to check API connectivity and authentication.
    Supports both API-based authentication and direct internal calls.

    Args:
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Identity, not credential: this endpoint never calls the broker, so it
        # must not be gated on a live broker session. get_auth_token_broker()
        # withholds the token after the daily rollover, which would fail this
        # every morning for no reason.
        if not verify_api_key(api_key):
            return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403
        return ping_with_auth("", get_broker_name(api_key))

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return ping_with_auth(auth_token, broker)

    # Case 3: Invalid parameters
    else:
        return (
            False,
            {
                "status": "error",
                "message": "Either api_key or both auth_token and broker must be provided",
            },
            400,
        )
