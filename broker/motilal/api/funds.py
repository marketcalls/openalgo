# api/funds.py

import os
import httpx
import json
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from Motilal Oswal API using the provided auth token."""
    api_key = os.getenv('BROKER_API_KEY')

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Motilal Oswal required headers
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'MOSL/V.1.1.0',
        'Authorization': auth_token,
        'ApiKey': api_key,
        'ClientLocalIp': '127.0.0.1',
        'ClientPublicIp': '127.0.0.1',
        'MacAddress': '00:00:00:00:00:00',
        'SourceId': 'WEB',
        'osname': 'Windows',
        'osversion': '10.0',
        'devicemodel': 'PC',
        'manufacturer': 'Generic',
        'productname': 'OpenAlgo',
        'productversion': '1.0.0',
        'browsername': 'Chrome',
        'browserversion': '120.0'
    }

    # Motilal Oswal Margin Detail API endpoint (more comprehensive than summary)
    response = client.post(
        "https://openapi.motilaloswal.com/rest/report/v1/getreportmargindetail",
        headers=headers,
        json={}
    )

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    margin_data = response.json()

    logger.info(f"Margin Data: {margin_data}")

    # Parse Motilal Oswal margin data response
    if margin_data.get('status') == 'SUCCESS' and margin_data.get('data'):
        # Extract key margin fields from the data array
        data_items = margin_data['data']

        # Map Motilal Oswal fields to OpenAlgo standard fields
        margin_dict = {}
        for item in data_items:
            srno = item.get('srno')
            amount = item.get('amount', 0)

            # Map specific srno to field names based on API documentation
            if srno == 102:  # Available for Cash / SLBM Segment
                margin_dict['availablecash'] = amount
            elif srno == 220:  # Non-Cash Balance (Non-Cash Margin) - collateral
                margin_dict['collateral'] = amount
            elif srno == 201:  # Cash Balance (Cash Margin) - fallback if 102 not available
                if 'availablecash' not in margin_dict:
                    margin_dict['availablecash'] = amount
            elif srno == 300:  # Margin Usage Details (B) - total utilized
                margin_dict['utiliseddebits'] = amount
            elif srno == 301:  # Margin Usage Equities - fallback
                if 'utiliseddebits' not in margin_dict:
                    margin_dict['utiliseddebits'] = amount
            elif srno == 600:  # Total Profit and Loss (MTM)
                margin_dict['m2munrealized'] = amount
            elif srno == 700:  # Total Profit and Loss (BPL) - Booked Profit/Loss
                margin_dict['m2mrealized'] = amount
            elif srno == 400:  # Profit / Loss (MTM) Details - fallback
                if 'm2munrealized' not in margin_dict:
                    margin_dict['m2munrealized'] = amount

        # Format values to 2 decimal places
        filtered_data = {}
        for key in ['availablecash', 'collateral', 'm2mrealized', 'm2munrealized', 'utiliseddebits']:
            value = margin_dict.get(key, 0)
            try:
                formatted_value = "{:.2f}".format(float(value))
            except (ValueError, TypeError):
                formatted_value = "0.00"
            filtered_data[key] = formatted_value

        return filtered_data
    else:
        logger.error(f"Failed to fetch margin data: {margin_data.get('message', 'Unknown error')}")
        return {
            'availablecash': '0.00',
            'collateral': '0.00',
            'm2mrealized': '0.00',
            'm2munrealized': '0.00',
            'utiliseddebits': '0.00'
        }
