import json
import os

from broker.dhan_sandbox.api.baseurl import get_url
from broker.dhan_sandbox.mapping.margin_data import (
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
    Get Dhan Sandbox client ID from BROKER_API_KEY or database.

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

    logger.info(f"Dhan Sandbox margin calculation payload: {payload}")

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

        logger.info(f"Dhan Sandbox margin calculation response: {response_data}")

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


def calculate_margin_api(positions, auth, api_key=None):
    """
    Calculate margin requirement for a basket of positions using Dhan Sandbox API.

    Note: Dhan Sandbox's margin calculator accepts only one order at a time,
    so we make multiple API calls and aggregate the results.

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

    for position_data in transformed_positions:
        response, parsed_response = calculate_single_margin(position_data, auth, client_id)
        last_response = response
        margin_responses.append(parsed_response)

        # If any single margin calculation fails, we might want to continue
        # but log the error
        if parsed_response.get("status") == "error":
            logger.warning(
                f"Margin calculation failed for position: {position_data}, Error: {parsed_response.get('message')}"
            )

    # Aggregate the responses
    if len(margin_responses) == 1:
        # Single position - return as-is
        final_response = margin_responses[0]
    else:
        # Multiple positions - aggregate
        final_response = parse_batch_margin_response(margin_responses)

    # Return the last HTTP response object and the aggregated data
    return last_response, final_response
