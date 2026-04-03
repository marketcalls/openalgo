# api/funds.py

import os

from broker.rmoney.baseurl import INTERACTIVE_URL
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from RMoney's API using the provided auth token."""
    client = get_httpx_client()

    headers = {"authorization": auth_token, "Content-Type": "application/json"}

    response = client.get(f"{INTERACTIVE_URL}/user/balance", headers=headers)

    margin_data = response.json()

    logger.info(f"RMoney Funds Raw Response: {margin_data}")

    if (
        margin_data.get("result")
        and margin_data["result"].get("BalanceList")
        and margin_data["result"]["BalanceList"]
    ):
        # Use the ALL|ALL|ALL balance entry which has the consolidated account balances.
        # The CASH|NSE|MTF entry (index 0) typically has zeros.
        balance_list = margin_data["result"]["BalanceList"]
        balance_entry = balance_list[0]  # default fallback
        for entry in balance_list:
            if entry.get("limitHeader") == "ALL|ALL|ALL":
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

        processed_margin_data = {
            "availablecash": filtered_data.get("netMarginAvailable"),
            "collateral": filtered_data.get("collateral"),
            "m2munrealized": filtered_data.get("UnrealizedMTM"),
            "m2mrealized": filtered_data.get("RealizedMTM"),
            "utiliseddebits": filtered_data.get("marginUtilized"),
        }

        return processed_margin_data
    else:
        return {}
