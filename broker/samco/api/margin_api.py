# api/margin_api.py

import json
from database.token_db import get_br_symbol
from broker.samco.mapping.margin_data import (
    transform_margin_position,
    parse_margin_response
)
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Samco API base URL
BASE_URL = "https://tradeapi.samco.in"


def calculate_margin_api(positions, auth, api_key=None):
    """
    Calculate margin requirement for a basket of positions using Samco Span Margin API.

    Samco's spanMargin API supports multiple scrips in a single request and
    automatically calculates spread benefits.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Samco
        api_key: OpenAlgo API key (optional, not used for Samco)

    Returns:
        Tuple of (response, response_data)
    """
    # Get the shared httpx client
    client = get_httpx_client()

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'x-session-token': auth
    }

    # Transform positions to Samco format
    transformed_positions = []
    skipped_count = 0

    for position in positions:
        transformed = transform_margin_position(position)
        if transformed:
            transformed_positions.append(transformed)
        else:
            skipped_count += 1

    if not transformed_positions:
        error_response = {
            'status': 'error',
            'message': 'No valid positions to calculate margin. Check if symbols are valid.'
        }
        class MockResponse:
            status_code = 400
            status = 400
        return MockResponse(), error_response

    # Log the margin calculation request
    logger.info("="*80)
    logger.info("SAMCO SPAN MARGIN CALCULATION")
    logger.info("="*80)
    logger.info(f"Total positions received: {len(positions)}")
    logger.info(f"Valid positions to process: {len(transformed_positions)}")
    if skipped_count > 0:
        logger.warning(f"Skipped positions (invalid/missing symbols): {skipped_count}")
    logger.info("="*80)

    # Prepare payload for Samco spanMargin API
    payload = {
        "request": transformed_positions
    }

    logger.info(f"Samco span margin payload: {json.dumps(payload, indent=2)}")

    try:
        # Make the POST request to spanMargin endpoint
        response = client.post(
            f"{BASE_URL}/spanMargin",
            headers=headers,
            json=payload
        )

        # Add status attribute for compatibility
        response.status = response.status_code

        # Parse the JSON response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response from Samco: {response.text}")
            error_response = {
                'status': 'error',
                'message': 'Invalid response from broker API'
            }
            return response, error_response

        logger.info("="*80)
        logger.info("SAMCO SPAN MARGIN API - RAW RESPONSE")
        logger.info("="*80)
        logger.info(f"Response Status Code: {response.status_code}")
        logger.info(f"Full Response: {json.dumps(response_data, indent=2)}")
        logger.info("="*80)

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        # Log the standardized response
        logger.info("STANDARDIZED OPENALGO RESPONSE")
        logger.info("="*80)
        logger.info(f"Standardized Response: {json.dumps(standardized_response, indent=2)}")

        if standardized_response.get('status') == 'success':
            data = standardized_response.get('data', {})
            logger.info("")
            logger.info(f"Total Margin Required:   Rs. {data.get('total_margin_required', 0):,.2f}")
            logger.info(f"SPAN Margin:             Rs. {data.get('span_margin', 0):,.2f}")
            logger.info(f"Exposure Margin:         Rs. {data.get('exposure_margin', 0):,.2f}")
            logger.info(f"Spread Benefit:          Rs. {data.get('spread_benefit', 0):,.2f}")
        logger.info("="*80)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Samco span margin API: {e}")
        error_response = {
            'status': 'error',
            'message': f'Failed to calculate margin: {str(e)}'
        }
        class MockResponse:
            status_code = 500
            status = 500
        return MockResponse(), error_response
