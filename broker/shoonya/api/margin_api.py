import json
import os

from broker.shoonya.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using Shoonya Span Calculator API.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token (jKey) for Shoonya

    Returns:
        Tuple of (response, response_data)
    """
    AUTH_TOKEN = auth

    # Get account ID from BROKER_API_KEY
    api_key = os.getenv("BROKER_API_KEY")
    if not api_key:
        error_response = {"status": "error", "message": "BROKER_API_KEY not configured"}

        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response

    # Extract account ID (remove last 2 characters)
    account_id = api_key[:-2]

    # Transform positions to Shoonya format
    margin_data = transform_margin_positions(positions, account_id)

    if not margin_data.get("pos") or len(margin_data["pos"]) == 0:
        error_response = {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    # Prepare headers
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    # Prepare payload in Shoonya format: jData={...}&jKey={token}
    jdata = json.dumps(margin_data)
    payload = f"jData={jdata}&jKey={AUTH_TOKEN}"

    logger.info(f"Shoonya margin calculation payload: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Make the request to Shoonya Span Calculator API
        response = client.post(
            "https://api.shoonya.com/NorenWClientTP/SpanCalc", headers=headers, content=payload
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

        logger.info(f"Shoonya margin response: {response_data}")

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Shoonya margin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response
