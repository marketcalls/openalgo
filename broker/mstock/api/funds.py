import os
import httpx
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from broker.mstock.database import master_contract_db

logger = get_logger(__name__)

def get_margin_data(auth_token):
    """Fetch margin (fund) data from MStock API using Type A authentication."""
    api_key = os.getenv('BROKER_API_KEY')

    if not api_key:
        logger.error("Missing environment variable: BROKER_API_KEY")
        return {}

    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
    }

    try:
        client = get_httpx_client()
        response = client.get(
            'https://api.mstock.trade/openapi/typea/user/fundsummary',
            headers=headers,
            timeout=10.0
        )
        response.raise_for_status()
        margin_data = response.json()

        if margin_data.get('status') == 'success' and margin_data.get('data'):
            data = margin_data['data'][0]
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
                    formatted_value = "{:.2f}".format(float(value))
                except (ValueError, TypeError):
                    formatted_value = "0.00"
                filtered_data[openalgo_key] = formatted_value

            logger.info(f"filteredMargin Data: {filtered_data}")
            return filtered_data

        logger.error(f"Margin API failed: {margin_data.get('message', 'No data')}")
        return {}

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP Error while fetching margin data: {e}")
        return {}
    except httpx.RequestError as e:
        logger.error(f"Network Error while fetching margin data: {e}")
        return {}
    except Exception as e:
        logger.exception("Unexpected error while fetching margin data.")
        return {}
