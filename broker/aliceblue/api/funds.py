# api/funds.py

import json

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


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

        # Map V2 API fields to OpenAlgo format
        processed_margin_data["availablecash"] = "{:.2f}".format(
            float(item.get("tradingLimit", 0))
        )
        processed_margin_data["collateral"] = "{:.2f}".format(
            float(item.get("collateralMargin", 0))
        )
        processed_margin_data["m2munrealized"] = "0.00"
        processed_margin_data["m2mrealized"] = "0.00"
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
