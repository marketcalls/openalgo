import requests
import hashlib
import json
import os

def sha256_hash(text):
    """Generate SHA256 hash."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def authenticate_broker(userid, password, totp_code):
    """
    Authenticate with Firstock and return the auth token.
    """
    # Get the Firstock API key and other credentials from environment variables
    api_secretkey = os.getenv('BROKER_API_SECRET')
    vendor_code = os.getenv('BROKER_API_KEY')

    try:
        # Firstock API login URL
        url = "https://connect.thefirstock.com/api/V4/login"

        # Prepare login payload
        payload = {
            "userId": userid,
            "password": sha256_hash(password),  # SHA256 hashed password
            "TOTP": totp_code,
            "vendorCode": vendor_code,
            "apiKey": api_secretkey
        }

        # Set headers for the API request
        headers = {
            'Content-Type': 'application/json'
        }

        # Send the POST request to Firstock's API
        response = requests.post(url, json=payload, headers=headers)

        # Handle the response
        if response.status_code == 200:
            data = response.json()
            if data['status'] == "success":
                return data['data']['susertoken'], None  # Return the token on success
            else:
                # Handle error response
                error_msg = data.get('error', {}).get('message', 'Authentication failed. Please try again.')
                return None, error_msg
        else:
            return None, f"Error: {response.status_code}, {response.text}"

    except Exception as e:
        return None, str(e)