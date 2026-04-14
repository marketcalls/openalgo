import copy
import importlib
from typing import Any, Dict, List, Optional, Tuple

from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from events import AnalyzerErrorEvent, AllOrdersCancelledEvent, OrderFailedEvent
from utils.event_bus import bus
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

API_TYPE = "cancelallorder"


def emit_analyzer_error(request_data: dict[str, Any], error_message: str) -> dict[str, Any]:
    """
    Helper function to emit analyzer error events

    Args:
        request_data: Original request data
        error_message: Error message to emit

    Returns:
        Error response dictionary
    """
    error_response = {"mode": "analyze", "status": "error", "message": error_message}

    # Store complete request data without apikey
    analyzer_request = request_data.copy()
    if "apikey" in analyzer_request:
        del analyzer_request["apikey"]
    analyzer_request["api_type"] = API_TYPE

    bus.publish(AnalyzerErrorEvent(
        mode="analyze", api_type=API_TYPE,
        request_data=analyzer_request, response_data=error_response,
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


def cancel_all_orders_with_auth(
    order_data: dict[str, Any], auth_token: str, broker: str, original_data: dict[str, Any]
) -> tuple[bool, dict[str, Any], int]:
    """
    Cancel all orders using provided auth token.

    Args:
        order_data: Order data
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

    # If in analyze mode, route to sandbox for virtual trading
    if get_analyze_mode():
        from services.sandbox_service import sandbox_cancel_all_orders

        api_key = original_data.get("apikey")
        if not api_key:
            return (
                False,
                emit_analyzer_error(original_data, "API key required for sandbox mode"),
                400,
            )

        # Route to sandbox cancel all orders
        success, response_data, status_code = sandbox_cancel_all_orders(
            order_data, api_key, original_data
        )

        # Store complete request data without apikey
        analyzer_request = order_request_data.copy()
        analyzer_request["api_type"] = API_TYPE

        bus.publish(AllOrdersCancelledEvent(
            mode="analyze", api_type=API_TYPE,
            canceled_count=response_data.get("canceled_count", 0) if isinstance(response_data, dict) else 0,
            failed_count=response_data.get("failed_count", 0) if isinstance(response_data, dict) else 0,
            canceled_orders=response_data.get("canceled_orders", []) if isinstance(response_data, dict) else [],
            failed_cancellations=response_data.get("failed_cancellations", []) if isinstance(response_data, dict) else [],
            request_data=analyzer_request, response_data=response_data,
            api_key=order_data.get("apikey", ""),
        ))
        return success, response_data, status_code

    broker_module = import_broker_module(broker)
    if broker_module is None:
        error_response = {"status": "error", "message": "Broker-specific module not found"}
        bus.publish(OrderFailedEvent(
            mode="live", api_type=API_TYPE,
            request_data=order_request_data, response_data=error_response,
            api_key=original_data.get("apikey", ""),
            error_message="Broker-specific module not found",
        ))
        return False, error_response, 404

    try:
        # Use the dynamically imported module's function to cancel all orders
        canceled_orders, failed_cancellations = broker_module.cancel_all_orders_api(
            order_data, auth_token
        )
    except Exception as e:
        logger.exception(f"Error in broker_module.cancel_all_orders_api: {e}")
        error_response = {
            "status": "error",
            "message": "Failed to cancel all orders due to internal error",
        }
        bus.publish(OrderFailedEvent(
            mode="live", api_type=API_TYPE,
            request_data=order_request_data, response_data=error_response,
            api_key=original_data.get("apikey", ""),
            error_message=str(e),
        ))
        return False, error_response, 500

    # Prepare response data
    response_data = {
        "status": "success",
        "canceled_orders": canceled_orders,
        "failed_cancellations": failed_cancellations,
        "message": f"Canceled {len(canceled_orders)} orders. Failed to cancel {len(failed_cancellations)} orders.",
    }

    bus.publish(AllOrdersCancelledEvent(
        mode="live", api_type=API_TYPE,
        canceled_count=len(canceled_orders), failed_count=len(failed_cancellations),
        canceled_orders=canceled_orders, failed_cancellations=failed_cancellations,
        request_data=order_request_data, response_data=response_data,
        api_key=original_data.get("apikey", ""),
    ))

    return True, response_data, 200


def cancel_all_orders(
    order_data: dict[str, Any] = None,
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Cancel all open orders.
    Supports both API-based authentication and direct internal calls.

    Args:
        order_data: Order data (optional, may contain additional filters)
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    if order_data is None:
        order_data = {}

    original_data = copy.deepcopy(order_data)
    if api_key:
        original_data["apikey"] = api_key

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Check if user is in semi-auto mode (cancelallorder is blocked in semi-auto)
        # BUT allow execution in analyze/sandbox mode (virtual trading should always work)
        from database.auth_db import get_order_mode, verify_api_key

        # Check analyze mode first - if in analyze mode, allow execution
        if not get_analyze_mode():
            user_id = verify_api_key(api_key)
            if user_id:
                order_mode = get_order_mode(user_id)
                if order_mode == "semi_auto":
                    error_response = {
                        "status": "error",
                        "message": "Cancel all orders operation is not allowed in Semi-Auto mode. Please switch to Auto mode to cancel orders.",
                    }
                    logger.warning(f"Cancel all orders blocked for user {user_id} (semi-auto mode)")
                    order_request_data = copy.deepcopy(original_data)
                    if "apikey" in order_request_data:
                        order_request_data.pop("apikey", None)
                    bus.publish(AllOrdersCancelledEvent(
                        mode="live", api_type=API_TYPE,
                        canceled_count=0, failed_count=0,
                        canceled_orders=[], failed_cancellations=[],
                        request_data=order_request_data, response_data=error_response,
                        api_key=api_key,
                    ))
                    return False, error_response, 403

        # Add API key to order data
        order_data["apikey"] = api_key

        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {"status": "error", "message": "Invalid openalgo apikey"}
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403

        return cancel_all_orders_with_auth(order_data, AUTH_TOKEN, broker_name, original_data)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return cancel_all_orders_with_auth(order_data, auth_token, broker, original_data)

    # Case 3: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400
