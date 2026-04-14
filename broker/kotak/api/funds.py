# api/funds.py
import json

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """
    Fetch margin data from the broker's API using the provided auth token.

    Auth token format: trading_token:::trading_sid:::base_url:::access_token
    """
    try:
        # Parse auth token components
        access_token_parts = auth_token.split(":::")
        if len(access_token_parts) != 4:
            logger.error(
                f"Invalid auth token format. Expected 4 parts, got {len(access_token_parts)}"
            )
            return {}

        trading_token = access_token_parts[0]
        trading_sid = access_token_parts[1]
        base_url = access_token_parts[2]
        access_token = access_token_parts[3]

        if not base_url:
            logger.error("Base URL not found in auth token")
            return {}

        logger.debug(f"Fetching margin data from {base_url}")

        # Get the shared httpx client with connection pooling
        client = get_httpx_client()

        # Prepare payload as per Kotak API docs: jData with seg, exch, prod
        payload = (
            "jData=%7B%22seg%22%3A%22ALL%22%2C%22exch%22%3A%22ALL%22%2C%22prod%22%3A%22ALL%22%7D"
        )

        headers = {
            "accept": "application/json",
            "Sid": trading_sid,
            "Auth": trading_token,
            "neo-fin-key": "neotradeapi",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # Construct full URL
        url = f"{base_url}/quick/user/limits"

        logger.debug(f"Making POST request to {url}")

        response = client.post(url, headers=headers, content=payload)

        logger.debug(f"Kotak Limits API Response Status: {response.status_code}")
        logger.debug(f"Kotak Limits API Response: {response.text}")

        margin_data = json.loads(response.text)

        # Check for API errors
        if margin_data.get("stat") != "Ok":
            error_msg = margin_data.get("emsg", "Unknown error")
            logger.error(f"Kotak Limits API error: {error_msg}")
            return {}

        # Process and return the margin data
        # Note: Based on the API docs, the response fields are at root level
        # Available Balance = CollateralValue + RmsPayInAmt - RmsPayOutAmt + Collateral
        collateral_value = float(margin_data.get("CollateralValue", 0))
        pay_in = float(margin_data.get("RmsPayInAmt", 0))
        pay_out = float(margin_data.get("RmsPayOutAmt", 0))
        collateral = float(margin_data.get("Collateral", 0))

        processed_margin_data = {
            "availablecash": f"{collateral_value + pay_in - pay_out + collateral:.2f}",
            "collateral": f"{collateral:.2f}",
            "m2munrealized": f"{float(margin_data.get('UnrealizedMtomPrsnt', 0)):.2f}",
            "m2mrealized": f"{float(margin_data.get('RealizedMtomPrsnt', 0)):.2f}",
            "utiliseddebits": f"{float(margin_data.get('MarginUsed', 0)):.2f}",
        }

        logger.info(f"Successfully fetched margin data: {processed_margin_data}")
        return processed_margin_data

    except KeyError as e:
        logger.error(f"Missing expected field in margin data: {e}")
        return {}
    except httpx.HTTPError as e:
        logger.error(f"HTTP request failed while fetching margin data: {e}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse margin data JSON: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error fetching margin data: {e}")
        return {}
