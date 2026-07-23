# broker/hdfcsky/api/auth_api.py
#
# HDFC Sky login (browser-redirect flow):
#   1. The user is sent to  GET /oapi/v1/login?api_key=<api_key>  which hosts
#      the HDFC Securities login + 2FA + consent screens.
#   2. HDFC redirects back to the app's registered callback with a request
#      token.
#   3. We exchange it here:
#        POST /oapi/v1/access-token?api_key=<key>&request_token=<token>
#        body: {"apiSecret": "<api_secret>"}
#      -> {"accessToken": "<jwt>"}
#
# Literal field names taken verbatim from the docs' curl sample: the body key
# is `apiSecret` (camelCase) and the api_key / request_token travel as QUERY
# params, not in the body.

import os

from broker.hdfcsky.api.baseurl import get_hdfcsky_headers, get_root_url
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_broker(request_token):
    """Exchange the HDFC Sky request token for an access token.

    Returns:
        (auth_token, error_message) -- exactly one of the two is set.
    """
    try:
        api_key = os.getenv("BROKER_API_KEY")
        api_secret = os.getenv("BROKER_API_SECRET")

        if not api_key or not api_secret:
            return None, "BROKER_API_KEY / BROKER_API_SECRET are not configured in .env"
        if not request_token:
            return None, "No request token received from HDFC Sky callback"

        client = get_httpx_client()
        url = f"{get_root_url()}/oapi/v1/access-token"
        # `Authorization` is not available yet at this point; pass an empty
        # value so the mandatory User-Agent / Content-Type still go out.
        headers = get_hdfcsky_headers("", with_json=True)
        headers.pop("Authorization", None)

        response = client.post(
            url,
            headers=headers,
            params={"api_key": api_key, "request_token": request_token},
            json={"apiSecret": api_secret},
        )

        try:
            payload = response.json()
        except ValueError:
            return None, (
                f"HDFC Sky returned a non-JSON response (HTTP {response.status_code}): "
                f"{response.text[:200]}"
            )

        # Success shape: {"accessToken": "..."}; some deployments wrap it in
        # the standard {"data": {...}, "status": "success"} envelope.
        access_token = payload.get("accessToken") or payload.get("access_token")
        if not access_token and isinstance(payload.get("data"), dict):
            data = payload["data"]
            access_token = data.get("accessToken") or data.get("access_token")

        if access_token:
            return access_token, None

        message = payload.get("message") or payload.get("error") or str(payload)[:300]
        return None, f"HDFC Sky authentication failed: {message}"

    except Exception as e:
        logger.exception(f"HDFC Sky authentication error: {e}")
        return None, f"An exception occurred: {e}"
