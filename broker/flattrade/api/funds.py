import os
import httpx
import json
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_pnl(entry):
    """Calculate realized and unrealized PnL for a given entry."""
    # Use broker-provided values directly for more accurate calculation
    unrealized_pnl = float(entry.get("urmtom", 0))
    realized_pnl = float(entry.get("rpnl", 0))
    
    # Fallback calculation if broker values aren't available
    if unrealized_pnl == 0 and float(entry.get("netqty", 0)) != 0:
        price_factor = float(entry.get("prcftr", 1))
        unrealized_pnl = (float(entry.get("lp", 0)) - float(entry.get("netavgprc", 0))) * float(entry.get("netqty", 0)) * price_factor
    
    return realized_pnl, unrealized_pnl

def fetch_data(endpoint, payload, headers, client):
    """Send a POST request and return the parsed JSON response using httpx."""
    url = f"https://piconnect.flattrade.in{endpoint}"
    response = client.post(url, content=payload, headers=headers)
    return response.json()

def get_margin_data(auth_token):
    """Fetch and process margin and position data."""
    full_api_key = os.getenv('BROKER_API_KEY')
    userid = full_api_key.split(':::')[0]
    actid = userid

    # Prepare payload
    data = {"uid": userid, "actid": actid}
    payload = f"jData={json.dumps(data)}&jKey={auth_token}"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    # Get the shared httpx client
    client = get_httpx_client()

    # Fetch margin data
    margin_data = fetch_data("/PiConnectTP/Limits", payload, headers, client)
    
    # Check if the request was successful
    if margin_data.get('stat') != 'Ok':
        # Log the error or return an empty dictionary to indicate failure
        logger.info(f"Error fetching margin data: {margin_data.get('emsg')}")
        return {}

    # Fetch position data
    position_data = fetch_data("/PiConnectTP/PositionBook", payload, headers, client)
    
    total_realised = 0
    total_unrealised = 0

    # Process position data if it's a list
    if isinstance(position_data, list):
        for entry in position_data:
            realized_pnl, unrealized_pnl = calculate_pnl(entry)
            total_realised += realized_pnl
            total_unrealised += unrealized_pnl

    try:
        # Calculate total_available_margin as the sum of 'cash' and 'payin'
        total_available_margin = float(margin_data.get('cash',0)) + float(margin_data.get('payin',0)) - float(margin_data.get('marginused',0))
        total_collateral = float(margin_data.get('brkcollamt',0))
        total_used_margin = float(margin_data.get('marginused',0))

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": "{:.2f}".format(total_available_margin),
            "collateral": "{:.2f}".format(total_collateral),
            "m2munrealized": "{:.2f}".format(total_unrealised),
            "m2mrealized": "{:.2f}".format(total_realised),
            "utiliseddebits": "{:.2f}".format(total_used_margin),
        }
        return processed_margin_data
    except KeyError as e:
        # Log the exception and return an empty dictionary if there's an unexpected error
        logger.error(f"Error processing margin data: {e}")
        return {}
