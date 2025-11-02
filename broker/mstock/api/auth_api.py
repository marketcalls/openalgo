import os
from utils.httpx_client import get_httpx_client
import pyotp

def mstock_login(username, password):
    """
    Logs in to mstock and returns the ugid.
    """
    try:
        url = 'https://api.mstock.trade/openapi/typea/connect/login'
        headers = {
            'X-Mirae-Version': '1',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        data = {
            'username': username,
            'password': password,
        }
        client = get_httpx_client()
        response = client.post(url, headers=headers, data=data)
        response.raise_for_status()
        response_data = response.json()
        if response_data.get('status') == 'success':
            return response_data['data'], None
        else:
            return None, response_data.get('message', 'Login failed.')
    except Exception as e:
        return None, f"An exception occurred during login: {str(e)}"

def generate_session_totp(api_key, totp_secret):
    """
    Generates a session using TOTP.
    """
    try:
        totp = pyotp.TOTP(totp_secret)
        url = 'https://api.mstock.trade/openapi/typea/session/verifytotp'
        headers = {
            'X-Mirae-Version': '1',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        data = {
            'api_key': api_key,
            'totp': totp.now(),
        }
        client = get_httpx_client()
        response = client.post(url, headers=headers, data=data)
        response.raise_for_status()
        response_data = response.json()
        if response_data.get('status') == 'success':
            return response_data['data']['access_token'], None
        else:
            return None, response_data.get('message', 'Session generation failed.')
    except Exception as e:
        return None, f"An exception occurred during session generation: {str(e)}"

def authenticate_broker_mstock():
    """
    Main function to authenticate mstock broker.
    This function will be called by the application to get the access token.
    It orchestrates the login and session generation process.
    """
    try:
        BROKER_API_KEY = os.getenv('MSTOCK_BROKER_API_KEY')
        MSTOCK_USERNAME = os.getenv('MSTOCK_USERNAME')
        MSTOCK_PASSWORD = os.getenv('MSTOCK_PASSWORD')
        MSTOCK_TOTP_SECRET = os.getenv('MSTOCK_TOTP_SECRET')

        # Step 1: Login to get ugid (and trigger OTP, which we ignore for TOTP flow)
        login_data, error = mstock_login(MSTOCK_USERNAME, MSTOCK_PASSWORD)
        if error:
            return None, error

        # Step 2: Generate session with TOTP
        access_token, error = generate_session_totp(BROKER_API_KEY, MSTOCK_TOTP_SECRET)
        if error:
            return None, error

        return access_token, None

    except Exception as e:
        return None, f"An exception occurred during mstock authentication: {str(e)}"

def mstock_callback(request):
    """
    Handles the callback from mstock. Since mstock uses a TOTP-based flow,
    this endpoint is a simple placeholder that returns a success message.
    """
    return "mstock authentication successful. You can close this window."
