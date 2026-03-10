import hashlib
import json
import os

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_broker(userid, authCode):
    """
    Authenticate with AliceBlue using the new V2 vendor API.

    Returns:
        Tuple of (userSession, clientId, error_message)

    Flow:
      1. Compute SHA-256 checksum of: userId + authCode + apiSecret
      2. POST {"checkSum": checksum} to /open-api/od/v1/vendor/getUserDetails
      3. Return the userSession from the response

    Environment variables:
      BROKER_API_KEY    = App Code (appCode)
      BROKER_API_SECRET = API Secret (apiSecret)
    """
    try:
        # Fetching the necessary credentials from environment variables
        # BROKER_API_KEY   = appCode  (used for the login redirect, not needed here)
        # BROKER_API_SECRET = apiSecret (used to build the checksum)
        BROKER_API_SECRET = os.environ.get("BROKER_API_SECRET")

        if not BROKER_API_SECRET:
            logger.error("BROKER_API_SECRET not found in environment variables")
            return None, None, "API secret not set in environment variables"

        logger.debug(f"Authenticating with AliceBlue for user {userid}")

        # Step 1: Get the shared httpx client with connection pooling
        client = get_httpx_client()

        # Step 2: Generate SHA-256 checksum = hash(userId + authCode + apiSecret)
        logger.debug("Generating checksum for authentication")
        checksum_input = f"{userid}{authCode}{BROKER_API_SECRET}"
        logger.debug("Checksum input pattern: userId + authCode + apiSecret")
        checksum = hashlib.sha256(checksum_input.encode()).hexdigest()

        # Step 3: Prepare request payload matching the new API documentation
        payload = {"checkSum": checksum}

        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        # Step 4: POST to the new vendor getUserDetails endpoint
        logger.debug("Making getUserDetails request to AliceBlue API")
        url = "https://ant.aliceblueonline.com/open-api/od/v1/vendor/getUserDetails"
        response = client.post(url, json=payload, headers=headers)

        logger.debug(f"AliceBlue API response status: {response.status_code}")
        data_dict = response.json()

        # Log full response for debugging
        logger.info(f"AliceBlue API response: {json.dumps(data_dict, indent=2)}")

        # --- Parse the response ---

        # Success case: stat == "Ok" and userSession is present
        if data_dict.get("stat") == "Ok" and data_dict.get("userSession"):
            client_id = data_dict.get("clientId")
            logger.info(f"Authentication successful for user {userid} (clientId={client_id})")
            return data_dict["userSession"], client_id, None

        # Error case: stat == "Not_ok" with an error message
        if data_dict.get("stat") == "Not_ok":
            error_msg = data_dict.get("emsg", "Unknown error occurred")
            logger.error(f"API returned Not_ok: {error_msg}")
            return None, None, f"API error: {error_msg}"

        # Fallback: check for emsg in any other shape of response
        if "emsg" in data_dict and data_dict["emsg"]:
            error_msg = data_dict["emsg"]
            logger.error(f"API error: {error_msg}")
            return None, None, f"API error: {error_msg}"

        # If we got here, we couldn't find a session token
        logger.error(f"Couldn't extract userSession from response: {data_dict}")
        return (
            None,
            None,
            "Failed to extract session from response. Please check API credentials and try again.",
        )

    except json.JSONDecodeError:
        return None, None, "Invalid response format from AliceBlue API."
    except httpx.HTTPError as e:
        return None, None, f"HTTP connection error: {str(e)}"
    except Exception as e:
        return None, None, f"An exception occurred: {str(e)}"
