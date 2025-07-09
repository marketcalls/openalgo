# api/funds.py

import json
import logging
from utils.httpx_client import get_httpx_client
from broker.indmoney.api.baseurl import get_url
from utils.logging import get_logger

logger = get_logger(__name__)

# Default response format for margin data
DEFAULT_MARGIN_RESPONSE = {
    "availablecash": "0.00",
    "collateral": "0.00",
    "m2munrealized": "0.00",
    "m2mrealized": "0.00",
    "utiliseddebits": "0.00"
}

def get_margin_data(auth_token):
    """
    Fetch margin data from Indmoney API using the provided auth token.
    
    Args:
        auth_token (str): The authorization token for Indmoney API
        
    Returns:
        dict: Formatted margin data or default values if request fails
    """
    logger.info(f"Getting margin data from Indmoney API with token: {auth_token[:10]}...")
    
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        logger.info(f"Making request to: {auth_token}")
        # Headers that exactly mimic Bruno's request to avoid Cloudflare detection
        headers = {
            'Authorization': auth_token
        }
        
        # Get the API URL from baseurl
        url = get_url("/funds")
        
        logger.info(f"Making request to: {url}")
        
        # Make the API request with standard timeout
        response = client.get(
            url, 
            headers=headers, 
            timeout=30.0
        )
        
        # Check if the request was successful
        if response.status_code != 200:
            logger.error(f"Error fetching margin data: HTTP {response.status_code} - {response.text[:200]}...")
            
            # Check if it's a Cloudflare challenge
            if response.status_code == 403 and ('cloudflare' in response.text.lower() or 'just a moment' in response.text.lower()):
                logger.warning("Cloudflare protection detected - API requires browser-based access")
                logger.warning("Consider using a headless browser solution or contacting Indmoney for API whitelisting")
                
                # Return a message indicating the limitation
                return {
                    "availablecash": "0.00",
                    "collateral": "0.00", 
                    "m2munrealized": "0.00",
                    "m2mrealized": "0.00",
                    "utiliseddebits": "0.00",
                    "sod_balance": "0.00",
                    "funds_added": "0.00",
                    "funds_withdrawn": "0.00",
                    "option_sell_balance": "0.00",
                    "future_balance": "0.00",
                    "option_buy_balance": "0.00",
                    "eq_mis_balance": "0.00",
                    "eq_cnc_balance": "0.00",
                    "eq_mtf_balance": "0.00",
                    "_error": "Cloudflare protection - requires browser access"
                }
            
            return DEFAULT_MARGIN_RESPONSE
        
        try:
            # Try to parse the JSON response
            response_data = response.json()
            logger.debug(f"Raw response from Indmoney API: {response_data}")
            
            # Check if the response indicates success
            if response_data.get('status') != 'success':
                error_msg = response_data.get('message', 'Unknown error')
                logger.error(f"API returned error: {error_msg}")
                return DEFAULT_MARGIN_RESPONSE
            
            # Extract the margin data
            data = response_data.get('data', {})
            if not data:
                logger.error("No data in API response")
                return DEFAULT_MARGIN_RESPONSE
            
            # Extract required fields from the response
            sod_balance = float(data.get('sod_balance', 0.0))
            withdrawal_balance = float(data.get('withdrawal_balance', 0.0))
            pledge_received = float(data.get('pledge_received', 0.0))
            realized_pnl = float(data.get('realized_pnl', 0.0))
            unrealized_pnl = float(data.get('unrealized_pnl', 0.0))
            
            # Calculate utilized debits (SOD balance minus withdrawal balance)
            utilised_debits = max(0, sod_balance - withdrawal_balance)
            
            # Get detailed available balances if needed
            detailed_balance = data.get('detailed_avl_balance', {})
            
            # Prepare the response in the standard format
            processed_data = {
                # Available cash is the withdrawal balance
                "availablecash": f"{withdrawal_balance:.2f}",
                
                # Collateral is the pledge received
                "collateral": f"{pledge_received:.2f}",
                
                # Unrealized P&L from the API
                "m2munrealized": f"{unrealized_pnl:.2f}",
                
                # Realized P&L from the API
                "m2mrealized": f"{realized_pnl:.2f}",
                
                # Utilized debits (SOD - withdrawal balance)
                "utiliseddebits": f"{utilised_debits:.2f}",
                
                # Additional fields that might be useful
                "sod_balance": f"{sod_balance:.2f}",
                "funds_added": f"{float(data.get('funds_added', 0.0)):.2f}",
                "funds_withdrawn": f"{float(data.get('funds_withdrawn', 0.0)):.2f}",
                
                # Detailed available balances
                "option_sell_balance": f"{float(detailed_balance.get('option_sell', 0.0)):.2f}",
                "future_balance": f"{float(detailed_balance.get('future', 0.0)):.2f}",
                "option_buy_balance": f"{float(detailed_balance.get('option_buy', 0.0)):.2f}",
                "eq_mis_balance": f"{float(detailed_balance.get('eq_mis', 0.0)):.2f}",
                "eq_cnc_balance": f"{float(detailed_balance.get('eq_cnc', 0.0)):.2f}",
                "eq_mtf_balance": f"{float(detailed_balance.get('eq_mtf', 0.0)):.2f}"
            }
            
            logger.info("Successfully processed margin data from Indmoney API")
            return processed_data
            
        except (json.JSONDecodeError, ValueError, TypeError) as parse_err:
            logger.error(f"Failed to parse API response: {str(parse_err)}")
            if 'response' in locals():
                logger.debug(f"Response content: {response.text[:500]}...")
            return DEFAULT_MARGIN_RESPONSE
            
    except Exception as e:
        logger.error(f"Unexpected error in get_margin_data: {str(e)}", exc_info=True)
        return DEFAULT_MARGIN_RESPONSE

