import os
import http.client
import json
from dotenv import load_dotenv
from broker.fivepaisa.api.order_api import get_positions


# Load environment variables from the .env file
load_dotenv()

def get_margin_data(auth_token):
    """Fetch margin data from the broker's API using the provided auth token."""
    # Retrieve the BROKER_API_KEY environment variable
    broker_api_key = os.getenv('BROKER_API_KEY')

    if not broker_api_key:
        raise ValueError("BROKER_API_KEY not found in environment variables")

    # Split the string to separate the API key and the client ID
    try:
        api_key, user_id, client_id  = broker_api_key.split(':::')
    except ValueError:
        raise ValueError("BROKER_API_KEY format is incorrect. Expected format: 'api_key:::client_id'")

    conn = http.client.HTTPSConnection("Openapi.5paisa.com")

    json_data = {
        "head": {
            "key": api_key  # Ensure key matches the expected capitalization
        },
        "body": {
            "ClientCode": client_id
        }
    }

    payload = json.dumps(json_data)
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'bearer {auth_token}'
    }

    try:
        conn.request("POST", "/VendorsAPI/Service1.svc/V4/Margin", payload, headers)
        res = conn.getresponse()
        data = res.read()
        margin_data = json.loads(data.decode("utf-8"))
        print(f"Margin Data is : {margin_data}")
        
        equity_margin = margin_data.get('body', {}).get('EquityMargin', [])[0]  # Access the first element of the list
        positions_data = get_positions(auth_token)

        # Extracting the position details
        net_position_details = positions_data['body']['NetPositionDetail']

        # Calculating the total BookedPL and total MTOM
        total_booked_pl = sum(position['BookedPL'] for position in net_position_details)
        total_mtom = sum(position['MTOM'] for position in net_position_details)

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": "{:.2f}".format(equity_margin.get('NetAvailableMargin', 0)),
            "collateral": "{:.2f}".format(equity_margin.get('TotalCollateralValue', 0)),
            "m2munrealized": round(total_mtom,2),
            "m2mrealized": round(total_booked_pl,2),
            "utiliseddebits": "{:.2f}".format(equity_margin.get('MarginUtilized', 0)),
        }

        return processed_margin_data
    except Exception as e:
        return {}


