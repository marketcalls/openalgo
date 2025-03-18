# api/funds.py

import os
import http.client
import json


def get_margin_data(auth_token):
    """Fetch margin data from Zerodha's API using the provided auth token."""
    api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')
    conn = http.client.HTTPSConnection("xts.compositedge.com")
    
    headers = {
        
        'authorization': auth_token ,
    }

    conn.request("GET", "/interactive/user/balance", '', headers)

    res = conn.getresponse()
    data = res.read()
    
    margin_data = json.loads(data.decode("utf-8"))

    #print(f"Funds Details: {margin_data}")

    if (
        margin_data.get("result") and 
        margin_data["result"].get("BalanceList") and 
        margin_data["result"]["BalanceList"]
    ):
        rms_sublimits = margin_data["result"]["BalanceList"][0]["limitObject"]["RMSSubLimits"]
        
        required_keys = [
            "netMarginAvailable", 
            "collateral", 
            "UnrealizedMTM", 
            "RealizedMTM",
            "marginUtilized"
        ]
        
        filtered_data = {}
        for key in required_keys:
            value = rms_sublimits.get(key, 0)
            try:
                formatted_value = "{:.2f}".format(float(value)) if str(value).lower() != "nan" else "0.00"
            except (ValueError, TypeError):
                formatted_value = "0.00"
            
            filtered_data[key] = formatted_value
            #print(f"Funds Dashboard: {key} = {filtered_data[key]}")

        processed_margin_data = {
            "availablecash": filtered_data.get('netMarginAvailable'),
            "collateral":  filtered_data.get('collateral'),
            "m2munrealized": filtered_data.get('UnrealizedMTM'),
            "m2mrealized": filtered_data.get('RealizedMTM'),
            "utiliseddebits": filtered_data.get('marginUtilized'),
        }
        
        #print(f"Funds = {processed_margin_data}")
        return processed_margin_data
    else:
        return {}