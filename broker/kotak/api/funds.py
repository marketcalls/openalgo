# api/funds.py
import urllib.parse
import http.client
import json
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from the broker's API using the provided auth token."""
    # Updated for Neo API v2: session_token:::session_sid:::base_url:::access_token
    session_token, session_sid, base_url, access_token = auth_token.split(":::")
    
    # Debug logging for baseUrl
    logger.info(f"FUNDS API - Using baseUrl: {base_url}")
    
    # Extract hostname from base_url
    if base_url.startswith('https://'):
        hostname = base_url.replace('https://', '')
    else:
        hostname = base_url
    
    logger.info(f"FUNDS API - Extracted hostname: {hostname}")
    
    conn = http.client.HTTPSConnection(hostname)
    payload = 'jData=%7B%22seg%22%3A%22ALL%22%2C%22exch%22%3A%22ALL%22%2C%22prod%22%3A%22ALL%22%7D'
    
    headers = {
        'accept': 'application/json',
        'Sid': session_sid,
        'Auth': session_token,
        'neo-fin-key': 'neotradeapi',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    conn.request("POST", "/quick/user/limits", payload, headers)
    try:
        res = conn.getresponse()
        data = res.read()
        logger.info(f"{data.decode('utf-8')}")
        margin_data = json.loads(data.decode("utf-8"))

        # Process and return the margin data for Neo API v2
        if margin_data.get('stat') == 'Ok':
            processed_margin_data = {
                "availablecash": f"{float(margin_data.get('Net', 0)):.2f}",
                "collateral": f"{float(margin_data.get('CollateralValue', 0)):.2f}",
                "m2munrealized": f"{float(margin_data.get('UnrealizedMtomPrsnt', 0)):.2f}",
                "m2mrealized": f"{float(margin_data.get('RealizedMtomPrsnt', 0)):.2f}",
                "utiliseddebits": f"{float(margin_data.get('MarginUsed', 0)):.2f}"
            }
        else:
            # Return default values if API call fails
            processed_margin_data = {
                "availablecash": "0.00",
                "collateral": "0.00", 
                "m2munrealized": "0.00",
                "m2mrealized": "0.00",
                "utiliseddebits": "0.00"
            }
            
        return processed_margin_data
    except Exception as e:
        logger.error(f"Error fetching margin data: {e}")
        return {
            "availablecash": "0.00",
            "collateral": "0.00",
            "m2munrealized": "0.00", 
            "m2mrealized": "0.00",
            "utiliseddebits": "0.00"
        }
