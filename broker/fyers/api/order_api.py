import http.client
import json
import os
from database.token_db import get_br_symbol, get_oa_symbol
from broker.fyers.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data



def get_api_response(endpoint, auth, method="GET", payload=''):
    
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_KEY')

    conn = http.client.HTTPSConnection("api-t1.fyers.in")
    headers = {
        'Authorization': f'{api_key}:{AUTH_TOKEN}',
        'Content-Type': 'application/json'  # Added if payloads are JSON
    }

    conn.request(method, endpoint, payload, headers)
    res = conn.getresponse()
    data = res.read()
    return json.loads(data.decode("utf-8"))

def get_order_book(auth):
    return get_api_response("/api/v3/orders",auth)

def get_trade_book(auth):
    return get_api_response("/api/v3/tradebook",auth)

def get_positions(auth):
    return get_api_response("/api/v3/positions",auth)

def get_holdings(auth):
    return get_api_response("/api/v3/holdings",auth)

def get_open_position(tradingsymbol, exchange, product,auth):

    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    

    positions_data = get_positions(auth)
    net_qty = '0'
    #print(positions_data['data']['net'])

    if positions_data and positions_data.get('s') and positions_data.get('netPositions'):
        for position in positions_data['netPositions']:

            if position.get('symbol') == tradingsymbol  and position.get("productType") == product:
                net_qty = position.get('netQty', '0')
                print(f'Net Quantity {net_qty}')
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data,auth):
    
    AUTH_TOKEN = auth
    
    BROKER_API_KEY = os.getenv('BROKER_API_KEY')
    data['apikey'] = BROKER_API_KEY
    #token = get_token(data['symbol'], data['exchange'])

    headers = {
        'Authorization': f'{BROKER_API_KEY}:{AUTH_TOKEN}',
        'Content-Type': 'application/json'  # Added if payloads are JSON
    }

    payload = transform_data(data)  

    print(payload)

    # Convert payload to JSON and then encode to bytes
    payload_bytes = json.dumps(payload).encode('utf-8')

    conn = http.client.HTTPSConnection("api-t1.fyers.in")
    conn.request("POST", "/api/v3/orders/sync", payload_bytes, headers)
    res = conn.getresponse()
    response_data = json.loads(res.read().decode("utf-8"))


    #print(response_data)

    if response_data['s'] == 'ok':
        orderid = response_data['id']
    elif response_data['s'] == 'error':
        orderid = response_data.get('id')
        if not orderid: 
            orderid = None
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
        res, response, orderid = place_order_api(data,AUTH_TOKEN)
        #print(res)
        #print(response)
        
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
        res, response, orderid = place_order_api(order_data,AUTH_TOKEN)
        #print(res)
        #print(response)
        
        return res , response, orderid
    



def close_all_positions(current_api_key,auth):

    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth

    api_key = os.getenv('BROKER_API_KEY')
    
    # Set up the request headers
    headers = {
        'Authorization': f'{api_key}:{AUTH_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    # Prepare the payload with the specific requirement to close all positions
    payload = json.dumps({"exit_all": 1})  # Match the API expected payload
    
    # Establish the connection and send the request to the positions endpoint
    conn = http.client.HTTPSConnection("api-t1.fyers.in")
    conn.request("DELETE", "/api/v3/positions", payload, headers)
    res = conn.getresponse()
    data = json.loads(res.read().decode("utf-8"))
    print(data)
    
    # Check if the request was successful
    if data.get("s") == "ok":
        # Return a success response
        return {"status": "success", "message": "The position is closed"}, 200
    else:
        # Return an error response
        return {"status": "error", "message": data.get("message", "Failed to close position")}, res.status

def cancel_order(orderid,auth):
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth

    api_key = os.getenv('BROKER_API_KEY')
    
    # Set up the request headers
    headers = {
        'Authorization': f'{api_key}:{AUTH_TOKEN}',
        'Content-Type': 'application/json'  # Added if payloads are JSON
    }
    
    # Prepare the payload
    payload = json.dumps({"id": orderid})  # Use json.dumps to convert the dictionary to a JSON string
    
    
    # Establish the connection and send the request
    conn = http.client.HTTPSConnection("api-t1.fyers.in")
    conn.request("DELETE", "/api/v3/orders/sync", payload, headers)
    res = conn.getresponse()
    data = json.loads(res.read().decode("utf-8"))
    print(data)
    
    # Check if the request was successful
    if data.get("s")=="ok":
        # Return a success response
        return {"status": "success", "orderid": data['id']}, 200
    else:
        # Return an error response
        return {"status": "error", "message": data.get("message", "Failed to cancel order")}, res.status


def modify_order(data,auth):

    

    AUTH_TOKEN = auth
    
    api_key = os.getenv('BROKER_API_KEY')
    
  
    # Set up the request headers
    headers = {
        'Authorization': f'{api_key}:{AUTH_TOKEN}',
        'Content-Type': 'application/json'  # Added if payloads are JSON
    }

    payload = transform_modify_order_data(data) 

    print(payload)

    # Convert payload to JSON and then encode to bytes
    payload_bytes = json.dumps(payload).encode('utf-8')

    conn = http.client.HTTPSConnection("api-t1.fyers.in")
    conn.request("PATCH", "/api/v3/orders/sync", payload_bytes, headers)
    res = conn.getresponse()
    data = json.loads(res.read().decode("utf-8"))
    print(data)

    if data.get("s") == "ok" or data.get("s") == "OK":
        return {"status": "success", "orderid": data["id"]}, 200
    else:
        print(data)
        return {"status": "error", "message": data.get("message", "Failed to modify order")}, res.status
    

def cancel_all_orders_api(data,auth):

    AUTH_TOKEN = auth
    # Get the order book
    order_book_response = get_order_book(AUTH_TOKEN)
    #print(order_book_response)
    if order_book_response['s'] != 'ok':
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response.get('orderBook', [])
                        if order['status'] in [4, 6]]
    print(orders_to_cancel)
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['id']
        cancel_response, status_code = cancel_order(orderid,AUTH_TOKEN)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations

