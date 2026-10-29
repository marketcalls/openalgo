"""Sahi margin calculator.

One position goes to POST /v1/margins/order; two or more go to
POST /v1/margins/basket so Sahi nets hedged legs against each other and
against open positions (broker-api-docs/sahi-api-docs, Funds). Each leg is the
exact place-order body. Both answer {"required_margin", "available_margin"} in
paise.

A basket takes at most 10 legs. A larger request is sent as consecutive
baskets of 10 and their requirements added, which can overstate the margin of
a hedge split across two baskets; the response says so.

Sahi reports one required figure with no SPAN / exposure split, so
``span_margin`` and ``exposure_margin`` are reported as 0.
"""

from broker.sahi.api.baseurl import get_headers, get_url
from broker.sahi.api.order_api import _error_message
from broker.sahi.api.rate_limiter import sahi_request
from broker.sahi.mapping.transform_data import OrderMappingError, from_paise, transform_data
from utils.broker_backpressure import BrokerBusyError
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

BASKET_LEG_CAP = 10


class BrokerResponse:
    """Response-shaped object; margin_service reads ``status_code``."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.status = status_code


def _leg(position):
    """Place-order body for one OpenAlgo margin position."""
    order = {
        "symbol": position.get("symbol"),
        "exchange": position.get("exchange"),
        "action": position.get("action"),
        "quantity": position.get("quantity"),
        "product": position.get("product"),
        "pricetype": position.get("pricetype", "MARKET"),
        "price": position.get("price", 0),
        "trigger_price": position.get("trigger_price", 0),
    }
    return transform_data(order)


def _post(path, body, auth):
    client = get_httpx_client()
    response = sahi_request(
        client,
        "POST",
        get_url(path),
        "margin",
        headers=get_headers(auth, json_body=True),
        json=body,
        timeout=30,
    )
    try:
        data = response.json()
    except ValueError:
        data = {}
    return response.status_code, data


def calculate_margin_api(positions, auth):
    """Returns (response, response_data) as margin_service expects."""
    try:
        legs = [_leg(p) for p in positions]
    except OrderMappingError as exc:
        return BrokerResponse(400), {"status": "error", "message": str(exc)}
    if not legs:
        return BrokerResponse(400), {
            "status": "error",
            "message": "No positions to calculate margin for.",
        }

    required = 0.0
    available = None
    try:
        if len(legs) == 1:
            batches = [("/v1/margins/order", legs[0])]
        else:
            batches = [
                ("/v1/margins/basket", {"legs": legs[i : i + BASKET_LEG_CAP]})
                for i in range(0, len(legs), BASKET_LEG_CAP)
            ]
        for path, body in batches:
            status, data = _post(path, body, auth)
            if status != 200 or "required_margin" not in data:
                logger.error(f"Sahi margin {path} returned HTTP {status}: {data}")
                if data.get("code") == "UNDER_MAINTENANCE":
                    message = (
                        "Sahi's margin calculator is closed for daily maintenance until 07:00 IST."
                    )
                else:
                    message = _error_message(status, data)
                return BrokerResponse(status if status >= 400 else 502), {
                    "status": "error",
                    "message": message,
                }
            required += from_paise(data.get("required_margin"))
            available = from_paise(data.get("available_margin"))
    except BrokerBusyError:
        raise
    except Exception:
        logger.exception("Sahi margin request failed")
        return BrokerResponse(500), {
            "status": "error",
            "message": "Could not reach Sahi to calculate margin.",
        }

    result = {
        "status": "success",
        "data": {
            "total_margin_required": round(required, 2),
            "span_margin": 0.0,
            "exposure_margin": 0.0,
            "available_margin": available,
        },
    }
    if len(batches) > 1:
        result["message"] = (
            f"Sahi prices at most {BASKET_LEG_CAP} legs together; this basket was priced in "
            f"{len(batches)} parts and added, so hedge benefits across parts are not counted."
        )
    return BrokerResponse(200), result
