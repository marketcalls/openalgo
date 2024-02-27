import http.client
import json
import os
from database.auth_db import get_auth_token, get_api_key
from database.token_db import get_token
from mapping.transform_data import transform_data , map_product_type

def get_api_response(endpoint, method="GET", payload=''):
    login_username = os.getenv('LOGIN_USERNAME')
    AUTH_TOKEN = get_auth_token(login_username)
    api_key = os.getenv('BROKER_API_KEY')

    conn = http.client.HTTPSConnection("apiconnect.angelbroking.com")
    headers = {
      'Authorization': f'Bearer {AUTH_TOKEN}',
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'X-UserType': 'USER',
      'X-SourceID': 'WEB',
      'X-ClientLocalIP': 'CLIENT_LOCAL_IP',
      'X-ClientPublicIP': 'CLIENT_PUBLIC_IP',
      'X-MACAddress': 'MAC_ADDRESS',
      'X-PrivateKey': api_key
    }
    conn.request(method, endpoint, payload, headers)
    res = conn.getresponse()
    data = res.read()
    return json.loads(data.decode("utf-8"))

def get_order_book():
    return get_api_response("/rest/secure/angelbroking/order/v1/getOrderBook")

def get_trade_book():
    return get_api_response("/rest/secure/angelbroking/order/v1/getTradeBook")

def get_positions():
    return get_api_response("/rest/secure/angelbroking/order/v1/getPosition")

def get_holdings():
    return get_api_response("/rest/secure/angelbroking/portfolio/v1/getAllHolding")

def get_open_position(tradingsymbol, exchange, producttype):
    positions_data = get_positions()
    net_qty = '0'

    if positions_data and positions_data.get('status') and positions_data.get('data'):
        for position in positions_data['data']:
            if position.get('tradingsymbol') == tradingsymbol and position.get('exchange') == exchange and position.get('producttype') == producttype:
                net_qty = position.get('netqty', '0')
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data):
    login_username = os.getenv('LOGIN_USERNAME')
    AUTH_TOKEN = get_auth_token(login_username)
    BROKER_API_KEY = os.getenv('BROKER_API_KEY')
    data['apikey'] = BROKER_API_KEY
    token = get_token(data['symbol'], data['exchange'])
    newdata = transform_data(data, token)  
    headers = {
        'Authorization': f'Bearer {AUTH_TOKEN}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-UserType': 'USER',
        'X-SourceID': 'WEB',
        'X-ClientLocalIP': 'CLIENT_LOCAL_IP', 
        'X-ClientPublicIP': 'CLIENT_PUBLIC_IP',
        'X-MACAddress': 'MAC_ADDRESS',
        'X-PrivateKey': newdata['apikey']
    }
    payload = json.dumps({
        "variety": newdata.get('variety', 'NORMAL'),
        "tradingsymbol": newdata['tradingsymbol'],
        "symboltoken": newdata['symboltoken'],
        "transactiontype": newdata['transactiontype'],
        "exchange": newdata['exchange'],
        "ordertype": newdata.get('ordertype', 'MARKET'),
        "producttype": newdata.get('producttype', 'INTRADAY'),
        "duration": newdata.get('duration', 'DAY'),
        "price": newdata.get('price', '0'),
        "triggerprice": newdata.get('triggerprice', '0'),
        "squareoff": newdata.get('squareoff', '0'),
        "stoploss": newdata.get('stoploss', '0'),
        "quantity": newdata['quantity']
    })
    conn = http.client.HTTPSConnection("apiconnect.angelbroking.com")
    conn.request("POST", "/rest/secure/angelbroking/order/v1/placeOrder", payload, headers)
    res = conn.getresponse()
    response_data = json.loads(res.read().decode("utf-8"))
    return res, response_data

def place_smartorder_api(data):
    # Extract the required fields from data
    action = data['action']
    desired_position_size = int(data['position_size'])
    quantity = int(data['quantity'])

    # Get the current open position for the given symbol, exchange, and product
    current_position_size_str = get_open_position(data['symbol'], data['exchange'], map_product_type(data['product']))
    print(f"Current Position : {current_position_size_str}")
    # Convert current position size to integer
    current_position_size = int(current_position_size_str) if current_position_size_str.isdigit() else 0

    # Initialize the response dictionary
    response = {
        'status': 'error',
        'message': 'Initial',
        'orderid': None
    }

    # Decide the action based on the current and desired positions
    if action == "BUY":
        if current_position_size < desired_position_size:
            # Calculate the quantity to buy to match the desired position size
            quantity_to_buy = desired_position_size - current_position_size
            data['quantity'] = quantity_to_buy
            data['action'] = 'BUY'
            # Place the order with the adjusted quantity
            #print(f'place_smartapi_request : {place_order_api(data)}')
            response_data = place_order_api(data)
            # Process response
            if response_data['status'] == 'success' and 'orderid' in response_data['data']:
                response['status'] = 'success'
                response['message'] = 'Order placed successfully'
                response['orderid'] = response_data['data']['orderid']
            else:
                response['message'] = response_data.get('message', 'Failed to place order')
        else:
            response['status'] = 'success'
            response['message'] = 'Position is already matched or exceeded. No action taken.'

    elif action == "SELL":
        if current_position_size > desired_position_size:
            # Calculate the quantity to sell to match the desired position size
            quantity_to_sell = current_position_size - desired_position_size
            data['quantity'] = quantity_to_sell
            data['action'] = 'SELL'
            # Place the order with the adjusted quantity
            response_data = place_order_api(data)
            # Process response
            if response_data['status'] == 'success' and 'orderid' in response_data['data']:
                response['status'] = 'success'
                response['message'] = 'Order placed successfully'
                response['orderid'] = response_data['data']['orderid']
            else:
                response['message'] = response_data.get('message', 'Failed to place order')
        else:
            response['status'] = 'success'
            response['message'] = 'Position is already matched or lower. No action taken.'
    else:
        response['message'] = 'Invalid action specified.'

    return response

