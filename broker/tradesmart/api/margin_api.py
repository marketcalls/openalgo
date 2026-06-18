import json

from broker.tradesmart.api.baseurl import post, resolve_uid
from broker.tradesmart.mapping.margin_data import build_order_margin_payload, parse_order_margin
from utils.logging import get_logger

logger = get_logger(__name__)


class _MockResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.status = status_code


def calculate_margin_api(positions, auth):
    """Calculate required margin for one or more positions.

    TradeSmart v2 only offers a single-order calculator (/GetOrderMargin), so we
    price each leg and sum the per-leg margins. Returns ``(response, data)`` with
    ``data.data = {total_margin_required, span_margin, exposure_margin}``.
    """
    if not positions:
        return _MockResponse(400), {"status": "error", "message": "No positions supplied"}

    total_margin = 0.0
    last_response = None
    priced_any = False
    uid = resolve_uid(auth)

    for position in positions:
        payload = build_order_margin_payload(position, uid=uid)
        if not payload:
            continue

        safe_payload = {k: v for k, v in payload.items() if k not in ("uid", "actid")}
        logger.info(f"TradeSmart order margin payload: {safe_payload}")

        try:
            response = post("/GetOrderMargin", payload, auth)
            last_response = response
            try:
                response_data = response.json()
            except json.JSONDecodeError:
                logger.error(f"GetOrderMargin non-JSON response: {response.text}")
                return _MockResponse(502), {
                    "status": "error",
                    "message": "Invalid response from broker API",
                }

            logger.info(f"TradeSmart order margin response: {response_data}")

            leg_margin = parse_order_margin(response_data)
            if leg_margin is None:
                error_message = response_data.get("emsg") or "Failed to calculate margin"
                return _MockResponse(400), {"status": "error", "message": error_message}

            total_margin += leg_margin
            priced_any = True

        except Exception as e:
            logger.error(f"Error calling GetOrderMargin: {e}")
            return _MockResponse(500), {
                "status": "error",
                "message": f"Failed to calculate margin: {str(e)}",
            }

    if not priced_any:
        return _MockResponse(400), {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

    response_obj = last_response if last_response is not None else _MockResponse(200)
    response_obj.status = getattr(response_obj, "status_code", 200)

    return response_obj, {
        "status": "success",
        "data": {
            "total_margin_required": total_margin,
            "span_margin": 0,
            "exposure_margin": 0,
        },
    }
