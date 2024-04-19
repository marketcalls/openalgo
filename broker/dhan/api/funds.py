# api/funds.py

import os
import http.client
import json
from broker.dhan.api.order_api import get_positions
from broker.dhan.mapping.order_data import map_position_data

def get_margin_data(auth_token):
    print(auth_token)
    """Fetch margin data from Dhan API using the provided auth token."""
    api_key = os.getenv('BROKER_API_KEY')
    conn = http.client.HTTPSConnection("api.dhan.co")
    headers = {
        'access-token': auth_token,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    conn.request("GET", "/fundlimit", '', headers)

    res = conn.getresponse()
    data = res.read()
    margin_data = json.loads(data.decode("utf-8"))

    print(f"Funds Details: {margin_data}")


    if margin_data.get('status') == 'error':
        # Log the error or return an empty dictionary to indicate failure
        print(f"Error fetching margin data: {margin_data.get('errors')}")
        return {}

    try:

        position_book = get_positions(auth_token)

        print(f'Positionbook : {position_book}')

        #position_book = map_position_data(position_book)

        def sum_realised_unrealised(position_book):
            total_realised = 0
            total_unrealised = 0
            total_realised = sum(position['realizedProfit'] for position in position_book)
            total_unrealised = sum(position['unrealizedProfit'] for position in position_book)
            return total_realised, total_unrealised

        total_realised, total_unrealised = sum_realised_unrealised(position_book)
        
        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": "{:.2f}".format(margin_data.get('availabelBalance')),
            "collateral": "{:.2f}".format(margin_data.get('collateralAmount')),
            "m2munrealized": "{:.2f}".format(total_unrealised),
            "m2mrealized": "{:.2f}".format(total_realised),
            "utiliseddebits": "{:.2f}".format(margin_data.get('utilizedAmount')),
        }
        return processed_margin_data
    except KeyError:
        # Return an empty dictionary in case of unexpected data structure
        return {}
