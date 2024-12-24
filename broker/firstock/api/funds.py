import requests
import json
import os

def get_margin_data(auth_token):
    """Get margin/limit data from Firstock."""
    try:
        # Get user ID from environment variable and trim the last 4 characters
        userid = os.getenv('BROKER_API_KEY')
        userid = userid[:-4]  # Trim the last 4 characters

        # Firstock API URL for getting limits
        url = "https://connect.thefirstock.com/api/V4/limit"

        # Prepare payload
        payload = {
            "jKey": auth_token,
            "userId": userid
        }

        # Set headers
        headers = {
            'Content-Type': 'application/json'
        }

        # Send POST request
        response = requests.post(url, json=payload, headers=headers)

        # Handle the response
        if response.status_code == 200:
            data = response.json()
            if data['status'] == "success":
                margin_data = data['data']
                
                # Calculate total_available_margin as the sum of 'cash' and 'payin'
                total_available_margin = float(margin_data.get('cash', 0)) + float(margin_data.get('payin', 0)) - float(margin_data.get('marginused', 0))
                total_collateral = float(margin_data.get('brkcollamt', 0))
                total_used_margin = float(margin_data.get('marginused', 0))
                
                # Construct and return the processed margin data in same format as Shoonya
                processed_margin_data = {
                    "availablecash": "{:.2f}".format(total_available_margin),
                    "collateral": "{:.2f}".format(total_collateral),
                    "m2munrealized": "0.00",  # Not provided by Firstock API
                    "m2mrealized": "0.00",    # Not provided by Firstock API
                    "utiliseddebits": "{:.2f}".format(total_used_margin)
                }
                
                return processed_margin_data
            else:
                print(f"Error fetching margin data: {data.get('error', {}).get('message')}")
                return {}
        else:
            print(f"Error: {response.status_code}, {response.text}")
            return {}

    except Exception as e:
        print(f"Error processing margin data: {str(e)}")
        return {}
