# api/funds.py

import json
from utils.logging import get_logger
from utils.httpx_client import get_httpx_client

logger = get_logger(__name__)

def get_margin_data(auth_token):
    """Fetch margin data from DefinedGe Securities API using the provided auth token."""
    # Initialize with default values following OpenAlgo format (like AliceBlue)
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
        
        logger.debug(f"Making limits request to DefinedGe API")
        response = client.get(url, headers=headers)
        response.raise_for_status()  # Raise exception for error status codes
        
        response_data = response.json()
        logger.debug(f"Funds Details: {json.dumps(response_data, indent=2)}")

        # Check if the response is successful
        if response_data.get('stat') == 'Ok' or response_data.get('status') == '200' or 'cash' in response_data:
            # Format values to 2 decimal places like Angel and AliceBlue
            def format_value(value):
                try:
                    return "{:.2f}".format(float(value))
                except (ValueError, TypeError):
                    return "0.00"
            
            # Map DefinedGe margin fields to OpenAlgo format
            # Using same field names as Angel/AliceBlue
            processed_margin_data["availablecash"] = format_value(response_data.get('cash', response_data.get('net', 0)))
            processed_margin_data["collateral"] = format_value(response_data.get('collateralvalue', response_data.get('collateral', 0)))
            processed_margin_data["m2munrealized"] = format_value(response_data.get('unrealizedMtomPrsnt', response_data.get('m2munrealized', 0)))
            processed_margin_data["m2mrealized"] = format_value(response_data.get('realizedMtomPrsnt', response_data.get('m2mrealized', 0)))
            processed_margin_data["utiliseddebits"] = format_value(response_data.get('marginUsed', response_data.get('utiliseddebits', response_data.get('cncMarginUsed', 0))))
            
            return processed_margin_data
        else:
            # Log error if status is not OK
            error_msg = response_data.get('emsg', response_data.get('message', 'Unknown error'))
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