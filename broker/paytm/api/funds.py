# api/funds.py

import os
import json
from utils.httpx_client import get_httpx_client
from broker.paytm.api.order_api import get_positions
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from Paytm API using the provided auth token."""
    try:
        base_url = "https://developer.paytmmoney.com"
        request_path = "/accounts/v1/funds/summary?config=true"
        headers = {
            'x-jwt-token': auth_token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

        logger.debug(f"Making request to: {base_url}{request_path}")
        client = get_httpx_client()
        response = client.get(f"{base_url}{request_path}", headers=headers)
        margin_data = response.json()

        logger.debug(f"Funds Details: {margin_data}")

        if margin_data.get('status') == 'error':
            error_details = margin_data.get('errors')
            logger.error(f"Error fetching margin data: {error_details}")
            logger.debug(f"Full error response from margin API: {margin_data}")
            return {}
        
        # Extracting funds summary safely
        funds_summary = margin_data.get('data', {}).get('funds_summary', {})
        position_book = get_positions(auth_token)
        logger.debug(f"Positionbook: {position_book}")

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
    except Exception:
        logger.exception("An error occurred while fetching margin data")
        return {}
