from broker.groww.api.rate_limiter import groww_request
from broker.groww.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.broker_backpressure import BrokerBusyError
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Groww API constants
GROWW_BASE_URL = "https://api.groww.in"
GROWW_MARGIN_URL = f"{GROWW_BASE_URL}/v1/margins/detail/orders"


class _Status:
    """The HTTP status the margin service reads from a broker response."""

    def __init__(self, status):
        self.status = status
        self.status_code = status


def _request_margin(segment, items, auth):
    """One POST /v1/margins/detail/orders call, parsed into OpenAlgo's format."""
    headers = {
        "Authorization": f"Bearer {auth}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-API-VERSION": "1.0",
    }
    response = groww_request(
        get_httpx_client(),
        "POST",
        GROWW_MARGIN_URL,
        "non_trading",
        headers=headers,
        params={"segment": segment},
        json=items,
        timeout=30,
    )
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, parse_margin_response(body)


def calculate_margin_api(positions, auth):
    """
    Margin required for a basket of positions (07-margin).

    Groww calculates a basket only for FNO; a CASH request carries one order.
    So the FNO positions go as one basket, each CASH position as its own
    request, and the results are added. Cash and F&O margins are not offset
    against each other, so the sum is the margin the basket needs.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Groww

    Returns:
        tuple: (response with .status, OpenAlgo margin response)
    """
    try:
        groups = transform_margin_positions(positions)
    except ValueError as e:
        return _Status(400), {"status": "error", "message": str(e)}
    if not groups:
        return _Status(400), {"status": "error", "message": "No positions to calculate margin for"}

    requests_to_send = []
    if groups.get("FNO"):
        requests_to_send.append(("FNO", groups["FNO"]))
    requests_to_send += [("CASH", [item]) for item in groups.get("CASH", [])]

    totals = {"total_margin_required": 0.0, "span_margin": 0.0, "exposure_margin": 0.0}
    try:
        for segment, items in requests_to_send:
            status, result = _request_margin(segment, items, auth)
            if result.get("status") != "success":
                # A partial total would understate the margin; report the failure
                logger.warning(f"Groww margin refused for {segment}: {result.get('message')}")
                return _Status(status if status >= 400 else 400), result
            for key in totals:
                totals[key] += result["data"][key]
    except BrokerBusyError:
        raise  # the margin service answers this one itself
    except Exception:
        logger.exception("Error calling Groww margin API")
        return _Status(500), {
            "status": "error",
            "message": "Could not reach Groww to calculate the margin. Try again shortly.",
        }

    return _Status(200), {"status": "success", "data": totals}
