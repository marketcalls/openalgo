# api/funds.py for Fyers

import os
import json
from typing import Dict, Any, Optional
import httpx
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def get_margin_data(auth_token: str) -> Dict[str, str]:
    """
    Fetch and process margin/funds data from Fyers' API using shared HTTP client with connection pooling.
    
    Args:
        auth_token: The authentication token for Fyers API (format: 'app_id:access_token')
        
    Returns:
        dict: Processed margin data with standardized keys:
            - availablecash: Total available balance
            - collateral: Collateral value
            - m2munrealized: Unrealized M2M
            - m2mrealized: Realized M2M
            - utiliseddebits: Utilized amount
    """
    # Initialize default response
    default_response = {
        "availablecash": "0.00",
        "collateral": "0.00",
        "m2munrealized": "0.00",
        "m2mrealized": "0.00",
        "utiliseddebits": "0.00"
    }
    
    api_key = os.getenv('BROKER_API_KEY')
    if not api_key:
        logger.error("BROKER_API_KEY environment variable not set")
        return default_response
    
    # Get shared HTTP client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'Authorization': f'{api_key}:{auth_token}',
        'Content-Type': 'application/json'
    }
    
    try:
        # Get the funds data
        response = client.get(
            'https://api-t1.fyers.in/api/v3/funds',
            headers=headers,
            timeout=30.0
        )
        response.raise_for_status()
        
        funds_data = response.json()
        logger.debug(f"Fyers funds API response: {json.dumps(funds_data, indent=2)}")
        
        if funds_data.get('code') != 200:
            error_msg = funds_data.get('message', 'Unknown error')
            logger.error(f"Error in Fyers funds API: {error_msg}")
            return default_response
        
        # Process the funds data
        processed_funds = {}
        for fund in funds_data.get('fund_limit', []):
            try:
                key = fund['title'].lower().replace(' ', '_')
                processed_funds[key] = {
                    "equity_amount": float(fund.get('equityAmount', 0)),
                    "commodity_amount": float(fund.get('commodityAmount', 0))
                }
            except (KeyError, ValueError) as e:
                logger.warning(f"Error processing fund entry: {e}")
                continue
        
        # Calculate totals with proper error handling
        try:
            # Get available balance
            balance = processed_funds.get('available_balance', {})
            balance_equity = float(balance.get('equity_amount', 0))
            balance_commodity = float(balance.get('commodity_amount', 0))
            total_balance = balance_equity + balance_commodity
            
            # Get collateral
            collateral = processed_funds.get('collaterals', {})
            collateral_equity = float(collateral.get('equity_amount', 0))
            collateral_commodity = float(collateral.get('commodity_amount', 0))
            total_collateral = collateral_equity + collateral_commodity
            
            # Get realized P&L
            pnl = processed_funds.get('realized_profit_and_loss', {})
            real_pnl_equity = float(pnl.get('equity_amount', 0))
            real_pnl_commodity = float(pnl.get('commodity_amount', 0))
            total_real_pnl = real_pnl_equity + real_pnl_commodity
            
            # Get utilized amount
            utilized = processed_funds.get('utilized_amount', {})
            utilized_equity = float(utilized.get('equity_amount', 0))
            utilized_commodity = float(utilized.get('commodity_amount', 0))
            total_utilized = utilized_equity + utilized_commodity
            
            # Format and return the response
            return {
                "availablecash": "{:.2f}".format(total_balance),
                "collateral": "{:.2f}".format(total_collateral),
                "m2munrealized": "{:.2f}".format(total_collateral),  # Using collateral as unrealized M2M
                "m2mrealized": "{:.2f}".format(total_real_pnl),
                "utiliseddebits": "{:.2f}".format(total_utilized)
            }
            
        except (ValueError, TypeError) as e:
            logger.exception("Error calculating fund totals")
            return default_response
            
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error {e.response.status_code} fetching Fyers funds: {e.response.text}")
    except httpx.RequestError as e:
        logger.error(f"Request failed: {str(e)}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Fyers API response: {str(e)}")
    except Exception as e:
        logger.exception("Unexpected error in get_margin_data")
    
    return default_response


