import json
import os
from broker.firstock.mapping.margin_data import (
    transform_margin_position,
    parse_margin_response,
    parse_batch_margin_response
)
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def get_user_id():
    """
    Get Firstock user ID from BROKER_API_KEY.

    Returns:
        User ID string or None
    """
    api_key = os.getenv('BROKER_API_KEY')
    if not api_key:
        logger.error("BROKER_API_KEY not found in environment variables")
        return None

    # Remove last 4 characters to get user_id
    user_id = api_key[:-4]
    return user_id

def calculate_single_margin(position_data, auth, user_id):
    """
    Calculate margin for a single position using Firstock API.

    Args:
        position_data: Transformed position data in Firstock format
        auth: Authentication token (jKey)
        user_id: Firstock user ID

    Returns:
        Tuple of (response, parsed_response_data)
    """
    # Add jKey to the position data
    position_data['jKey'] = auth

    # Prepare headers
    headers = {
        'Content-Type': 'application/json'
    }

    logger.info(f"Firstock margin calculation payload: {json.dumps(position_data)}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Make the request to Firstock Order Margin API
        response = client.post(
            "https://api.firstock.in/V1/orderMargin",
            headers=headers,
            json=position_data,
            timeout=30
        )

        # Add status attribute for compatibility
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

        logger.info(f"Firstock margin response: {response_data}")

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Firstock margin API: {e}")
        error_response = {
            'status': 'error',
            'message': f'Failed to calculate margin: {str(e)}'
        }
        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500
        return MockResponse(), error_response

def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using Firstock API.

    Note: Firstock's margin API accepts only one order at a time,
    so we make multiple API calls and aggregate the results.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token (jKey) for Firstock

    Returns:
        Tuple of (response, response_data)
    """
    # Get user ID
    user_id = get_user_id()

    if not user_id:
        error_response = {
            'status': 'error',
            'message': 'Could not determine Firstock user ID. Please ensure BROKER_API_KEY is configured correctly.'
        }
        class MockResponse:
            status_code = 400
            status = 400
        return MockResponse(), error_response

    # Transform all positions
    transformed_positions = []
    for position in positions:
        transformed = transform_margin_position(position, user_id)
        if transformed:
            transformed_positions.append(transformed)

    if not transformed_positions:
        error_response = {
            'status': 'error',
            'message': 'No valid positions to calculate margin. Check if symbols are valid.'
        }
        class MockResponse:
            status_code = 400
            status = 400
        return MockResponse(), error_response

    # Calculate margin for each position
    margin_responses = []
    last_response = None

    for position_data in transformed_positions:
        response, parsed_response = calculate_single_margin(position_data, auth, user_id)
        last_response = response
        margin_responses.append(parsed_response)

        # If any single margin calculation fails, we might want to continue
        # but log the error
        if parsed_response.get('status') == 'error':
            logger.warning(f"Margin calculation failed for position: {position_data}, Error: {parsed_response.get('message')}")

    # Aggregate the responses
    if len(margin_responses) == 1:
        # Single position - return as-is
        final_response = margin_responses[0]
    else:
        # Multiple positions - aggregate
        final_response = parse_batch_margin_response(margin_responses)

    # Return the last HTTP response object and the aggregated data
    return last_response, final_response
