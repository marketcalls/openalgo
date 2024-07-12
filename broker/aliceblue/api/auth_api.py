import os
import hashlib
import json
import http.client


def authenticate_broker(userid, encKey):
    try:
        # Fetching the necessary credentials from environment variables
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        
        conn = http.client.HTTPSConnection("ant.aliceblueonline.com")

        # Generating the checksum as a SHA-256 hash of concatenated api_key, request_token, and api_secret
        checksum_input = f"{userid}{BROKER_API_SECRET}{encKey}"
        checksum = hashlib.sha256(checksum_input.encode()).hexdigest()

        payload_session = json.dumps({
                "userId": userid,
                "userData": checksum
                })
        headers = {
                'Content-Type': 'application/json'
            }
        
        conn.request("POST", "/rest/AliceBlueAPIService/api/customer/getUserSID", payload_session, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")
        data_dict = json.loads(data)
        
        
        if data_dict['stat']== 'Ok' or data_dict['stat']== 'ok':
            # Success response from Zerodha
            session_id = data_dict['sessionID']
            if session_id :
                # Access token found in response data
                return session_id, None
            else:
                # Access token not present in the response
                return None, "Authentication succeeded but no access token was returned. Please check the response."
        else:
            # Handling errors from the API
            error_detail = data_dict['emsg']
            error_message = error_detail.get('message', 'Authentication failed. Please try again.')
            return None, f"API error: {error_message}"
    except Exception as e:
        # Exception handling
        return None, f"An exception occurred: {str(e)}"
