import http.client
import json
import os

def authenticate_broker(clientcode, broker_pin, totp_code):
    """
    Authenticate with the broker and return the auth token.
    """
    api_key = os.getenv('BROKER_API_KEY')

    try:
        conn = http.client.HTTPSConnection("apiconnect.angelbroking.com")
        payload = json.dumps({
            "clientcode": clientcode,
            "password": broker_pin,
            "totp": totp_code
        })
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-UserType': 'USER',
            'X-SourceID': 'WEB',
            'X-ClientLocalIP': 'CLIENT_LOCAL_IP',  # Ensure these are handled or replaced appropriately
            'X-ClientPublicIP': 'CLIENT_PUBLIC_IP',
            'X-MACAddress': 'MAC_ADDRESS',
            'X-PrivateKey': api_key
        }

        conn.request("POST", "/rest/auth/angelbroking/user/v1/loginByPassword", payload, headers)
        res = conn.getresponse()
        data = res.read()
        mydata = data.decode("utf-8")

        data_dict = json.loads(mydata)

        if 'data' in data_dict and 'jwtToken' in data_dict['data']:
            return data_dict['data']['jwtToken'], None
        else:
            return None, data_dict.get('message', 'Authentication failed. Please try again.')
    except Exception as e:
        return None, str(e)
