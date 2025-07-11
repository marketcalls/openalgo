# api/funds.py

import os
import json
import httpx
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data directly from Groww API using the provided auth token."""
    logger.info(f"Getting margin data with token: {auth_token}...")
    
    try:
        # Define the API endpoint for user margin details
        url = "https://api.groww.in/v1/margins/detail/user"
        
        # Set up headers with authentication token
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {auth_token}'
        }
        
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        # Make the API request using the shared client
        response = client.get(url, headers=headers)
        
        # Check if the request was successful
        if response.status_code != 200:
            logger.error(f"Error fetching margin data: HTTP {{response.status_code}} - {response.text}")
            return {}
        
        # Parse the JSON response
        response_data = response.json()
        logger.info(f"Funds Details: {response_data}")
        
        # Check if the response was successful according to Groww's status field
        if response_data.get('status') != 'SUCCESS':
            logger.info(f"Error fetching margin data: {response_data.get('status')}")
            return {}
        
        # Extract the margin data from the payload
        margin_data = response_data.get('payload', {})
        
        if not margin_data:
            logger.error("Error fetching margin data: Empty payload")
            return {}
            
        # Create position data structure to calculate P&L
        # For Groww, we need to get positions separately if needed for P&L
        # This is a placeholder for when position API integration is added
        total_unrealised = 0
        total_realised = 0
        
        try:
            # Get positions or P&L data if available
            # This would be implemented when adding position support
            pass
        except Exception as e:
            logger.error(f"Error fetching position data: {e}")
            # Default to zeros if unable to fetch
            total_unrealised = 0
            total_realised = 0
        
        # Extract equity and F&O margin details
        equity_margin_details = margin_data.get('equity_margin_details', {})
        fno_margin_details = margin_data.get('fno_margin_details', {})
        
        # Construct and return the processed margin data in the standard format
        # Map Groww API response fields to the expected structure
        processed_margin_data = {
            # Use clear_cash as available cash
            "availablecash": "{:.2f}".format(margin_data.get('clear_cash', 0)),
            
            # Use collateral_available for collateral
            "collateral": "{:.2f}".format(margin_data.get('collateral_available', 0)),
            
            # Use calculated or fetched unrealized P&L
            "m2munrealized": "{:.2f}".format(total_unrealised),
            
            # Use calculated or fetched realized P&L
            "m2mrealized": "{:.2f}".format(total_realised),
            
            # Use net_margin_used for utilized debits
            "utiliseddebits": "{:.2f}".format(margin_data.get('net_margin_used', 0)),
            
            # Additional Groww-specific fields that might be useful
            "brokerage_and_charges": "{:.2f}".format(margin_data.get('brokerage_and_charges', 0)),
            "adhoc_margin": "{:.2f}".format(margin_data.get('adhoc_margin', 0)),
            
            # Add equity and F&O specific balances for additional details
            "equity_cnc_balance": "{:.2f}".format(
                equity_margin_details.get('cnc_balance_available', 0)
            ),
            "equity_mis_balance": "{:.2f}".format(
                equity_margin_details.get('mis_balance_available', 0)
            ),
            "fno_futures_balance": "{:.2f}".format(
                fno_margin_details.get('future_balance_available', 0)
            ),
            "fno_option_buy_balance": "{:.2f}".format(
                fno_margin_details.get('option_buy_balance_available', 0)
            ),
            "fno_option_sell_balance": "{:.2f}".format(
                fno_margin_details.get('option_sell_balance_available', 0)
            ),
        }
        return processed_margin_data
        
    except Exception as e:
        logger.error(f"Error in get_margin_data: {e}")
        # Return an empty dictionary in case of unexpected data structure or error
        return {}
