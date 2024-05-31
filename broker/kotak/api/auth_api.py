import http.client
import json
import os

def authenticate_broker(otp,token,sid,userid,api_secret):
    """
    Authenticate with the broker and return the auth token.
    """
    try:
        import http.client
        import json

        conn = http.client.HTTPSConnection("gw-napi.kotaksecurities.com")
        payload = json.dumps({
        "userId": userid,
        "otp": otp
        })
        headers = {
        'accept': '*/*',
        'sid': sid,
        'Auth': token,
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_secret}'
        }
        conn.request("POST", "/login/1.0/login/v2/validate", payload, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")
        data_dict = json.loads(data)
        
        token = data_dict['data']['token']
        sidotp = data_dict['data']['sid']
        
        auth_string = f"{token}:::{sidotp}"
        return auth_string, None
        
    except Exception as e:
        return None, str(e)
