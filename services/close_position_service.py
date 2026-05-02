import copy
import importlib
import traceback
import time
from typing import Any, Dict, Optional, Tuple

from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from database.qty_freeze_db import get_freeze_qty
from database.token_db import get_symbol
from events import AnalyzerErrorEvent, PositionClosedEvent
from utils.event_bus import bus
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

API_TYPE = "closeposition"


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


def close_position_with_auth(
    position_data: dict[str, Any], auth_token: str, broker: str, original_data: dict[str, Any]
) -> tuple[bool, dict[str, Any], int]:
    """
    Close all positions using provided auth token.

    Args:
        position_data: Position data
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    position_request_data = copy.deepcopy(original_data)
    if "apikey" in position_request_data:
        position_request_data.pop("apikey", None)

    # If in analyze mode, route to sandbox for real position closing
    if get_analyze_mode():
        from services.sandbox_service import sandbox_close_position

        api_key = original_data.get("apikey")
        if not api_key:
            return (
                False,
                {
                    "status": "error",
                    "message": "API key required for sandbox mode",
                    "mode": "analyze",
                },
                400,
            )

        # Convert position_data format if needed
        close_data = {
            "symbol": position_data.get("symbol"),
            "exchange": position_data.get("exchange"),
            "product": position_data.get("product_type") or position_data.get("product"),
        }

        success, response, status_code = sandbox_close_position(close_data, api_key, original_data)

        position_request_data["api_type"] = API_TYPE
        bus.publish(PositionClosedEvent(
            mode="analyze", api_type=API_TYPE,
            symbol=position_data.get("symbol", ""),
            exchange=position_data.get("exchange", ""),
            product=position_data.get("product_type", "") or position_data.get("product", ""),
            message=response.get("message", ""),
            request_data=position_request_data,
            response_data=response,
            api_key=api_key,
        ))

        return success, response, status_code

    broker_module = import_broker_module(broker)
    if broker_module is None:
        error_response = {"status": "error", "message": "Broker-specific module not found"}
        bus.publish(PositionClosedEvent(
            mode="live", api_type=API_TYPE,
            symbol=position_data.get("symbol", ""), exchange=position_data.get("exchange", ""),
            product=position_data.get("product_type", "") or position_data.get("product", ""),
            orderid="", message="Broker-specific module not found",
            request_data=position_request_data, response_data=error_response,
            api_key=original_data.get("apikey", ""),
        ))
        return False, error_response, 404

    try:
        # Fetch current open positions from the broker module
        positions_response = broker_module.get_positions(auth_token)
        
        if not positions_response or not positions_response.get("data"):
            response_data = {"status": "success", "message": "No Open Positions Found"}
            return True, response_data, 200

        # Track symbols that fail to close (Violation 3 Fix)
        failed_symbols = []

        # Loop through each position to close with Freeze Quantity Splitting
        for position in positions_response["data"]:
            # Handle different field names for quantity across brokers
            try:
                # Wrap quantity conversion for schema safety (Violation 1 Fix)
                raw_qty = position.get("netqty") or position.get("quantity") or 0
                net_qty = int(raw_qty)
            except (ValueError, TypeError):
                # If quantity is invalid, we MUST count this as a failure (Cubic Violation Update)
                token_err = position.get("symboltoken") or position.get("token") or "Unknown"
                logger.warning(f"Skipping position with invalid quantity: {raw_qty} | token={token_err}")
                failed_symbols.append(token_err)
                continue
            
            if net_qty == 0:
                continue

            # Determine action based on net quantity
            action = "SELL" if net_qty > 0 else "BUY"
            total_quantity = abs(net_qty)
            
            # Map broker token to OpenAlgo symbol to fetch freeze limit
            token = position.get("symboltoken") or position.get("token") or position.get("instrument_token")
            symbol = get_symbol(token, position["exchange"])
            
            # Retrieve the freeze quantity limit from the database
            freeze_limit = get_freeze_qty(symbol, position["exchange"])
            
            # If no limit is found, default to the full quantity
            if not freeze_limit or freeze_limit <= 0:
                freeze_limit = total_quantity

            # Split into multiple orders if total_quantity exceeds freeze_limit
            remaining_qty = total_quantity
            while remaining_qty > 0:
                current_order_qty = min(remaining_qty, freeze_limit)
                
                # Prepare the order payload for the broker's place_order_api
                split_payload = {
                    "apikey": position_data.get("apikey", ""),
                    "strategy": "Squareoff_Split",
                    "symbol": symbol,
                    "action": action,
                    "exchange": position["exchange"],
                    "pricetype": "MARKET",
                    "product": broker_module.reverse_map_product_type(position["producttype"]),
                    "quantity": str(current_order_qty),
                }

                logger.info(f"Splitting Close Position: {symbol} | Qty: {current_order_qty}")
                
                # Place the order using the broker module's placement function
                res, response, orderid = broker_module.place_order_api(split_payload, auth_token)
                
                if not orderid:
                    logger.error(f"Failed to place split order for {symbol}: {response}")
                    failed_symbols.append(symbol)
                    break # Stop further splits for this symbol on failure

                remaining_qty -= current_order_qty
                
                # Small sleep to prevent rate limiting rejections (429) from brokers
                if remaining_qty > 0:
                    time.sleep(0.2)

        # Handle overall response (Violation 2 Fix)
        if failed_symbols:
            status_msg = f"Completed with errors. Failed to close: {', '.join(failed_symbols)}"
            response_data = {"status": "partial_error", "message": status_msg}
            success_status = False
            status_code = 207  # Multi-Status
        else:
            response_data = {"status": "success", "message": "All Open Positions Squared Off"}
            success_status = True
            status_code = 200

        # Publish result to event bus
        bus.publish(PositionClosedEvent(
            mode="live", api_type=API_TYPE,
            symbol="ALL", exchange="ALL", product="ALL",
            orderid="", message=response_data["message"],
            request_data=position_request_data, response_data=response_data,
            api_key=original_data.get("apikey", ""),
        ))
        
        return success_status, response_data, status_code

    except Exception as e:
        logger.error(f"Error in centralized close_all_positions logic: {e}")
        traceback.print_exc()
        error_response = {
            "status": "error",
            "message": f"Failed to close positions due to internal error: {str(e)}",
        }
        bus.publish(PositionClosedEvent(
            mode="live", api_type=API_TYPE,
            symbol=position_data.get("symbol", ""), exchange=position_data.get("exchange", ""),
            product=position_data.get("product_type", "") or position_data.get("product", ""),
            orderid="", message=error_response["message"],
            request_data=position_request_data, response_data=error_response,
            api_key=original_data.get("apikey", ""),
        ))
        return False, error_response, 500


def close_position(
    position_data: dict[str, Any] = None,
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Close all open positions.
    Supports both API-based authentication and direct internal calls.
    """
    if position_data is None:
        position_data = {}

    original_data = copy.deepcopy(position_data)
    if api_key:
        original_data["apikey"] = api_key

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        from database.auth_db import get_order_mode, verify_api_key

        if not get_analyze_mode():
            user_id = verify_api_key(api_key)
            if user_id:
                order_mode = get_order_mode(user_id)
                if order_mode == "semi_auto":
                    error_response = {
                        "status": "error",
                        "message": "Close position operation is not allowed in Semi-Auto mode. Please switch to Auto mode to close positions.",
                    }
                    logger.warning(f"Close position blocked for user {user_id} (semi-auto mode)")
                    position_request_data = copy.deepcopy(original_data)
                    if "apikey" in position_request_data:
                        position_request_data.pop("apikey", None)
                    bus.publish(PositionClosedEvent(
                        mode="live", api_type=API_TYPE,
                        symbol=position_data.get("symbol", ""), exchange=position_data.get("exchange", ""),
                        product=position_data.get("product_type", "") or position_data.get("product", ""),
                        orderid="", message=error_response["message"],
                        request_data=position_request_data, response_data=error_response,
                        api_key=api_key,
                    ))
                    return False, error_response, 403

        position_data["apikey"] = api_key

        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403

        return close_position_with_auth(position_data, AUTH_TOKEN, broker_name, original_data)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return close_position_with_auth(position_data, auth_token, broker, original_data)

    # Case 3: Invalid parameters
    else:
        return False, {"status": "error", "message": "Invalid parameters"}, 400