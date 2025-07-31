import os
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def authenticate_broker(request_token):
    """
    Authenticate with Paytm Money broker API.

    The authentication flow works as follows:
    1. Navigate to Paytm Money API endpoint: https://login.paytmmoney.com/merchant-login?apiKey={api_key}&state={state_key}
    2. After successful login, a request_token is returned as URL parameter to the registered redirect URL
    3. Use the request_token to generate an access_token

    Args:
        code: The request token received from the redirect URL after successful login

    Returns:
        tuple: (access_token, error_message)
            - access_token: The token to use for subsequent API calls
            - error_message: Error details if authentication fails, None on success
    """
    try:
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')

        url = 'https://developer.paytmmoney.com/accounts/v2/gettoken'
        data = {
            'api_key': BROKER_API_KEY,
            'api_secret_key': BROKER_API_SECRET,
            'request_token': request_token
        }
        headers = {'Content-Type': 'application/json'}
        client = get_httpx_client()
        response = client.post(url, json=data, headers=headers)

        if response.status_code == 200:
            response_data = response.json()
            if 'access_token' in response_data:
                logger.debug("Successfully authenticated and received access token.")
                return response_data['access_token'], None
            else:
                error_msg = "Authentication succeeded but no access token was returned."
                logger.error(error_msg)
                logger.debug(f"Full response: {response_data}")
                return None, error_msg
        else:
            # Parsing the error message from the API response
            try:
                error_detail = response.json()
                error_messages = error_detail.get('errors', [])
                detailed_error_message = "; ".join([error['message'] for error in error_messages])
                error_msg = f"API error: {detailed_error_message}" if detailed_error_message else f"Authentication failed with response: {response.text}"
            except Exception:
                error_msg = f"Authentication failed with status code {response.status_code} and non-JSON response: {response.text}"

            logger.error(f"Authentication failed with status code {response.status_code}. Error: {error_msg}")
            return None, error_msg
    except Exception:
        logger.exception("An exception occurred during authentication.")
        return None, "An unexpected error occurred during authentication."
