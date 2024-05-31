import http.client
import json
import urllib.parse
import os
from database.auth_db import get_auth_token
from database.token_db import get_token , get_br_symbol, get_symbol
from broker.kotak.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data, reverse_map_exchange,map_exchange


def get_api_response(endpoint, auth, method="GET", payload=''):

    AUTH_TOKEN = auth


    access_token_parts = AUTH_TOKEN.split(":::")
    token = access_token_parts[0]
    sid = access_token_parts[1]
    
    api_secret = os.getenv('BROKER_API_SECRET')
    print(api_secret) 
    conn = http.client.HTTPSConnection("gw-napi.kotaksecurities.com")
    payload = ''
    headers = {
    'accept': 'application/json',
    'Sid': sid,
    'Auth': token,
    'neo-fin-key': 'neotradeapi',
    'Authorization': f'Bearer {api_secret}'
    }
    conn.request(method, endpoint, payload, headers)
    res = conn.getresponse()
    data = res.read()
    print(data.decode("utf-8"))
        
    return json.loads(data.decode("utf-8"))

def get_order_book(auth):
    return get_api_response("/Orders/2.0/quick/user/orders?sId=server1",auth)

def get_trade_book(auth):
    return get_api_response("/Orders/2.0/quick/user/trades?sId=server1",auth)

def get_positions(auth):
    return get_api_response("/Orders/2.0/quick/user/positions?sId=server1",auth)

def get_holdings(auth):
    return get_api_response("/Portfolio/1.0/portfolio/v1/holdings?alt=false",auth)

def get_open_position(tradingsymbol, exchange, producttype,auth):
    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    positions_data = get_positions(auth)
    print(positions_data)
    
    net_qty = '0'
    exchange = reverse_map_exchange(exchange)
    
    if positions_data.get('data'):
        for position in positions_data['data']:
            if position.get('trdSym') == tradingsymbol and position.get('exSeg') == exchange and position.get('prod') == producttype:
                net_qty = (int(position.get('flBuyQty', 0)) - int(position.get('flSellQty', 0)))+(int(position.get('cfBuyQty', 0)) - int(position.get('cfSellQty', 0)))
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data,auth):
    AUTH_TOKEN = auth
    access_token_parts = AUTH_TOKEN.split(":::")
    auth_token_broker = access_token_parts[0]
    sid = access_token_parts[1]
    
    api_secret = os.getenv('BROKER_API_SECRET')
    
    conn = http.client.HTTPSConnection("gw-napi.kotaksecurities.com")
    token = get_token(data['symbol'], data['exchange'])
    newdata = transform_data(data, token)  
    
    
    json_string = json.dumps(newdata)
    print(json_string)
    payload = urllib.parse.quote(json_string)
    payload = f'jData={payload}'
    
    headers = {
    'accept': 'application/json',
    'Sid': sid,
    'Auth': auth_token_broker,
    'neo-fin-key': 'neotradeapi',
    'Authorization': f'Bearer {api_secret}',
    'Content-Type': 'application/x-www-form-urlencoded'
    
    }
    
    conn.request("POST", "/Orders/2.0/quick/order/rule/ms/place?sId=server1", payload, headers)
    res = conn.getresponse()
    data = res.read()
    
    response_data = data.decode("utf-8")
    response_data = json.loads(response_data)
    print(response_data)
    if response_data['stat'] == 'Ok':
        orderid = response_data['nOrdNo']
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
    #print(positions_response)
    # Check if the positions data is null or empty
    if positions_response['data'] is None or not positions_response['data']:
        return {"message": "No Open Positions Found"}, 200

    if positions_response['data']:
        # Loop through each position to close
        for position in positions_response['data']:
            # Skip if net quantity is zero
            net_qty = (int(position.get('flBuyQty', 0)) - int(position.get('flSellQty', 0)))+(int(position.get('cfBuyQty', 0)) - int(position.get('cfSellQty', 0)))
            if net_qty == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if net_qty > 0 else 'BUY'
            quantity = abs(net_qty)


            #get openalgo symbol to send to placeorder function
            symboltoken = position['tok']
            exchange = map_exchange(position['exSeg'])
            position['exSeg'] = exchange
            
            
            # Use the get_symbol function to fetch the symbol from the database
            symbol = get_symbol(symboltoken, exchange)  
            
            print(f'The Symbol is {symbol}')

            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position['exSeg'],
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position['prod']),
                "quantity": str(quantity)
            }

            print(place_order_payload)

            # Place the order to close the position
            res, response, orderid =   place_order_api(place_order_payload,auth)

            print(res)
            print(response)
            print(orderid)


            
            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid,auth):
    AUTH_TOKEN = auth
    access_token_parts = AUTH_TOKEN.split(":::")
    auth_token_broker = access_token_parts[0]
    sid = access_token_parts[1]
    
    api_secret = os.getenv('BROKER_API_SECRET')
    
    conn = http.client.HTTPSConnection("gw-napi.kotaksecurities.com")
    orderid = {"on":orderid}
    
    json_string = json.dumps(orderid)
    print(json_string)
    payload = urllib.parse.quote(json_string)
    payload = f'jData={payload}'
    
    headers = {
    'accept': 'application/json',
    'Sid': sid,
    'Auth': auth_token_broker,
    'neo-fin-key': 'neotradeapi',
    'Authorization': f'Bearer {api_secret}',
    'Content-Type': 'application/x-www-form-urlencoded'
    
    }
    
    conn.request("POST", "/Orders/2.0/quick/order/cancel?sId=server1", payload, headers)
    res = conn.getresponse()
    data = res.read()
    response_data = data.decode("utf-8")
    response_data = json.loads(response_data)
    print(response_data)
    # Check if the request was successful
    if response_data.get("stat"):
        # Return a success response
        return {"status": "success", "orderid": response_data.get("result")}, 200
    else:
        # Return an error response
        return {"status": "error", "message": response_data.get("message", "Failed to cancel order")}, res.status


def modify_order(data,auth):

    AUTH_TOKEN = auth
    access_token_parts = AUTH_TOKEN.split(":::")
    auth_token_broker = access_token_parts[0]
    sid = access_token_parts[1]
    
    api_secret = os.getenv('BROKER_API_SECRET')
    
    conn = http.client.HTTPSConnection("gw-napi.kotaksecurities.com")
    token = get_token(data['symbol'], data['exchange'])
    print(data)
    print(token)
    newdata = transform_modify_order_data(data, token)  
    
    
    json_string = json.dumps(newdata)
    print(json_string)
    payload = urllib.parse.quote(json_string)
    payload = f'jData={payload}'
    
    headers = {
    'accept': 'application/json',
    'Sid': sid,
    'Auth': auth_token_broker,
    'neo-fin-key': 'neotradeapi',
    'Authorization': f'Bearer {api_secret}',
    'Content-Type': 'application/x-www-form-urlencoded'
    
    }
    
    conn.request("POST", "/Orders/2.0/quick/order/vr/modify?sId=server1", payload, headers)
    res = conn.getresponse()
    data = res.read()
    
    response_data = data.decode("utf-8")
    response_data = json.loads(response_data)
    print(response_data)
    if response_data.get("stat") == "Ok":
        return {"status": "success", "orderid": response_data["nOrdNo"]}, 200
    else:
        return {"status": "error", "message": response_data.get("message", "Failed to modify order")}, res.status


def cancel_all_orders_api(data,auth):
    # Get the order book

    AUTH_TOKEN = auth
    

    order_book_response = get_order_book(AUTH_TOKEN)
    
    if order_book_response['data'] is None:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response.get('data', [])
                        if order['ordSt'] in ['open', 'trigger pending']]
    #print(orders_to_cancel)
    canceled_orders = []
    failed_cancellations = []
    print(orders_to_cancel)
    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['nOrdNo']
        cancel_response, status_code = cancel_order(orderid,auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations

