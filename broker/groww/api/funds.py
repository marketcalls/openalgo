# api/funds.py

import json
import os

import httpx

from broker.groww.api.rate_limiter import groww_request
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from utils.broker_backpressure import BrokerBusyError

logger = get_logger(__name__)


def _day_m2m(auth_token):
    """Realised and unrealised P&L of the day's positions, in rupees.

    Uses the strict position read, so a CASH book that cannot be read is
    reported rather than summed as empty. OpenAlgo's funds format has no field
    for "incomplete", so what is missing is logged instead of hidden: an FNO
    segment that was not read, and open positions Groww returned no live price
    for (their unrealised P&L is unknown, not 0). Returns (0.0, 0.0) when the
    book cannot be read at all; the cash figures are still worth showing.
    """
    from broker.groww.api.order_api import get_positions

    try:
        payload, status = get_positions(auth_token, strict=True, include_ltp=True)
    except BrokerBusyError:
        raise
    except Exception:
        logger.exception("Groww positions could not be read for funds P&L")
        return 0.0, 0.0
    if status != 200 or payload.get("status") != "success":
        logger.warning(f"Groww positions not read for funds P&L: {payload.get('message')}")
        return 0.0, 0.0
    if payload.get("failed_segments"):
        logger.warning(
            f"Groww funds P&L excludes the {payload['failed_segments']} positions, which could not be read"
        )
    rows = payload.get("data") or []
    unpriced = [
        row.get("symbol")
        for row in rows
        if float(row.get("quantity") or 0) != 0 and not float(row.get("ltp") or 0)
    ]
    if unpriced:
        logger.warning(
            f"Groww funds unrealised P&L excludes open positions with no live price: {unpriced}"
        )
    realised = sum(float(row.get("realised") or 0) for row in rows)
    unrealised = sum(float(row.get("unrealised") or 0) for row in rows)
    return realised, unrealised


def get_margin_data(auth_token):
    """Fetch margin data directly from Groww API using the provided auth token."""
    logger.info("Getting margin data; auth_token_present=%s", bool(auth_token))

    try:
        # Define the API endpoint for user margin details
        url = "https://api.groww.in/v1/margins/detail/user"

        # Set up headers with authentication token
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {auth_token}",
            "X-API-VERSION": "1.0",
        }

        # Get the shared httpx client with connection pooling
        client = get_httpx_client()

        # Make the API request using the shared client
        response = groww_request(client, "GET", url, "non_trading", headers=headers, timeout=30)

        # Check if the request was successful
        if response.status_code != 200:
            logger.error(f"Error fetching margin data: HTTP {response.status_code}")
            return {}

        # Parse the JSON response
        response_data = response.json()
        logger.info("Funds response received; status=%s", response_data.get("status"))

        # Check if the response was successful according to Groww's status field
        if response_data.get("status") != "SUCCESS":
            logger.info(f"Error fetching margin data: {response_data.get('status')}")
            return {}

        # Extract the margin data from the payload
        margin_data = response_data.get("payload", {})

        if not margin_data:
            logger.error("Error fetching margin data: Empty payload")
            return {}

        # The margins endpoint carries no P&L. Groww documents realised_pnl on
        # positions (06-portfolio), and get_positions adds each open
        # position's move from its average using the live LTP.
        total_realised, total_unrealised = _day_m2m(auth_token)

        # OpenAlgo's funds format (docs/api/account-services/funds.md) has
        # exactly these five fields, from Groww's margins/detail/user payload
        processed_margin_data = {
            "availablecash": "{:.2f}".format(margin_data.get("clear_cash", 0)),
            "collateral": "{:.2f}".format(margin_data.get("collateral_available", 0)),
            "m2mrealized": f"{total_realised:.2f}",
            "m2munrealized": f"{total_unrealised:.2f}",
            "utiliseddebits": "{:.2f}".format(margin_data.get("net_margin_used", 0)),
        }
        return processed_margin_data

    except BrokerBusyError:
        raise
    except Exception as e:
        logger.error(f"Error in get_margin_data: {e}")
        # Return an empty dictionary in case of unexpected data structure or error
        return {}
