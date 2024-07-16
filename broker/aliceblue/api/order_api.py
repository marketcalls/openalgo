import http.client
import json
import os
import urllib.parse
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_oa_symbol
from broker.aliceblue.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data
from utils.config import get_broker_api_key , get_broker_api_secret


def get_api_response(endpoint, auth, method="GET", payload=''):
    
    AUTH_TOKEN = auth
    conn = http.client.HTTPSConnection("ant.aliceblueonline.com")
    headers = {
    'Authorization': f'Bearer {get_broker_api_key()} {AUTH_TOKEN}',
    'Content-Type': 'application/json'
    }
    
    conn.request(method, endpoint, payload, headers)
    res = conn.getresponse()
    data = res.read()
    print(data)
    return json.loads(data.decode("utf-8"))

def get_order_book(auth):

    return get_api_response("/rest/AliceBlueAPIService/api/placeOrder/fetchOrderBook",auth)

def get_trade_book(auth):

    return get_api_response("/rest/AliceBlueAPIService/api/placeOrder/fetchTradeBook",auth)

def get_positions(auth):
    payload = json.dumps({
    "ret": "NET"
    })
    
    return get_api_response("/rest/AliceBlueAPIService/api/positionAndHoldings/positionBook",auth,"POST",payload=payload)

def get_holdings(auth):
    return get_api_response("/rest/AliceBlueAPIService/api/positionAndHoldings/holdings",auth)

def get_open_position(tradingsymbol, exchange, product,auth):

    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    

    position_data = get_positions(auth)

    if isinstance(position_data, dict):
        if position_data['stat'] == 'Not_Ok' :
            # Handle the case where there is an error in the data
            # For example, you might want to display an error message to the user
            # or pass an empty list or dictionary to the template.
            print(f"Error fetching order data: {position_data['emsg']}")
            position_data = {}
    else:
        position_data = position_data

    net_qty = '0'
    #print(positions_data['data']['net'])

    if position_data :
        for position in position_data:
            if position.get('Tsym') == tradingsymbol and position.get('Exchange') == exchange and position.get('Pcode') == product:
                net_qty = position.get('Netqty', '0')
                print(f'Net Quantity {net_qty}')
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data,auth):
    
    AUTH_TOKEN = auth

    #token = get_token(data['symbol'], data['exchange'])
    newdata = transform_data(data)
    headers = {
    'Authorization': f'Bearer {get_broker_api_key()} {AUTH_TOKEN}',
    'Content-Type': 'application/json'
    }

    payload = json.dumps([newdata])

    print(payload)

    conn = http.client.HTTPSConnection("ant.aliceblueonline.com")
    conn.request("POST", "/rest/AliceBlueAPIService/api/placeOrder/executePlaceOrder", payload, headers)
    res = conn.getresponse()
    response_data = json.loads(res.read().decode("utf-8"))


    print(response_data)
    
    response_data = response_data[0]

    if response_data['stat'] == 'Ok':
        orderid = response_data['NOrdNo']
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

    AUTH_TOKEN = auth
    # Fetch the current open positions
    positions_response = get_positions(AUTH_TOKEN)

    if isinstance(positions_response, dict):
        if positions_response['stat'] == 'Not_Ok' :
            # Handle the case where there is an error in the data
            # For example, you might want to display an error message to the user
            # or pass an empty list or dictionary to the template.
            print(f"Error fetching order data: {positions_response['emsg']}")
            positions_response = {}
    else:
        positions_response = positions_response


    #print(positions_response)
    # Check if the positions data is null or empty
    if positions_response is None or not positions_response:
        return {"message": "No Open Positions Found"}, 200



    if positions_response:
        # Loop through each position to close
        for position in positions_response:
            # Skip if net quantity is zero
            if int(position['Netqty']) == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if int(position['Netqty']) > 0 else 'BUY'
            quantity = abs(int(position['Netqty']))

            #Get OA Symbol before sending to Place Order
            symbol = get_oa_symbol(position['Tsym'],position['Exchange'])
            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position['Exchange'],
                "pricetype": "MARKET",
                "product": position['Pcode'],
                "quantity": str(quantity)
            }

            print(place_order_payload)

            # Place the order to close the position
            _, api_response, _ =   place_order_api(place_order_payload,AUTH_TOKEN)

            print(api_response)
            
            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid,auth):
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    order_book_response = get_order_book(AUTH_TOKEN)
    # Set up the request headers
    headers = {
    'Authorization': f'Bearer {get_broker_api_key()} {AUTH_TOKEN}',
    'Content-Type': 'application/json'
    }      
    Trading_symbol = ""
    Exchange = ""
    orders = (order_book_response)
    for order in orders:
        if order.get("Nstordno") == orderid:
            Trading_symbol = order.get("Trsym")
            Exchange = order.get("Exchange")

    # Prepare the payload
    payload = json.dumps({
        "exch": Exchange,
        "nestOrderNumber": orderid,
        "trading_symbol": Trading_symbol
    })
    
    # Establish the connection and send the request
    conn = http.client.HTTPSConnection("ant.aliceblueonline.com")
    conn.request("POST", "/rest/AliceBlueAPIService/api/placeOrder/cancelOrder", payload, headers)
    res = conn.getresponse()
    response_data = json.loads(res.read().decode("utf-8"))
    print(response_data)

    # Check if the request was successful
    if response_data.get("stat") == "Ok":
        # Return a success response
        return {"status": "success", "orderid": response_data["nestOrderNumber"]}, 200
    else:
        # Return an error response
        return {"status": "error", "message": response_data.get("emsg", "Failed to cancel order")}, res.status


def modify_order(data,auth):

    AUTH_TOKEN = auth
    newdata = transform_modify_order_data(data)  # You need to implement this function
    
    # Set up the request headers
    headers = {
    'Authorization': f'Bearer {get_broker_api_key()} {AUTH_TOKEN}',
    'Content-Type': 'application/json'
    }    
    payload = json.dumps(newdata)

    print(payload)

    conn = http.client.HTTPSConnection("ant.aliceblueonline.com")
    conn.request("POST", "/rest/AliceBlueAPIService/api/placeOrder/modifyOrder", payload, headers)
    res = conn.getresponse()
    response_data = json.loads(res.read().decode("utf-8"))
    print(response_data)

    if response_data.get("stat") == "Ok":
        return {"status": "success", "orderid": response_data["nestOrderNumber"]}, 200
    else:
        return {"status": "error", "message": response_data.get("emsg", "Failed to modify order")}, res.status
    

def cancel_all_orders_api(data,auth):

    AUTH_TOKEN = auth
    # Get the order book
    order_book_response = get_order_book(AUTH_TOKEN)
    #print(order_book_response)
    if isinstance(order_book_response, dict):
        if order_book_response['stat'] == 'Not_Ok':
            return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response
                        if order['Status'] in ['open', 'trigger pending']]
    print(orders_to_cancel)
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['Nstordno']
        cancel_response, status_code = cancel_order(orderid,AUTH_TOKEN)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations

