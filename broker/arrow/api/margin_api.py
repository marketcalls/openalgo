# broker/arrow/api/margin_api.py
#
# Margin calculation, structured like broker/dhan/api/margin_api.py:
#   - one position   -> calculate_single_margin  (POST /margin/order: detailed
#                       per-order charge breakdown)
#   - multi-leg      -> calculate_basket_margin  (POST /margin/basket:
#                       portfolio-level margin benefit -- a short straddle
#                       prices at final_margin ~206k vs ~336k as a per-leg sum)
# If the basket endpoint rejects a request, degrades to the conservative
# per-order sum instead of failing.
#
# Output follows the OpenAlgo standard:
#   {"status": "success", "data": {total_margin_required, span_margin,
#    exposure_margin, total_charges}}
# Contract (margin_service): calculate_margin_api(positions, auth) -> (response, data),
# where `response` exposes .status / .status_code.

import json

from broker.arrow.api.baseurl import ROOT_URL, get_arrow_headers
from broker.arrow.mapping.margin_data import (
    parse_basket_margin_response,
    parse_margin_response,
    transform_margin_positions,
)
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


class BrokerResponse:
    """Small response-compatible object used for local validation failures."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.status = status_code


def _normalise_success_response(response, response_data):
    """Keep services.margin_service status handling aligned with response_data.

    The margin service treats any broker HTTP 200 as success. If Arrow ever
    sends an error payload with HTTP 200, convert it into a non-200
    response-like object so the error is surfaced as an error.
    """
    if (
        getattr(response, "status_code", None) == 200
        and isinstance(response_data, dict)
        and response_data.get("status") == "error"
    ):
        return BrokerResponse(400), response_data
    return response, response_data


def _post_json(url, headers, payload, label):
    """POST and decode JSON with Dhan-style guards.

    Returns (response, data, error_tuple) where error_tuple is None on
    success or a ready-to-return (response_like, error_dict).
    """
    client = get_httpx_client()
    response = client.post(url, headers=headers, json=payload)
    response.status = response.status_code
    try:
        data = response.json()
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON from Arrow {label} margin API: {response.text[:200]}")
        return (
            response,
            None,
            (
                BrokerResponse(502),
                {"status": "error", "message": "Invalid response from broker API"},
            ),
        )
    return response, data, None


def calculate_single_margin(position_data, auth):
    """Calculate margin for a single order via Arrow POST /margin/order.

    Returns:
        Tuple of (response, standardized_response_data)
    """
    headers = get_arrow_headers(auth, with_json=True)
    logger.info(
        "Arrow single margin request: exchange=%s symbol=%s qty=%s product=%s",
        position_data.get("exchange"),
        position_data.get("symbol"),
        position_data.get("quantity"),
        position_data.get("product"),
    )
    try:
        response, payload, err = _post_json(
            f"{ROOT_URL}/margin/order", headers, position_data, "single"
        )
        if err:
            return err

        if payload.get("status") != "success":
            return _normalise_success_response(
                response,
                {
                    "status": "error",
                    "message": payload.get("message", "Failed to calculate margin"),
                },
            )
        return response, parse_margin_response([payload.get("data") or {}])
    except Exception as e:
        logger.exception(f"Error calling Arrow margin API: {e}")
        return BrokerResponse(500), {
            "status": "error",
            "message": f"Failed to calculate margin: {str(e)}",
        }


def calculate_basket_margin(positions_data, auth):
    """Calculate portfolio margin via Arrow POST /margin/basket.

    includePositions=True so existing positions/open orders are netted into
    the requirement (matching the Dhan multi calculator's includePosition).
    Falls back to the per-order sum if the basket endpoint rejects the
    request (e.g. an instrument it does not cover).

    Returns:
        Tuple of (response, standardized_response_data)
    """
    headers = get_arrow_headers(auth, with_json=True)
    logger.info("Arrow basket margin request: positions=%s", len(positions_data))
    try:
        response, payload, err = _post_json(
            f"{ROOT_URL}/margin/basket",
            headers,
            {"orders": positions_data, "includePositions": True},
            "basket",
        )
        if err:
            return err

        if payload.get("status") == "success":
            return response, parse_basket_margin_response(payload.get("data") or {})

        logger.warning(
            f"Arrow basket margin failed ({payload.get('message')}); falling back to per-order sum"
        )
        return _order_margin_sum(positions_data, headers)
    except Exception as e:
        logger.exception(f"Error calling Arrow basket margin API: {e}")
        return BrokerResponse(500), {
            "status": "error",
            "message": f"Failed to calculate basket margin: {str(e)}",
        }


def _order_margin_sum(positions_data, headers):
    """Conservative fallback: sum per-order /margin/order requirements."""
    order_data_list = []
    last_response = None
    for body in positions_data:
        last_response, payload, err = _post_json(
            f"{ROOT_URL}/margin/order", headers, body, "single"
        )
        if err:
            return err
        if payload.get("status") != "success":
            return _normalise_success_response(
                last_response,
                {
                    "status": "error",
                    "message": payload.get("message", "Failed to calculate margin"),
                },
            )
        order_data_list.append(payload.get("data") or {})
    return last_response or BrokerResponse(200), parse_margin_response(order_data_list)


def calculate_margin_api(positions, auth, api_key=None):
    """Calculate margin requirement for positions using Arrow's API.

    One position is sent to Arrow's single-order calculator (detailed charge
    breakdown). Two or more positions are sent to the basket calculator so
    spread/hedge benefits are included by the broker.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Arrow JWT access token
        api_key: OpenAlgo API key (unused; present for interface parity)

    Returns:
        Tuple of (response, response_data)
    """
    transformed_positions = transform_margin_positions(positions)
    if not transformed_positions:
        return BrokerResponse(400), {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

    if len(transformed_positions) == 1:
        logger.info("Arrow margin route: single-order calculator")
        return calculate_single_margin(transformed_positions[0], auth)

    logger.info(
        "Arrow margin route: basket calculator for %s positions",
        len(transformed_positions),
    )
    return calculate_basket_margin(transformed_positions, auth)
