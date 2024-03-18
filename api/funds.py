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

    # Process and return the 'data' key from margin_data if it exists and is not None
    if margin_data.get('data') is not None:
        for key, value in margin_data['data'].items():
            if value is not None and isinstance(value, str):
                try:
                    margin_data['data'][key] = "{:.2f}".format(float(value))
                except ValueError:
                    pass
        return margin_data['data']
    else:
        # Return an empty dictionary if 'data' is None or doesn't exist
        return {}
