import os

import httpx

from broker.mstock.database import master_contract_db
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin (fund) data from MStock API using Type B authentication."""
    # Use BROKER_API_SECRET which contains the mStock API key
    api_key = os.getenv("BROKER_API_SECRET")

    if not api_key:
        logger.error("Missing environment variable: BROKER_API_SECRET")
        return {}

    logger.info(
        f"Fetching margin data with auth_token length: {len(auth_token) if auth_token else 0}"
    )
    logger.debug(f"Auth token (first 30 chars): {auth_token[:30] if auth_token else 'None'}...")
    logger.debug(f"API key length: {len(api_key) if api_key else 0}")

    headers = {
        "X-Mirae-Version": "1",
        "Authorization": f"Bearer {auth_token}",
        "X-PrivateKey": api_key,
    }

    try:
        client = get_httpx_client()
        response = client.get(
            "https://api.mstock.trade/openapi/typeb/user/fundsummary", headers=headers, timeout=10.0
        )
        logger.info(f"Fund summary API response status: {response.status_code}")

        response.raise_for_status()
        margin_data = response.json()

        logger.debug(
            f"Fund summary response: status={margin_data.get('status')}, has_data={bool(margin_data.get('data'))}"
        )
        logger.debug(f"Full margin data response: {margin_data}")
        if margin_data.get("status") == True and margin_data.get("data"):
            data = margin_data["data"][0]
            key_mapping = {
                "AVAILABLE_BALANCE": "availablecash",
                "COLLATERALS": "collateral",
                "REALISED_PROFITS": "m2mrealized",
                "MTM_COMBINED": "m2munrealized",
                "AMOUNT_UTILIZED": "utiliseddebits",
            }

            filtered_data = {}
            for mstock_key, openalgo_key in key_mapping.items():
                value = data.get(mstock_key)
                if value in (None, "None", ""):
                    value = 0
                try:
                    formatted_value = f"{float(value):.2f}"
                except (ValueError, TypeError):
                    formatted_value = "0.00"
                filtered_data[openalgo_key] = formatted_value

            logger.debug(f"filteredMargin Data: {filtered_data}")
            return filtered_data

        logger.error(f"Margin API failed: {margin_data.get('message', 'No data')}")
        return {}

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP Error while fetching margin data: {e}")
        logger.error(f"Response status code: {e.response.status_code}")
        logger.error(f"Response body: {e.response.text}")
        try:
            error_detail = e.response.json()
            logger.error(f"Error details: {error_detail}")
        except:
            pass
        return {}
    except httpx.RequestError as e:
        logger.error(f"Network Error while fetching margin data: {e}")
        return {}
    except Exception:
        logger.exception("Unexpected error while fetching margin data.")
        return {}
