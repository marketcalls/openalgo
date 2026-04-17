import importlib
from typing import Any, Dict, List, Optional, Tuple, Union

from database.auth_db import Auth, db_session, get_auth_token_broker, verify_api_key
from database.token_db import get_token
from utils.constants import VALID_EXCHANGES
from utils.data_router import (
    VendorCapabilityError,
    VendorSymbolError,
    build_data_handler,
    is_vendor_enabled,
    vendor_capability_enabled,
    vendor_exchange_supported,
)
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


def validate_symbol_exchange(symbol: str, exchange: str) -> tuple[bool, str | None]:
    """
    Validate that a symbol exists for the given exchange.

    Args:
        symbol: Trading symbol
        exchange: Exchange (e.g., NSE, NFO)

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Validate exchange
    exchange_upper = exchange.upper()
    if exchange_upper not in VALID_EXCHANGES:
        return False, f"Invalid exchange '{exchange}'. Must be one of: {', '.join(VALID_EXCHANGES)}"

    # Validate symbol exists in master contract
    token = get_token(symbol, exchange_upper)
    if token is None:
        return (
            False,
            f"Symbol '{symbol}' not found for exchange '{exchange}'. Please verify the symbol name and ensure master contracts are downloaded.",
        )

    return True, None


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


def get_depth_with_auth(
    auth_token: str,
    feed_token: str | None,
    broker: str,
    symbol: str,
    exchange: str,
    user_id: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get market depth for a symbol using provided auth tokens.

    Args:
        auth_token: Authentication token for the broker API
        feed_token: Feed token for market data (if required by broker)
        broker: Name of the broker
        symbol: Trading symbol
        exchange: Exchange (e.g., NSE, BSE)
        user_id: User ID for broker-specific functionality

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Validate symbol and exchange before making broker API call
    is_valid, error_msg = validate_symbol_exchange(symbol, exchange)
    if not is_valid:
        return False, {"status": "error", "message": error_msg}, 400

    if is_vendor_enabled():
        if not vendor_exchange_supported(exchange):
            return (
                False,
                {"status": "error", "message": f"Active data vendor does not support exchange '{exchange}'"},
                400,
            )
        if not vendor_capability_enabled("depth"):
            return (
                False,
                {"status": "error", "message": "Market depth is not supported by the active data vendor"},
                501,
            )

    try:
        data_handler, _kind, _name = build_data_handler(broker, auth_token, feed_token, user_id)
    except Exception as e:
        logger.exception(f"Failed to build data handler: {e}")
        return False, {"status": "error", "message": str(e)}, 500

    try:
        depth = data_handler.get_depth(symbol, exchange)

        if depth is None:
            return False, {"status": "error", "message": "Failed to fetch market depth"}, 500

        return True, {"status": "success", "data": depth}, 200
    except VendorSymbolError as e:
        return False, {"status": "error", "message": str(e)}, 400
    except VendorCapabilityError as e:
        return False, {"status": "error", "message": str(e)}, 501
    except Exception as e:
        logger.exception(f"Error fetching depth: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_depth(
    symbol: str,
    exchange: str,
    api_key: str | None = None,
    auth_token: str | None = None,
    feed_token: str | None = None,
    broker: str | None = None,
    user_id: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get market depth for a symbol.
    Supports both API-based authentication and direct internal calls.

    Args:
        symbol: Trading symbol
        exchange: Exchange (e.g., NSE, BSE)
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        feed_token: Direct broker feed token (for internal calls)
        broker: Direct broker name (for internal calls)
        user_id: User ID for broker-specific functionality (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        auth_info = get_auth_token_broker(api_key, include_feed_token=True)
        if len(auth_info) == 3:
            AUTH_TOKEN, FEED_TOKEN, broker_name = auth_info
        else:
            return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403

        # Get user_id from auth database
        extracted_user_id = None
        try:
            extracted_user_id = verify_api_key(api_key)  # Get the actual user_id from API key
            if extracted_user_id:
                auth_obj = Auth.query.filter_by(
                    name=extracted_user_id
                ).first()  # Query using user_id instead of api_key
                if auth_obj and auth_obj.user_id:
                    extracted_user_id = auth_obj.user_id
        except Exception as e:
            logger.warning(f"Could not fetch user_id: {e}")

        return get_depth_with_auth(
            AUTH_TOKEN, FEED_TOKEN, broker_name, symbol, exchange, extracted_user_id
        )

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_depth_with_auth(auth_token, feed_token, broker, symbol, exchange, user_id)

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
