import httpx
import os
import requests
import hashlib
from utils.httpx_client import get_httpx_client

def authenticate_broker(request_token):
    try:
        # Get the shared httpx client
        client = get_httpx_client()
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

        #SESSION_URL = "https://xts.compositedge.com/interactive/user/session"
        response = client.post("https://xts.compositedge.com/interactive/user/session", json=payload, headers=headers)

  
        if response.status_code == 200:
            result = response.json()
            if result.get('type') == 'success':
                token = result['result']['token']
                print(f"Auth Token: {token}")
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
        return None, f"Error during authentication: {str(e)}"

def get_feed_token():
    try:
        # Fetch credentials for feed token
        BROKER_API_KEY_MARKET = os.getenv('BROKER_API_KEY_MARKET')
        BROKER_API_SECRET_MARKET = os.getenv('BROKER_API_SECRET_MARKET')

        # Construct payload for feed token request
        feed_payload = {
            "secretKey": BROKER_API_SECRET_MARKET,
            "appKey": BROKER_API_KEY_MARKET,
            "source": "WebAPI"
        }

        feed_headers = {
            'Content-Type': 'application/json'
        }

        # Get feed token
        feed_url = "https://xts.compositedge.com/apibinarymarketdata/auth/login"
        client = get_httpx_client()
        feed_response = client.post(feed_url, json=feed_payload, headers=feed_headers)

        feed_token = None
        if feed_response.status_code == 200:
            feed_result = feed_response.json()
            if feed_result.get("type") == "success":
                feed_token = feed_result["result"].get("token")
                print(f"Feed Token: {feed_token}")
            else:
                return None, "Feed token request failed. Please check the response."
        else:
            feed_error_detail = feed_response.json()
            feed_error_message = feed_error_detail.get('description', 'Feed token request failed. Please try again.')
            return None, f"API Error (Feed): {feed_error_message}"
        
        return feed_token, None
    except Exception as e:
        return None, f"An exception occurred: {str(e)}"


def authenticate_and_get_feed_token(request_token):
    auth_token, auth_error = authenticate_broker(request_token)
    if auth_error:
        return auth_token, None, auth_error
    feed_token, feed_error = get_feed_token()
    if feed_error:
        return auth_token, feed_token, feed_error
    
    return auth_token, feed_token, None
