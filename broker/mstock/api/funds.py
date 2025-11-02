import os
import httpx
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def get_margin_data(auth_token):
    """
    Fetch margin (fund) data from MStock API using Type A authentication.
    Returns:
        (dict, str): Tuple of (margin_data, error_message)
    """
    api_key = os.getenv('BROKER_API_KEY')
    if not api_key:
        return None, "Missing environment variable: BROKER_API_KEY"

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


        # Validate response
        if margin_data.get('status') == 'success' and margin_data.get('data'):
            data = margin_data['data'][0]

            # Mapping between MStock keys and OpenAlgo internal keys
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

            # Include optional balance summary fields if available
            filtered_data["totalbalance"] = "{:.2f}".format(
                float(data.get("SUM_OF_ALL", filtered_data.get("availablecash", 0)))
            )

            logger.info(f"filteredMargin Data: {filtered_data}")
            
            return filtered_data, None

        # If status is not success
        error_message = margin_data.get('message', 'Failed to fetch margin data')
        logger.error(f"Margin API failed: {error_message}")
        return None, error_message

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP Error while fetching margin data: {e}")
        return None, f"HTTP error occurred: {e.response.status_code} - {e.response.text}"

    except httpx.RequestError as e:
        logger.error(f"Network Error while fetching margin data: {e}")
        return None, f"Network error: {str(e)}"

    except Exception as e:
        logger.exception("Unexpected error while fetching margin data.")
        return None, str(e)
