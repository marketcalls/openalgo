import os
import json
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_pnl(entry):
    """Calculate realized and unrealized PnL for a given entry."""
    unrealized_pnl = (float(entry.get("lp", 0)) - float(entry.get("netavgprc", 0))) * float(entry.get("netqty", 0))
    realized_pnl = (float(entry.get("daysellavgprc", 0)) - float(entry.get("daybuyavgprc", 0))) * float(entry.get("daysellqty", 0))
    return realized_pnl, unrealized_pnl

def get_margin_data(auth_token):
    """Fetch margin data from Tradejini's API
    
    Args:
        auth_token (str): The authentication token
        
    Returns:
        dict: Processed margin data in OpenAlgo format
    """
    try:
        # Get API key from environment
        api_key = os.getenv('BROKER_API_SECRET')
        if not api_key:
            logger.info("Error: BROKER_API_SECRET not set")
            return {}
            
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Set up authentication header
        auth_header = f"{api_key}:{auth_token}"
        headers = {
            'Authorization': f'Bearer {auth_header}',
            'Content-Type': 'application/json'
        }
        
        # Make request to get limits
        response = client.get(
            'https://api.tradejini.com/v2/api/oms/limits',
            headers=headers
        )
        
        # Print response for debugging
        logger.info(f'Tradejini Funds Response: {response.status_code}')
        logger.info(f'Tradejini Funds Data: {response.text}')
        
        if response.status_code != 200:
            logger.info(f"Error fetching margin data: {response.text}")
            return {}
            
        data = response.json()
        
        # Check if response is valid
        if data.get('s') != 'ok' or 'd' not in data:
            logger.info(f"Invalid response format: {data}")
            return {}
            
        # Extract margin details
        margin = data['d']
        
        # Map Tradejini response to OpenAlgo format
        processed_margin_data = {
            "availablecash": "{:.2f}".format(float(margin.get('availMargin', 0))),
            "collateral": "{:.2f}".format(float(margin.get('stockCollateral', 0))),
            "m2munrealized": "{:.2f}".format(float(margin.get('unrealizedPnL', 0))),
            "m2mrealized": "{:.2f}".format(float(margin.get('realizedPnl', 0))),
            "utiliseddebits": "{:.2f}".format(float(margin.get('marginUsed', 0))),
        }
        
        return processed_margin_data
        
    except Exception as e:
        logger.info(f"Error processing margin data: {e}")
        return {}
