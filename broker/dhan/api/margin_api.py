import json
import os

from broker.dhan.api.baseurl import get_url
from broker.dhan.mapping.margin_data import (
    parse_batch_margin_response,
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


def calculate_margin_api(positions, auth, api_key=None):
    """
    Calculate margin requirement for a basket of positions using Dhan API.

    IMPORTANT: Dhan's margin calculator API accepts only ONE order at a time.
    For multi-leg strategies:
    - We calculate margin for each leg individually
    - Sum up all the individual margins
    - Return the total as combined margin requirement

    NOTE: This is a simple summation approach. It does NOT account for:
    - Spread benefits (hedge/combo margin benefits)
    - Portfolio-level optimizations

    This limitation is due to Dhan API design, not OpenAlgo.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Dhan
        api_key: OpenAlgo API key (optional, for client ID lookup)

    Returns:
        Tuple of (response, response_data)
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
    logger.info("DHAN MULTI-LEG MARGIN CALCULATION")
    logger.info("=" * 80)
    logger.info(f"Total positions received: {len(positions)}")
    logger.info(f"Valid positions to process: {len(transformed_positions)}")
    if skipped_count > 0:
        logger.warning(f"Skipped positions (invalid/missing symbols): {skipped_count}")
    logger.info("")
    logger.warning("⚠ LIMITATION: Dhan API supports only single-leg margin calculation")
    logger.warning("⚠ Strategy: Calculate each leg individually and SUM the margins")
    logger.warning("⚠ Note: Does NOT include spread/hedge benefits (if any)")
    logger.info("=" * 80)

    # Calculate margin for each position
    margin_responses = []
    last_response = None
    success_count = 0
    error_count = 0

    for idx, position_data in enumerate(transformed_positions, 1):
        logger.info(
            f"Calculating margin for leg {idx}/{len(transformed_positions)}: {position_data.get('securityId')}"
        )
        response, parsed_response = calculate_single_margin(position_data, auth, client_id)
        last_response = response
        margin_responses.append(parsed_response)

        # Track success/failure
        if parsed_response.get("status") == "error":
            error_count += 1
            logger.warning(f"Leg {idx} failed: {parsed_response.get('message')}")
        else:
            success_count += 1
            data = parsed_response.get("data", {})
            logger.info(f"Leg {idx} margin: Rs. {data.get('total_margin_required', 0):,.2f}")

    # Log summary of individual calculations
    logger.info("")
    logger.info("INDIVIDUAL LEG CALCULATION SUMMARY")
    logger.info("-" * 80)
    logger.info(f"Successful calculations: {success_count}/{len(transformed_positions)}")
    logger.info(f"Failed calculations: {error_count}/{len(transformed_positions)}")
    logger.info("")

    # Aggregate the responses
    if len(margin_responses) == 1:
        # Single position - return as-is
        final_response = margin_responses[0]
        logger.info("Single leg strategy - returning individual margin")
    else:
        # Multiple positions - aggregate by summing
        final_response = parse_batch_margin_response(margin_responses)
        logger.info(f"Multi-leg strategy - summed {success_count} individual leg margins")

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
    logger.info("=" * 80)

    # Return the last HTTP response object and the aggregated data
    return last_response, final_response
