import os
import http.client
import json

def get_margin_data(auth_token):
    """Fetch margin data from Zebu's API using the provided auth token."""
    
    # Zebu API endpoint for fetching margin data
    url = "go.mynt.in"
    
    # Fetch UserID and AccountID from environment variables
    userid = os.getenv('BROKER_API_KEY')
    actid = userid  # Assuming AccountID is the same as UserID

    # Prepare the payload for the request
    data = {
        "uid": userid,  # User ID
        "actid": actid  # Account ID
    }

    # Prepare the jData payload with the authentication token (jKey)
    payload = "jData=" + json.dumps(data) + "&jKey=" + auth_token

    # Initialize HTTP connection
    conn = http.client.HTTPSConnection(url)

    # Set headers
    headers = {
        'Content-Type': 'application/json'
    }

    # Send the POST request to Zebu's API
    conn.request("POST", "/NorenWClientTP/Limits", payload, headers)

    # Get the response
    res = conn.getresponse()
    data = res.read()

    # Parse the response
    margin_data = json.loads(data.decode("utf-8"))

    print(margin_data)

    # Check if the request was successful
    if margin_data.get('stat') != 'Ok':
        # Log the error or return an empty dictionary to indicate failure
        print(f"Error fetching margin data: {margin_data.get('emsg')}")
        return {}

    try:
        # Calculate total_available_margin as the sum of 'cash' and 'payin'
        total_available_margin = float(margin_data.get('cash',0)) + float(margin_data.get('payin',0)) - float(margin_data.get('marginused',0))
        total_collateral = float(margin_data.get('brkcollamt',0))
        total_used_margin = float(margin_data.get('marginused',0))
        total_realised = float(margin_data.get('rpnl',0))
        total_unrealised = float(margin_data.get('urmtom',0))

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

