# api/margin_api.py
# RMoney XTS Margin Calculator API
# Reference: XTS Interactive API - Regular Order Margin (POST /orders/margindetails)

import json

from broker.rmoney.baseurl import INTERACTIVE_URL
from broker.rmoney.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using RMoney XTS API.

    The OpenAlgo framework calls this function with a list of positions and
    an auth token.  We transform them into XTS format, POST to the
    /orders/margindetails endpoint, and return a standardised response.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for RMoney XTS

    Returns:
        Tuple of (response, response_data)
    """
    AUTH_TOKEN = auth

    # Transform positions to RMoney XTS format
    portfolio = transform_margin_positions(positions)

    if not portfolio:
        error_response = {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    # Prepare request payload
    margin_request = {
        "portfolio": portfolio,
    }

    headers = {
        "authorization": AUTH_TOKEN,
        "Content-Type": "application/json",
    }

    logger.info(f"RMoney Margin Request: {json.dumps(margin_request, indent=2)}")

    client = get_httpx_client()

    try:
        response = client.post(
            f"{INTERACTIVE_URL}/orders/margindetails",
            headers=headers,
            content=json.dumps(margin_request),
        )

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        logger.info(f"RMoney Margin Response Status: {response.status_code}")
        logger.debug(f"RMoney Margin Response: {response.text}")

        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {response.text}")
            error_response = {"status": "error", "message": "Invalid response from broker API"}
            return response, error_response

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling RMoney margin API: {e}", exc_info=True)
        error_response = {"status": "error", "message": "Failed to calculate margin"}

        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response
