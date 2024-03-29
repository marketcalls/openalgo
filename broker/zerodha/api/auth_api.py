import os
import requests
import hashlib

def authenticate_broker(request_token):
    try:
        # Fetching the necessary credentials from environment variables
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        
        # Zerodha's endpoint for session token exchange
        url = 'https://api.kite.trade/session/token'
        
        # Generating the checksum as a SHA-256 hash of concatenated api_key, request_token, and api_secret
        checksum_input = f"{BROKER_API_KEY}{request_token}{BROKER_API_SECRET}"
        checksum = hashlib.sha256(checksum_input.encode()).hexdigest()
        
        # The payload for the POST request
        data = {
            'api_key': BROKER_API_KEY,
            'request_token': request_token,
            'checksum': checksum
        }


        
        # Setting the headers as specified by Zerodha's documentation
        headers = {
            'X-Kite-Version': '3'
        }
        
        # Performing the POST request
        response = requests.post(url, headers=headers, data=data)
        if response.status_code == 200:
            # Success response from Zerodha
            response_data = response.json()
            if 'data' in response_data and 'access_token' in response_data['data']:
                # Access token found in response data
                return response_data['data']['access_token'], None
            else:
                # Access token not present in the response
                return None, "Authentication succeeded but no access token was returned. Please check the response."
        else:
            # Handling errors from the API
            error_detail = response.json()
            error_message = error_detail.get('message', 'Authentication failed. Please try again.')
            return None, f"API error: {error_message}"
    except Exception as e:
        # Exception handling
        return None, f"An exception occurred: {str(e)}"
