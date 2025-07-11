# api/funds.py

import os
import json
import httpx
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def get_margin_data(auth_token):
    """Fetch margin data from Alice Blue's API using the provided auth token and shared connection pooling."""
    # Initialize processed data dictionary
    processed_margin_data = {
        "availablecash": "0.00",
        "collateral": "0.00",
        "m2munrealized": "0.00",
        "m2mrealized": "0.00",
        "utiliseddebits": "0.00",
    }
    
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        url = "https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/limits/getRmsLimits"
        headers = {
            'Authorization': f'Bearer {auth_token}',
        }
        
        # Make the API request using the shared client
        logger.debug(f"Making getRmsLimits request to AliceBlue API")
        response = client.get(url, headers=headers)
        response.raise_for_status()
        
        margin_data = response.json()
        logger.debug(f"Funds Details: {json.dumps(margin_data, indent=2)}")
        
        # Process the margin data
        for item in margin_data:
            if item.get('stat') == 'Not_Ok':
                # Log the error or return an empty dictionary to indicate failure
                logger.error(f"Error fetching margin data: {item.get('emsg', 'Unknown error')}")
                return {}

            # Accumulate values
            processed_margin_data["availablecash"] = "{:.2f}".format(float(item.get('net', 0)))
            processed_margin_data["collateral"] = "{:.2f}".format(float(item.get('collateralvalue', 0)))
            processed_margin_data["m2munrealized"] = "{:.2f}".format(float(item.get('unrealizedMtomPrsnt', 0)))
            processed_margin_data["m2mrealized"] = "{:.2f}".format(float(item.get('realizedMtomPrsnt', 0)))
            processed_margin_data["utiliseddebits"] = "{:.2f}".format(float(item.get('cncMarginUsed', 0)))

        return processed_margin_data
    except KeyError as e:
        # Return an empty dictionary in case of unexpected data structure
        logger.error(f"KeyError while processing margin data: {str(e)}")
        return {}
    except httpx.HTTPError as e:
        # Handle HTTPX connection errors
        logger.error(f"HTTP connection error: {str(e)}")
        return {}
    except Exception as e:
        # General exception handling
        logger.error(f"An exception occurred while fetching margin data: {str(e)}")
        return {}