# api/funds.py

import os
import http.client
import json

def get_margin_data(auth_token):
    """Fetch margin data from the broker's API using the provided auth token."""
    access_token_parts = auth_token.split(":::")
    token = access_token_parts[0]
    sid = access_token_parts[1]
    
    api_secret = os.getenv('BROKER_API_SECRET')
    print(api_secret) 
    conn = http.client.HTTPSConnection("gw-napi.kotaksecurities.com")
    payload = 'jData=%7B%22seg%22%3A%22ALL%22%2C%22exch%22%3A%22ALL%22%2C%22prod%22%3A%22ALL%22%7D'
    headers = {
    'accept': 'application/json',
    'Sid': sid,
    'Auth': token,
    'neo-fin-key': 'neotradeapi',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Authorization': f'Bearer {api_secret}'
    }
    conn.request("POST", "/Orders/2.0/quick/user/limits?sId=server1", payload, headers)
    try:
        res = conn.getresponse()
        data = res.read()
        print(data.decode("utf-8"))
        margin_data = json.loads(data.decode("utf-8"))

        #print(f"Margin Data {margin_data}")

        # Process and return the 'data' key from margin_data if it exists and is not None
        
        #TODO FIX realized and unrealized
        processed_margin_data = {
                "availablecash": f"{margin_data['Net']}",
                "collateral": f"{margin_data['Collateral']}",
                "m2munrealized": '0.0',
                "m2mrealized": '0.0',
                "utiliseddebits": f"{margin_data['MarginUsed']}"
            }
        return processed_margin_data
    except Exception as e:
        print(f"Error fetching margin data: {e}")
        return {}
