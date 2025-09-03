import http.client
import json
import urllib.parse
from hashlib import sha256
from utils.logging import get_logger

logger = get_logger(__name__)

def authenticate_broker(api_token, api_secret, otp):
    """
    Authenticate with DefinedGe Securities using 2-step process:
    1. Login with API token/secret to get OTP token
    2. Verify OTP with auth code to get session keys
    """
    try:
        # Step 1: Login with API credentials to get OTP token
        step1_response = login_step1(api_token, api_secret)
        if not step1_response:
            return None, "Failed to initiate login"

        otp_token = step1_response.get('otp_token')
        if not otp_token:
            return None, "Failed to get OTP token"

        # Step 2: Verify OTP with auth code to get session keys
        session_response = login_step2(otp_token, otp, api_secret)
        if not session_response:
            return None, "Failed to verify OTP"

        # Check response status
        if session_response.get('stat') != 'Ok':
            error_msg = session_response.get('emsg', 'Unknown authentication error')
            return None, f"Authentication failed: {error_msg}"

        api_session_key = session_response.get('api_session_key')
        susertoken = session_response.get('susertoken')

        if not api_session_key:
            return None, "Failed to get API session key"

        # Return auth string in format expected by OpenAlgo
        auth_string = f"{api_session_key}:::{susertoken}:::{api_token}"
        return auth_string, None

    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return None, str(e)

def login_step1(api_token, api_secret):
    """Step 1: Login with API credentials"""
    try:
        conn = http.client.HTTPSConnection("signin.definedgesecurities.com")
        headers = {
            'api_secret': api_secret
        }

        url = f"/auth/realms/debroking/dsbpkc/login/{api_token}"
        conn.request("GET", url, headers=headers)

        res = conn.getresponse()
        data = res.read().decode("utf-8")

        if res.status == 200:
            return json.loads(data)
        else:
            logger.error(f"Step 1 failed: {data}")
            return None

    except Exception as e:
        logger.error(f"Step 1 error: {e}")
        return None

def login_step2(otp_token, otp, api_secret):
    """Step 2: Verify OTP with auth code to get session keys"""
    try:
        conn = http.client.HTTPSConnection("signin.definedgesecurities.com")

        # Calculate authentication code using SHA256
        auth_string = f"{otp_token}{otp}{api_secret}"
        auth_code = sha256(auth_string.encode("utf-8")).hexdigest()

        payload = {
            "otp_token": otp_token,
            "otp": otp,
            "ac": auth_code
        }

        headers = {
            'Content-Type': 'application/json'
        }

        json_payload = json.dumps(payload)
        conn.request("POST", "/auth/realms/debroking/dsbpkc/token", json_payload, headers)

        res = conn.getresponse()
        data = res.read().decode("utf-8")

        if res.status == 200:
            return json.loads(data)
        else:
            logger.error(f"Step 2 failed: {data}")
            return None

    except Exception as e:
        logger.error(f"Step 2 error: {e}")
        return None

