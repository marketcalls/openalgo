import httpx
import hashlib
import json
import os
from utils.httpx_client import get_httpx_client

def sha256_hash(text):
    """Generate SHA256 hash."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def authenticate_broker(userid, password, totp_code):
    """
    Authenticate with Zebu and return the auth token using httpx with connection pooling.
    """
    # Get the Zebu API key and other credentials from environment variables
    api_secretkey = os.getenv('BROKER_API_SECRET')
    vendor_code = os.getenv('BROKER_API_KEY')
    imei = '1234567890abcdef' # Default IMEI if not provided

    try:
        # Get the shared httpx client
        client = get_httpx_client()

        # Zebu API login URL
        url = "https://go.mynt.in/NorenWClientTP/QuickAuth"

        # Prepare login payload
        payload = {
            "uid": userid,  # User ID
            "pwd": sha256_hash(password),  # SHA256 hashed password
            "factor2": totp_code,  # PAN or TOTP or DOB (second factor)
            "apkversion": "1.0.8",  # API version (as per Zebu's requirement)
            "appkey": sha256_hash(f"{userid}|{api_secretkey}"),  # SHA256 of uid and API key
            "imei": imei,  # IMEI or MAC address
            "vc": vendor_code,  # Vendor code
            "source": "API"  # Source of login request
        }

        # Convert payload to string with 'jData=' prefix
        payload_str = "jData=" + json.dumps(payload)

        # Set headers for the API request
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        # Send the POST request to Zebu's API using httpx client
        response = client.post(url, content=payload_str, headers=headers)

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        # Handle the response
        if response.status_code == 200:
            data = response.json()
            if data['stat'] == "Ok":
                return data['susertoken'], None  # Return the token on success
            else:
                return None, data.get('emsg', 'Authentication failed. Please try again.')
        else:
            return None, f"Error: {response.status_code}, {response.text}"

    except Exception as e:
        return None, str(e)