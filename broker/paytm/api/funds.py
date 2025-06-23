# api/funds.py

import os
import json
from utils.httpx_client import get_httpx_client
from broker.paytm.api.order_api import get_positions
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from Paytm API using the provided auth token."""
    base_url = "https://developer.paytmmoney.com"
    request_path = "/accounts/v1/funds/summary?config=true"
    headers = {
        'x-jwt-token': auth_token,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    logger.info("Making request to: {base_url}%s", request_path)
    client = get_httpx_client()
    response = client.get(f"{base_url}{request_path}", headers=headers)
    margin_data = response.json()

    logger.info("Funds Details: %s", margin_data)


    if margin_data.get('status') == 'error':
        # Log the error or return an empty dictionary to indicate failure
        logger.info("Error fetching margin data: %s", margin_data.get('errors'))
        return {}
    # Extracting funds summary safely
    funds_summary = margin_data.get('data', {}).get('funds_summary', {})

    try:

        position_book = get_positions(auth_token)

        logger.info("Positionbook : %s", position_book)

        #position_book = map_position_data(position_book)

        def sum_realised_unrealised(position_book):
            total_realised = 0
            total_unrealised = 0
            if isinstance(position_book.get('data', []), list):
                for position in position_book['data']:
                    total_realised += float(position.get('realised_profit', 0))
                    # Since all positions are closed, unrealized profit is 0
                    total_unrealised += float(position.get('unrealised_profit', 0))
            return total_realised, total_unrealised

        total_realised, total_unrealised = sum_realised_unrealised(position_book)
        
        # Construct and return the processed margin data

        processed_margin_data = {
            "availablecash": f"{funds_summary.get('available_cash', 0):.2f}",
            "collateral": f"{funds_summary.get('collaterals', 0):.2f}",
            "m2munrealized": f"{total_unrealised:.2f}",
            "m2mrealized": f"{total_realised:.2f}",
            "utiliseddebits": f"{funds_summary.get('utilised_amount', 0):.2f}",
        }
        return processed_margin_data
    except KeyError:
        # Return an empty dictionary in case of unexpected data structure
        return {}
