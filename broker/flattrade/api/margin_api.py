import json
import os

from broker.flattrade.api.funds import fetch_data
from broker.flattrade.api.rate_limit import DATA_LIMITER, clamp_from_response
from broker.flattrade.mapping.margin_data import (
    MarginLegUnresolved,
    MarginPriceUnavailable,
    parse_limits_margin_used,
    parse_margin_response,
    transform_margin_positions,
)
from utils.broker_backpressure import BrokerBusyError
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


class _ErrorStatus:
    """Response stand-in carrying an error status for margin_service."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.status = status_code


def _as_error(response, result):
    """
    Return an error result with a non-200 status.

    margin_service reports any HTTP 200 as a successful calculation, and
    Flattrade answers a rejected basket with HTTP 200 and stat Not_Ok, so an
    error result must not ride on the broker's 200.
    """
    status = getattr(response, "status_code", 500)
    return (response if status != 200 else _ErrorStatus(500)), result


def calculate_margin_api(positions, auth):
    """
    Calculate basket margin via Flattrade's GetBasketMargin endpoint.

    The result is the basket's own post-trade margin (hedge benefit applied),
    excluding margin already in use: marginusedtrade - Limits.marginused.

    Applies MPP (Market Price Protection): MARKET/SL-M are converted to
    LMT/SL-LMT with a protected price — Flattrade's basket margin accepts
    only LMT/SL-LMT and requires a non-zero price. See
    broker/flattrade/mapping/transform_data.py for the equivalent order
    placement conversion.
    """
    AUTH_TOKEN = auth

    full_api_key = os.getenv("BROKER_API_KEY")
    if not full_api_key or ":::" not in full_api_key:
        error_response = {
            "status": "error",
            "message": "BROKER_API_KEY not configured or invalid format",
        }

        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response

    userid = full_api_key.split(":::")[0]

    try:
        margin_data = transform_margin_positions(positions, userid, auth_token=AUTH_TOKEN)
    except (MarginLegUnresolved, MarginPriceUnavailable) as e:
        error_response = {"status": "error", "message": str(e)}

        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    if "tsym" not in margin_data:
        error_response = {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    jdata = json.dumps(margin_data)
    payload = f"jData={jdata}&jKey={AUTH_TOKEN}"

    safe_payload = {k: v for k, v in margin_data.items() if k not in ("uid", "actid")}
    logger.info(f"Flattrade basket margin payload: {safe_payload}")

    client = get_httpx_client()

    # GetBasketMargin is a non-order endpoint but is called per basket preview,
    # so it shares the data window with the rest of the Flattrade client.
    DATA_LIMITER.acquire()

    try:
        response = client.post(
            "https://piconnect.flattrade.in/PiConnectAPI/GetBasketMargin",
            headers=headers,
            content=payload,
        )

        response.status = response.status_code

        try:
            response_data = response.json()
            # Learn a lower ceiling from the rejection. Not retried: a basket
            # margin preview is user-initiated, so a stale retry is worse than
            # surfacing the error.
            clamp_from_response(response_data, DATA_LIMITER)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {response.text}")
            return _as_error(
                response, {"status": "error", "message": "Invalid response from broker API"}
            )

        logger.info(f"Flattrade basket margin response: {response_data}")

        if response_data.get("stat") != "Ok":
            return _as_error(response, parse_margin_response(response_data))

        # GetBasketMargin's figures include margin already blocked on the
        # account; Limits.marginused is that amount (issue #2156).
        limits_payload = f"jData={json.dumps({'uid': userid, 'actid': userid})}&jKey={AUTH_TOKEN}"
        limits_data = fetch_data("/PiConnectAPI/Limits", limits_payload, headers, client)
        existing_margin_used = parse_limits_margin_used(limits_data)
        if existing_margin_used is None:
            reason = (limits_data or {}).get("emsg") if isinstance(limits_data, dict) else None
            logger.error(f"Flattrade Limits failed during basket margin: {limits_data}")
            return _ErrorStatus(500), {
                "status": "error",
                "message": f"Could not read margin already in use: {reason or 'Limits request failed'}",
            }
        logger.info(f"Flattrade margin already in use (Limits.marginused): {existing_margin_used}")

        standardized_response = parse_margin_response(response_data, existing_margin_used)
        if standardized_response.get("status") != "success":
            return _as_error(response, standardized_response)
        return response, standardized_response

    except BrokerBusyError:
        # margin_service answers this with its busy result; the generic
        # handler below would turn it into a plain failure.
        raise
    except Exception as e:
        logger.error(f"Error calling Flattrade GetBasketMargin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response
