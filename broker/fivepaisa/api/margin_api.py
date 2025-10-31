import json
import os
from broker.fivepaisa.mapping.margin_data import parse_margin_response
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Base URL for 5Paisa API
BASE_URL = "https://Openapi.5paisa.com"

def calculate_margin_api(positions, auth):
    """
    Retrieve margin information from 5paisa account.

    Note: 5paisa does not have a margin calculator API for specific positions.
    This function returns account-level margin information instead.
    The positions parameter is accepted for API consistency but not used.

    Args:
        positions: List of positions in OpenAlgo format (not used by 5paisa)
        auth: Authentication token for 5paisa

    Returns:
        Tuple of (response, response_data)
    """
    AUTH_TOKEN = auth

    # Get API credentials from environment
    broker_api_key = os.getenv('BROKER_API_KEY')
    if not broker_api_key:
        error_response = {
            'status': 'error',
            'message': '5paisa API key not configured'
        }
        class MockResponse:
            status_code = 500
            status = 500
        return MockResponse(), error_response

    try:
        # Parse the broker API key format: api_key:::user_id:::client_id
        api_key, user_id, client_id = broker_api_key.split(':::')
    except ValueError:
        error_response = {
            'status': 'error',
            'message': '5paisa BROKER_API_KEY format invalid. Expected: api_key:::user_id:::client_id'
        }
        class MockResponse:
            status_code = 500
            status = 500
        return MockResponse(), error_response

    # Prepare headers
    headers = {
        'Authorization': f'bearer {AUTH_TOKEN}',
        'Content-Type': 'application/json'
    }

    # Prepare payload in 5paisa format
    payload = {
        "head": {
            "key": api_key
        },
        "body": {
            "ClientCode": client_id
        }
    }

    logger.info(f"5paisa margin request for client: {client_id}")
    logger.info(f"Note: 5paisa returns account-level margin, not position-specific calculations")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Make the request to 5paisa Margin API
        response = client.post(
            f"{BASE_URL}/VendorsAPI/Service1.svc/V4/Margin",
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

        logger.info(f"5paisa margin response: {response_data}")

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling 5paisa margin API: {e}")
        error_response = {
            'status': 'error',
            'message': f'Failed to retrieve margin: {str(e)}'
        }
        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500
        return MockResponse(), error_response
