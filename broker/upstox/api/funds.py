# api/funds.py

import os
import json
import httpx
from utils.httpx_client import get_httpx_client
from broker.upstox.api.order_api import get_positions
from broker.upstox.mapping.order_data import map_order_data
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from Upstox's API using the provided auth token with httpx connection pooling."""
    api_key = os.getenv('BROKER_API_KEY')
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'Authorization': f'Bearer {auth_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    
    response = client.get("https://api.upstox.com/v2/user/get-funds-and-margin", headers=headers)
    
    # Add status attribute for compatibility with existing code that expects http.client response
    response.status = response.status_code
    
    margin_data = response.json()

    logger.info(f"Funds Details: {margin_data}")


    if margin_data.get('status') == 'error':
        # Log the error or return an empty dictionary to indicate failure
        logger.info("Error fetching margin data: %s", margin_data.get('errors'))
        return {}

    try:
        # Calculate the sum of available_margin and used_margin
        total_available_margin = sum([
            margin_data['data']['commodity']['available_margin'],
            margin_data['data']['equity']['available_margin']
        ])
        total_used_margin = sum([
            margin_data['data']['commodity']['used_margin'],
            margin_data['data']['equity']['used_margin']
        ])

        position_book = get_positions(auth_token)

        position_book = map_order_data(position_book)

        def sum_realised_unrealised(position_book):
            total_realised = 0
            total_unrealised = 0
            total_realised = sum(position['realised'] for position in position_book)
            total_unrealised = sum(position['unrealised'] for position in position_book)
            return total_realised, total_unrealised

        total_realised, total_unrealised = sum_realised_unrealised(position_book)


        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": "{:.2f}".format(total_available_margin),
            "collateral": "0.00",
            "m2munrealized": "{:.2f}".format(total_unrealised),
            "m2mrealized": "{:.2f}".format(total_realised),
            "utiliseddebits": "{:.2f}".format(total_used_margin),
        }
        return processed_margin_data
    except KeyError:
        # Return an empty dictionary in case of unexpected data structure
        return {}
