import json
import os

from broker.fyers.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using Fyers API.

    Fyers multiorder margin API endpoint:
    POST https://api-t1.fyers.in/api/v3/multiorder/margin

    This API calculates the total margin required for a basket of positions.
    Unlike Angel/Zerodha, Fyers does not provide detailed margin breakdown
    (SPAN/Exposure) and only returns total margin values.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Fyers

    Returns:
        Tuple of (response, response_data)
    """
    AUTH_TOKEN = auth
    BROKER_API_KEY = os.getenv("BROKER_API_KEY")

    # Transform positions to Fyers format
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

    # Prepare headers as per Fyers API documentation
    headers = {
        "Authorization": f"{BROKER_API_KEY}:{AUTH_TOKEN}",
        "Content-Type": "application/json",
    }

    # Prepare payload with the data array
    payload = {"data": transformed_positions}

    logger.debug(f"Fyers margin calculation payload: {json.dumps(payload, indent=2)}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Make the request using the v3 multiorder margin endpoint
        response = client.post(
            "https://api-t1.fyers.in/api/v3/multiorder/margin", headers=headers, json=payload
        )

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        # Parse the JSON response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response from Fyers: {response.text}")
            error_response = {"status": "error", "message": "Invalid response from broker API"}
            return response, error_response

        # Log the complete raw response from Fyers
        logger.info("=" * 80)
        logger.info("FYERS MARGIN API - RAW RESPONSE")
        logger.info("=" * 80)
        logger.info(f"Response Status Code: {response.status_code}")
        logger.info(f"Full Response: {json.dumps(response_data, indent=2)}")
        logger.info("=" * 80)

        # Parse and standardize the response to OpenAlgo format
        standardized_response = parse_margin_response(response_data)

        # Log the standardized response
        logger.info("STANDARDIZED OPENALGO RESPONSE")
        logger.info("=" * 80)
        logger.info(f"Standardized Response: {json.dumps(standardized_response, indent=2)}")
        logger.info("=" * 80)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Fyers margin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response
