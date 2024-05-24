import http.client
import json
import os
from database.auth_db import get_auth_token
from database.token_db import get_token , get_br_symbol, get_symbol
from broker.fivepaisa.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data

# Retrieve the BROKER_API_KEY and BROKER_API_SECRET environment variables
broker_api_key = os.getenv('BROKER_API_KEY')
api_secret = os.getenv('BROKER_API_SECRET')
api_key, user_id, client_id  = broker_api_key.split(':::')

def get_api_response(endpoint, auth, method="GET", payload=''):

    AUTH_TOKEN = auth


 
    conn = http.client.HTTPSConnection("Openapi.5paisa.com")
    headers = {
      'Authorization': f'bearer {AUTH_TOKEN}',
      'Content-Type': 'application/json',
    }
    conn.request(method, endpoint, payload, headers)
    res = conn.getresponse()
    data = res.read()
    
    return json.loads(data.decode("utf-8"))

def get_order_book(auth):
    json_data = {
        "head": {
            "key": api_key
        },
        "body": {
            "ClientCode": client_id
        }
    }

    payload = json.dumps(json_data)
    return get_api_response("/VendorsAPI/Service1.svc/V3/OrderBook",auth,method="POST",payload=payload)

def get_trade_book(auth):
    json_data = {
        "head": {
            "key": api_key
        },
        "body": {
            "ClientCode": client_id
        }
    }

    payload = json.dumps(json_data)
    return get_api_response("/VendorsAPI/Service1.svc/V1/TradeBook",auth,method="POST",payload=payload)

def get_positions(auth):
    json_data = {
        "head": {
            "key": api_key
        },
        "body": {
            "ClientCode": client_id
        }
    }

    payload = json.dumps(json_data)
    return get_api_response("/VendorsAPI/Service1.svc/V2/NetPositionNetWise",auth,method="POST",payload=payload)

def get_holdings(auth):
    json_data = {
        "head": {
            "key": api_key
        },
        "body": {
            "ClientCode": client_id
        }
    }

    payload = json.dumps(json_data)
    return get_api_response("/VendorsAPI/Service1.svc/V3/Holding",auth,method="POST",payload=payload)

def get_open_position(tradingsymbol, exchange, producttype,auth):
    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    positions_data = get_positions(auth)

    print(positions_data)

    net_qty = '0'

    if positions_data and positions_data.get('status') and positions_data.get('data'):
        for position in positions_data['data']:
            if position.get('tradingsymbol') == tradingsymbol and position.get('exchange') == exchange and position.get('producttype') == producttype:
                net_qty = position.get('netqty', '0')
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data,auth):
    AUTH_TOKEN = auth
    
    # Retrieve the BROKER_API_KEY and BROKER_API_SECRET environment variables
    broker_api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')

    if not broker_api_key or not api_secret:
        return None, "BROKER_API_KEY or BROKER_API_SECRET not found in environment variables"

    # Split the string to separate the API key and the client ID
    try:
        api_key, user_id, client_id  = broker_api_key.split(':::')
    except ValueError:
        return None, "BROKER_API_KEY format is incorrect. Expected format: 'api_key:::user_id:::client_id'"



    token = get_token(data['symbol'], data['exchange'])
    newdata = transform_data(data, token)  
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'bearer {AUTH_TOKEN}'
    }
    

    json_data = {
            "head": {
                "key": api_key
            },
            "body": newdata
        }

    payload = json.dumps(json_data)



    print(payload)
    conn = http.client.HTTPSConnection("Openapi.5paisa.com")
    conn.request("POST", "/VendorsAPI/Service1.svc/V1/PlaceOrderRequest", payload, headers)
    res = conn.getresponse()
    response_data = json.loads(res.read().decode("utf-8"))
    print(response_data)
    if response_data['head']['statusDescription'] == "Success":
        orderid = response_data['body']['BrokerOrderID']
    else:
        orderid = None
    return res, response_data, orderid

def place_smartorder_api(data,auth):

    AUTH_TOKEN = auth

    #If no API call is made in this function then res will return None
    res = None

    # Extract necessary info from data
    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")
    position_size = int(data.get("position_size", "0"))

    

    # Get current open position for the symbol
    current_position = int(get_open_position(symbol, exchange, map_product_type(product),AUTH_TOKEN))


    print(f"position_size : {position_size}") 
    print(f"Open Position : {current_position}") 
    
    # Determine action based on position_size and current_position
    action = None
    quantity = 0


    # If both position_size and current_position are 0, do nothing
    if position_size == 0 and current_position == 0:
        action = data['action']
        quantity = data['quantity']
        #print(f"action : {action}")
        #print(f"Quantity : {quantity}")
        res, response, orderid = place_order_api(data,auth)
        # print(res)
        # print(response)
        # print(orderid)
        return res , response, orderid
        
    elif position_size == current_position:
        response = {"status": "success", "message": "No action needed. Position size matches current position."}
        orderid = None
        return res, response, orderid  # res remains None as no API call was mad
   
   

    if position_size == 0 and current_position>0 :
        action = "SELL"
        quantity = abs(current_position)
    elif position_size == 0 and current_position<0 :
        action = "BUY"
        quantity = abs(current_position)
    elif current_position == 0:
        action = "BUY" if position_size > 0 else "SELL"
        quantity = abs(position_size)
    else:
        if position_size > current_position:
            action = "BUY"
            quantity = position_size - current_position
            #print(f"smart buy quantity : {quantity}")
        elif position_size < current_position:
            action = "SELL"
            quantity = current_position - position_size
            #print(f"smart sell quantity : {quantity}")




    if action:
        # Prepare data for placing the order
        order_data = data.copy()
        order_data["action"] = action
        order_data["quantity"] = str(quantity)

        #print(order_data)
        # Place the order
        res, response, orderid = place_order_api(order_data,auth)
        #print(res)
        print(response)
        print(orderid)
        
        return res , response, orderid
    



def close_all_positions(current_api_key,auth):
    # Fetch the current open positions
    AUTH_TOKEN = auth

    positions_response = get_positions(AUTH_TOKEN)

    # Check if the positions data is null or empty
    if positions_response['data'] is None or not positions_response['data']:
        return {"message": "No Open Positions Found"}, 200

    if positions_response['status']:
        # Loop through each position to close
        for position in positions_response['data']:
            # Skip if net quantity is zero
            if int(position['netqty']) == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if int(position['netqty']) > 0 else 'BUY'
            quantity = abs(int(position['netqty']))


            #get openalgo symbol to send to placeorder function
            symbol = get_symbol(position['symboltoken'],position['exchange'])
            print(f'The Symbol is {symbol}')

            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position['exchange'],
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position['producttype']),
                "quantity": str(quantity)
            }

            print(place_order_payload)

            # Place the order to close the position
            res, response, orderid =   place_order_api(place_order_payload,auth)

            # print(res)
            # print(response)
            # print(orderid)


            
            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid,auth):
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_KEY')
    
    # Set up the request headers
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
    
    # Prepare the payload
    payload = json.dumps({
        "variety": "NORMAL",
        "orderid": orderid,
    })
    
    # Establish the connection and send the request
    conn = http.client.HTTPSConnection("apiconnect.angelbroking.com")  # Adjust the URL as necessary
    conn.request("POST", "/rest/secure/angelbroking/order/v1/cancelOrder", payload, headers)
    res = conn.getresponse()
    data = json.loads(res.read().decode("utf-8"))
    
    # Check if the request was successful
    if data.get("status"):
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Return an error response
        return {"status": "error", "message": data.get("message", "Failed to cancel order")}, res.status


def modify_order(data,auth):

    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_KEY')

    token = get_token(data['symbol'], data['exchange'])
    data['symbol'] = get_br_symbol(data['symbol'],data['exchange'])

    transformed_data = transform_modify_order_data(data, token)  # You need to implement this function
    # Set up the request headers
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
    payload = json.dumps(transformed_data)

    conn = http.client.HTTPSConnection("apiconnect.angelbroking.com")
    conn.request("POST", "/rest/secure/angelbroking/order/v1/modifyOrder", payload, headers)
    res = conn.getresponse()
    data = json.loads(res.read().decode("utf-8"))

    if data.get("status") == "true" or data.get("message") == "SUCCESS":
        return {"status": "success", "orderid": data["data"]["orderid"]}, 200
    else:
        return {"status": "error", "message": data.get("message", "Failed to modify order")}, res.status



def cancel_all_orders_api(data,auth):
    # Get the order book

    AUTH_TOKEN = auth
    

    order_book_response = get_order_book(AUTH_TOKEN)
    #print(order_book_response)
    if order_book_response['status'] != True:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response.get('data', [])
                        if order['status'] in ['open', 'trigger pending']]
    #print(orders_to_cancel)
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['orderid']
        cancel_response, status_code = cancel_order(orderid,auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations

