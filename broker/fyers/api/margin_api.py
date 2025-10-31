import json
import os
from broker.fyers.mapping.margin_data import transform_margin_positions, parse_margin_response
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using Fyers API.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Fyers

    Returns:
        Tuple of (response, response_data)
    """
    AUTH_TOKEN = auth
    BROKER_API_KEY = os.getenv('BROKER_API_KEY')

    # Transform positions to Fyers format
    transformed_positions = transform_margin_positions(positions)

    if not transformed_positions:
        error_response = {
            'status': 'error',
            'message': 'No valid positions to calculate margin. Check if symbols are valid.'
        }
        # Create a mock response object
        class MockResponse:
            status_code = 400
            status = 400
        return MockResponse(), error_response

    # Prepare headers
    headers = {
        'Authorization': f'{BROKER_API_KEY}:{AUTH_TOKEN}',
        'Content-Type': 'application/json'
    }

    # Prepare payload with the data array
    payload = {
        "data": transformed_positions
    }

    logger.info(f"Margin calculation payload: {json.dumps(payload)}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Make the request using the v3 multiorder margin endpoint
        response = client.post(
            "https://api-t1.fyers.in/api/v3/multiorder/margin",
            headers=headers,
            json=payload
        )

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        # Parse the JSON response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {response.text}")
            error_response = {
                'status': 'error',
                'message': 'Invalid response from broker API'
            }
            return response, error_response

        logger.info(f"Margin calculation response: {response_data}")

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Fyers margin API: {e}")
        error_response = {
            'status': 'error',
            'message': f'Failed to calculate margin: {str(e)}'
        }
        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500
        return MockResponse(), error_response
