# api/funds.py

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def _get_realized_pnl(client, headers):
    """Fetch positions and sum up realizedPnl from all positions.

    Note: AliceBlue positions API does not return LTP, so unrealized PnL
    cannot be accurately calculated here. Only realized PnL is returned.
    """
    try:
        positions_url = "https://a3.aliceblueonline.com/open-api/od/v1/positions"
        response = client.get(positions_url, headers=headers)
        response.raise_for_status()

        positions_data = response.json()

        if positions_data.get("status") != "Ok":
            logger.warning(
                f"Error fetching positions for PnL: {positions_data.get('message', 'Unknown error')}"
            )
            return 0.0

        positions = positions_data.get("result", [])
        if not positions:
            return 0.0

        total_realized_pnl = 0.0

        for position in positions:
            total_realized_pnl += float(position.get("realizedPnl", 0) or 0)

        return total_realized_pnl

    except Exception as e:
        logger.warning(f"Failed to fetch positions for PnL calculation: {str(e)}")
        return 0.0


def get_margin_data(auth_token):
    """Fetch margin/funds data from Alice Blue's V2 API using the provided auth token and shared connection pooling."""
    # Initialize processed data dictionary
    processed_margin_data = {
        "availablecash": "0.00",
        "collateral": "0.00",
        "m2munrealized": "0.00",
        "m2mrealized": "0.00",
        "utiliseddebits": "0.00",
    }

    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()

        url = "https://a3.aliceblueonline.com/open-api/od/v1/limits/"
        # V2 API uses just the auth_token (JWT) in the Bearer header
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }

        # Make the API request using the shared client
        response = client.get(url, headers=headers)
        response.raise_for_status()

        margin_data = response.json()

        # Check for API-level errors in the new response format
        if margin_data.get("status") != "Ok":
            error_msg = margin_data.get("message", "Unknown error")
            logger.error(f"Error fetching margin data: {error_msg}")
            return {}

        # Process the result array from the V2 API response
        results = margin_data.get("result", [])
        if not results:
            logger.warning("No margin data returned from AliceBlue API")
            return processed_margin_data

        item = results[0]

        # Fetch realized PnL from positions API
        # Note: unrealized PnL requires LTP which is not available via REST API
        realized_pnl = _get_realized_pnl(client, headers)

        # Map V2 API fields to OpenAlgo format
        processed_margin_data["availablecash"] = "{:.2f}".format(
            float(item.get("tradingLimit", 0))
        )
        processed_margin_data["collateral"] = "{:.2f}".format(
            float(item.get("collateralMargin", 0))
        )
        processed_margin_data["m2munrealized"] = "0.00"
        processed_margin_data["m2mrealized"] = "{:.2f}".format(realized_pnl)
        processed_margin_data["utiliseddebits"] = "{:.2f}".format(
            float(item.get("utilizedMargin", 0))
        )

        return processed_margin_data
    except KeyError as e:
        logger.error(f"KeyError while processing margin data: {str(e)}")
        return {}
    except httpx.HTTPError as e:
        logger.error(f"HTTP connection error: {str(e)}")
        return {}
    except Exception as e:
        logger.error(f"An exception occurred while fetching margin data: {str(e)}")
        return {}
