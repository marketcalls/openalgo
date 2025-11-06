# api/funds.py

from broker.zerodha.api.api_response import get_api_response
from utils.logging import get_logger

logger = get_logger(__name__)



def get_margin_data(auth_token):
    """Fetch margin data from Zerodha's API using the provided auth token."""
    margin_data = get_api_response("/user/margins",auth_token)

    logger.info(f"Funds Details: {margin_data}")

    if margin_data.get('status') == 'error':
        # Log the error or return an empty dictionary to indicate failure
        logger.info(f"Error fetching margin data: {margin_data.get('errors')}")
        return {}

    try:
        # Calculate the sum of net values for available margin
        total_available_margin = sum([
            margin_data['data']['commodity']['net'],
            margin_data['data']['equity']['net']
        ])
        # Calculate the sum of debits for used margin
        total_used_margin = sum([
            margin_data['data']['commodity']['utilised']['debits'],
            margin_data['data']['equity']['utilised']['debits']
        ])

        # Calculate the sum of collateral values
        total_collateral = sum([
            margin_data['data']['commodity']['available']['collateral'],
            margin_data['data']['equity']['available']['collateral']
        ])

        # Calculate the sum of m2m_unrealised
        total_unrealised = sum([
            margin_data['data']['commodity']['utilised']['m2m_unrealised'],
            margin_data['data']['equity']['utilised']['m2m_unrealised']
        ])

        # Calculate the sum of m2m_realised
        total_realised = sum([
            margin_data['data']['commodity']['utilised']['m2m_realised'],
            margin_data['data']['equity']['utilised']['m2m_realised']
        ])

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": "{:.2f}".format(total_available_margin),
            "collateral": "{:.2f}".format(total_collateral),
            "m2munrealized": "{:.2f}".format(total_unrealised),
            "m2mrealized": "{:.2f}".format(total_realised),
            "utiliseddebits": "{:.2f}".format(total_used_margin),
        }
        return processed_margin_data
    except KeyError:
        # Return an empty dictionary in case of unexpected data structure
        return {}
