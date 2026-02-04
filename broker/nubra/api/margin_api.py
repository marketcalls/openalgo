import json
import os

from broker.nubra.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

NUBRA_BASE_URL = "https://api.nubra.io"

def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using Nubra API.

    API: POST /orders/v2/margin_required

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token (session_token) for Nubra

    Returns:
        Tuple of (response, response_data)
    """
    AUTH_TOKEN = auth
    device_id = "OPENALGO"

    # Transform positions to Nubra format (this returns the full payload)
    payload_data = transform_margin_positions(positions)

    if not payload_data:
        error_response = {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

        # Create a mock response object
        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    # Prepare headers
    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-device-id": device_id,
    }

    # Prepare JSON payload
    payload = json.dumps(payload_data)

    logger.info(f"Nubra margin calculation payload: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Make the request using the shared client
        response = client.post(
            f"{NUBRA_BASE_URL}/orders/v2/margin_required",
            headers=headers,
            content=payload,
        )

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code
        
        # Log raw response for debugging
        logger.debug(f"Nubra margin raw response: {response.text}")

        # Parse the JSON response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {response.text}")
            error_response = {"status": "error", "message": "Invalid response from broker API"}
            return response, error_response

        logger.info(f"Nubra margin calculation response: {response_data}")

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Nubra margin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response
