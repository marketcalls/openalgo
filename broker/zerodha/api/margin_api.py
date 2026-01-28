import json

from broker.zerodha.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using Zerodha Kite Connect API.

    Zerodha supports two margin calculation endpoints:
    - /margins/basket: For multiple positions with spread benefit calculation
    - /margins/orders: For individual order margins

    Basket endpoint considers spread/hedge benefit and returns:
    - initial: Total margins without spread benefit
    - final: Total margins with spread benefit (optimized)
    - orders: Individual order margins

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Zerodha (format: api_key:access_token)

    Returns:
        Tuple of (response, response_data)
    """
    AUTH_TOKEN = auth

    # Transform positions to Zerodha format
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

    # Prepare headers as per Zerodha API documentation
    headers = {
        "X-Kite-Version": "3",
        "Authorization": f"token {AUTH_TOKEN}",
        "Content-Type": "application/json",
    }

    # Prepare payload and endpoint
    # Use basket endpoint for multiple positions to get spread benefit
    # Use orders endpoint for single position
    # Both endpoints expect array of orders directly in the body
    if len(transformed_positions) > 1:
        # Basket endpoint with consider_positions=true to factor in existing positions
        endpoint = "https://api.kite.trade/margins/basket?consider_positions=true"
        payload = transformed_positions
        logger.info(f"Using basket margin endpoint for {len(transformed_positions)} positions")
    else:
        # Orders endpoint for single position
        endpoint = "https://api.kite.trade/margins/orders"
        payload = transformed_positions
        logger.info("Using orders margin endpoint for single position")

    logger.debug(f"Zerodha margin calculation payload: {json.dumps(payload)}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Make the request using the shared client
        response = client.post(endpoint, headers=headers, json=payload)

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        # Parse the JSON response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response from Zerodha: {response.text}")
            error_response = {"status": "error", "message": "Invalid response from broker API"}
            return response, error_response

        # Log the complete raw response from Zerodha
        logger.info("=" * 80)
        logger.info("ZERODHA BASKET MARGIN API - RAW RESPONSE")
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
        logger.error(f"Error calling Zerodha margin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response
