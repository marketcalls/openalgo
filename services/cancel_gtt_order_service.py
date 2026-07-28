import copy
import importlib
from typing import Any, Dict, Optional, Tuple

from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from events import AnalyzerErrorEvent, GTTCancelFailedEvent, GTTCancelledEvent
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)

API_TYPE = "cancelgttorder"


def emit_analyzer_error(request_data: dict[str, Any], error_message: str) -> dict[str, Any]:
    error_response = {"mode": "analyze", "status": "error", "message": error_message}

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


def import_broker_gtt_module(broker_name: str) -> Any | None:
    try:
        return importlib.import_module(f"broker.{broker_name}.api.gtt_api")
    except ImportError as error:
        logger.error(f"Error importing GTT module for broker '{broker_name}': {error}")
        return None


def cancel_gtt_order_with_auth(
    trigger_id: str,
    auth_token: str,
    broker: str,
    original_data: dict[str, Any],
) -> tuple[bool, dict[str, Any], int]:
    order_request_data = copy.deepcopy(original_data)
    order_request_data.pop("apikey", None)
    api_key = original_data.get("apikey", "")

    if get_analyze_mode():
        error_response = {
            "mode": "analyze",
            "status": "error",
            "message": "Sandbox GTT support not yet implemented",
        }
        return False, error_response, 501

    broker_module = import_broker_gtt_module(broker)
    if broker_module is None:
        message = f"GTT orders are not supported for broker '{broker}' yet"
        error_response = {"status": "error", "message": message}
        bus.publish(GTTCancelFailedEvent(
            mode="live", api_type=API_TYPE,
            trigger_id=trigger_id, error_message=message,
            request_data=order_request_data, response_data=error_response, api_key=api_key,
        ))
        return False, error_response, 501

    try:
        response_message, status_code = broker_module.cancel_gtt_order(trigger_id, auth_token)
    except Exception as e:
        logger.exception(f"Error in broker_module.cancel_gtt_order: {e}")
        error_response = {"status": "error", "message": "Failed to cancel GTT due to internal error"}
        bus.publish(GTTCancelFailedEvent(
            mode="live", api_type=API_TYPE,
            trigger_id=trigger_id, error_message=str(e),
            request_data=order_request_data, response_data=error_response, api_key=api_key,
        ))
        return False, error_response, 500

    if status_code == 200:
        success_response = {
            "status": "success",
            "trigger_id": response_message.get("trigger_id", trigger_id)
            if isinstance(response_message, dict)
            else trigger_id,
        }
        bus.publish(GTTCancelledEvent(
            mode="live", api_type=API_TYPE,
            trigger_id=str(success_response["trigger_id"]),
            status=response_message.get("status", "success") if isinstance(response_message, dict) else "success",
            request_data=order_request_data, response_data=success_response, api_key=api_key,
        ))
        return True, success_response, 200

    message = (
        response_message.get("message", "Failed to cancel GTT")
        if isinstance(response_message, dict)
        else "Failed to cancel GTT"
    )
    error_response = {"status": "error", "message": message}
    bus.publish(GTTCancelFailedEvent(
        mode="live", api_type=API_TYPE,
        trigger_id=trigger_id, error_message=message,
        request_data=order_request_data, response_data=error_response, api_key=api_key,
    ))
    return False, error_response, status_code


def cancel_gtt_order(
    trigger_id: str,
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
    strategy: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    original_data: dict[str, Any] = {"trigger_id": trigger_id}
    if strategy:
        original_data["strategy"] = strategy
    if api_key:
        original_data["apikey"] = api_key

    if not trigger_id:
        error_response = {"status": "error", "message": "trigger_id is missing"}
        bus.publish(GTTCancelFailedEvent(
            mode="live", api_type=API_TYPE,
            trigger_id="", error_message=error_response["message"],
            request_data=original_data, response_data=error_response, api_key=api_key or "",
        ))
        return False, error_response, 400

    # API-based auth
    if api_key and not (auth_token and broker):
        from database.auth_db import get_order_mode, verify_api_key

        if not get_analyze_mode():
            user_id = verify_api_key(api_key)
            if user_id:
                order_mode = get_order_mode(user_id)
                if order_mode == "semi_auto":
                    error_response = {
                        "status": "error",
                        "message": "Cancel GTT order is not allowed in Semi-Auto mode. Switch to Auto mode.",
                    }
                    logger.warning(f"Cancel GTT blocked for user {user_id} (semi-auto mode)")
                    bus.publish(GTTCancelFailedEvent(
                        mode="live", api_type=API_TYPE,
                        trigger_id=trigger_id, error_message=error_response["message"],
                        request_data=original_data, response_data=error_response,
                        api_key=api_key,
                    ))
                    return False, error_response, 403

        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403
        return cancel_gtt_order_with_auth(trigger_id, AUTH_TOKEN, broker_name, original_data)

    # Direct internal call
    if auth_token and broker:
        return cancel_gtt_order_with_auth(trigger_id, auth_token, broker, original_data)

    return (
        False,
        {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        },
        400,
    )
