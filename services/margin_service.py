import copy
import importlib
import traceback
from typing import Any, Dict, List, Optional, Tuple

from database.apilog_db import async_log_order, executor
from database.auth_db import get_auth_token_broker
from utils.constants import VALID_ACTIONS, VALID_EXCHANGES, VALID_PRICE_TYPES, VALID_PRODUCT_TYPES
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Required fields for each position in the margin calculation
REQUIRED_POSITION_FIELDS = ["exchange", "symbol", "action", "quantity", "product", "pricetype"]


def import_broker_module(broker_name: str) -> Any | None:
    """
    Dynamically import the broker-specific margin API module.

    Args:
        broker_name: Name of the broker

    Returns:
        The imported module or None if import fails
    """
    try:
        module_path = f"broker.{broker_name}.api.margin_api"
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None


def validate_position(position: dict[str, Any], position_index: int) -> tuple[bool, str | None]:
    """
    Validate a single position in the margin calculation request.

    Args:
        position: Position data to validate
        position_index: Index of the position in the array (for error messages)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Error message (str) or None if validation succeeded
    """
    # Check for missing mandatory fields
    missing_fields = [field for field in REQUIRED_POSITION_FIELDS if field not in position]
    if missing_fields:
        return (
            False,
            f"Position {position_index}: Missing mandatory field(s): {', '.join(missing_fields)}",
        )

    # Validate exchange
    if position.get("exchange") not in VALID_EXCHANGES:
        return (
            False,
            f"Position {position_index}: Invalid exchange. Must be one of: {', '.join(VALID_EXCHANGES)}",
        )

    # Convert action to uppercase and validate
    if "action" in position:
        position["action"] = position["action"].upper()
        if position["action"] not in VALID_ACTIONS:
            return (
                False,
                f"Position {position_index}: Invalid action. Must be one of: {', '.join(VALID_ACTIONS)}",
            )

    # Validate price type
    if position.get("pricetype") not in VALID_PRICE_TYPES:
        return (
            False,
            f"Position {position_index}: Invalid price type. Must be one of: {', '.join(VALID_PRICE_TYPES)}",
        )

    # Validate product type
    if position.get("product") not in VALID_PRODUCT_TYPES:
        return (
            False,
            f"Position {position_index}: Invalid product type. Must be one of: {', '.join(VALID_PRODUCT_TYPES)}",
        )

    # Validate quantity is a positive number
    try:
        qty = int(position.get("quantity", 0))
        if qty <= 0:
            return False, f"Position {position_index}: Quantity must be a positive number"
    except (ValueError, TypeError):
        return False, f"Position {position_index}: Invalid quantity format"

    # Validate price is a number (can be 0 for market orders)
    try:
        price = float(position.get("price", 0))
        if price < 0:
            return False, f"Position {position_index}: Price cannot be negative"
    except (ValueError, TypeError):
        return False, f"Position {position_index}: Invalid price format"

    return True, None


def validate_margin_data(
    data: dict[str, Any],
) -> tuple[bool, list[dict[str, Any]] | None, str | None]:
    """
    Validate margin calculation request data.

    Args:
        data: Margin data to validate

    Returns:
        Tuple containing:
        - Success status (bool)
        - Validated positions list (list) or None if validation failed
        - Error message (str) or None if validation succeeded
    """
    # Check for apikey
    if "apikey" not in data:
        return False, None, "Missing mandatory field: apikey"

    # Check for positions array
    if "positions" not in data:
        return False, None, "Missing mandatory field: positions"

    positions = data.get("positions", [])

    # Validate positions is a list
    if not isinstance(positions, list):
        return False, None, "positions must be an array"

    # Validate positions is not empty
    if len(positions) == 0:
        return False, None, "positions array cannot be empty"

    # Validate maximum positions (Angel supports up to 50)
    if len(positions) > 50:
        return False, None, "Maximum 50 positions allowed per request"

    # Validate each position
    validated_positions = []
    for index, position in enumerate(positions, 1):
        is_valid, error_message = validate_position(position, index)
        if not is_valid:
            return False, None, error_message
        validated_positions.append(position)

    return True, validated_positions, None


def calculate_margin_with_auth(
    positions: list[dict[str, Any]], auth_token: str, broker: str, original_data: dict[str, Any]
) -> tuple[bool, dict[str, Any], int]:
    """
    Calculate margin using provided auth token.

    Args:
        positions: List of validated positions
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Import broker-specific module
    broker_module = import_broker_module(broker)
    if broker_module is None:
        error_response = {
            "status": "error",
            "message": f"Margin calculation not supported for broker: {broker}",
        }
        executor.submit(async_log_order, "margin", original_data, error_response)
        return False, error_response, 404

    # Check if broker module has margin calculation function
    if not hasattr(broker_module, "calculate_margin_api"):
        error_response = {
            "status": "error",
            "message": f"Margin calculation not implemented for broker: {broker}",
        }
        executor.submit(async_log_order, "margin", original_data, error_response)
        return False, error_response, 501

    try:
        # Call the broker's calculate_margin_api function
        response, response_data = broker_module.calculate_margin_api(positions, auth_token)
    except NotImplementedError as e:
        logger.info(f"Margin calculation not supported by broker {broker}: {e}")
        error_response = {"status": "error", "message": str(e)}
        executor.submit(async_log_order, "margin", original_data, error_response)
        return False, error_response, 501
    except Exception as e:
        logger.error(f"Error in broker_module.calculate_margin_api: {e}")
        traceback.print_exc()
        error_response = {
            "status": "error",
            "message": "Failed to calculate margin due to internal error",
        }
        executor.submit(async_log_order, "margin", original_data, error_response)
        return False, error_response, 500

    # Check response status
    if hasattr(response, "status_code"):
        status_code = response.status_code
    elif hasattr(response, "status"):
        status_code = response.status
    else:
        status_code = 500

    if status_code == 200:
        # Log successful margin calculation
        executor.submit(async_log_order, "margin", original_data, response_data)
        return True, response_data, 200
    else:
        message = (
            response_data.get("message", "Failed to calculate margin")
            if isinstance(response_data, dict)
            else "Failed to calculate margin"
        )
        error_response = {"status": "error", "message": message}
        executor.submit(async_log_order, "margin", original_data, error_response)
        return False, error_response, status_code if status_code != 200 else 500


def calculate_margin(
    margin_data: dict[str, Any],
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Calculate margin requirement for a basket of positions.
    Supports both API-based authentication and direct internal calls.

    Args:
        margin_data: Margin data containing positions array and apikey
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(margin_data)

    # Validate the margin data
    is_valid, validated_positions, error_message = validate_margin_data(margin_data)
    if not is_valid:
        error_response = {"status": "error", "message": error_message}
        executor.submit(async_log_order, "margin", original_data, error_response)
        return False, error_response, 400

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {"status": "error", "message": "Invalid openalgo apikey"}
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403

        return calculate_margin_with_auth(
            validated_positions, AUTH_TOKEN, broker_name, original_data
        )

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return calculate_margin_with_auth(validated_positions, auth_token, broker, original_data)

    # Case 3: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400
