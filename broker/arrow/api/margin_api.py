# broker/arrow/api/margin_api.py
#
# Margin calculation via Arrow's POST /margin/order. Arrow's endpoint is
# per-order and has no documented basket endpoint, so for a multi-leg basket we
# query each leg and sum requiredMargin. Output follows the OpenAlgo standard:
#   {"status": "success", "data": {total_margin_required, span_margin, exposure_margin}}
# Contract (margin_service): calculate_margin_api(positions, auth) -> (response, data),
# where `response` exposes .status / .status_code.

from broker.arrow.api.baseurl import ROOT_URL, get_arrow_headers
from broker.arrow.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


class _MockResponse:
    """Lightweight stand-in so callers can read .status / .status_code when no
    real HTTP response is available (validation/exception paths)."""

    def __init__(self, code):
        self.status_code = code
        self.status = code


def calculate_margin_api(positions, auth):
    """Calculate basket margin by summing Arrow's per-order margins."""
    bodies = transform_margin_positions(positions)
    if not bodies:
        return _MockResponse(400), {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

    client = get_httpx_client()
    headers = get_arrow_headers(auth, with_json=True)

    order_data_list = []
    last_response = None
    try:
        for body in bodies:
            # TODO(arrow): switch to the Basket Margin endpoint (URL not yet
            # documented) once available, to get spread-benefit aggregation
            # instead of a naive per-order sum.
            last_response = client.post(f"{ROOT_URL}/margin/order", headers=headers, json=body)
            last_response.status = last_response.status_code
            payload = last_response.json()
            if payload.get("status") == "success":
                order_data_list.append(payload.get("data", {}))
            else:
                return last_response, {
                    "status": "error",
                    "message": payload.get("message", "Failed to calculate margin"),
                }
        return last_response or _MockResponse(200), parse_margin_response(order_data_list)
    except Exception as e:
        logger.error(f"Error calling Arrow margin API: {e}")
        return _MockResponse(500), {
            "status": "error",
            "message": f"Failed to calculate margin: {str(e)}",
        }
