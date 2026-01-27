# api/funds.py

import json
import os

import httpx

from broker.upstox.api.order_api import get_holdings, get_positions
from broker.upstox.mapping.order_data import map_order_data
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_total_collateral(holdings):
    """
    Calculate total potential collateral value from holdings.

    Formula: Σ (quantity × average_price × (1 - haircut))

    Args:
        holdings: List of holding dictionaries from Upstox API

    Returns:
        float: Total potential collateral value
    """
    total = 0.0

    for h in holdings:
        qty = h.get("quantity", 0)
        price = h.get("average_price", 0.0)
        haircut = h.get("haircut", 0.0)

        holding_value = qty * price
        collateral_value = holding_value * (1 - haircut)

        total += collateral_value

    return round(total, 2)


def get_margin_data(auth_token):
    """Fetch margin data from Upstox's API using the provided auth token with httpx connection pooling."""
    logger.debug("Attempting to fetch margin data...")
    try:
        api_key = os.getenv("BROKER_API_KEY")
        if not api_key:
            logger.error("BROKER_API_KEY environment variable not set.")
            return {}

        client = get_httpx_client()
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        url = "https://api.upstox.com/v2/user/get-funds-and-margin"
        logger.debug(f"Requesting funds and margin data from {url}")

        response = client.get(url, headers=headers)
        response.raise_for_status()

        margin_data = response.json()
        logger.info(f"Received funds and margin data: {margin_data}")

        if margin_data.get("status") == "error":
            error_details = margin_data.get("errors", "Unknown error")
            logger.error(f"API error fetching margin data: {error_details}")
            return {}

        # Calculate the sum of available_margin and used_margin
        total_available_margin = sum(
            [
                margin_data["data"]["commodity"]["available_margin"],
                margin_data["data"]["equity"]["available_margin"],
            ]
        )
        total_used_margin = sum(
            [
                margin_data["data"]["commodity"]["used_margin"],
                margin_data["data"]["equity"]["used_margin"],
            ]
        )

        position_book = get_positions(auth_token)
        position_book = map_order_data(position_book)

        def sum_realised_unrealised(position_book):
            total_realised = sum(position.get("realised", 0) for position in position_book)
            total_unrealised = sum(position.get("unrealised", 0) for position in position_book)
            return total_realised, total_unrealised

        total_realised, total_unrealised = sum_realised_unrealised(position_book)

        # Get holdings and calculate collateral
        holdings_response = get_holdings(auth_token)
        logger.debug(f"Holdings response: {holdings_response}")

        total_collateral = 0.0
        if holdings_response.get("status") == "success" and holdings_response.get("data"):
            holdings_data = holdings_response["data"]
            logger.debug(
                f"Holdings data for collateral calculation: {json.dumps(holdings_data, indent=2)}"
            )
            total_collateral = calculate_total_collateral(holdings_data)
            logger.info(f"Calculated total collateral: {total_collateral}")

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": f"{total_available_margin:.2f}",
            "collateral": f"{total_collateral:.2f}",
            "m2munrealized": f"{total_unrealised:.2f}",
            "m2mrealized": f"{total_realised:.2f}",
            "utiliseddebits": f"{total_used_margin:.2f}",
        }
        logger.debug(f"Successfully processed margin data: {processed_margin_data}")
        return processed_margin_data

    except httpx.HTTPStatusError as e:
        response_text = e.response.text

        # Check if it's a service hours error (423 Locked)
        if e.response.status_code == 423:
            try:
                error_data = json.loads(response_text)
                if error_data.get("status") == "error":
                    errors = error_data.get("errors", [])
                    for error in errors:
                        if error.get("errorCode") == "UDAPI100072":
                            # Return default values for service hours error
                            logger.info(
                                "Upstox funds service is outside operating hours (5:30 AM to 12:00 AM IST). Returning default values."
                            )
                            return {
                                "availablecash": "0.00",
                                "collateral": "0.00",
                                "m2munrealized": "0.00",
                                "m2mrealized": "0.00",
                                "utiliseddebits": "0.00",
                            }
            except json.JSONDecodeError:
                pass

        # Log the full error only if it's not a service hours issue
        logger.exception(f"HTTP error occurred while fetching margin data: {response_text}")
        return {}
    except (KeyError, TypeError) as e:
        logger.exception(f"Error processing margin data structure: {e}")
        return {}
    except Exception:
        logger.exception("An unexpected error occurred while fetching margin data")
        return {}
