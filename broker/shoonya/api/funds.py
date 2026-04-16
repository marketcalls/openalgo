# api/funds.py

import json
import os

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from Shoonya's API using the provided auth token."""

    # BROKER_API_KEY format: userid:::client_id
    full_api_key = os.getenv("BROKER_API_KEY")
    if not full_api_key or ":::" not in full_api_key:
        logger.error("BROKER_API_KEY not configured or invalid format")
        return {}
    userid = full_api_key.split(":::")[0]  # Trading user ID
    actid = userid

    # Prepare the payload for the request
    data = {
        "uid": userid,
        "actid": actid,
    }

    # Prepare the jData payload
    payload_str = "jData=" + json.dumps(data)

    # Get the shared httpx client
    client = get_httpx_client()

    # Set headers with Bearer token authentication
    headers = {
        "Content-Type": "text/plain",
        "Authorization": f"Bearer {auth_token}",
    }

    url = "https://api.shoonya.com/NorenWClientAPI/Limits"

    # Send the POST request to Shoonya's API
    response = client.post(url, content=payload_str, headers=headers)

    # Parse the response
    margin_data = json.loads(response.text)

    logger.info(f"Funds Details: {margin_data}")

    # Check if the request was successful
    if margin_data.get("stat") != "Ok":
        logger.info(f"Error fetching margin data: {margin_data.get('emsg')}")
        return {}

    try:
        # Calculate total_available_margin as the sum of 'cash' and 'payin'
        total_available_margin = (
            float(margin_data.get("cash", 0))
            + float(margin_data.get("payin", 0))
            - float(margin_data.get("marginused", 0))
        )
        total_collateral = float(margin_data.get("brkcollamt", 0))
        total_used_margin = float(margin_data.get("marginused", 0))
        total_realised = -float(margin_data.get("rpnl", 0))
        total_unrealised = float(margin_data.get("unmtom", 0))

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": f"{total_available_margin:.2f}",
            "collateral": f"{total_collateral:.2f}",
            "m2munrealized": f"{total_unrealised:.2f}",
            "m2mrealized": f"{total_realised:.2f}",
            "utiliseddebits": f"{total_used_margin:.2f}",
        }
        return processed_margin_data
    except KeyError as e:
        logger.error(f"Error processing margin data: {e}")
        return {}
