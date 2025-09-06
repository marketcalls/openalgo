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
    logger.debug("Attempting to fetch margin data...")
    try:
        api_key = os.getenv('BROKER_API_KEY')
        if not api_key:
            logger.error("BROKER_API_KEY environment variable not set.")
            return {}

        client = get_httpx_client()
        headers = {
            'Authorization': f'Bearer {auth_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        
        url = "https://api.upstox.com/v2/user/get-funds-and-margin"
        logger.debug(f"Requesting funds and margin data from {url}")
        
        response = client.get(url, headers=headers)
        response.raise_for_status()
        
        margin_data = response.json()
        logger.debug(f"Received funds and margin data: {margin_data}")

        if margin_data.get('status') == 'error':
            error_details = margin_data.get('errors', 'Unknown error')
            logger.error(f"API error fetching margin data: {error_details}")
            return {}

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
            total_realised = sum(position.get('realised', 0) for position in position_book)
            total_unrealised = sum(position.get('unrealised', 0) for position in position_book)
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
        logger.debug(f"Successfully processed margin data: {processed_margin_data}")
        return processed_margin_data
        
    except httpx.HTTPStatusError as e:
        response_text = e.response.text
        
        # Check if it's a service hours error (423 Locked)
        if e.response.status_code == 423:
            try:
                error_data = json.loads(response_text)
                if error_data.get('status') == 'error':
                    errors = error_data.get('errors', [])
                    for error in errors:
                        if error.get('errorCode') == 'UDAPI100072':
                            # Return default values for service hours error
                            logger.info("Upstox funds service is outside operating hours (5:30 AM to 12:00 AM IST). Returning default values.")
                            return {
                                "availablecash": "0.00",
                                "collateral": "0.00",
                                "m2munrealized": "0.00",
                                "m2mrealized": "0.00",
                                "utiliseddebits": "0.00"
                            }
            except json.JSONDecodeError:
                pass
        
        # Log the full error only if it's not a service hours issue
        logger.exception(f"HTTP error occurred while fetching margin data: {response_text}")
        return {}
    except (KeyError, TypeError) as e:
        logger.exception(f"Error processing margin data structure: {e}")
        return {}
    except Exception as e:
        logger.exception("An unexpected error occurred while fetching margin data")
        return {}
