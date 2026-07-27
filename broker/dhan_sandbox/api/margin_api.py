import json
import os

from broker.dhan_sandbox.api.baseurl import get_url
from broker.dhan_sandbox.mapping.margin_data import (
    parse_batch_margin_response,
    parse_margin_response,
    parse_multi_margin_response,
    transform_margin_position,
)
from database.auth_db import get_user_id, verify_api_key
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_client_id(api_key=None):
    """
    Get Dhan Sandbox client ID from BROKER_API_KEY or database.

    Args:
        api_key: OpenAlgo API key (optional)

    Returns:
        Client ID string or None
    """
    broker_api_key = os.getenv("BROKER_API_KEY")

    # Extract client_id from BROKER_API_KEY if format is client_id:::api_key
    client_id = None
    if broker_api_key and ":::" in broker_api_key:
        client_id, _ = broker_api_key.split(":::", 1)
        return client_id
    if broker_api_key:
        return broker_api_key

    # If client_id not found in API key, try to fetch from database
    if api_key:
        user_id = verify_api_key(api_key)
        if user_id:
            client_id = get_user_id(user_id)

    return client_id


def calculate_single_margin(position_data, auth, client_id):
    """
    Calculate margin for a single position using Dhan Sandbox API.

    Args:
        position_data: Transformed position data in Dhan Sandbox format
        auth: Authentication token
        client_id: Dhan Sandbox client ID

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

    logger.info(
        "Margin calculation request: exchange=%s qty=%s product=%s",
        position_data.get("exchangeSegment"),
        position_data.get("quantity"),
        position_data.get("productType"),
    )

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Get the URL for margin calculator endpoint
        url = get_url("/v2/margincalculator")

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

        logger.debug(
            "Margin calculation response status=%s keys=%s",
            response.status_code,
            list(response_data.keys()) if isinstance(response_data, dict) else type(response_data).__name__,
        )

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Dhan Sandbox margin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response


def calculate_multi_margin(positions, auth, client_id):
    """
    Calculate margin for multiple positions using Dhan Sandbox /v2/margincalculator/multi API.

    Args:
        positions: List of transformed position data in Dhan Sandbox format
        auth: Authentication token
        client_id: Dhan Sandbox client ID

    Returns:
        Tuple of (response, parsed_response_data)
    """
    AUTH_TOKEN = auth

    headers = {
        "access-token": AUTH_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    if client_id:
        headers["client-id"] = client_id

    # Build multi-margin payload
    payload = {
        "includePosition": True,
        "includeOrders": True,
        "scripts": positions
    }

    payload_json = json.dumps(payload)
    logger.info("Multi-margin request scripts_count=%s", len(positions))

    client = get_httpx_client()

    try:
        url = get_url("/v2/margincalculator/multi")
        response = client.post(url, headers=headers, content=payload_json)
        response.status = response.status_code

        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {response.text}")
            error_response = {"status": "error", "message": "Invalid response from broker API"}
            return response, error_response

        logger.debug(
            "Multi-margin response status=%s keys=%s",
            response.status_code,
            list(response_data.keys()) if isinstance(response_data, dict) else type(response_data).__name__,
        )

        # Use multi-margin parser
        standardized_response = parse_multi_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Dhan Sandbox multi-margin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response


def calculate_margin_api(positions, auth, api_key=None):
    """
    Calculate margin requirement for a basket of positions using Dhan Sandbox API.

    Strategy:
        1. Try /v2/margincalculator/multi first for efficiency
        2. Fall back to looping /v2/margincalculator for each position if multi fails

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Dhan Sandbox
        api_key: OpenAlgo API key (optional, for client ID lookup)

    Returns:
        Tuple of (response, response_data)
    """
    # Get client ID
    client_id = get_client_id(api_key)

    if not client_id:
        logger.error("Could not determine Dhan Sandbox client ID")
        error_response = {
            "status": "error",
            "message": "Could not determine Dhan Sandbox client ID. Please ensure BROKER_API_KEY is configured correctly.",
        }

        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    # Transform all positions
    transformed_positions = []
    for position in positions:
        transformed = transform_margin_position(position, client_id)
        if transformed:
            transformed_positions.append(transformed)

    if not transformed_positions:
        error_response = {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    # Calculate margin for each position
    margin_responses = []
    last_response = None
    multi_used = False
    multi_error = None

    # Try multi-margin endpoint first (more efficient)
    try:
        response, parsed_response = calculate_multi_margin(transformed_positions, auth, client_id)
        last_response = response

        if parsed_response.get("status") == "success":
            multi_used = True
            return last_response, parsed_response
        else:
            multi_error = parsed_response.get("message", "Multi-margin failed")
            logger.warning(f"Multi-margin failed, falling back to single calls: {multi_error}")
    except Exception as e:
        multi_error = str(e)
        logger.warning(f"Multi-margin call failed, falling back to single calls: {multi_error}")

    # Fallback: loop through each position individually
    for position_data in transformed_positions:
        response, parsed_response = calculate_single_margin(position_data, auth, client_id)
        last_response = response
        margin_responses.append(parsed_response)

        if parsed_response.get("status") == "error":
            logger.warning(
                "Margin calculation failed for exchange=%s qty=%s: %s",
                position_data.get("exchangeSegment"),
                position_data.get("quantity"),
                parsed_response.get("message"),
            )

    # Aggregate the responses
    if len(margin_responses) == 1:
        # Single position - return as-is
        final_response = margin_responses[0]
    else:
        # Multiple positions - aggregate
        final_response = parse_batch_margin_response(margin_responses)

    # Add info about fallback
    if multi_used:
        final_response["_multi_margin_used"] = True
    elif multi_error:
        final_response["_fallback_reason"] = multi_error

    # Return the last HTTP response object and the aggregated data
    return last_response, final_response
