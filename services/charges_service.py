"""Charges for an order: brokerage and statutory charges, before it is placed.

The figures come from the same calculation that charges sandbox trades
(``sandbox/charges.py``), under the brokerage plan saved on
/sandbox/commissions. No broker is called: the result is the same in live and
analyzer mode, and it does not depend on which broker is logged in.
"""

import copy
from typing import Any

from database.apilog_db import async_log_order, executor
from database.auth_db import verify_api_key
from database.token_db import get_symbol_info
from utils.constants import VALID_ACTIONS, VALID_EXCHANGES, VALID_PRODUCT_TYPES
from utils.logging import get_logger

logger = get_logger(__name__)

#: The request fields, all required.
REQUIRED_FIELDS = ("symbol", "exchange", "product", "action", "quantity", "price")


def validate_charges_data(
    data: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Check a charges request and return it in the form the calculation takes.

    Args:
        data: The request: symbol, exchange, product, action, quantity, price.

    Returns:
        ``(ok, order, error)``. ``order`` holds the cleaned fields when ``ok``.
    """
    if not isinstance(data, dict):
        return False, None, "Request must be a JSON object"

    for name in REQUIRED_FIELDS:
        if data.get(name) in (None, ""):
            return False, None, f"Missing mandatory field: {name}"

    symbol = str(data["symbol"]).strip()
    exchange = str(data["exchange"]).strip().upper()
    product = str(data["product"]).strip().upper()
    action = str(data["action"]).strip().upper()

    if not symbol or len(symbol) > 50:
        return False, None, "Symbol must be between 1 and 50 characters"
    if exchange not in VALID_EXCHANGES:
        return False, None, f"Invalid exchange. Must be one of: {', '.join(VALID_EXCHANGES)}"
    if product not in VALID_PRODUCT_TYPES:
        return (
            False,
            None,
            f"Invalid product type. Must be one of: {', '.join(VALID_PRODUCT_TYPES)}",
        )
    if action not in VALID_ACTIONS:
        return False, None, f"Invalid action. Must be one of: {', '.join(VALID_ACTIONS)}"

    try:
        quantity = float(data["quantity"])
    except (TypeError, ValueError):
        return False, None, "Quantity must be a positive number"
    if not quantity > 0 or quantity != quantity or quantity == float("inf"):
        return False, None, "Quantity must be a positive number"

    try:
        price = float(data["price"])
    except (TypeError, ValueError):
        return False, None, "Price must be a positive number"
    if not price > 0 or price != price or price == float("inf"):
        return False, None, "Price must be a positive number"

    return (
        True,
        {
            "symbol": symbol,
            "exchange": exchange,
            "product": product,
            "action": action,
            "quantity": int(quantity) if quantity == int(quantity) else quantity,
            "price": price,
        },
        None,
    )


def charges_for_order(order: dict[str, Any]) -> tuple[bool, dict[str, Any], int]:
    """Work out the charges for a validated order.

    Args:
        order: From validate_charges_data.

    Returns:
        ``(success, response, status_code)``.
    """
    from sandbox.charge_manager import order_charges

    if get_symbol_info(order["symbol"], order["exchange"]) is None:
        return (
            False,
            {
                "status": "error",
                "message": f"Symbol {order['symbol']} not found on {order['exchange']}",
            },
            400,
        )

    result = order_charges(**order)
    if result is None:
        return (
            False,
            {
                "status": "error",
                "message": (
                    f"Orders cannot be placed on {order['exchange']}, so no charges apply to it"
                ),
            },
            400,
        )

    return True, {"status": "success", "data": {**order, **result}}, 200


def calculate_charges(
    charges_data: dict[str, Any],
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """Brokerage and statutory charges for one order.

    Supports both API-based authentication and direct internal calls.

    Args:
        charges_data: symbol, exchange, product, action, quantity and price.
        api_key: OpenAlgo API key (for API-based calls).
        auth_token: Broker authentication token (for internal calls). Not
            used by the calculation; it marks a caller that is already
            authenticated, as in the other services.
        broker: Broker name (for internal calls). Not used either.

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(charges_data) if isinstance(charges_data, dict) else {}
    # The key is the caller's secret and has no place in the request log.
    original_data.pop("apikey", None)

    is_valid, order, error_message = validate_charges_data(charges_data)
    if not is_valid:
        error_response = {"status": "error", "message": error_message}
        executor.submit(async_log_order, "charges", original_data, error_response)
        return False, error_response, 400

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        if verify_api_key(api_key) is None:
            # Skip logging for invalid API keys to prevent database flooding
            return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403

    # Case 2: Direct internal call, already authenticated
    elif not (auth_token and broker):
        return (
            False,
            {
                "status": "error",
                "message": "Either api_key or both auth_token and broker must be provided",
            },
            400,
        )

    try:
        success, response, status_code = charges_for_order(order)
    except Exception:
        logger.exception("Error calculating charges")
        error_response = {
            "status": "error",
            "message": "Failed to calculate charges due to internal error",
        }
        executor.submit(async_log_order, "charges", original_data, error_response)
        return False, error_response, 500

    executor.submit(async_log_order, "charges", original_data, response)
    return success, response, status_code
