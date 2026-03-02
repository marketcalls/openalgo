import os

from broker.rmoney.baseurl import HOSTLOOKUP_URL, INTERACTIVE_URL, MARKET_DATA_URL
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_host_lookup():
    """Call HostLookup API to get UniqueKey and ConnectionString."""
    try:
        client = get_httpx_client()
        payload = {
            "AccessPassword": "2021HostLookUpAccess",
            "version": "interactive_1.0.1",
        }
        headers = {"Content-Type": "application/json"}
        response = client.post(HOSTLOOKUP_URL, json=payload, headers=headers)

        if response.status_code == 200:
            result = response.json()
            if result.get("type") == "success":
                unique_key = result["result"]["UniqueKey"]
                connection_string = result["result"].get("connectionString")
                return unique_key, connection_string, None
            else:
                desc = result.get("description", "Unknown error")
                return None, None, f"HostLookup failed: {desc}"
        else:
            return None, None, f"HostLookup error: HTTP {response.status_code}"
    except Exception as e:
        return None, None, f"HostLookup exception: {str(e)}"


def authenticate_broker(request_token):
    """Authenticate with RMoney XTS using token from OAuth callback.

    For RMoney, the XTS OAuth third-party login already returns the full session
    with auth token. This function is kept for compatibility with the plugin system
    and for non-OAuth authentication flows.
    """
    try:
        # The request_token from OAuth IS the final auth token
        auth_token = request_token

        # Get feed token for market data
        feed_token, user_id, feed_error = get_feed_token()
        if feed_error:
            return auth_token, None, None, f"Feed token error: {feed_error}"

        return auth_token, feed_token, user_id, None

    except Exception as e:
        return None, None, None, f"Error during authentication: {str(e)}"


def get_feed_token():
    try:
        BROKER_API_KEY_MARKET = os.getenv("BROKER_API_KEY_MARKET")
        BROKER_API_SECRET_MARKET = os.getenv("BROKER_API_SECRET_MARKET")

        feed_payload = {
            "secretKey": BROKER_API_SECRET_MARKET,
            "appKey": BROKER_API_KEY_MARKET,
            "source": "WebAPI",
        }

        feed_headers = {"Content-Type": "application/json"}

        feed_url = f"{MARKET_DATA_URL}/auth/login"
        client = get_httpx_client()
        feed_response = client.post(feed_url, json=feed_payload, headers=feed_headers)

        feed_token = None
        user_id = None
        if feed_response.status_code == 200:
            feed_result = feed_response.json()
            if feed_result.get("type") == "success":
                feed_token = feed_result["result"].get("token")
                user_id = feed_result["result"].get("userID")
                logger.info(f"Feed Token: {feed_token}")
            else:
                return None, None, "Feed token request failed. Please check the response."
        else:
            feed_error_detail = feed_response.json()
            feed_error_message = feed_error_detail.get(
                "description", "Feed token request failed. Please try again."
            )
            return None, None, f"API Error (Feed): {feed_error_message}"

        return feed_token, user_id, None
    except Exception as e:
        return None, None, f"An exception occurred: {str(e)}"
