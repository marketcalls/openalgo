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
    if margin_data.get('stat') != 'Ok':
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

    # Calculate margin details
    try:
        total_available_margin = (
            float(margin_data.get('cash', 0)) + 
            float(margin_data.get('payin', 0)) - 
            float(margin_data.get('marginused', 0))
        )
        total_collateral = float(margin_data.get('brkcollamt', 0))
        total_used_margin = float(margin_data.get('marginused', 0))

        # Construct and return processed data
        return {
            "availablecash": f"{total_available_margin:.2f}",
            "collateral": f"{total_collateral:.2f}",
            "m2munrealized": f"{total_unrealised:.2f}",
            "m2mrealized": f"{total_realised:.2f}",
            "utiliseddebits": f"{total_used_margin:.2f}",
        }
    except (KeyError, ValueError) as e:
        print(f"Error processing margin data: {str(e)}")
        return {}
