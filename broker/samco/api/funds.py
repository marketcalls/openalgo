# api/funds.py

import json
import os

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Samco API base URL
BASE_URL = "https://tradeapi.samco.in"


def get_margin_data(auth_token):
    """Fetch margin data from Samco's API using the provided auth token."""

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {"Accept": "application/json", "x-session-token": auth_token}

    response = client.get(f"{BASE_URL}/limit/getLimits", headers=headers)

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    margin_data = response.json()

    logger.info(f"Samco Margin Data: {margin_data}")

    if margin_data.get("status") == "Success":
        equity_limit = margin_data.get("equityLimit", {})
        commodity_limit = margin_data.get("commodityLimit", {})

        # Calculate total available margin from equity and commodity
        equity_available = float(equity_limit.get("netAvailableMargin", 0) or 0)
        commodity_available = float(commodity_limit.get("netAvailableMargin", 0) or 0)

        equity_used = float(equity_limit.get("marginUsed", 0) or 0)
        commodity_used = float(commodity_limit.get("marginUsed", 0) or 0)

        # Map Samco fields to OpenAlgo standard format
        filtered_data = {
            "availablecash": f"{equity_available + commodity_available:.2f}",
            "collateral": "{:.2f}".format(
                float(equity_limit.get("collateralMarginAgainstShares", 0) or 0)
                + float(commodity_limit.get("collateralMarginAgainstShares", 0) or 0)
            ),
            "m2mrealized": f"{0:.2f}",  # Not provided by Samco
            "m2munrealized": f"{0:.2f}",  # Not provided by Samco
            "utiliseddebits": f"{equity_used + commodity_used:.2f}",
        }
        return filtered_data
    else:
        logger.error(
            f"Samco margin data fetch failed: {margin_data.get('statusMessage', 'Unknown error')}"
        )
        return {}
