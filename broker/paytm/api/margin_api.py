import json
from broker.paytm.mapping.margin_data import (
    transform_margin_position,
    parse_margin_response,
    parse_batch_margin_response
)
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Paytm API constants
PAYTM_BASE_URL = 'https://developer.paytmmoney.com'
PAYTM_MARGIN_URL = f'{PAYTM_BASE_URL}/margin/v1/scrips/calculator'

def calculate_single_margin(body, auth):
    """
    Calculate margin for a single position using Paytm API.

    According to API docs: POST request to /margin/v1/scrips/calculator
    with JSON body containing: source, exchange, segment, security_id,
    txn_type, quantity, strike_price, trigger_price, instrument

    Args:
        body: Request body dict for Paytm margin API
        auth: Authentication token (JWT token)

    Returns:
        Tuple of (response, parsed_response_data)
    """
    AUTH_TOKEN = auth

    # Prepare headers
    headers = {
        'x-jwt-token': AUTH_TOKEN,
        'Content-Type': 'application/json'
    }

    logger.info(f"Paytm margin calculation body: {body}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Make the POST request with JSON body
        response = client.post(
            PAYTM_MARGIN_URL,
            headers=headers,
            json=body
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

        logger.info(f"Paytm margin calculation response: {response_data}")

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Paytm margin API: {e}")
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
    Calculate margin requirement for a basket of positions using Paytm API.

    According to API docs, the margin calculator accepts POST requests to
    /margin/v1/scrips/calculator. We make one API call per position and
    aggregate the results.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token (JWT token) for Paytm

    Returns:
        Tuple of (response, response_data)
    """
    # Transform all positions to request bodies
    transformed_bodies = []
    for position in positions:
        body = transform_margin_position(position)
        if body:
            transformed_bodies.append(body)

    if not transformed_bodies:
        error_response = {
            'status': 'error',
            'message': 'No valid positions to calculate margin. Check if symbols are valid.'
        }
        class MockResponse:
            status_code = 400
            status = 400
        return MockResponse(), error_response

    logger.info(f"Calculating margin for {len(transformed_bodies)} position(s)")

    # Calculate margin for each position
    margin_responses = []
    last_response = None

    for body in transformed_bodies:
        response, parsed_response = calculate_single_margin(body, auth)
        last_response = response
        margin_responses.append(parsed_response)

        # If any single margin calculation fails, we might want to continue
        # but log the error
        if parsed_response.get('status') == 'error':
            logger.warning(f"Margin calculation failed for body: {body}, Error: {parsed_response.get('message')}")

    # Aggregate the responses
    if len(margin_responses) == 1:
        # Single position - return as-is
        final_response = margin_responses[0]
    else:
        # Multiple positions - aggregate
        final_response = parse_batch_margin_response(margin_responses)

    # Log the final aggregated response
    logger.info(f"Final margin calculation result: {final_response}")

    # Return the last HTTP response object and the aggregated data
    return last_response, final_response
