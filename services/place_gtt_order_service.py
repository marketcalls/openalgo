import copy
import importlib
from typing import Any, Dict, Optional, Tuple

from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from events import AnalyzerErrorEvent, GTTFailedEvent, GTTPlacedEvent
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)

API_TYPE = "placegttorder"


def emit_analyzer_error(request_data: dict[str, Any], error_message: str) -> dict[str, Any]:
    """Publish an analyzer error event and return the error response dict."""
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
    """Dynamically import the broker-specific GTT API module."""
    try:
        return importlib.import_module(f"broker.{broker_name}.api.gtt_api")
    except ImportError as error:
        logger.error(f"Error importing GTT module for broker '{broker_name}': {error}")
        return None


def place_gtt_order_with_auth(
    order_data: dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: dict[str, Any],
) -> tuple[bool, dict[str, Any], int]:
    """Place a GTT using the provided broker auth token."""
    order_request_data = copy.deepcopy(original_data)
    order_request_data.pop("apikey", None)
    api_key = original_data.get("apikey", "")

    # Analyze (sandbox) mode: not wired yet — clean 501 until Phase 3.
    if get_analyze_mode():
        error_response = {
            "mode": "analyze",
            "status": "error",
            "message": "Sandbox GTT support not yet implemented",
        }
        return False, error_response, 501

    # Capability gate: if the broker does not ship a gtt_api module, 501.
    broker_module = import_broker_gtt_module(broker)
    if broker_module is None:
        message = f"GTT orders are not supported for broker '{broker}' yet"
        error_response = {"status": "error", "message": message}
        bus.publish(GTTFailedEvent(
            mode="live", api_type=API_TYPE,
            symbol=order_data.get("symbol", ""), exchange=order_data.get("exchange", ""),
            trigger_type=order_data.get("trigger_type", ""),
            error_message=message,
            request_data=order_request_data, response_data=error_response, api_key=api_key,
        ))
        return False, error_response, 501

    try:
        res, response_data, trigger_id = broker_module.place_gtt_order(order_data, auth_token)
    except Exception as e:
        logger.exception(f"Error in broker_module.place_gtt_order: {e}")
        error_response = {"status": "error", "message": "Failed to place GTT due to internal error"}
        bus.publish(GTTFailedEvent(
            mode="live", api_type=API_TYPE,
            symbol=order_data.get("symbol", ""), exchange=order_data.get("exchange", ""),
            trigger_type=order_data.get("trigger_type", ""),
            error_message=str(e),
            request_data=order_request_data, response_data=error_response, api_key=api_key,
        ))
        return False, error_response, 500

    if res.status == 200 and trigger_id:
        success_response = {"status": "success", "trigger_id": trigger_id}
        # Derive trigger_prices for the event from the flat fields.
        if (order_data.get("trigger_type") or "").upper() == "OCO":
            event_trigger_prices = [
                float(order_data.get("triggerprice_sl") or 0),
                float(order_data.get("triggerprice_tg") or 0),
            ]
        else:
            event_trigger_prices = [float(order_data.get("trigger_price") or 0)]
        bus.publish(GTTPlacedEvent(
            mode="live", api_type=API_TYPE,
            strategy=order_data.get("strategy", ""),
            symbol=order_data.get("symbol", ""), exchange=order_data.get("exchange", ""),
            trigger_type=order_data.get("trigger_type", ""),
            trigger_id=trigger_id,
            trigger_prices=event_trigger_prices,
            request_data=order_request_data, response_data=success_response, api_key=api_key,
        ))
        return True, success_response, 200

    message = (
        response_data.get("message", "Failed to place GTT")
        if isinstance(response_data, dict)
        else "Failed to place GTT"
    )
    error_response = {"status": "error", "message": message}
    bus.publish(GTTFailedEvent(
        mode="live", api_type=API_TYPE,
        symbol=order_data.get("symbol", ""), exchange=order_data.get("exchange", ""),
        trigger_type=order_data.get("trigger_type", ""),
        error_message=message,
        request_data=order_request_data, response_data=error_response, api_key=api_key,
    ))
    return False, error_response, res.status if res.status != 200 else 500


def place_gtt_order(
    order_data: dict[str, Any],
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """Place a GTT trigger.

    Supports API-key-based auth (external callers) and direct auth_token+broker
    (internal callers, matches place_order_service pattern).
    """
    original_data = copy.deepcopy(order_data)
    if api_key:
        original_data["apikey"] = api_key
        order_data["apikey"] = api_key

    # Semi-auto / Action Center routing (place-side is queueable per Phase 0.3).
    if api_key and not (auth_token and broker):
        from services.order_router_service import queue_order, should_route_to_pending

        if should_route_to_pending(api_key, API_TYPE):
            return queue_order(api_key, original_data, API_TYPE)

    # API-based auth
    if api_key and not (auth_token and broker):
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403
        return place_gtt_order_with_auth(order_data, AUTH_TOKEN, broker_name, original_data)

    # Direct internal call
    if auth_token and broker:
        return place_gtt_order_with_auth(order_data, auth_token, broker, original_data)

    return (
        False,
        {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        },
        400,
    )
