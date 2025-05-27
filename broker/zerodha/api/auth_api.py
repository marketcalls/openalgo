import os
import hashlib
import json
from utils.httpx_client import get_httpx_client

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


        
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        # Setting the headers as specified by Zerodha's documentation
        headers = {
            'X-Kite-Version': '3'
            }
        
        try:
            # Performing the POST request using the shared client
            response = client.post(
                url,
                headers=headers,
                data=data,
                )
            response.raise_for_status()  # Raises an exception for 4XX/5XX responses
            
            response_data = response.json()
            if 'data' in response_data and 'access_token' in response_data['data']:
                # Access token found in response data
                return response_data['data']['access_token'], None
            else:
                # Access token not present in the response
                return None, "Authentication succeeded but no access token was returned. Please check the response."
                
        except Exception as e:
            # Handle HTTP errors and timeouts
            error_message = str(e)
            try:
                if hasattr(e, 'response') and e.response is not None:
                    error_detail = e.response.json()
                    error_message = error_detail.get('message', str(e))
            except:
                pass
                
            return None, f"API error: {error_message}"
    except Exception as e:
        # Exception handling
        return None, f"An exception occurred: {str(e)}"
