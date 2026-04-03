import hashlib
import json
import os

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_broker(code):
    """
    Authenticate with Zebu using OAuth 2.0 flow.
    Exchanges the authorization code for an access token.
    """
    # BROKER_API_KEY format: userid:::client_id (e.g., Z56004:::Z56004_U)
    full_api_key = os.getenv("BROKER_API_KEY")
    client_id = full_api_key.split(":::")[1]  # OAuth client_id
    secret_key = os.getenv("BROKER_API_SECRET")

    try:
        # Get the shared httpx client
        client = get_httpx_client()

        # Zebu OAuth token exchange endpoint
        url = "https://go.mynt.in/NorenWClientAPI/GenAcsTok"

        # Compute checksum: SHA256(client_id + secret_key + code)
        checksum_input = f"{client_id}{secret_key}{code}"
        checksum = hashlib.sha256(checksum_input.encode()).hexdigest()

        # Prepare token exchange payload
        payload = {
            "code": code,
            "checksum": checksum,
        }

        # Convert payload to jData format
        payload_str = "jData=" + json.dumps(payload)

        # Set headers as per Zebu OAuth docs
        headers = {"Content-Type": "text/plain"}

        logger.debug(f"Zebu OAuth token exchange request to {url}")

        # Send the POST request
        response = client.post(url, content=payload_str, headers=headers)

        # Handle the response
        if response.status_code == 200:
            data = response.json()
            if data.get("stat") == "Ok" and "access_token" in data:
                logger.info("Zebu OAuth authentication successful")
                return data["access_token"], None
            else:
                error_msg = data.get("emsg", "Authentication failed. Please try again.")
                logger.error(f"Zebu OAuth auth error: {error_msg}")
                return None, error_msg
        else:
            error_msg = f"Error: {response.status_code}, {response.text}"
            logger.error(f"Zebu OAuth HTTP error: {error_msg}")
            return None, error_msg

    except Exception as e:
        logger.error(f"Zebu OAuth exception: {e}")
        return None, str(e)
