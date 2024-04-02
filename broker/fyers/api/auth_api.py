import os
import requests
import hashlib

def authenticate_broker(request_token):
    try:
        # Fetching the necessary credentials from environment variables
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        
        # Fyers's endpoint for session token exchange
        url = 'https://api-t1.fyers.in/api/v3/validate-authcode'
        
        # Generating the checksum as a SHA-256 hash of concatenated api_key, and api_secret
        checksum_input = f"{BROKER_API_KEY}:{BROKER_API_SECRET}"
        appIdHash = hashlib.sha256(checksum_input.encode('utf-8')).hexdigest()
        
        # The payload for the POST request
        payload = {
            'grant_type': 'authorization_code',
            'appIdHash': appIdHash,
            'code': request_token
        }

        # Setting the headers as specified by Fyers's documentation
        headers = {'Content-Type': 'application/json'}
        
        # Performing the POST request with json=payload
        response = requests.post(url, headers=headers, json=payload)
        print(f"The response is {response}")
        if response.status_code == 200:
            # Success response from Fyers
            response_data = response.json()
            if response_data['s'] == 'ok':
                # Access token found in response data
                return response_data.get('access_token'), None
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
