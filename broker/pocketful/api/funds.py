# api/funds.py

import os
import httpx
import json
from flask import session
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)



def get_margin_data(auth_token):
    """Fetch margin data from Pocketful's API using the provided auth token.
    
    The client_id is retrieved from the session where it was stored during authentication.
    """
    # For Pocketful, we need the client_id which is stored in the session after authentication
    client_id = session.get('USER_ID')
    # Pocketful's base URL and endpoint for funds
    logger.info(f"Auth token is {auth_token}")
    base_url = "https://trade.pocketful.in"
    endpoint = "/api/v2/funds/view"
    
    # Set up headers with authorization token
    headers = {
        'Authorization': f'Bearer {auth_token}',
        'Content-Type': 'application/json'
    }
    
    # If no client_id is provided, we need to get it first
    if not client_id:
        try:
            # Get the shared httpx client
            client = get_httpx_client()
            
            # Make a request to the trading_info endpoint to get client_id
            trading_info_url = f"{base_url}/api/v1/user/trading_info"
            info_response = client.get(trading_info_url, headers=headers)
            info_response.status = info_response.status_code  # Add status attribute for compatibility
            info_response.raise_for_status()  # Raise exception for non-200 status codes
            
            # Parse the response JSON
            info_data = info_response.json()
            
            if info_data.get('status') == 'success':
                client_id = info_data.get('data', {}).get('client_id')
                logger.info(f"Retrieved client_id: {client_id}")
            else:
                logger.info(f"Error fetching client_id: {info_data.get('message', 'Unknown error')}")
                return {}
        except Exception as e:
            logger.error(f"Error retrieving client_id: {e}")
            return {}
    
    # Required query parameters including client_id
    params = {
        "client_id": client_id,
        "type": "all"
    }
    
    try:
        # Construct the full URL
        url = f"{base_url}{endpoint}"
        
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Make the API request with query parameters
        response = client.get(url, headers=headers, params=params)
        response.status = response.status_code  # Add status attribute for compatibility
        response.raise_for_status()  # Raise exception for non-200 status codes
        
        # Parse the response JSON
        margin_data = response.json()
        
        logger.info(f"Funds Details: {margin_data}")
        
        # Check if the response was successful
        if margin_data.get('status') != 'success':
            logger.info(f"Error fetching margin data: {margin_data.get('message')}")
            return {}
        
        # Client ID is already used in the query parameters
        # We'll include it in the processed data for reference
        
        # Initialize values
        available_cash = 0.0
        collateral = 0.0
        net_margin = 0.0
        utilized_margin = 0.0
        span_margin = 0.0
        var_margin = 0.0
        ext_loss_margin = 0.0
        option_premium = 0.0
        
        # Extract values from Pocketful's response format
        # The values are in a list of [description, value] pairs
        values = margin_data.get('data', {}).get('values', [])
        
        # Map to find values by description
        value_map = {item[0]: float(item[1]) for item in values}
        
        # Extract specific values based on their descriptions
        available_cash = value_map.get('Available Margin', 0.0)
        collateral = (value_map.get('DP Collateral Benefit', 0.0) + 
                      value_map.get('Manual Collateral', 0.0) + 
                      value_map.get('Pool Collateral Benefit', 0.0) + 
                      value_map.get('Sar Collateral Benefit', 0.0))
        net_margin = value_map.get('Margin Used', 0.0)
        #span_margin = value_map.get('Span Margin', 0.0)
        #var_margin = value_map.get('Var Margin', 0.0)
        #ext_loss_margin = value_map.get('Extreme Loss Margin', 0.0)
        #option_premium = value_map.get('Option Credit For Sell', 0.0) + value_map.get('Premium', 0.0)
        collateral = value_map.get('Total Pledge Collateral', 0.0)
        # Calculate utilized margin from components
        utilized_margin = net_margin
        m2munrealized = value_map.get('unrealized_mtm', 0.0)
        m2mrealized = value_map.get('realized_mtm', 0.0)
        
        # Unrealized and realized M2M are not directly available in Pocketful's response
        # Use 0.0 as default or calculate from other values if needed
        
        # Construct and return the processed margin data to match expected format
        processed_margin_data = {
            "availablecash": "{:.2f}".format(available_cash),
            "collateral": "{:.2f}".format(collateral),
            "m2munrealized":"{:.2f}".format(m2munrealized),
            "m2mrealized":"{:.2f}".format(m2mrealized),   
            "utiliseddebits": "{:.2f}".format(utilized_margin),
        }
        return processed_margin_data
        
    except httpx.HTTPError as e:
        logger.error(f"API request error: {e}")
        return {}
    except (ValueError, KeyError, TypeError) as e:
        logger.error(f"Error processing margin data: {e}")
        return {}