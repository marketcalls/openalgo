import importlib
from typing import Any, Dict, List, Optional, Tuple, Union

from database.auth_db import get_broker_name, verify_api_key
from utils.credential_errors import credential_error
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


def import_broker_module(broker_name: str) -> Any | None:
    """
    Dynamically import the broker-specific data module.

    Args:
        broker_name: Name of the broker

    Returns:
        The imported module or None if import fails
    """
    try:
        module_path = f"broker.{broker_name}.api.data"
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None


def get_intervals_with_auth(auth_token: str, broker: str) -> tuple[bool, dict[str, Any], int]:
    """
    Get supported intervals for the broker using provided auth token.

    Args:
        auth_token: Authentication token for the broker API
        broker: Name of the broker

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    broker_module = import_broker_module(broker)
    if broker_module is None:
        return False, {"status": "error", "message": "Broker-specific module not found"}, 404

    try:
        # Initialize broker's data handler
        data_handler = broker_module.BrokerData(auth_token)

        # Get supported intervals from the timeframe map with proper numerical sorting
        def sort_intervals(interval_list):
            """Sort intervals numerically instead of alphabetically"""

            def extract_number(interval):
                """Extract numeric value from interval string for proper sorting"""
                import re

                match = re.match(r"(\d+)", interval)
                return int(match.group(1)) if match else 0

            return sorted(interval_list, key=extract_number)

        intervals = {
            "seconds": sort_intervals(
                [k for k in data_handler.timeframe_map.keys() if k.endswith("s")]
            ),
            "minutes": sort_intervals(
                [k for k in data_handler.timeframe_map.keys() if k.endswith("m")]
            ),
            "hours": sort_intervals(
                [k for k in data_handler.timeframe_map.keys() if k.endswith("h")]
            ),
            "days": sorted([k for k in data_handler.timeframe_map.keys() if k == "D"]),
            "weeks": sorted([k for k in data_handler.timeframe_map.keys() if k == "W"]),
            "months": sorted([k for k in data_handler.timeframe_map.keys() if k == "M"]),
        }

        return True, {"status": "success", "data": intervals}, 200
    except Exception as e:
        logger.exception(f"Error getting supported intervals: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_intervals(
    api_key: str | None = None, auth_token: str | None = None, broker: str | None = None
) -> tuple[bool, dict[str, Any], int]:
    """
    Get supported intervals for the broker.
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

        # get_broker_name() answers None when the Auth row is absent or revoked,
        # and this endpoint dispatches on the name: import_broker_module(None)
        # would look for broker.None.api.data and answer 404 "Broker-specific
        # module not found" plus an ERROR log line per call. The key is valid, so
        # the honest answer is the shared credential one.
        broker_name = get_broker_name(api_key)
        if not broker_name:
            return False, *credential_error(api_key)

        return get_intervals_with_auth("", broker_name)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_intervals_with_auth(auth_token, broker)

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
