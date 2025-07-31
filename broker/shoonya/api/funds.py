import os
import httpx
import json
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from Shoonya's API using the provided auth token."""
    
    # Fetch UserID and AccountID from environment variables
    userid = os.getenv('BROKER_API_KEY')
    userid = userid[:-2]  # Trim the last two characters
    actid = userid  # Assuming AccountID is the same as UserID

    # Prepare the payload for the request
    data = {
        "uid": userid,  # User ID
        "actid": actid  # Account ID
    }

    # Prepare the jData payload with the authentication token (jKey)
    payload_str = "jData=" + json.dumps(data) + "&jKey=" + auth_token

    # Get the shared httpx client
    client = get_httpx_client()

    # Set headers
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    url = "https://api.shoonya.com/NorenWClientTP/Limits"

    # Send the POST request to Shoonya's API
    response = client.post(url, content=payload_str, headers=headers)

    # Parse the response
    margin_data = json.loads(response.text)

    logger.info(f"Funds Details: {margin_data}")

    # Check if the request was successful
    if margin_data.get('stat') != 'Ok':
        # Log the error or return an empty dictionary to indicate failure
        logger.info(f"Error fetching margin data: {margin_data.get('emsg')}")
        return {}

    try:
        # Calculate total_available_margin as the sum of 'cash' and 'payin'
        total_available_margin = float(margin_data.get('cash',0)) + float(margin_data.get('payin',0)) - float(margin_data.get('marginused',0))
        total_collateral = float(margin_data.get('brkcollamt',0))
        total_used_margin = float(margin_data.get('marginused',0))
        total_realised = -float(margin_data.get('rpnl',0))
        total_unrealised = float(margin_data.get('urmtom',0))

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
