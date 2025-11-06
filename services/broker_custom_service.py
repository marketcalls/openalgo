"""
Broker-specific custom API service.

Provides a thin wrapper to dynamically invoke broker modules
that expose a `get_api_response` function.
"""
from __future__ import annotations

import importlib
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

def import_broker_module(broker_name: str) -> Any | None:
    """Dynamically import the broker-specific order API module.

    Args:
        broker_name: Name of the broker (e.g., 'zerodha', 'angel').

    Returns:
        The imported module or None if the import fails.
    """
    module_path = f"broker.{broker_name}.api.api_response"
    try:
        return importlib.import_module(module_path)
    except ImportError as exc:
        logger.error("Error importing broker module '%s': %s", module_path, exc)
        return None

def execute_custom(
    endpoint: str,
    auth_token: str,
    broker_name: str,
    method: str = "POST",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a custom API request through the specified broker module.

    Args:
        endpoint: API endpoint (e.g., "/orders").
        auth_token: Authentication token for the broker API.
        broker_name: Name of the broker.
        method: HTTP method ("GET" or "POST").
        payload: Optional request payload.

    Returns:
        Response data dict. On broker module failure returns
        {'status': 'error', 'message': '<reason>'}.
    """
    broker_module = import_broker_module(broker_name)
    if broker_module is None:
        return {
            "status": "error",
            "message": f"Broker module for {broker_name} not found",
        }
    return broker_module.get_api_response(endpoint, auth_token, method, payload or {})
