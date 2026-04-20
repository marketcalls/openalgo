import json
import os

from broker.flattrade.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_margin_api(positions, auth):
    """
    Calculate basket margin via Flattrade's GetBasketMargin endpoint.

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

    margin_data = transform_margin_positions(positions, userid, auth_token=AUTH_TOKEN)

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

    try:
        response = client.post(
            "https://piconnect.flattrade.in/PiConnectAPI/GetBasketMargin",
            headers=headers,
            content=payload,
        )

        response.status = response.status_code

        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {response.text}")
            error_response = {"status": "error", "message": "Invalid response from broker API"}
            return response, error_response

        logger.info(f"Flattrade basket margin response: {response_data}")

        standardized_response = parse_margin_response(response_data)
        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Flattrade GetBasketMargin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response
