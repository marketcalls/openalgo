# api/funds.py

import os
import json
import logging

try:
    from growwapi import GrowwAPI
except ImportError:
    logging.warning("growwapi package not found. Please install it using 'pip install growwapi'.")

def get_margin_data(auth_token):
    """Fetch margin data from Groww API using the provided auth token."""
    print(f"Getting margin data with token: {auth_token}...")
    
    try:
        # Initialize Groww API client
        groww = GrowwAPI(auth_token)
        
        # Get available margin details
        margin_data = groww.get_available_margin_details()
        print(f"Funds Details: {margin_data}")
        
        if not margin_data:
            print("Error fetching margin data: Empty response")
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
            print(f"Error fetching position data: {str(e)}")
            # Default to zeros if unable to fetch
            total_unrealised = 0
            total_realised = 0
        
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
            
            # Add equity and F&O specific balances for additional details
            "equity_cnc_balance": "{:.2f}".format(
                margin_data.get('equity_margin_details', {}).get('cnc_balance_available', 0)
            ),
            "equity_mis_balance": "{:.2f}".format(
                margin_data.get('equity_margin_details', {}).get('mis_balance_available', 0)
            ),
            "fno_futures_balance": "{:.2f}".format(
                margin_data.get('fno_margin_details', {}).get('future_balance_available', 0)
            ),
            "fno_option_buy_balance": "{:.2f}".format(
                margin_data.get('fno_margin_details', {}).get('option_buy_balance_available', 0)
            ),
            "fno_option_sell_balance": "{:.2f}".format(
                margin_data.get('fno_margin_details', {}).get('option_sell_balance_available', 0)
            ),
        }
        return processed_margin_data
        
    except Exception as e:
        print(f"Error in get_margin_data: {str(e)}")
        # Return an empty dictionary in case of unexpected data structure or error
        return {}
