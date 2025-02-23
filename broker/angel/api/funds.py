# api/funds.py

import os
import http.client
import json

def get_margin_data(auth_token):
    """Fetch margin data from the broker's API using the provided auth token."""
    api_key = os.getenv('BROKER_API_KEY')
    conn = http.client.HTTPSConnection("apiconnect.angelbroking.com")
    headers = {
        'Authorization': f'Bearer {auth_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-UserType': 'USER',
        'X-SourceID': 'WEB',
        'X-ClientLocalIP': 'CLIENT_LOCAL_IP',
        'X-ClientPublicIP': 'CLIENT_PUBLIC_IP',
        'X-MACAddress': 'MAC_ADDRESS',
        'X-PrivateKey': api_key
    }
    conn.request("GET", "/rest/secure/angelbroking/user/v1/getRMS", '', headers)

    res = conn.getresponse()
    data = res.read()
    margin_data = json.loads(data.decode("utf-8"))

    print(f"Margin Data {margin_data}")

    if margin_data.get('data'):
        required_keys = [
            "availablecash", 
            "collateral", 
            "m2mrealized", 
            "m2munrealized", 
            "utiliseddebits"
        ]
        filtered_data = {}
        for key in required_keys:
            value = margin_data['data'].get(key, 0)
            try:
                formatted_value = "{:.2f}".format(float(value))
            except (ValueError, TypeError):
                formatted_value = value
            filtered_data[key] = formatted_value
        return filtered_data
    else:
        return {}
