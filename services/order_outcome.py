"""Decide whether a broker plugin's place_order_api answer is a placed order.

Broker plugins return ``(res, response_data, order_id)``. A plugin may answer
with ``res.status == 200`` for a refusal (the broker's error envelope arrived
over HTTP 200), or with ``res`` set to ``None`` when the request failed. Only an
answer with a 200 status and an order id is a placed order.
"""

from typing import Any

from utils.httpx_client import UNANSWERED_ORDER_MESSAGE

NO_ORDER_ID_MESSAGE = (
    "The broker accepted the order but did not return an order id. "
    "Check the order book before placing it again."
)

DEFAULT_FAILURE_MESSAGE = "Failed to place order"


def place_order_outcome(
    res: Any, response_data: Any, order_id: Any, unanswered: bool = False
) -> tuple[bool, str | None, int]:
    """Classify a place_order_api answer.

    Args:
        res: The plugin's response object (``.status``), or ``None``.
        response_data: The plugin's response dict.
        order_id: The order id the plugin returned.
        unanswered: Whether the connection dropped after the order was sent.

    Returns:
        ``(placed, message, status_code)``. ``message`` is ``None`` when placed.
    """
    status = getattr(res, "status", None)

    if status == 200 and order_id:
        return True, None, 200

    if unanswered:
        return False, UNANSWERED_ORDER_MESSAGE, 502

    refused = (
        res is None
        or status != 200
        or (isinstance(response_data, dict) and response_data.get("status") == "error")
    )
    if refused:
        message = DEFAULT_FAILURE_MESSAGE
        if isinstance(response_data, dict):
            message = response_data.get("message") or DEFAULT_FAILURE_MESSAGE
        if isinstance(status, int) and status != 200:
            return False, message, status
        return False, message, 500

    # The broker answered 200 without an error, but there is no order id.
    # It may still be a real order, so do not tell the trader it failed.
    return False, NO_ORDER_ID_MESSAGE, 502
