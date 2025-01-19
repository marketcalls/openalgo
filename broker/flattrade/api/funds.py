import os
import http.client
import json

def calculate_pnl(entry):
    """Calculate realized and unrealized PnL for a given entry."""
    unrealized_pnl = (float(entry.get("lp", 0)) - float(entry.get("netavgprc", 0))) * float(entry.get("netqty", 0))
    realized_pnl = (float(entry.get("daysellavgprc", 0)) - float(entry.get("daybuyavgprc", 0))) * float(entry.get("daysellqty", 0))
    return realized_pnl, unrealized_pnl

def fetch_data(endpoint, payload, headers, conn):
    """Send a POST request and return the parsed JSON response."""
    conn.request("POST", endpoint, payload, headers)
    response = conn.getresponse()
    return json.loads(response.read().decode("utf-8"))

def get_margin_data(auth_token):
    """Fetch and process margin and position data."""
    url = "piconnect.flattrade.in"
    full_api_key = os.getenv('BROKER_API_KEY')
    userid = full_api_key.split(':::')[0]
    actid = userid

    # Prepare payload
    data = {"uid": userid, "actid": actid}
    payload = f"jData={json.dumps(data)}&jKey={auth_token}"
    headers = {'Content-Type': 'application/json'}

    # Initialize HTTP connection
    conn = http.client.HTTPSConnection(url)

    # Fetch margin data
    margin_data = fetch_data("/PiConnectTP/Limits", payload, headers, conn)
    
    # Check if the request was successful
    if margin_data.get('stat') != 'Ok':
        # Log the error or return an empty dictionary to indicate failure
        print(f"Error fetching margin data: {margin_data.get('emsg')}")
        return {}

    # Fetch position data
    position_data = fetch_data("/PiConnectTP/PositionBook", payload, headers, conn)
    
    total_realised = 0
    total_unrealised = 0

    # Process position data if it's a list
    if isinstance(position_data, list):
        for entry in position_data:
            realized_pnl, unrealized_pnl = calculate_pnl(entry)
            total_realised += realized_pnl
            total_unrealised += unrealized_pnl

    try:
        # Calculate total_available_margin as the sum of 'cash' and 'payin'
        total_available_margin = float(margin_data.get('cash',0)) + float(margin_data.get('payin',0)) - float(margin_data.get('marginused',0))
        total_collateral = float(margin_data.get('brkcollamt',0))
        total_used_margin = float(margin_data.get('marginused',0))

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": "{:.2f}".format(total_available_margin),
            "collateral": "{:.2f}".format(total_collateral),
            "m2munrealized": "{:.2f}".format(total_unrealised),
            "m2mrealized": "{:.2f}".format(total_realised),
            "utiliseddebits": "{:.2f}".format(total_used_margin),
        }
        return processed_margin_data
    except KeyError as e:
        # Log the exception and return an empty dictionary if there's an unexpected error
        print(f"Error processing margin data: {str(e)}")
        return {}
