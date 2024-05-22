import http.client
import json
import os
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

def authenticate_broker(clientcode, broker_pin, totp_code):
    """
    Authenticate with the broker and return the auth token.
    """
    # Retrieve the BROKER_API_KEY and BROKER_API_SECRET environment variables
    broker_api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')

    if not broker_api_key or not api_secret:
        return None, "BROKER_API_KEY or BROKER_API_SECRET not found in environment variables"

    # Split the string to separate the API key and the client ID
    try:
        api_key, user_id, client_id  = broker_api_key.split(':::')
    except ValueError:
        return None, "BROKER_API_KEY format is incorrect. Expected format: 'api_key:::user_id:::client_id'"

    try:
        # Step 1: Perform TOTP login
        conn = http.client.HTTPSConnection("Openapi.5paisa.com")

        json_data = {
            "head": {
                "Key": api_key
            },
            "body": {
                "Email_ID": clientcode,
                "TOTP": totp_code,
                "PIN": broker_pin
            }
        }

        payload = json.dumps(json_data)
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        conn.request("POST", "/VendorsAPI/Service1.svc/TOTPLogin", payload, headers)
        res = conn.getresponse()
        data = res.read()
        mydata = data.decode("utf-8")

        data_dict = json.loads(mydata)

        print(f"The Request Token response is :{data_dict}")

        request_token = data_dict.get('body', {}).get('RequestToken')

        print(f"The Request Token is :{request_token}")

        if not request_token:
            error_message = data_dict.get('message', 'Failed to obtain request token. Please try again.')
            return None, f"TOTP Login Error: {error_message}"

        # Step 2: Get access token using the request token
        conn = http.client.HTTPSConnection("Openapi.5paisa.com")

        json_data = {
            "head": {
                "Key": api_key
            },
            "body": {
                "RequestToken": request_token,
                "EncryKey": api_secret,
                "UserId": user_id
            }
        }

        payload = json.dumps(json_data)


        print(f"The Access Token request is :{payload}")

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        conn.request("POST", "/VendorsAPI/Service1.svc/GetAccessToken", payload, headers)
        res = conn.getresponse()
        data = res.read()
        mydata = data.decode("utf-8")

        data_dict = json.loads(mydata)

        print(f"The Access Token response is :{data_dict}")

        if 'body' in data_dict and 'AccessToken' in data_dict['body']:
            return data_dict['body']['AccessToken'], None
        else:
            error_message = data_dict.get('message', 'Failed to obtain access token. Please try again.')
            return None, f"Access Token Error: {error_message}"

    except http.client.HTTPException as e:
        return None, f"HTTP error occurred: {e}"
    except json.JSONDecodeError:
        return None, "Failed to parse JSON response from the server"
    except Exception as e:
        return None, str(e)

