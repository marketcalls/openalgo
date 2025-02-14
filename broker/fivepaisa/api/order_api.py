import http.client
import json
import os
from database.auth_db import get_auth_token
from database.token_db import get_token , get_br_symbol, get_symbol, get_oa_symbol
from broker.fivepaisa.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data
from broker.fivepaisa.mapping.transform_data import map_exchange, map_exchange_type, reverse_map_exchange

# Retrieve the BROKER_API_KEY and BROKER_API_SECRET environment variables
broker_api_key = os.getenv('BROKER_API_KEY')
api_secret = os.getenv('BROKER_API_SECRET')
api_key, user_id, client_id  = broker_api_key.split(':::')

json_data = {
        "head": {
            "key": api_key
        },
        "body": {
            "ClientCode": client_id
        }
    }

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
    payload = json.dumps(json_data)
    return get_api_response("/VendorsAPI/Service1.svc/V3/OrderBook",auth,method="POST",payload=payload)

def get_trade_book(auth):
    payload = json.dumps(json_data)
    return get_api_response("/VendorsAPI/Service1.svc/V1/TradeBook",auth,method="POST",payload=payload)

def get_positions(auth):
    payload = json.dumps(json_data)
    return get_api_response("/VendorsAPI/Service1.svc/V2/NetPositionNetWise",auth,method="POST",payload=payload)

def get_holdings(auth):
    payload = json.dumps(json_data)
    return get_api_response("/VendorsAPI/Service1.svc/V3/Holding",auth,method="POST",payload=payload)

def get_open_position(tradingsymbol, exchange, Exch,ExchType , producttype,auth):
    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    token = int(get_token(tradingsymbol, exchange))  # Convert token to integer
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    positions_data = get_positions(auth)
    print("Token : ",token)
    print("Product Type : ",producttype)
    print(positions_data)



    net_qty = '0'

    if positions_data and positions_data.get('body'):
        for position in positions_data['body']['NetPositionDetail']:

            if position.get('ScripCode') == token and position.get('Exch') == Exch and position.get('ExchType') == ExchType and position.get('OrderFor') == producttype:
                net_qty = position.get('NetQty', '0')
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data,auth):
    AUTH_TOKEN = auth
    

    token = get_token(data['symbol'], data['exchange'])
    newdata = transform_data(data, token)  
    headers = {
        'Content-Type': 'application/json',
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

    exch = map_exchange(exchange)
    exchtype = map_exchange_type(exchange)




    # Get current open position for the symbol
    current_position = int(get_open_position(symbol, exchange, exch, exchtype, map_product_type(product),AUTH_TOKEN))


    print(f"position_size : {position_size}") 
    print(f"Open Position : {current_position}") 
    
    # Determine action based on position_size and current_position
    action = None
    quantity = 0


    # If both position_size and current_position are 0, do nothing
    if position_size == 0 and current_position == 0 and int(data['quantity'])!=0:
        action = data['action']
        quantity = data['quantity']
        #print(f"action : {action}")
        #print(f"Quantity : {quantity}")
        res, response, orderid = place_order_api(data,AUTH_TOKEN)
        #print(res)
        #print(response)
        
        return res , response, orderid
        
    elif position_size == current_position:
        if int(data['quantity'])==0:
            response = {"status": "success", "message": "No OpenPosition Found. Not placing Exit order."}
        else:
            response = {"status": "success", "message": "No action needed. Position size matches current position"}
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
    print(positions_response)
    # Check if the positions data is null or empty
    if positions_response['body']['NetPositionDetail'] is None or not positions_response['body']['NetPositionDetail']:
        return {"message": "No Open Positions Found"}, 200

    if positions_response['body']['NetPositionDetail']:
        # Loop through each position to close
        for position in positions_response['body']['NetPositionDetail']:
            # Skip if net quantity is zero
            if int(position['NetQty']) == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if int(position['NetQty']) > 0 else 'BUY'
            quantity = abs(int(position['NetQty']))

            exchange = reverse_map_exchange(position['Exch'],position['ExchType'])
            #get openalgo symbol to send to placeorder function
    
            symbol = get_symbol(position['ScripCode'],exchange)

            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": exchange,
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position['OrderFor'],exchange),
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
    AUTH_TOKEN = auth

    # First get the order details from orderbook
    orderbook_data = get_order_book(AUTH_TOKEN)
    
    # Find the order with matching BrokerOrderId and get its ExchOrderID
    exch_order_id = None
    order_data = None
    if orderbook_data and orderbook_data.get('body') and orderbook_data['body'].get('OrderBookDetail'):
        for order in orderbook_data['body']['OrderBookDetail']:
            if str(order.get('BrokerOrderId')) == str(orderid):
                exch_order_id = order.get('ExchOrderID')
                order_data = order
                break
    
    if not exch_order_id:
        return {"status": "error", "message": f"Order {orderid} not found in orderbook"}

    headers = {
      'Authorization': f'bearer {AUTH_TOKEN}',
      'Content-Type': 'application/json'

    }

    # Prepare the payload
    json_data = {
        "head": {
            "key": api_key
        },
        "body": {
                "ExchOrderID": exch_order_id,
        }
    }

    payload = json.dumps(json_data)

    print(payload)
    
    # Establish the connection and send the request
    conn = http.client.HTTPSConnection("Openapi.5paisa.com")  # Adjust the URL as necessary
    conn.request("POST", "/VendorsAPI/Service1.svc/V1/CancelOrderRequest", payload, headers)
    res = conn.getresponse()
    data = json.loads(res.read().decode("utf-8"))
    print(data)
    
    # Check if the request was successful
    if  data["head"]["status"]=='0' and data["body"]["Status"]==0 :
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Return an error response
        return {"status": "error", "message": data.get('body', {}).get('Message', 'Failed to cancel order')}, res.status


def modify_order(data,auth):

    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    transformed_data = transform_modify_order_data(data)  # You need to implement this function
    # Set up the request headers

    headers = {
      'Authorization': f'bearer {AUTH_TOKEN}',
      'Content-Type': 'application/json',
    }

    # Prepare the payload
    json_data = {
            "head": {
                "key": api_key
            },
            "body": transformed_data
        }

    payload = json.dumps(json_data)
    print(payload)

    conn = http.client.HTTPSConnection("Openapi.5paisa.com")
    conn.request("POST", "/VendorsAPI/Service1.svc/V1/ModifyOrderRequest", payload, headers)
    res = conn.getresponse()
    data = json.loads(res.read().decode("utf-8"))
    response = print(f'The response is {data}')

    if data['body']['Message'] == "Success" or data['body']['Message'] == "SUCCESS":
        return {"status": "success", "orderid": data["body"]["BrokerOrderID"]}, 200
    else:
        return {"status": "error", "message":  data.get('body', {}).get('Message', 'Failed to Modify order')}, res.status



def cancel_all_orders_api(data,auth):
    # Get the order book

    AUTH_TOKEN = auth
    

    order_book_response = get_order_book(AUTH_TOKEN)
    #print(order_book_response)
    if order_book_response['body']['OrderBookDetail'] is None:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response['body']['OrderBookDetail']
                        if order['OrderStatus'] in ['Pending','Modified']]
    #print(orders_to_cancel)
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['BrokerOrderId']
        cancel_response, status_code = cancel_order(orderid,auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations
