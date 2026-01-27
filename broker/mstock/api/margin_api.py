import json
import os

from broker.mstock.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using mStock Type B API.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for mStock

    Returns:
        Tuple of (response, response_data)
    """
    AUTH_TOKEN = auth
    API_KEY = os.getenv("BROKER_API_SECRET")

    # Transform positions to mStock Type B format
    transformed_positions = transform_margin_positions(positions)

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

    # Prepare headers for mStock Type B API
    headers = {
        "X-Mirae-Version": "1",
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "X-PrivateKey": API_KEY,
        "Content-Type": "application/json",
    }

    # Prepare payload with "orders" key as per mStock Type B API
    payload = json.dumps({"orders": transformed_positions})

    logger.debug(f"Margin calculation payload: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Make the request using the shared client
        response = client.post(
            "https://api.mstock.trade/openapi/typeb/margins/orders",
            headers=headers,
            content=payload,
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

        logger.debug(f"Margin calculation response: {response_data}")

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling mStock margin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response
