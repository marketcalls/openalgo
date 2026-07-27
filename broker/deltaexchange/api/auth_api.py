import os

from broker.deltaexchange.api.baseurl import BASE_URL, get_auth_headers, get_url
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_broker(code):
    """
    Authenticate with Delta Exchange using API Key + Secret (HMAC-SHA256).

    Delta Exchange does NOT use an OAuth flow — credentials are provided once
    via environment variables.  This function validates that both vars are
    present and then makes a signed GET /v2/profile call to confirm the key
    is valid and active.

    Args:
        code: Not used for Delta Exchange (kept for interface compatibility).

    Returns:
        (api_key, None)         on success
        (None, error_message)   on failure
    """
    try:
        api_key = os.getenv("BROKER_API_KEY", "").strip()
        api_secret = os.getenv("BROKER_API_SECRET", "").strip()

        if not api_key:
            return None, "BROKER_API_KEY is not set in environment variables"
        if not api_secret:
            return None, "BROKER_API_SECRET is not set in environment variables"

        # Verify credentials with a live signed request to GET /v2/profile
        path = "/v2/profile"
        headers = get_auth_headers(
            method="GET",
            path=path,
            query_string="",
            payload="",
            api_key=api_key,
            api_secret=api_secret,
        )

        url = get_url(path)
        client = get_httpx_client()

        logger.info("Verifying Delta Exchange credentials via GET /v2/profile")
        response = client.get(url, headers=headers)

        logger.debug(f"Profile response status: {response.status_code}")
        logger.debug(f"Profile response body: {response.text}")

        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                user = data.get("result", {})
                logger.info(
                    f"Delta Exchange authentication successful for user: "
                    f"{user.get('email', 'unknown')}"
                )
                return api_key, None
            else:
                error = data.get("error", {})
                msg = f"Delta Exchange API error: {error}"
                logger.error(msg)
                return None, msg

        elif response.status_code == 401:
            msg = "Invalid API key or signature — check BROKER_API_KEY and BROKER_API_SECRET"
            logger.error(msg)
            return None, msg

        elif response.status_code == 403:
            msg = (
                "Request forbidden by Delta Exchange CDN. "
                "This may be an IP whitelist issue — verify your IP is whitelisted "
                "for this API key in the Delta Exchange dashboard."
            )
            logger.error(msg)
            return None, msg

        else:
            msg = f"Unexpected HTTP {response.status_code} from Delta Exchange: {response.text}"
            logger.error(msg)
            return None, msg

    except Exception as e:
        msg = f"An exception occurred during Delta Exchange authentication: {str(e)}"
        logger.exception(msg)
        return None, msg
