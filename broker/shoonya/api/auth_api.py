import hashlib
import json
import os

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_broker(code):
    """
    Authenticate with Shoonya using the new GenAcsTok flow.
    Exchanges the code for an access token.
    """
    try:
        # BROKER_API_KEY format: userid:::client_id
        full_api_key = os.getenv("BROKER_API_KEY")
        if not full_api_key or ":::" not in full_api_key:
            return None, "BROKER_API_KEY must be in format userid:::client_id"
        userid = full_api_key.split(":::")[0]  # Noren user id
        client_id = full_api_key.split(":::")[1]  # appKey / client_id
        secret_key = os.getenv("BROKER_API_SECRET")
        if not secret_key:
            return None, "BROKER_API_SECRET is required"

        # Get the shared httpx client
        client = get_httpx_client()

        # Shoonya GenAcsTok endpoint
        url = "https://api.shoonya.com/NorenWClientAPI/GenAcsTok"

        # Compute checksum: SHA-256(appKey + secretKey + code)
        checksum_input = f"{client_id}{secret_key}{code}"
        checksum = hashlib.sha256(checksum_input.encode()).hexdigest()

        # Prepare token exchange payload. Shoonya's GenAcsTok requires the
        # uid field; without it the server returns INVALID_VERIFIER even with
        # a correct checksum (matches Finvasia's NorenRestApiOAuth.getAccessToken).
        payload = {
            "code": code,
            "checksum": checksum,
            "uid": userid,
        }

        # Convert payload to jData format
        payload_str = "jData=" + json.dumps(payload)

        # Set headers
        headers = {"Content-Type": "text/plain"}

        logger.debug(f"Shoonya GenAcsTok request to {url}")

        # Send the POST request
        response = client.post(url, content=payload_str, headers=headers)

        # Handle the response
        if response.status_code == 200:
            data = response.json()
            # GenAcsTok success returns the access_token; it is not guaranteed
            # to carry stat == "Ok", so key the success on access_token presence
            # (matches Finvasia's NorenRestApiOAuth.getAccessToken).
            if "access_token" in data:
                logger.info("Shoonya authentication successful")
                return data["access_token"], None
            else:
                error_msg = data.get("emsg", "Authentication failed. Please try again.")
                logger.error(f"Shoonya auth error: {error_msg}")
                return None, error_msg
        else:
            error_msg = f"Error: {response.status_code}, {response.text}"
            logger.error(f"Shoonya HTTP error: {error_msg}")
            return None, error_msg

    except Exception as e:
        logger.error(f"Shoonya auth exception: {e}")
        return None, str(e)
