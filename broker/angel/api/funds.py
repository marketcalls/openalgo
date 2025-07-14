# api/funds.py

import os
import json
from flask import session
from utils.httpx_client import get_httpx_client
from utils.broker_credentials import get_broker_credentials
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from the broker's API using the provided auth token."""
    # Get credentials from database for current user
    user_id = session.get('user')
    broker_creds = None
    
    if user_id:
        broker_creds = get_broker_credentials(user_id, 'angel')
    
    # Use database credentials or fall back to environment
    if broker_creds and broker_creds.get('api_key'):
        api_key = broker_creds.get('api_key')
        logger.info(f"Using database API key for Angel funds API")
    else:
        api_key = os.getenv('BROKER_API_KEY')
        logger.info(f"Using environment API key for Angel funds API")
    
    if not api_key:
        logger.error("No API key available for Angel funds API")
        return {}
    
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
