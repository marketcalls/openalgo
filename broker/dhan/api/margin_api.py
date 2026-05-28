import json
import os

from broker.dhan.api.baseurl import get_url
from broker.dhan.mapping.margin_data import (
    parse_margin_response,
    transform_margin_position,
)
from database.auth_db import get_user_id, verify_api_key
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_client_id(api_key=None):
    """
    Get Dhan client ID from BROKER_API_KEY or database.

    Args:
        api_key: OpenAlgo API key (optional)

    Returns:
        Client ID string or None
    """
    BROKER_API_KEY = os.getenv("BROKER_API_KEY")

    # Extract client_id from BROKER_API_KEY if format is client_id:::api_key
    client_id = None
    if BROKER_API_KEY and ":::" in BROKER_API_KEY:
        client_id, _ = BROKER_API_KEY.split(":::")
        return client_id

    # If client_id not found in API key, try to fetch from database
    if api_key:
        user_id = verify_api_key(api_key)
        if user_id:
            client_id = get_user_id(user_id)

    return client_id


def calculate_single_margin(position_data, auth, client_id):
    """
    Calculate margin for a single position using Dhan API.

    Args:
        position_data: Transformed position data in Dhan format
        auth: Authentication token
        client_id: Dhan client ID

    Returns:
        Tuple of (response, parsed_response_data)
    """
    AUTH_TOKEN = auth

    # Prepare headers
    headers = {
        "access-token": AUTH_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Add client-id header if available
    if client_id:
        headers["client-id"] = client_id

    # Prepare payload
    payload = json.dumps(position_data)

    logger.info(f"Dhan margin calculation payload: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Get the URL for margin calculator endpoint
        url = get_url("/v2/margincalculator")

        logger.info(f"Calling Dhan margin API: {url}")

        # Make the POST request
        response = client.post(url, headers=headers, content=payload)

        # Add status attribute for compatibility
        response.status = response.status_code

        # Parse the JSON response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response from Dhan: {response.text}")
            error_response = {"status": "error", "message": "Invalid response from broker API"}
            return response, error_response

        logger.info("=" * 80)
        logger.info("DHAN MARGIN API - RAW RESPONSE")
        logger.info("=" * 80)
        logger.info(f"Response Status Code: {response.status_code}")
        logger.info(f"Full Response: {json.dumps(response_data, indent=2)}")
        logger.info("=" * 80)

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        # Log the standardized response
        logger.info("STANDARDIZED OPENALGO RESPONSE")
        logger.info("=" * 80)
        logger.info(f"Standardized Response: {json.dumps(standardized_response, indent=2)}")
        logger.info("=" * 80)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Dhan margin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response


def calculate_basket_margin_api(positions_payload, auth, client_id):
    """Call Dhan ``/v2/margincalculator/multi`` for true basket margin.

    Dhan's basket endpoint computes SPAN + exposure with spread / hedge
    benefit for up to 50 positions in a single round-trip. This replaces
    the prior per-leg loop + summation approach which inflated defined-
    risk-spread margin 4-5x by treating each leg as independent.

    Args:
        positions_payload: List of transformed positions in Dhan format.
        auth: Dhan access token.
        client_id: Dhan client ID.

    Returns:
        Tuple of ``(httpx response, standardized response dict)``.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "access-token": auth,
    }
    if client_id:
        headers["client-id"] = client_id

    payload = json.dumps({
        "dhanClientId": client_id,
        "scripList": positions_payload,
    })
    logger.info(f"Dhan BASKET margin payload: {payload}")

    client = get_httpx_client()
    try:
        url = get_url("/v2/margincalculator/multi")
        logger.info(f"Calling Dhan basket margin API: {url}")
        response = client.post(url, headers=headers, content=payload)
        response.status = response.status_code

        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON from Dhan: {response.text}")
            return response, {
                "status": "error",
                "message": "Invalid response from broker API",
            }

        logger.info("=" * 80)
        logger.info("DHAN BASKET MARGIN API - RAW RESPONSE")
        logger.info("=" * 80)
        logger.info(f"Response Status Code: {response.status_code}")
        logger.info(f"Full Response: {json.dumps(response_data, indent=2)}")
        logger.info("=" * 80)

        if response.status_code == 200 and isinstance(response_data, dict):
            # Dhan /v2/margincalculator/multi response key shape has
            # diverged between docs (snake_case) and live API
            # (camelCase observed empirically 2026-05-28). The sandbox
            # parser at broker/dhan_sandbox/mapping/margin_data.py also
            # uses snake_case (per docs). Read snake_case first to match
            # docs + sandbox; fall back to camelCase for live-API
            # responses that haven't migrated. If both are missing the
            # field stays 0.0 (matches prior behavior for malformed
            # responses).
            def _pick(*keys):
                for k in keys:
                    v = response_data.get(k)
                    if v is not None and v != "":
                        try:
                            return float(v)
                        except (TypeError, ValueError):
                            continue
                return 0.0

            standardized = {
                "status": "success",
                "data": {
                    "total_margin_required": _pick("total_margin", "totalMargin"),
                    "span_margin": _pick("span_margin", "spanMargin"),
                    "exposure_margin": _pick(
                        "exposure_margin", "exposureMargin", "exposure",
                    ),
                    "hedge_benefit": _pick("hedge_benefit", "hedgeBenefit"),
                },
            }
        else:
            msg = (
                response_data.get("errorMessage")
                if isinstance(response_data, dict)
                else str(response_data)
            )
            standardized = {
                "status": "error",
                "message": msg or "Basket margin call failed",
            }

        logger.info("STANDARDIZED OPENALGO RESPONSE")
        logger.info("=" * 80)
        logger.info(
            f"Standardized Response: {json.dumps(standardized, indent=2)}"
        )
        logger.info("=" * 80)

        return response, standardized

    except Exception as e:
        logger.exception(f"Error calling Dhan basket margin API: {e}")
        error_response = {
            "status": "error",
            "message": f"Failed to calculate basket margin: {str(e)}",
        }

        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response


def calculate_margin_api(positions, auth, api_key=None):
    """Calculate margin requirement for a basket of positions using Dhan API.

    Uses Dhan's ``/v2/margincalculator/multi`` endpoint which accepts a
    list of positions (up to 50) via ``scripList`` field and returns
    SPAN + exposure + hedge benefit for the basket as a whole. This
    correctly accounts for spread benefits in defined-risk strategies
    (e.g. bull put spread, iron condor, calendar spread).

    Args:
        positions: List of positions in OpenAlgo format.
        auth: Authentication token for Dhan.
        api_key: OpenAlgo API key (optional, for client ID lookup).

    Returns:
        Tuple of ``(response, response_data)``.
    """
    # Get client ID
    client_id = get_client_id(api_key)

    if not client_id:
        logger.error("Could not determine Dhan client ID")
        error_response = {
            "status": "error",
            "message": "Could not determine Dhan client ID. Please ensure BROKER_API_KEY is configured correctly.",
        }

        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    # Transform all positions
    transformed_positions = []
    skipped_count = 0

    for position in positions:
        transformed = transform_margin_position(position, client_id)
        if transformed:
            transformed_positions.append(transformed)
        else:
            skipped_count += 1

    if not transformed_positions:
        error_response = {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    # Log the margin calculation strategy
    logger.info("=" * 80)
    logger.info("DHAN BASKET MARGIN CALCULATION")
    logger.info("=" * 80)
    logger.info(f"Total positions received: {len(positions)}")
    logger.info(f"Valid positions to process: {len(transformed_positions)}")
    if skipped_count > 0:
        logger.warning(f"Skipped positions (invalid/missing symbols): {skipped_count}")
    logger.info("=" * 80)

    # Single round-trip basket call to Dhan /v2/margincalculator/multi.
    # Dhan returns SPAN + exposure + hedge benefit for the basket as a
    # whole (not summed per-leg). For defined-risk spreads this is the
    # correct economic margin; per-leg sum overstated margin 4-5x.
    last_response, final_response = calculate_basket_margin_api(
        transformed_positions, auth, client_id,
    )
    if final_response.get("status") == "success":
        logger.info("Basket margin via /v2/margincalculator/multi (hedge-aware)")
    else:
        logger.warning(
            f"Basket margin failed: {final_response.get('message')}"
        )

    # Log the final aggregated response
    logger.info("=" * 80)
    logger.info("FINAL MARGIN CALCULATION RESULT")
    logger.info("=" * 80)
    logger.info(f"Final Response: {json.dumps(final_response, indent=2)}")
    if final_response.get("status") == "success":
        data = final_response.get("data", {})
        logger.info("")
        logger.info(f"Total Margin Required:   Rs. {data.get('total_margin_required', 0):,.2f}")
        logger.info(f"SPAN Margin:             Rs. {data.get('span_margin', 0):,.2f}")
        logger.info(f"Exposure Margin:         Rs. {data.get('exposure_margin', 0):,.2f}")
        logger.info(f"Hedge Benefit:           Rs. {data.get('hedge_benefit', 0):,.2f}")
    logger.info("=" * 80)

    return last_response, final_response
