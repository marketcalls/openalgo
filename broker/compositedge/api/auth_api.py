import os
import requests
import hashlib

def authenticate_broker(request_token):
    try:
        # Fetching the necessary credentials from environment variables
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')

        
        # Make POST request to get the final token
        payload = {
            "appKey": BROKER_API_KEY,
            "secretKey": BROKER_API_SECRET,
            "accessToken": request_token
        }
        
        headers = {
            'Content-Type': 'application/json'
        }

        SESSION_URL = "https://xts.compositedge.com/interactive/user/session"
        response = requests.post(SESSION_URL, json=payload, headers=headers)

  
        if response.status_code == 200:
            result = response.json()
            if result.get('type') == 'success':
                token = result['result']['token']
                return token, None
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
