# api/funds.py for Fyers

import os
import http.client
import json

def get_margin_data(auth_token):

    api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')
    """Fetch funds data from Fyers' API using the provided authentication token."""
    conn = http.client.HTTPSConnection("api-t1.fyers.in")
    headers = {
        'Authorization': f'{api_key}:{auth_token}',  # 'app_id:access_token' format expected in auth_token
    }
    conn.request("GET", "/api/v3/funds", '', headers)

    res = conn.getresponse()
    data = res.read()
    funds_data = json.loads(data.decode("utf-8"))

    #print(funds_data)

    if funds_data.get('code') != 200:
        print(f"Error fetching funds data: {funds_data.get('message')}")
        return {}

    try:
        processed_funds_data = {}
        for fund in funds_data.get('fund_limit', []):
            key = fund['title'].lower().replace(' ', '_')
            processed_funds_data[key] = {
                "equity_amount": "{:.2f}".format(fund['equityAmount']),
                "commodity_amount": "{:.2f}".format(fund['commodityAmount'])
            }
        print(processed_funds_data)
        # Using specified collateral data for both equity and commodity.
            
        balance_equity = processed_funds_data.get('available_balance', {}).get('equity_amount')
        balance_commodity = processed_funds_data.get('available_balance', {}).get('commodity_amount')
        total_balance = float(balance_equity) + float(balance_commodity)


        collateral_equity = processed_funds_data.get('collaterals', {}).get('equity_amount')
        collateral_commodity = processed_funds_data.get('collaterals', {}).get('commodity_amount')
        total_collateral = float(collateral_equity) + float(collateral_commodity)

        real_pnl_equity = processed_funds_data.get('realized_profit_and_loss', {}).get('equity_amount')
        real_pnl_commodity = processed_funds_data.get('realized_profit_and_loss', {}).get('commodity_amount')
        total_real_pnl = float(real_pnl_equity) + float(real_pnl_commodity)

        utilized_equity = processed_funds_data.get('utilized_amount', {}).get('equity_amount')
        utilized_commodity = processed_funds_data.get('utilized_amount', {}).get('commodity_amount')
        total_utilized = float(utilized_equity) + float(utilized_commodity)

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": "{:.2f}".format(total_balance),
            "collateral": "0.00",
            "m2munrealized": "{:.2f}".format(total_collateral),
            "m2mrealized": "{:.2f}".format(total_real_pnl),
            "utiliseddebits": "{:.2f}".format(total_utilized)
        }

        return processed_margin_data
    except KeyError as e:
        print(f"An error occurred while processing the funds data: {e}")
        return {}


