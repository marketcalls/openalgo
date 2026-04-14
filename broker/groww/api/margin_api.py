import json

from broker.groww.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Groww API constants
GROWW_BASE_URL = "https://api.groww.in"
GROWW_MARGIN_URL = f"{GROWW_BASE_URL}/v1/margins/detail/orders"


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using Groww API.

    Note: Groww basket margin is supported only for FNO segment.
    For CASH segment, only single position is supported.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Groww

    Returns:
        Tuple of (response, response_data)
    """
    AUTH_TOKEN = auth

    # Transform positions to Groww format
    segment, transformed_positions = transform_margin_positions(positions)

    if not transformed_positions:
        error_response = {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

        # Create a mock response object
        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    # Groww supports basket orders only for FNO segment
    if segment == "CASH" and len(transformed_positions) > 1:
        logger.warning(
            "Groww supports basket margin calculation only for FNO segment. For CASH, calculating only first position."
        )
        transformed_positions = [transformed_positions[0]]

    # Prepare headers
    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-API-VERSION": "1.0",
    }

    # Prepare query parameters
    params = {"segment": segment}

    logger.debug(f"Groww margin calculation for segment: {segment}")
    logger.debug(f"Margin calculation payload: {json.dumps(transformed_positions)}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Make the request using the Groww margin API
        response = client.post(
            GROWW_MARGIN_URL, headers=headers, params=params, json=transformed_positions
        )

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        # Parse the JSON response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {response.text}")
            error_response = {"status": "error", "message": "Invalid response from broker API"}
            return response, error_response

        logger.info(f"Groww margin calculation response: {response_data}")

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Groww margin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response
