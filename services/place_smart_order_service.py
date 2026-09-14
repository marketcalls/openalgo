import copy
import importlib
from typing import Any

from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from events import (
    AnalyzerErrorEvent,
    OrderFailedEvent,
    OrderPlacedEvent,
    SmartOrderNoActionEvent,
)
from utils.constants import (
    REQUIRED_SMART_ORDER_FIELDS,
    VALID_ACTIONS,
    VALID_EXCHANGES,
    VALID_PRICE_TYPES,
    VALID_PRODUCT_TYPES,
)
from utils.event_bus import bus
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


#: A smart order aims at a target position size, so the correct outcome is
#: often no order at all. Every broker adapter reports that the same way -
#: ``res`` is None because no API call was made, and the response carries a
#: success status and one of two messages, chosen by whether the caller asked
#: for a quantity:
#:
#:   "No action needed. Position size matches current position"
#:   "No OpenPosition Found. Not placing Exit order."
#:
#: The sandbox produces the same pair (``services/sandbox_service.py``), as does
#: the frontend, which already treats both as informational in
#: ``frontend/src/hooks/useSocket.ts``.
#:
#: Only the first was ever matched here. The second fell through to the failure
#: path, so closing a position the user does not hold - clicking the red X on an
#: empty positions page - was reported as a placed order in analyze mode and as
#: an error in live mode. Issue #2054.
NO_ACTION_MARKERS = (
    "No action needed",
    "No OpenPosition Found",
    # The live path rewrites the first message into this form before it reaches
    # the frontend, and the sandbox emits it directly.
    "Already Matched",
)


def is_no_action_response(response: dict[str, Any]) -> bool:
    """Whether a smart order correctly resulted in no order being placed.

    Args:
        response: The response dict from a broker adapter or the sandbox.

    Returns:
        bool: True when the adapter reported success and placed nothing.
    """
    if not isinstance(response, dict) or response.get("status") != "success":
        return False

    message = response.get("message") or ""
    return any(marker in message for marker in NO_ACTION_MARKERS)


def emit_analyzer_error(request_data: dict[str, Any], error_message: str) -> dict[str, Any]:
    """Publish an analyzer error event and return the error response dict."""
    error_response = {"mode": "analyze", "status": "error", "message": error_message}

    analyzer_request = request_data.copy()
    if "apikey" in analyzer_request:
        del analyzer_request["apikey"]
    analyzer_request["api_type"] = "placesmartorder"

    bus.publish(AnalyzerErrorEvent(
        mode="analyze",
        api_type="placesmartorder",
        request_data=analyzer_request,
        response_data=error_response,
        error_message=error_message,
    ))

    return error_response


def import_broker_module(broker_name: str) -> Any | None:
    """
    Dynamically import the broker-specific order API module.

    Args:
        broker_name: Name of the broker

    Returns:
        The imported module or None if import fails
    """
    try:
        module_path = f"broker.{broker_name}.api.order_api"
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None


def validate_smart_order(order_data: dict[str, Any]) -> tuple[bool, str | None]:
    """
    Validate smart order data

    Args:
        order_data: Order data to validate

    Returns:
        Tuple containing:
        - Success status (bool)
        - Error message (str) or None if validation succeeded
    """
    # Check for missing mandatory fields
    missing_fields = [field for field in REQUIRED_SMART_ORDER_FIELDS if field not in order_data]
    if missing_fields:
        return False, f"Missing mandatory field(s): {', '.join(missing_fields)}"

    # Validate exchange
    if "exchange" in order_data and order_data["exchange"] not in VALID_EXCHANGES:
        return False, f"Invalid exchange. Must be one of: {', '.join(VALID_EXCHANGES)}"

    # Convert action to uppercase and validate
    if "action" in order_data:
        order_data["action"] = order_data["action"].upper()
        if order_data["action"] not in VALID_ACTIONS:
            return (
                False,
                f"Invalid action. Must be one of: {', '.join(VALID_ACTIONS)} (case insensitive)",
            )

    # Validate price type if provided
    if "pricetype" in order_data and order_data["pricetype"] not in VALID_PRICE_TYPES:
        return False, f"Invalid price type. Must be one of: {', '.join(VALID_PRICE_TYPES)}"

    # Validate product type if provided
    if "product" in order_data and order_data["product"] not in VALID_PRODUCT_TYPES:
        return False, f"Invalid product type. Must be one of: {', '.join(VALID_PRODUCT_TYPES)}"

    return True, None


def place_smart_order_with_auth(
    order_data: dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: dict[str, Any],
) -> tuple[bool, dict[str, Any], int]:
    """
    Place a smart order using provided auth token.

    Args:
        order_data: Smart order data
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    order_request_data = copy.deepcopy(original_data)
    if "apikey" in order_request_data:
        order_request_data.pop("apikey", None)

    api_key = original_data.get("apikey", "")

    # Validate order data
    is_valid, error_message = validate_smart_order(order_data)
    if not is_valid:
        if get_analyze_mode():
            return False, emit_analyzer_error(original_data, error_message), 400
        error_response = {"status": "error", "message": error_message}
        bus.publish(OrderFailedEvent(
            mode="live", api_type="placesmartorder",
            request_data=order_request_data, response_data=error_response,
            error_message=error_message,
        ))
        return False, error_response, 400

    # If in analyze mode, route to sandbox for sandbox trading
    if get_analyze_mode():
        from services.sandbox_service import sandbox_place_smart_order

        if not api_key:
            return (
                False,
                emit_analyzer_error(original_data, "API key required for sandbox mode"),
                400,
            )

        success, response_data, status_code = sandbox_place_smart_order(
            order_data, api_key, original_data
        )

        analyzer_request = order_request_data.copy()
        analyzer_request["api_type"] = "placesmartorder"

        # Check if this is a no-action case. Written as one call so the two
        # messages cannot drift apart again, and so the status check applies to
        # every marker: as an inline expression the "and" bound tighter than the
        # "or", which let a failed response carrying "Already Matched" through.
        no_action = is_no_action_response(response_data)

        if no_action:
            bus.publish(SmartOrderNoActionEvent(
                mode="analyze", api_type="placesmartorder",
                symbol=order_data.get("symbol", ""),
                exchange=order_data.get("exchange", ""),
                message=response_data.get("message", ""),
                request_data=analyzer_request, response_data=response_data,
                api_key=api_key,
            ))
        else:
            bus.publish(OrderPlacedEvent(
                mode="analyze", api_type="placesmartorder",
                strategy=order_data.get("strategy", ""),
                symbol=order_data.get("symbol", ""),
                exchange=order_data.get("exchange", ""),
                action=order_data.get("action", ""),
                quantity=int(order_data.get("quantity", 0)),
                pricetype=order_data.get("pricetype", ""),
                product=order_data.get("product", ""),
                orderid=response_data.get("orderid", ""),
                request_data=analyzer_request, response_data=response_data,
                api_key=api_key,
            ))

        return success, response_data, status_code

    # Live Mode - Proceed with actual order placement
    broker_module = import_broker_module(broker)
    if broker_module is None:
        error_response = {"status": "error", "message": "Broker-specific module not found"}
        bus.publish(OrderFailedEvent(
            mode="live", api_type="placesmartorder",
            request_data=order_request_data, response_data=error_response,
            api_key=api_key, error_message="Broker-specific module not found",
        ))
        return False, error_response, 404

    try:
        res, response_data, order_id = broker_module.place_smartorder_api(order_data, auth_token)

        # Handle the cases where the adapter placed no order on purpose. It
        # makes no API call for either, so res is None and there is no order id
        # to report; both are a success, not a failure.
        if res is None and is_no_action_response(response_data):
            broker_message = response_data.get("message") or ""

            if "No OpenPosition Found" in broker_message:
                # Nothing to exit. Passed through as the adapter worded it, so
                # the message names the actual cause rather than claiming the
                # position matched a target the user never set.
                message = broker_message
            else:
                # Position already at the requested size. Reworded as before,
                # which is the wording the positions page matches on.
                message = "Positions Already Matched. No Action needed."

            order_response_data = {"status": "success", "message": message}
            bus.publish(SmartOrderNoActionEvent(
                mode="live", api_type="placesmartorder",
                symbol=order_data.get("symbol", ""),
                exchange=order_data.get("exchange", ""),
                message=message,
                request_data=order_request_data, response_data=order_response_data,
                api_key=api_key,
            ))
            return True, order_response_data, 200

        # Log successful order immediately after placement
        if res and res.status == 200:
            order_response_data = {"status": "success", "orderid": order_id}
            bus.publish(OrderPlacedEvent(
                mode="live", api_type="placesmartorder",
                strategy=order_data.get("strategy", ""),
                symbol=order_data.get("symbol", ""),
                exchange=order_data.get("exchange", ""),
                action=order_data.get("action", ""),
                quantity=int(order_data.get("quantity", 0)),
                pricetype=order_data.get("pricetype", ""),
                product=order_data.get("product", ""),
                orderid=str(order_id),
                request_data=order_request_data, response_data=order_response_data,
                api_key=api_key,
            ))

    except Exception as e:
        logger.exception(f"Error in broker_module.place_smartorder_api: {e}")
        error_response = {
            "status": "error",
            "message": "Failed to place smart order due to internal error",
        }
        bus.publish(OrderFailedEvent(
            mode="live", api_type="placesmartorder",
            request_data=order_request_data, response_data=error_response,
            api_key=api_key, error_message=str(e),
        ))
        return False, error_response, 500

    if res and res.status == 200:
        return True, order_response_data, 200
    else:
        message = (
            response_data.get("message", "Failed to place smart order")
            if isinstance(response_data, dict)
            else "Failed to place smart order"
        )
        error_response = {"status": "error", "message": message}
        bus.publish(OrderFailedEvent(
            mode="live", api_type="placesmartorder",
            request_data=order_request_data, response_data=error_response,
            api_key=api_key, error_message=message,
        ))
        status_code = res.status if res and hasattr(res, "status") else 500
        return False, error_response, status_code


def place_smart_order(
    order_data: dict[str, Any],
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Place a smart order.
    Supports both API-based authentication and direct internal calls.

    Args:
        order_data: Smart order data
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(order_data)
    if api_key:
        original_data["apikey"] = api_key

    # Add API key to order data if provided (needed for validation)
    if api_key:
        order_data["apikey"] = api_key

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Check if order should be routed to Action Center (semi-auto mode)
        from services.order_router_service import queue_order, should_route_to_pending

        if should_route_to_pending(api_key, "smartorder"):
            return queue_order(api_key, original_data, "smartorder")

        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {"status": "error", "message": "Invalid openalgo apikey"}
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403

        return place_smart_order_with_auth(
            order_data, AUTH_TOKEN, broker_name, original_data
        )

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return place_smart_order_with_auth(
            order_data, auth_token, broker, original_data
        )

    # Case 3: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400
