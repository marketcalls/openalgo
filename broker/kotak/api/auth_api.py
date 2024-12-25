import http.client
import json
import os

def authenticate_broker(otp,token,sid,userid,access_token,hsServerId):
    """
    Authenticate with the broker and return the auth token.
    """
    try:
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
        'Authorization': f'Bearer {access_token}'
        }
        conn.request("POST", "/login/1.0/login/v2/validate", payload, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")
        data_dict = json.loads(data)
        
        token = data_dict['data']['token']
        sidotp = data_dict['data']['sid']
        
        auth_string = f"{token}:::{sidotp}:::{hsServerId}:::{access_token}"
        return auth_string, None
        
    except Exception as e:
        return None, str(e)