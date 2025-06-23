# api/funds.py

import os
import json
import httpx
from broker.dhan_sandbox.api.order_api import get_positions
from broker.dhan_sandbox.mapping.order_data import map_position_data
from utils.httpx_client import get_httpx_client
from broker.dhan_sandbox.api.baseurl import get_url
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    logger.info("%s", auth_token)
    """Fetch margin data from Dhan API using the provided auth token."""
    api_key = os.getenv('BROKER_API_KEY')
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'access-token': auth_token,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    
    url = get_url("/v2/fundlimit")
    res = client.get(url, headers=headers)
    # Add status attribute for compatibility with existing codebase
    res.status = res.status_code
    margin_data = json.loads(res.text)

    logger.info(f"Funds Details: {margin_data}")


    if margin_data.get('status') == 'error':
        # Log the error or return an empty dictionary to indicate failure
        logger.info("Error fetching margin data: %s", margin_data.get('errors'))
        return {}

    try:

        position_book = get_positions(auth_token)

        logger.info(f"Positionbook : {position_book}")

        # Check if position_book is an error response
        if isinstance(position_book, dict) and position_book.get('errorType'):
            logger.info("Error getting positions: %s", position_book.get('errorMessage', 'Unknown error'))
            total_realised = 0
            total_unrealised = 0
        else:
            # If successful, process the positions
            #position_book = map_position_data(position_book)

            def sum_realised_unrealised(position_book):
                total_realised = 0
                total_unrealised = 0
                if isinstance(position_book, list):
                    total_realised = sum(position.get('realizedProfit', 0) for position in position_book)
                    total_unrealised = sum(position.get('unrealizedProfit', 0) for position in position_book)
                return total_realised, total_unrealised

            total_realised, total_unrealised = sum_realised_unrealised(position_book)
        
        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": "{:.2f}".format(margin_data.get('availabelBalance')),
            "collateral": "{:.2f}".format(margin_data.get('collateralAmount')),
            "m2munrealized": "{:.2f}".format(total_unrealised),
            "m2mrealized": "{:.2f}".format(total_realised),
            "utiliseddebits": "{:.2f}".format(margin_data.get('utilizedAmount')),
        }
        return processed_margin_data
    except KeyError:
        # Return an empty dictionary in case of unexpected data structure
        return {}
