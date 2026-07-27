import json
import os

from broker.indmoney.api.baseurl import get_url
from broker.indmoney.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using IndMoney API.

    Note: IndMoney API calculates margin for single orders only.
    This function processes each position separately and aggregates the results.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for IndMoney

    Returns:
        Tuple of (response, response_data)
    """
    AUTH_TOKEN = auth

    # Transform positions to IndMoney format
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

    # Prepare headers
    headers = {
        "Authorization": AUTH_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # IndMoney API processes single orders, so we need to calculate margin for each position
    # and aggregate the results
    aggregated_margin = {"total_margin_required": 0, "span_margin": 0, "exposure_margin": 0}

    failed_positions = []
    successful_count = 0

    # Process each position separately
    for position in transformed_positions:
        try:
            # Prepare payload for single position
            payload = json.dumps(position)

            logger.info(f"Margin calculation payload for {position.get('securityID')}: {payload}")

            # Make the GET request with JSON body (as per IndMoney API spec)
            response = client.request(
                method="GET", url=get_url("/margin"), headers=headers, content=payload
            )

            # Add status attribute for compatibility
            response.status = response.status_code

            # Parse the JSON response
            try:
                response_data = response.json()
            except json.JSONDecodeError:
                logger.error(
                    f"Failed to parse JSON response for {position.get('securityID')}: {response.text}"
                )
                failed_positions.append(position.get("securityID"))
                continue

            logger.info(
                f"Margin calculation response for {position.get('securityID')}: {response_data}"
            )

            # Parse and standardize the response
            standardized_response = parse_margin_response(response_data)

            # If successful, aggregate the margin data
            if standardized_response.get("status") == "success":
                data = standardized_response.get("data", {})

                # Aggregate only the three essential margin components
                aggregated_margin["total_margin_required"] += data.get("total_margin_required", 0)
                aggregated_margin["span_margin"] += data.get("span_margin", 0)
                aggregated_margin["exposure_margin"] += data.get("exposure_margin", 0)

                successful_count += 1
            else:
                failed_positions.append(position.get("securityID"))
                logger.warning(
                    f"Failed to calculate margin for {position.get('securityID')}: {standardized_response.get('message')}"
                )

        except Exception as e:
            logger.error(f"Error calculating margin for position {position.get('securityID')}: {e}")
            failed_positions.append(position.get("securityID"))
            continue

    # Prepare final response
    if successful_count == 0:
        error_response = {
            "status": "error",
            "message": f"Failed to calculate margin for all positions. Failed: {', '.join(failed_positions)}",
        }

        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response

    # Create success response matching OpenAlgo standard format
    final_response = {"status": "success", "data": aggregated_margin}

    # Create a mock response object for successful aggregation
    class MockResponse:
        status_code = 200
        status = 200

    logger.info(
        f"Aggregated margin calculation completed. Success: {successful_count}/{len(transformed_positions)}"
    )

    return MockResponse(), final_response
