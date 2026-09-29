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


def _active_first(response: dict[str, Any]) -> dict[str, Any]:
    """Put triggers that can still fire ahead of history.

    A stable sort, so each group keeps the newest-first order the source gave
    it. Applied to both the sandbox and the broker books so the tab reads the
    same way in either mode.
    """
    data = response.get("data")
    if isinstance(data, list):
        response["data"] = sorted(
            data, key=lambda gtt: (gtt.get("status") or "").lower() != "active"
        )
    return response


def get_gtt_orderbook_with_auth(
    auth_token: str,
    broker: str,
    original_data: dict[str, Any] | None = None,
    include_history: bool = False,
) -> tuple[bool, dict[str, Any], int]:
    # Analyze (sandbox) mode reads the sandbox GTT book. Gated on original_data
    # because that is where the API key lives, and the sandbox book is per-user.
    if get_analyze_mode() and original_data:
        from services.sandbox_service import sandbox_gtt_orderbook

        success, response, status_code = sandbox_gtt_orderbook(
            original_data.get("apikey", ""),
            status_filter=None if include_history else "active",
        )
        return success, (_active_first(response) if success else response), status_code

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
        response_data, status_code = broker_module.get_gtt_book(
            auth_token, include_history=include_history
        )
    except Exception as e:
        logger.exception(f"Error in broker_module.get_gtt_book: {e}")
        return False, {"status": "error", "message": str(e)}, 500

    if status_code != 200:
        return False, response_data, status_code

    return True, _active_first(response_data), 200


def get_gtt_orderbook(
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
    status: str = "active",
) -> tuple[bool, dict[str, Any], int]:
    # ``status`` is the request field: ``active`` (default) or ``all``.
    include_history = (status or "active").lower() == "all"

    if api_key and not (auth_token and broker):
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403
        return get_gtt_orderbook_with_auth(
            AUTH_TOKEN, broker_name, {"apikey": api_key}, include_history=include_history
        )

    if auth_token and broker:
        return get_gtt_orderbook_with_auth(
            auth_token, broker, None, include_history=include_history
        )

    return (
        False,
        {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        },
        400,
    )
