# api/funds.py

import json
import os

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from the broker's API using the provided auth token."""
    api_key = os.getenv("BROKER_API_KEY")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "CLIENT_LOCAL_IP",
        "X-ClientPublicIP": "CLIENT_PUBLIC_IP",
        "X-MACAddress": "MAC_ADDRESS",
        "X-PrivateKey": api_key,
    }

    response = client.get(
        "https://apiconnect.angelone.in/rest/secure/angelbroking/user/v1/getRMS",
        headers=headers,
    )

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    margin_data = json.loads(response.text)

    logger.info(f"Margin Data: {margin_data}")

    if margin_data.get("data"):
        data = margin_data["data"]

        # Angel's raw "availablecash" is actually a net-margin figure (Free
        # cash balance + Pledge margin - Amount utilised, confirmed against
        # a live account: 2043799.20 + 156600.22 - 1697.17 = 2198702.25),
        # not the free cash balance itself -- same class of bug as GitHub
        # issue #1582. Collateral is derived as availablecash - utilisedpayout
        # (empirically matches the real Pledge Margin), so back out the true
        # free cash the same way Kite's net = cash + collateral - debits is
        # inverted: cash = net + debits - collateral.
        raw_net = 0.0
        calculated_collateral = 0.0
        utiliseddebits = 0.0
        try:
            raw_net = float(data.get("availablecash", 0) or 0)
            utilisedpayout = float(data.get("utilisedpayout", 0) or 0)
            calculated_collateral = raw_net - utilisedpayout
            utiliseddebits = float(data.get("utiliseddebits", 0) or 0)
        except (ValueError, TypeError):
            pass

        availablecash = raw_net + utiliseddebits - calculated_collateral

        filtered_data = {
            "availablecash": f"{availablecash:.2f}",
            "collateral": f"{calculated_collateral:.2f}",
            "m2mrealized": "{:.2f}".format(float(data.get("m2mrealized", 0) or 0)),
            "m2munrealized": "{:.2f}".format(float(data.get("m2munrealized", 0) or 0)),
            "utiliseddebits": f"{utiliseddebits:.2f}",
        }

        logger.info(
            f"Calculated collateral (availablecash - utilisedpayout): {calculated_collateral}, "
            f"derived free cash: {availablecash}"
        )
        return filtered_data
    else:
        return {}
