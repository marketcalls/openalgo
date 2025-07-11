# api/funds.py

import os
import json
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)



def get_margin_data(auth_token):
    """Fetch margin data from Zerodha's API using the provided auth token."""
    api_key = os.getenv('BROKER_API_KEY')
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'X-Kite-Version': '3',
        'Authorization': f'token {auth_token}'
    }
    
    try:
        # Make the GET request using the shared client
        response = client.get(
            'https://api.kite.trade/user/margins',
            headers=headers
        )
        response.raise_for_status()  # Raises an exception for 4XX/5XX responses
        
        # Parse the response
        margin_data = response.json()
    except Exception as e:
        error_message = str(e)
        try:
            if hasattr(e, 'response') and e.response is not None:
                error_detail = e.response.json()
                error_message = error_detail.get('message', str(e))
        except:
            pass
            
        logger.error(f"Error fetching margin data: {error_message}")
        return {}

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
