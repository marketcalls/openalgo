# api/funds.py

import os
import http.client
import hashlib
import json
from datetime import datetime
from broker.icici.api.order_api import get_positions
from broker.icici.mapping.order_data import map_order_data

def get_margin_data(auth_token):
    """Fetch margin data from ICICI Direct's API using the provided Session token."""
    api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')
    conn = http.client.HTTPSConnection("api.icicidirect.com")
    payload = json.dumps({})

    #checksum computation
    #time_stamp & checksum generation for request-headers

    time_stamp = datetime.utcnow().isoformat()[:19] + '.000Z'
    checksum = hashlib.sha256((time_stamp+payload+api_secret).encode("utf-8")).hexdigest()

    headers = {
        'Content-Type': 'application/json',
        'X-Checksum': 'token ' + checksum,
        'X-Timestamp': time_stamp,
        'X-AppKey': api_key,
        'X-SessionToken': auth_token
    }
    conn.request("GET", "/breezeapi/api/v1/funds", payload, headers)
    res = conn.getresponse()
    data = res.read()
    
    margin_data = json.loads(data.decode("utf-8"))

    print(f"Funds Details: {margin_data}")


    if margin_data.get('status') == 'error':
        # Log the error or return an empty dictionary to indicate failure
        print(f"Error fetching margin data: {margin_data.get('errors')}")
        return {}

    try:
        # Calculate the sum of available_margin and used_margin
        total_available_margin = margin_data['Success']['total_bank_balance']
        total_used_margin = margin_data['Success']['block_by_trade_balance']

        #position_book = get_positions(auth_token)

        #position_book = map_order_data(position_book)

        def sum_realised_unrealised():
            total_realised = 0
            total_unrealised = 0
            total_realised = 0 #sum(position['realised'] for position in position_book)
            total_unrealised = 0 #sum(position['unrealised'] for position in position_book)
            return total_realised, total_unrealised

        #total_realised, total_unrealised = sum_realised_unrealised(position_book)
        total_realised, total_unrealised = sum_realised_unrealised()

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": "{:.2f}".format(total_available_margin),
            "collateral": "0.00",
            "m2munrealized": "{:.2f}".format(total_unrealised),
            "m2mrealized": "{:.2f}".format(total_realised),
            "utiliseddebits": "{:.2f}".format(total_used_margin),
        }
        return processed_margin_data
    except KeyError:
        # Return an empty dictionary in case of unexpected data structure
        return {}
