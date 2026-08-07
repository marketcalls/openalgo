# api/funds.py

import json
import os
from typing import Any, Dict

import httpx

from broker.fivepaisa.api.order_api import get_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Retrieve the BROKER_API_KEY environment variable
broker_api_key = os.getenv("BROKER_API_KEY")


def get_margin_data(auth_token: str) -> dict[str, Any]:
    """Fetch margin data from the broker's API using the provided auth token.

    Args:
        auth_token (str): Authentication token for the broker API

    Returns:
        Dict[str, Any]: Processed margin data with keys:
            - availablecash: Net available margin
            - collateral: Total collateral value
            - m2munrealized: Total mark-to-market unrealized P&L
            - m2mrealized: Total booked P&L
            - utiliseddebits: Utilized margin
    """
    if not broker_api_key:
        raise ValueError("BROKER_API_KEY not found in environment variables")

    # Split the string to separate the API key and the client ID
    try:
        api_key, user_id, client_id = broker_api_key.split(":::")
    except ValueError:
        raise ValueError(
            "BROKER_API_KEY format is incorrect. Expected format: 'api_key:::client_id'"
        )

    # Get the shared httpx client
    client = get_httpx_client()

    json_data = {"head": {"key": api_key}, "body": {"ClientCode": client_id}}

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"bearer {auth_token}",
    }

    try:
        response = client.post(
            "https://Openapi.5paisa.com/VendorsAPI/Service1.svc/V4/Margin",
            json=json_data,
            headers=headers,
        )
        response.raise_for_status()
        margin_data = response.json()
        logger.info(f"Margin Data is : {margin_data}")

        # EquityMargin is an array with a single entry; it comes back empty when
        # the API reports Status 1 ("No record found"), so don't index blindly.
        equity_margins = margin_data.get("body", {}).get("EquityMargin") or []
        if not equity_margins:
            logger.error(
                f"5Paisa Margin returned no EquityMargin entry: "
                f"{margin_data.get('body', {}).get('Message')}"
            )
            return {}
        equity_margin = equity_margins[0]

        positions_data = get_positions(auth_token)

        # 5Paisa sends NetPositionDetail as null (not []) when the account has
        # no open positions — iterating that raised TypeError, which the handler
        # below swallowed into an empty dict, so the funds page went blank for
        # every flat account. Coalesce to a list.
        net_position_details = (positions_data.get("body") or {}).get("NetPositionDetail") or []

        # Calculating the total BookedPL and total MTOM
        total_booked_pl = sum(position.get("BookedPL", 0) or 0 for position in net_position_details)
        total_mtom = sum(position.get("MTOM", 0) or 0 for position in net_position_details)

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": "{:.2f}".format(equity_margin.get("NetAvailableMargin", 0)),
            "collateral": "{:.2f}".format(equity_margin.get("TotalCollateralValue", 0)),
            "m2munrealized": round(total_mtom, 2),
            "m2mrealized": round(total_booked_pl, 2),
            "utiliseddebits": "{:.2f}".format(equity_margin.get("MarginUtilized", 0)),
        }

        return processed_margin_data
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
        return {}
    except httpx.RequestError as e:
        logger.error(f"Request error occurred: {e}")
        return {}
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return {}
