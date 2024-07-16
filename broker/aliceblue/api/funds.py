# api/funds.py

import os
import http.client
import json


def get_margin_data(auth_token):
    """Fetch margin data from Alice Blue's API using the provided auth token."""
    conn = http.client.HTTPSConnection("ant.aliceblueonline.com")
    payload = ""
    headers = {
        'Authorization': f'Bearer {auth_token}',
    }
    conn.request("GET", "/rest/AliceBlueAPIService/api/limits/getRmsLimits", payload, headers)

    res = conn.getresponse()
    data = res.read()
    margin_data = json.loads(data.decode("utf-8"))

    print(f"Funds Details: {margin_data}")

    # Initialize processed data dictionary
    processed_margin_data = {
        "availablecash": "0.00",
        "collateral": "0.00",
        "m2munrealized": "0.00",
        "m2mrealized": "0.00",
        "utiliseddebits": "0.00",
    }

    try:
        # Iterate through the list and process each dictionary
        for item in margin_data:
            if item['stat'] == 'Not_Ok':
                # Log the error or return an empty dictionary to indicate failure
                print(f"Error fetching margin data: {item['emsg']}")
                return {}

            # Accumulate values
            processed_margin_data["availablecash"] = "{:.2f}".format(float(item.get('net', 0)))
            processed_margin_data["collateral"] = "{:.2f}".format(float(item.get('collateralvalue', 0)))
            processed_margin_data["m2munrealized"] = "{:.2f}".format(float(item.get('unrealizedMtomPrsnt', 0)))
            processed_margin_data["m2mrealized"] = "{:.2f}".format(float(item.get('realizedMtomPrsnt', 0)))
            processed_margin_data["utiliseddebits"] = "{:.2f}".format(float(item.get('cncMarginUsed', 0)))

        return processed_margin_data
    except KeyError as e:
        # Return an empty dictionary in case of unexpected data structure
        print(f"KeyError: {str(e)}")
        return {}