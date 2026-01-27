import json

from broker.definedge.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Definedge API constants
DEFINEDGE_MARGIN_URL = "https://integrate.definedgesecurities.com/dart/v1/spancalculator"


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using Definedge Span Calculator API.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token (format: api_session_key:::susertoken:::api_token)

    Returns:
        Tuple of (response, response_data)
    """
    # Parse the auth token
    try:
        api_session_key, susertoken, api_token = auth.split(":::")
    except ValueError:
        error_response = {
            "status": "error",
            "message": "Invalid auth token format. Expected format: api_session_key:::susertoken:::api_token",
        }

        class MockResponse:
            status_code = 401
            status = 401

        return MockResponse(), error_response

    # Transform positions to Definedge format
    transformed_positions = transform_margin_positions(positions)

    if not transformed_positions:
        error_response = {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response
    logger.info(f"API session key: {api_session_key}")
    # Prepare headers
    headers = {"Authorization": api_session_key, "Content-Type": "application/json"}

    # Prepare payload
    payload = {"positions": transformed_positions}

    logger.info(f"Definedge margin calculation payload: {json.dumps(payload, indent=2)}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Make the request to Definedge Span Calculator API
        response = client.post(DEFINEDGE_MARGIN_URL, headers=headers, json=payload)

        # Add status attribute for compatibility
        response.status = response.status_code

        # Parse the JSON response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {response.text}")
            error_response = {"status": "error", "message": "Invalid response from broker API"}
            return response, error_response

        logger.info(f"Definedge margin calculation response: {json.dumps(response_data, indent=2)}")

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Definedge margin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response
