import copy
import importlib
import traceback
from typing import Any, Dict, Optional, Tuple

from database.analyzer_db import async_log_analyzer
from database.apilog_db import async_log_order, executor
from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from extensions import socketio
from services.telegram_alert_service import telegram_alert_service
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


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
    analyzer_request["api_type"] = "cancelorder"

    # Log to analyzer database
    executor.submit(async_log_analyzer, analyzer_request, error_response, "cancelorder")

    # Emit socket event asynchronously (non-blocking)
    socketio.start_background_task(
        socketio.emit, "analyzer_update", {"request": analyzer_request, "response": error_response}
    )

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


def cancel_order_with_auth(
    orderid: str, auth_token: str, broker: str, original_data: dict[str, Any]
) -> tuple[bool, dict[str, Any], int]:
    """
    Cancel an order using provided auth token.

    Args:
        orderid: Order ID to cancel
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
        from services.sandbox_service import sandbox_cancel_order

        # Get API key from original data
        api_key = original_data.get("apikey")
        if not api_key:
            error_response = {
                "status": "error",
                "message": "API key required for sandbox mode",
                "mode": "analyze",
            }
            return False, error_response, 400

        # Route to sandbox
        order_data = {"orderid": orderid}
        return sandbox_cancel_order(order_data, api_key, original_data)

    broker_module = import_broker_module(broker)
    if broker_module is None:
        error_response = {"status": "error", "message": "Broker-specific module not found"}
        executor.submit(async_log_order, "cancelorder", original_data, error_response)
        return False, error_response, 404

    try:
        # Use the dynamically imported module's function to cancel the order
        response_message, status_code = broker_module.cancel_order(orderid, auth_token)
    except Exception as e:
        logger.error(f"Error in broker_module.cancel_order: {e}")
        traceback.print_exc()
        error_response = {
            "status": "error",
            "message": "Failed to cancel order due to internal error",
        }
        executor.submit(async_log_order, "cancelorder", original_data, error_response)
        return False, error_response, 500

    if status_code == 200:
        # Emit SocketIO event asynchronously (non-blocking)
        socketio.start_background_task(
            socketio.emit,
            "cancel_order_event",
            {"status": response_message.get("status"), "orderid": orderid, "mode": "live"},
        )
        order_response_data = {"status": "success", "orderid": orderid}
        executor.submit(async_log_order, "cancelorder", order_request_data, order_response_data)
        # Send Telegram alert in background task (non-blocking)
        socketio.start_background_task(
            telegram_alert_service.send_order_alert,
            "cancelorder",
            {"orderid": orderid},
            order_response_data,
            original_data.get("apikey"),
        )
        return True, order_response_data, 200
    else:
        message = (
            response_message.get("message", "Failed to cancel order")
            if isinstance(response_message, dict)
            else "Failed to cancel order"
        )
        error_response = {"status": "error", "message": message}
        executor.submit(async_log_order, "cancelorder", original_data, error_response)
        return False, error_response, status_code


def cancel_order(
    orderid: str,
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Cancel an order.
    Supports both API-based authentication and direct internal calls.

    Args:
        orderid: Order ID to cancel
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = {"orderid": orderid}
    if api_key:
        original_data["apikey"] = api_key

    # Validate order ID
    if not orderid:
        error_message = "Order ID is missing"
        error_response = {"status": "error", "message": error_message}
        executor.submit(async_log_order, "cancelorder", original_data, error_response)
        return False, error_response, 400

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Check if user is in semi-auto mode (cancelorder is blocked in semi-auto)
        # BUT allow execution in analyze/sandbox mode (virtual trading should always work)
        from database.auth_db import get_order_mode, verify_api_key
        from database.settings_db import get_analyze_mode

        # Check analyze mode first - if in analyze mode, allow execution
        if not get_analyze_mode():
            user_id = verify_api_key(api_key)
            if user_id:
                order_mode = get_order_mode(user_id)
                if order_mode == "semi_auto":
                    error_response = {
                        "status": "error",
                        "message": "Cancel order operation is not allowed in Semi-Auto mode. Please switch to Auto mode to cancel orders.",
                    }
                    logger.warning(f"Cancel order blocked for user {user_id} (semi-auto mode)")
                    executor.submit(async_log_order, "cancelorder", original_data, error_response)
                    return False, error_response, 403

        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {"status": "error", "message": "Invalid openalgo apikey"}
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403

        return cancel_order_with_auth(orderid, AUTH_TOKEN, broker_name, original_data)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return cancel_order_with_auth(orderid, auth_token, broker, original_data)

    # Case 3: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400
