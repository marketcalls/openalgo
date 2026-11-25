# api/funds.py

import http.client
import json
import os

from broker.fivepaisaxts.baseurl import INTERACTIVE_URL
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from Compositedge's API using the provided auth token."""
    api_key = os.getenv("BROKER_API_KEY")
    api_secret = os.getenv("BROKER_API_SECRET")

    client = get_httpx_client()

    # conn = http.client.HTTPSConnection("xts.compositedge.com")

    headers = {"authorization": auth_token, "Content-Type": "application/json"}

    response = client.get(f"{INTERACTIVE_URL}/user/balance", headers=headers)

    margin_data = response.json()

    # logger.info(f"Funds Details: {margin_data}")

    if (
        margin_data.get("result")
        and margin_data["result"].get("BalanceList")
        and margin_data["result"]["BalanceList"]
    ):
        # XTS can return several balance entries (for example CASH|NSE|MTF,
        # which is often all zeros). The ALL|ALL|ALL entry holds the account's
        # consolidated limits; the first entry is used only when none is so named.
        balance_list = margin_data["result"]["BalanceList"]
        if isinstance(balance_list, dict):
            balance_list = [balance_list]
        balance_entry = balance_list[0]
        for entry in balance_list:
            if isinstance(entry, dict) and entry.get("limitHeader") == "ALL|ALL|ALL":
                balance_entry = entry
                break

        rms_sublimits = balance_entry["limitObject"]["RMSSubLimits"]

        required_keys = [
            "netMarginAvailable",
            "collateral",
            "UnrealizedMTM",
            "RealizedMTM",
            "marginUtilized",
        ]

        filtered_data = {}
        for key in required_keys:
            value = rms_sublimits.get(key, 0)
            try:
                formatted_value = f"{float(value):.2f}" if str(value).lower() != "nan" else "0.00"
            except (ValueError, TypeError):
                formatted_value = "0.00"

            filtered_data[key] = formatted_value
            # logger.info(f"Funds Dashboard: {key} = {filtered_data[key]}")

        processed_margin_data = {
            "availablecash": filtered_data.get("netMarginAvailable"),
            "collateral": filtered_data.get("collateral"),
            "m2munrealized": filtered_data.get("UnrealizedMTM"),
            "m2mrealized": filtered_data.get("RealizedMTM"),
            "utiliseddebits": filtered_data.get("marginUtilized"),
        }

        # logger.info(f"Funds = {processed_margin_data}")
        return processed_margin_data
    else:
        return {}
