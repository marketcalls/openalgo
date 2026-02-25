import json
import os

from broker.dhan_sandbox.api.baseurl import get_url
from broker.dhan_sandbox.api.order_api import get_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def _get_dhan_client_id() -> str | None:
    """Extract Dhan client-id from BROKER_API_KEY env value."""
    broker_api_key = os.getenv("BROKER_API_KEY")
    if not broker_api_key:
        return None
    if ":::" in broker_api_key:
        client_id, _ = broker_api_key.split(":::", 1)
        return client_id.strip() or None
    return broker_api_key.strip() or None


def test_auth_token(auth_token):
    """Test if the auth token is valid by making a simple API call to funds endpoint."""
    client_id = _get_dhan_client_id()

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        "access-token": auth_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    # Add client-id header if available (required by Dhan sandbox)
    if client_id:
        headers["client-id"] = client_id

    try:
        url = get_url("/v2/fundlimit")
        res = client.get(url, headers=headers)
        res.status = res.status_code
        response_data = json.loads(res.text)

        # Check for authentication errors
        if response_data.get("errorType") == "Invalid_Authentication":
            error_msg = response_data.get("errorMessage", "Invalid authentication token")
            return False, error_msg

        # Check for other error types
        if response_data.get("status") == "error":
            error_msg = response_data.get("errors", "Unknown error occurred")
            return False, str(error_msg)

        # If we get here, authentication is valid
        return True, None

    except Exception as e:
        logger.error(f"Error testing auth token: {str(e)}")
        return False, f"Error validating authentication: {str(e)}"


def get_margin_data(auth_token):
    """Fetch margin data from Dhan Sandbox API using the provided auth token."""
    client_id = _get_dhan_client_id()

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        "access-token": auth_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    # Add client-id header if available (required by Dhan sandbox)
    if client_id:
        headers["client-id"] = client_id

    url = get_url("/v2/fundlimit")
    res = client.get(url, headers=headers)
    # Add status attribute for compatibility with existing codebase
    res.status = res.status_code
    margin_data = json.loads(res.text)

    logger.debug(
        "Funds response status=%s keys=%s",
        res.status_code,
        list(margin_data.keys()) if isinstance(margin_data, dict) else type(margin_data).__name__,
    )

    # Check for any API errors (auth errors, service errors, after-hours etc.)
    if margin_data.get("errorType") or margin_data.get("status") in ("error", "failed"):
        error_type = margin_data.get("errorType", "")
        error_msg = margin_data.get("errorMessage") or margin_data.get("errors", "Unknown error")
        logger.error(f"Error fetching margin data: [{error_type}] {error_msg}")
        return {
            "availablecash": "0.00",
            "collateral": "0.00",
            "m2munrealized": "0.00",
            "m2mrealized": "0.00",
            "utiliseddebits": "0.00",
        }

    try:
        position_book = get_positions(auth_token)

        logger.debug(
            "Positionbook entries=%s",
            len(position_book) if isinstance(position_book, list) else 0,
        )

        # Check if position_book is an error response
        if isinstance(position_book, dict) and position_book.get("errorType"):
            logger.error(
                f"Error getting positions: {position_book.get('errorMessage', 'Unknown error')}"
            )
            total_realised = 0
            total_unrealised = 0
        else:
            # If successful, process the positions
            def sum_realised_unrealised(position_book):
                total_realised = 0
                total_unrealised = 0
                if isinstance(position_book, list):
                    total_realised = sum(
                        position.get("realizedProfit", 0) for position in position_book
                    )
                    total_unrealised = sum(
                        position.get("unrealizedProfit", 0) for position in position_book
                    )
                return total_realised, total_unrealised

            total_realised, total_unrealised = sum_realised_unrealised(position_book)

        # Construct and return the processed margin data with null checks
        processed_margin_data = {
            "availablecash": "{:.2f}".format(margin_data.get("availabelBalance") or 0),
            "collateral": "{:.2f}".format(margin_data.get("collateralAmount") or 0),
            "m2munrealized": f"{total_unrealised or 0:.2f}",
            "m2mrealized": f"{total_realised or 0:.2f}",
            "utiliseddebits": "{:.2f}".format(margin_data.get("utilizedAmount") or 0),
        }
        return processed_margin_data
    except KeyError:
        # Return an empty dictionary in case of unexpected data structure
        return {}
