import os
import json
import http.client
import hashlib
from datetime import datetime

def authenticate_broker(request_token):
    try:
        # Fetching the necessary credentials from environment variables
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        
        # ICICI Direct's endpoint for session token exchange
        conn = http.client.HTTPSConnection("api.icicidirect.com")
        
        # The payload for the request
        payload = f"{{\r\n    \"SessionToken\": \"{request_token}\",\r\n    \"AppKey\": \"{BROKER_API_KEY}\"\r\n}}"
        
        # Setting the headers as specified by ICICI Direct's documentation
        headers = {
            "Content-Type": "application/json"
        }

        # Making the API request
        conn.request("GET", "/breezeapi/api/v1/customerdetails", payload, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")

        #print(data)
        
        # Processing the response
        if res.status == 200:
            response_data = json.loads(data)
            if 'Success' in response_data and 'session_token' in response_data['Success']:
                # Session token found in response data under the 'Success' key
                return response_data['Success']['session_token'], None
            else:
                # Session token not present in the response where expected
                return None, "Authentication succeeded but no session token was returned. Please check the response."
        else:
            # Handling errors from the API
            return None, f"API error: {res.reason}"
    except Exception as e:
        # Exception handling
        return None, f"An exception occurred: {str(e)}"
