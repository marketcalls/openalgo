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


def _is_error_envelope(response_data: Any) -> bool:
    """Whether the plugin's response is a broker refusal, in any of the shapes plugins use."""
    if not isinstance(response_data, dict):
        return False
    return (
        response_data.get("status") in ("error", "failed")
        or response_data.get("s") == "error"
        or response_data.get("stat") == "Not_Ok"
    )


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
    # An error envelope wins over an order id: Fyers returns the id of an order
    # its risk checks rejected, inside {"s": "error"}.
    refused = res is None or status != 200 or _is_error_envelope(response_data)

    if not refused and order_id:
        return True, None, 200

    if unanswered:
        return False, UNANSWERED_ORDER_MESSAGE, 502

    if refused:
        message = DEFAULT_FAILURE_MESSAGE
        if isinstance(response_data, dict):
            message = (
                response_data.get("message") or response_data.get("emsg") or DEFAULT_FAILURE_MESSAGE
            )
        if isinstance(status, int) and status != 200:
            return False, message, status
        return False, message, 500

    # The broker answered 200 without an error, but there is no order id. It may
    # still be a real order, so the message sends the trader to the order book
    # instead of saying it was refused.
    return False, NO_ORDER_ID_MESSAGE, 502
