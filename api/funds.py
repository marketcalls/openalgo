# api/funds.py

import os
import http.client
import json

def get_margin_data(auth_token):
    """Fetch margin data from Upstox's API using the provided auth token."""
    api_key = os.getenv('BROKER_API_KEY')
    conn = http.client.HTTPSConnection("api.upstox.com")
    headers = {
        'Authorization': f'Bearer {auth_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    conn.request("GET", "/v2/user/get-funds-and-margin", '', headers)

    res = conn.getresponse()
    data = res.read()
    margin_data = json.loads(data.decode("utf-8"))

    #print(f"Margin Data {margin_data}")

    if margin_data.get('status') == 'error':
        # Log the error or return an empty dictionary to indicate failure
        print(f"Error fetching margin data: {margin_data.get('errors')}")
        return {}

    try:
        # Calculate the sum of available_margin and used_margin
        total_available_margin = sum([
            margin_data['data']['commodity']['available_margin'],
            margin_data['data']['equity']['available_margin']
        ])
        total_used_margin = sum([
            margin_data['data']['commodity']['used_margin'],
            margin_data['data']['equity']['used_margin']
        ])

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": "{:.2f}".format(total_available_margin),
            "collateral": "0.00",
            "m2munrealized": "0.00",
            "m2mrealized": "0.00",
            "utiliseddebits": "{:.2f}".format(total_used_margin),
        }
        return processed_margin_data
    except KeyError:
        # Return an empty dictionary in case of unexpected data structure
        return {}
