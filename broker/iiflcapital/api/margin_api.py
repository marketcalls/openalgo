from types import SimpleNamespace

from broker.iiflcapital.baseurl import BASE_URL
from broker.iiflcapital.mapping.margin_data import (
    parse_margin_response,
    transform_margin_positions,
)
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def _mock_response(status_code):
    return SimpleNamespace(status=status_code, status_code=status_code)


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using IIFL Capital API.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for IIFL Capital

    Returns:
        Tuple of (response, response_data)
    """
    transformed_positions = transform_margin_positions(positions)

    if not transformed_positions:
        return _mock_response(400), {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

    client = get_httpx_client()
    headers = {
        "Authorization": f"Bearer {auth}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    logger.info(f"IIFL Capital margin calculation payload: {transformed_positions}")

    try:
        response = client.post(
            f"{BASE_URL}/spanexposure",
            headers=headers,
            json=transformed_positions,
        )
        response.status = response.status_code

        try:
            response_data = response.json()
        except Exception:
            logger.error(f"Failed to parse IIFL Capital margin response: {response.text}")
            return response, {"status": "error", "message": "Invalid response from broker API"}

        logger.info(f"IIFL Capital margin calculation response: {response_data}")

        standardized_response = parse_margin_response(response_data)
        return response, standardized_response

    except Exception as error:
        logger.error(f"Error calling IIFL Capital margin API: {error}")
        return _mock_response(500), {
            "status": "error",
            "message": f"Failed to calculate margin: {error}",
        }
