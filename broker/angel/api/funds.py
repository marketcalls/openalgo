# api/funds.py

import os
import httpx
import json
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from the broker's API using the provided auth token."""
    api_key = os.getenv('BROKER_API_KEY')
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'Authorization': f'Bearer {auth_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-UserType': 'USER',
        'X-SourceID': 'WEB',
        'X-ClientLocalIP': 'CLIENT_LOCAL_IP',
        'X-ClientPublicIP': 'CLIENT_PUBLIC_IP',
        'X-MACAddress': 'MAC_ADDRESS',
        'X-PrivateKey': api_key
    }
    
    response = client.get(
        "https://apiconnect.angelbroking.com/rest/secure/angelbroking/user/v1/getRMS",
        headers=headers
    )
    
    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code
    
    margin_data = json.loads(response.text)

    logger.info(f"Margin Data: {margin_data}")

    if margin_data.get('data'):
        required_keys = [
            "availablecash", 
            "collateral", 
            "m2mrealized", 
            "m2munrealized", 
            "utiliseddebits"
        ]
        filtered_data = {}
        for key in required_keys:
            value = margin_data['data'].get(key, 0)
            try:
                formatted_value = "{:.2f}".format(float(value))
            except (ValueError, TypeError):
                formatted_value = value
            filtered_data[key] = formatted_value
        return filtered_data
    else:
        return {}
