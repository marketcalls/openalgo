import json
import urllib.parse

from broker.kotak.mapping.margin_data import (
    parse_batch_margin_response,
    parse_margin_response,
    transform_margin_position,
)
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_single_margin(position_data, auth_token):
    """
    Calculate margin for a single position using Kotak API.

    Args:
        position_data: Transformed position data in Kotak format
        auth_token: Authentication token (session_token:::session_sid:::base_url:::access_token)

    Returns:
        Tuple of (response, parsed_response_data)
    """
    # Parse auth token
    session_token, session_sid, base_url, access_token = auth_token.split(":::")[:4]

    # Debug logging for baseUrl
    logger.debug(f"MARGIN API - Using baseUrl: {base_url}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Prepare headers
    headers = {
        "accept": "application/json",
        "Sid": session_sid,
        "Auth": session_token,
        "neo-fin-key": "neotradeapi",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # Prepare payload in Kotak format (URL-encoded with jData parameter)
    json_string = json.dumps(position_data)
    payload = f"jData={urllib.parse.quote(json_string)}"

    logger.debug(f"Kotak margin calculation payload: {payload}")

    # Construct full URL
    url = f"{base_url}/quick/user/check-margin"

    try:
        # Make the request
        response = client.post(url, headers=headers, content=payload)

        # Add status attribute for compatibility
        response.status = response.status_code

        # Parse the JSON response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {response.text}")
            error_response = {"status": "error", "message": "Invalid response from broker API"}
            return response, error_response

        logger.debug(f"Kotak margin response: {response_data}")

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Kotak margin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using Kotak API.

    Note: Kotak's margin API accepts only one order at a time,
    so we make multiple API calls and aggregate the results.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Kotak

    Returns:
        Tuple of (response, response_data)
    """
    # Transform all positions. A leg that cannot be resolved fails the
    # basket: pricing the rest without it reported the margin of a different
    # basket as "success" (issue #2156).
    transformed_positions = []
    unresolved = []
    for position in positions:
        transformed = transform_margin_position(position)
        if transformed:
            transformed_positions.append(transformed)
        else:
            unresolved.append(f"{position.get('symbol')} ({position.get('exchange')})")

    if unresolved or not transformed_positions:
        error_response = {
            "status": "error",
            "message": (
                f"Could not prepare these legs for the margin check: {', '.join(unresolved)}. "
                "Check the symbol, exchange and expiry date."
                if unresolved
                else "No valid positions to calculate margin. Check if symbols are valid."
            ),
        }

        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    # Calculate margin for each position
    margin_responses = []
    last_response = None

    for position_data in transformed_positions:
        response, parsed_response = calculate_single_margin(position_data, auth)
        last_response = response
        margin_responses.append(parsed_response)

        # One failed leg fails the basket (parse_batch_margin_response), so
        # stop instead of spending calls on the remaining legs.
        if parsed_response.get("status") == "error":
            logger.warning(
                f"Margin calculation failed for position: {position_data}, Error: {parsed_response.get('message')}"
            )
            break

    # Aggregate the responses
    if len(margin_responses) == 1:
        # Single position - return as-is
        final_response = margin_responses[0]
    else:
        # Multiple positions - aggregate
        final_response = parse_batch_margin_response(margin_responses)

    # margin_service reports any HTTP 200 as a successful calculation, and
    # Kotak answers a rejected order with HTTP 200 and stat Not_Ok, so an
    # error result must not ride on the broker's 200.
    if (
        final_response.get("status") != "success"
        and getattr(last_response, "status_code", 500) == 200
    ):

        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), final_response

    # Return the last HTTP response object and the aggregated data
    return last_response, final_response
