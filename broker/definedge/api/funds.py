# api/funds.py

import json
from utils.logging import get_logger
from utils.httpx_client import get_httpx_client

logger = get_logger(__name__)

def get_margin_data(auth_token):
    """Fetch margin data from DefinedGe Securities API using the provided auth token."""
    # Initialize with default values following OpenAlgo format
    processed_margin_data = {
        "availablecash": "0.00",
        "collateral": "0.00",
        "m2munrealized": "0.00",
        "m2mrealized": "0.00",
        "utiliseddebits": "0.00",
    }
    
    try:
        # Parse the auth token
        api_session_key, susertoken, api_token = auth_token.split(":::")
        
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()

        headers = {
            'Authorization': api_session_key,
            'Content-Type': 'application/json'
        }

        url = "https://integrate.definedgesecurities.com/dart/v1/limits"
        
        logger.info("=== FETCHING FUNDS/LIMITS FROM DEFINEDGE ===")
        response = client.get(url, headers=headers)
        
        # Log raw response for debugging
        logger.info(f"Definedge Limits API Response Status: {response.status_code}")
        logger.info(f"Definedge Limits API Raw Response: {response.text}")
        
        response.raise_for_status()  # Raise exception for error status codes
        
        response_data = response.json()
        logger.info(f"Funds Details: {json.dumps(response_data, indent=2)}")

        # Check if the response is successful - Definedge returns SUCCESS status
        if response_data.get('status') == 'SUCCESS' or 'cash' in response_data:
            # Format values to 2 decimal places
            def format_value(value):
                try:
                    return "{:.2f}".format(float(value))
                except (ValueError, TypeError):
                    return "0.00"
            
            # Map DefinedGe limit fields to OpenAlgo format based on API documentation
            # Available cash - main cash balance
            processed_margin_data["availablecash"] = format_value(response_data.get('cash', 0))
            
            # Collateral - broker collateral amount
            processed_margin_data["collateral"] = format_value(response_data.get('brokerCollateralAmount', 0))
            
            # M2M Unrealized - current unrealized MTOM (Mark to Market)
            # Combine all unrealized MTOM values from different segments
            unrealized_mtom = float(response_data.get('currentUnrealizedMtom', 0))
            if unrealized_mtom == 0:
                # Try summing up segment-specific unrealized values if main field is 0
                unrealized_mtom = (
                    float(response_data.get('currentUnrealizedMTOMDerivativeIntraday', 0)) +
                    float(response_data.get('currentUnrealizedMTOMDerivativeMargin', 0)) +
                    float(response_data.get('currentUnrealizedMTOMEquityIntraday', 0)) +
                    float(response_data.get('currentUnrealizedMTOMEquityMargin', 0)) +
                    float(response_data.get('currentUnrealizedMTOMCommodityIntraday', 0)) +
                    float(response_data.get('currentUnrealizedMTOMCommodityMargin', 0))
                )
            processed_margin_data["m2munrealized"] = format_value(unrealized_mtom)
            
            # M2M Realized - current realized P&L
            # NOTE: Definedge seems to return P&L as absolute value in limits API
            # The actual P&L might be negative (loss) but shown as positive here
            # This needs to be verified with Definedge documentation or support
            
            # Get the raw P&L value
            realized_pnl = float(response_data.get('currentRealizedPNL', 0))
            
            # Log raw values for debugging
            logger.info(f"Raw currentRealizedPNL from Definedge: {response_data.get('currentRealizedPNL', 'Not found')}")
            
            # Check if there's brokerage that might affect the P&L
            brokerage = float(response_data.get('brokerage', 0))
            logger.info(f"Brokerage: {brokerage}")
            
            if realized_pnl == 0:
                # Try summing up segment-specific realized values if main field is 0
                equity_intraday_pnl = float(response_data.get('currentRealizedPNLEquityIntraday', 0))
                derivative_intraday_pnl = float(response_data.get('currentRealizedPNLDerivativeIntraday', 0))
                
                logger.info(f"Equity Intraday PNL: {equity_intraday_pnl}")
                logger.info(f"Derivative Intraday PNL: {derivative_intraday_pnl}")
                
                realized_pnl = (
                    derivative_intraday_pnl +
                    float(response_data.get('currentRealizedPNLDerivativeMargin', 0)) +
                    equity_intraday_pnl +
                    float(response_data.get('currentRealizedPNLEquityMargin', 0)) +
                    float(response_data.get('currentRealizedPNLCommodityIntraday', 0)) +
                    float(response_data.get('currentRealizedPNLCommodityMargin', 0))
                )
            
            # IMPORTANT: Based on observation, if the position book shows -0.04 but limits shows 0.04,
            # Definedge might be returning absolute value. In production, this should be verified
            # with actual profitable trades to determine the correct sign convention.
            # For now, we'll use the value as-is from the API.
            
            logger.info(f"Final realized PNL being set: {realized_pnl}")
            logger.warning("Note: Definedge may return P&L as absolute value in limits API. Verify sign convention with actual trades.")
            
            processed_margin_data["m2mrealized"] = format_value(realized_pnl)
            
            # Utilized debits/margin - margin used
            processed_margin_data["utiliseddebits"] = format_value(response_data.get('marginUsed', 0))
            
            logger.info(f"Processed margin data: {processed_margin_data}")
            return processed_margin_data
        else:
            # Log error if status is not SUCCESS
            error_msg = response_data.get('message', 'Unknown error')
            logger.error(f"Error fetching margin data: {error_msg}")
            return {}

    except KeyError as e:
        # Return an empty dictionary in case of unexpected data structure
        logger.error(f"KeyError while processing margin data: {str(e)}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        return {}
    except Exception as e:
        # General exception handling
        logger.error(f"An exception occurred while fetching margin data: {str(e)}")
        return {}