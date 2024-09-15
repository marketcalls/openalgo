import http.client
import json
import os
from database.auth_db import get_auth_token
from database.token_db import get_token , get_br_symbol, get_symbol
from broker.zebu.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data


def get_api_response(endpoint, auth, method="GET", payload=''):

    AUTH_TOKEN = auth

    api_key = os.getenv('BROKER_API_KEY')

    data = f'{{"uid": "{api_key}", "actid": "{api_key}"}}'

    if(endpoint == "/NorenWClientTP/Holdings"):
        data = f'{{"uid": "{api_key}", "actid": "{api_key}", "prd": "C"}}'

    payload = "jData=" + data + "&jKey=" + AUTH_TOKEN

    conn = http.client.HTTPSConnection("go.mynt.in")
    headers = {'Content-Type': 'application/json'}

    conn.request(method, endpoint, payload, headers)
    res = conn.getresponse()
    data = res.read()
    
    return json.loads(data.decode("utf-8"))

def get_order_book(auth):
    return get_api_response("/NorenWClientTP/OrderBook",auth,method="POST")

def get_trade_book(auth):
    return get_api_response("/NorenWClientTP/TradeBook",auth,method="POST")

def get_positions(auth):
    return get_api_response("/NorenWClientTP/PositionBook",auth,method="POST")

def get_holdings(auth):
    return get_api_response("/NorenWClientTP/Holdings",auth,method="POST")

def get_open_position(tradingsymbol, exchange, producttype,auth):
    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    positions_data = get_positions(auth)

    print(positions_data)

    net_qty = '0'

    if positions_data is None or (isinstance(positions_data, dict) and (positions_data['stat'] == "Not_Ok")):
        # Handle the case where there is no data
        print("No data available.")
        net_qty = '0'

    if positions_data and isinstance(positions_data, list):
        for position in positions_data:
            if position.get('tsym') == tradingsymbol and position.get('exch') == exchange and position.get('prd') == producttype:
                net_qty = position.get('netqty', '0')
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data,auth):
    AUTH_TOKEN = auth
    BROKER_API_KEY = os.getenv('BROKER_API_KEY')
    data['apikey'] = BROKER_API_KEY
    token = get_token(data['symbol'], data['exchange'])
    newdata = transform_data(data, token)  
    headers = {'Content-Type': 'application/json'}

    payload = "jData=" + json.dumps(newdata) + "&jKey=" + AUTH_TOKEN

    print(payload)
    conn = http.client.HTTPSConnection("go.mynt.in")
    conn.request("POST", "/NorenWClientTP/PlaceOrder", payload, headers)
    res = conn.getresponse()
    response_data = json.loads(res.read().decode("utf-8"))
    if response_data['stat'] == "Ok":
        orderid = response_data['norenordno']
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
    if positions_response is None or positions_response[0]['stat'] == "Not_Ok":
        return {"message": "No Open Positions Found"}, 200

    if positions_response:
        # Loop through each position to close
        for position in positions_response:
            # Skip if net quantity is zero
            if int(position['netqty']) == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if int(position['netqty']) > 0 else 'BUY'
            quantity = abs(int(position['netqty']))


            #get openalgo symbol to send to placeorder function
            symbol = get_symbol(position['token'],position['exch'])
            print(f'The Symbol is {symbol}')

            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position['exch'],
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position['prd']),
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
    data = {"uid": api_key, "norenordno": orderid}
    

    payload = "jData=" + json.dumps(data) + "&jKey=" + AUTH_TOKEN
    # Set up the request headers
    headers = {'Content-Type': 'application/json'}

    

    
    # Establish the connection and send the request
    conn = http.client.HTTPSConnection("go.mynt.in")  # Adjust the URL as necessary
    conn.request("POST", "/NorenWClientTP/CancelOrder", payload, headers)
    res = conn.getresponse()
    data = json.loads(res.read().decode("utf-8"))
    print(data)
    
    # Check if the request was successful
    if data.get("stat")=='Ok':
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
    data["apikey"] = api_key

    transformed_data = transform_modify_order_data(data, token)  # You need to implement this function
    # Set up the request headers
    headers = {'Content-Type': 'application/json'}
    payload = "jData=" + json.dumps(transformed_data) + "&jKey=" + AUTH_TOKEN


    conn = http.client.HTTPSConnection("go.mynt.in")
    conn.request("POST", "/NorenWClientTP/ModifyOrder", payload, headers)
    res = conn.getresponse()
    response = json.loads(res.read().decode("utf-8"))

    if response.get("stat")=='Ok':
        return {"status": "success", "orderid": data["orderid"]}, 200
    else:
        return {"status": "error", "message": response.get("emsg", "Failed to modify order")}, res.status



def cancel_all_orders_api(data,auth):
    # Get the order book

    AUTH_TOKEN = auth
    

    order_book_response = get_order_book(AUTH_TOKEN)
    #print(order_book_response)
    if order_book_response is None:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response
                        if order['status'] in ['OPEN', 'TRIGGER PENDING']]
    #print(orders_to_cancel)
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['norenordno']
        cancel_response, status_code = cancel_order(orderid,auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations

