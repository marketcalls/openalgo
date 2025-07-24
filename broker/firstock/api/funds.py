import json
import os
from utils.logging import get_logger
from utils.httpx_client import get_httpx_client

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """
    Get margin/limit data from Firstock using shared httpx client with connection pooling.
    
    Args:
        auth_token (str): Authentication token from Firstock login
        
    Returns:
        dict: Processed margin data in standardized format
    """
    try:
        # Get user ID from environment variable and trim the last 4 characters
        userid = os.getenv('BROKER_API_KEY')
        if not userid:
            logger.error("BROKER_API_KEY not found in environment variables")
            return {}
            
        userid = userid[:-4]  # Trim the last 4 characters

        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        # Firstock API URL for getting limits
        url = "https://api.firstock.in/V1/limit"

        # Prepare payload
        payload = {
            "jKey": auth_token,
            "userId": userid
        }

        # Set headers
        headers = {
            'Content-Type': 'application/json'
        }

        logger.info(f"Fetching margin data for user: {userid}")

        # Send POST request using shared httpx client
        response = client.post(url, json=payload, headers=headers, timeout=30)
        
        # Add status attribute for compatibility with existing codebase
        response.status = response.status_code

        # Handle the response
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == "success":
                margin_data = data.get('data', {})
                
                # Calculate total_available_margin as the sum of 'cash' and 'payin'
                cash = float(margin_data.get('cash', 0))
                payin = float(margin_data.get('payin', 0))
                margin_used = float(margin_data.get('marginused', 0))
                total_available_margin = cash + payin - margin_used
                
                total_collateral = float(margin_data.get('brkcollamt', 0))
                total_used_margin = margin_used
                
                # Construct and return the processed margin data in same format as Shoonya
                processed_margin_data = {
                    "availablecash": "{:.2f}".format(total_available_margin),
                    "collateral": "{:.2f}".format(total_collateral),
                    "m2munrealized": "0.00",  # Not provided by Firstock API
                    "m2mrealized": "0.00",    # Not provided by Firstock API
                    "utiliseddebits": "{:.2f}".format(total_used_margin)
                }
                
                logger.info("Successfully fetched and processed margin data")
                return processed_margin_data
            else:
                error_msg = data.get('error', {}).get('message', 'Unknown error')
                logger.error(f"API error fetching margin data: {error_msg}")
                return {}
        else:
            logger.error(f"HTTP error {response.status_code}: {response.text}")
            return {}

    except Exception as e:
        if "timeout" in str(e).lower():
            logger.error("Request timeout while fetching margin data")
            return {}
        elif "connection" in str(e).lower():
            logger.error("Connection error while fetching margin data")
            return {}
        else:
            logger.error(f"Unexpected error processing margin data: {e}")
            return {}
