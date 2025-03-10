# api/funds.py

import os
import http.client
import json
from broker.paytm.api.order_api import get_positions

def get_margin_data(auth_token):
    print(auth_token)
    """Fetch margin data from Paytm API using the provided auth token."""
    #api_key = os.getenv('BROKER_API_KEY')
    conn = http.client.HTTPSConnection("developer.paytmmoney.com")
    headers = {
        'x-jwt-token': auth_token,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    request_path = "/accounts/v1/funds/summary?config=true"
    print(f"Making request to: https://{conn.host}{request_path}")
    conn.request("GET", request_path, '', headers)
 

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
            if isinstance(position_book.get('data', []), list):
                for position in position_book['data']:
                    total_realised += float(position.get('realised_profit', 0))
                    # Since all positions are closed, unrealized profit is 0
                    total_unrealised += float(position.get('unrealised_profit', 0))
            return total_realised, total_unrealised

        total_realised, total_unrealised = sum_realised_unrealised(position_book)
        
        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": "{:.2f}".format(margin_data.get('data', {}).get('funds_summary', {}).get('available_cash', 0)),
            "collateral": "{:.2f}".format(margin_data.get('data', {}).get('funds_summary', {}).get('collaterals', 0)),
            "m2munrealized": "{:.2f}".format(total_unrealised),
            "m2mrealized": "{:.2f}".format(total_realised),
            "utiliseddebits": "{:.2f}".format(margin_data.get('data', {}).get('funds_summary', {}).get('utilised_amount', 0)),
        }
        return processed_margin_data
    except KeyError:
        # Return an empty dictionary in case of unexpected data structure
        return {}
