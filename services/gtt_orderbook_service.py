import importlib
from typing import Any, Dict, List, Optional, Tuple

from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from utils.logging import get_logger

logger = get_logger(__name__)

API_TYPE = "gttorderbook"


def import_broker_gtt_module(broker_name: str) -> Any | None:
    try:
        return importlib.import_module(f"broker.{broker_name}.api.gtt_api")
    except ImportError as error:
        logger.error(f"Error importing GTT module for broker '{broker_name}': {error}")
        return None


def get_gtt_orderbook_with_auth(
    auth_token: str, broker: str, original_data: dict[str, Any] | None = None
) -> tuple[bool, dict[str, Any], int]:
    if get_analyze_mode() and original_data:
        return (
            False,
            {
                "mode": "analyze",
                "status": "error",
                "message": "Sandbox GTT support not yet implemented",
            },
            501,
        )

    broker_module = import_broker_gtt_module(broker)
    if broker_module is None:
        return (
            False,
            {
                "status": "error",
                "message": f"GTT orders are not supported for broker '{broker}' yet",
            },
            501,
        )

    try:
        response_data, status_code = broker_module.get_gtt_book(auth_token)
    except Exception as e:
        logger.exception(f"Error in broker_module.get_gtt_book: {e}")
        return False, {"status": "error", "message": str(e)}, 500

    if status_code != 200:
        return False, response_data, status_code

    return True, response_data, 200


def get_gtt_orderbook(
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    if api_key and not (auth_token and broker):
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403
        return get_gtt_orderbook_with_auth(AUTH_TOKEN, broker_name, {"apikey": api_key})

    if auth_token and broker:
        return get_gtt_orderbook_with_auth(auth_token, broker, None)

    return (
        False,
        {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        },
        400,
    )
