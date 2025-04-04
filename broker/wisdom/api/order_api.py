import json
import os
from tokenize import Token
import httpx
from database.auth_db import get_auth_token
from database.token_db import get_token , get_br_symbol, get_symbol
from broker.wisdom.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data
from utils.httpx_client import get_httpx_client
from broker.wisdom.baseurl import INTERACTIVE_URL

def get_api_response(endpoint, auth, method="GET",  payload=''):
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_KEY')

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
      'authorization': AUTH_TOKEN,
      'Content-Type': 'application/json',
    }
    
    url = f"{INTERACTIVE_URL}{endpoint}"

    #print("Request URL:", url)
    #print("Headers:", headers)
    #print("Payload:", json.dumps(payload, indent=2) if payload else "None")
    
    if method == "GET":
        response = client.get(url, headers=headers)
    elif method == "POST":
        response = client.post(url, headers=headers, json=payload)
    else:
        response = client.request(method, url, headers=headers, json=payload)
    
    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code
    #print(f"Response Status Code: {response.status_code}")
    #print(f"Response Content: {response.text}")
    return response.json()

def get_order_book(auth):
    return get_api_response("/orders",auth)

def get_trade_book(auth):
    return get_api_response("/orders/trades",auth)

def get_positions(auth):
    return get_api_response("/portfolio/positions?dayOrNet=NetWise",auth)

def get_holdings(auth):
    return get_api_response("/portfolio/holdings",auth)

def get_open_position(tradingsymbol, exchange, producttype,auth):
    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    positions_data = get_positions(auth)

    net_qty = '0'

    if positions_data and positions_data.get('status') and positions_data.get('data'):
        for position in positions_data['data']:
            if position.get('tradingsymbol') == tradingsymbol and position.get('exchange') == exchange and position.get('producttype') == producttype:
                net_qty = position.get('Quantity', '0')
                #print(f"Net Quantity: {net_qty}")
                break  # Assuming you need the first match
        
    return net_qty

def place_order_api(data,auth):
    AUTH_TOKEN = auth   
    print(f"Data: {data}")

    # Check if this is a direct instrument ID payload or needs transformation
    if all(key in data for key in ['exchangeSegment', 'exchangeInstrumentID', 'productType', 'orderType']):
        newdata = data
    else:
        # Traditional symbol-based payload that needs transformation
        token = get_token(data['symbol'], data['exchange'])
        print(f"token: {token}")
        newdata = transform_data(data, token)

    headers = {
        'authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
    }
   
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    # Make the request using the shared client
    response = client.post(
        f"{INTERACTIVE_URL}/orders",
        headers=headers,
        json=newdata
    )
    
    # Add status attribute for compatibility
    response.status = response.status_code
    
    # Parse the JSON response
    try:
        response_data = response.json()
    except json.JSONDecodeError:
        response_data = {"error": "Invalid JSON response from server", "raw_response": response.text}

    orderid = response_data.get("result", {}).get("AppOrderID") if response_data.get("type") == "success" else None
    
    return response, response_data, orderid


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
    print(f"Open_positions : {positions_response}")

    positions_list = positions_response.get('result', {}).get('positionList', [])
    if not positions_list:
        return {"message": "No Open Positions Found"}, 200

    # If response has positions
    for position in positions_list:
        # Skip if net quantity is zero
        if int(position['Quantity']) == 0:
            continue

        # Determine action based on net quantity
        action = 'SELL' if int(position['Quantity']) > 0 else 'BUY'
        quantity = abs(int(position['Quantity']))

        exchange_segment = position['ExchangeSegment']
        instrument_id = position['ExchangeInstrumentId']
        
        print(f'Exchange Segment: {exchange_segment}')
        print(f'Exchange Instrument ID: {instrument_id}')

        # Prepare the order payload
        place_order_payload = {
            "exchangeSegment": exchange_segment,
            "exchangeInstrumentID": instrument_id,
            "productType": position['ProductType'],
            "orderType": "MARKET",
            "orderSide": action,
            "timeInForce": "DAY",
            "disclosedQuantity": "0",
            "orderQuantity": str(quantity),
            "limitPrice": "0",
            "stopPrice": "0",
            "orderUniqueIdentifier": "openalgo"
        }

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
    
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    #print(orderid)
    # Set up the request headers
    headers = {
        'authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
    }
    
    # Prepare the payload
    payload = json.dumps({
        "appOrderID": orderid,
        "orderUniqueIdentifier": "openalgo"
    })
    
    # Make the request using the shared client
    response = client.delete(
    f"{INTERACTIVE_URL}/orders?appOrderID={orderid}",
    headers=headers
)
    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code
    
    data = json.loads(response.text)
    
    # Check if the request was successful
    if data.get("status"):
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Return an error response
        return {"status": "error", "message": data.get("message", "Failed to cancel order")}, response.status


def modify_order(data,auth):

    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    token = get_token(data['symbol'], data['exchange'])
    data['symbol'] = get_br_symbol(data['symbol'],data['exchange'])

    transformed_data = transform_modify_order_data(data, token)  # You need to implement this function
    # Set up the request headers
    headers = {
        'authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
    }
    payload = json.dumps(transformed_data)

    # Make the request using the shared client
    response = client.put(f"{INTERACTIVE_URL}/orders",
        headers=headers,
        content=payload
    )
    
    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code
    print(f'Response of modify order :{response.status}')
    data = json.loads(response.text)

    if data.get("status") == "true" or data.get("message") == "SUCCESS":
        return {"status": "success", "orderid": data["data"]["orderid"]}, 200
    else:
        return {"status": "error", "message": data.get("message", "Failed to modify order")}, response.status


def cancel_all_orders_api(data,auth):
    # Get the order book

    AUTH_TOKEN = auth
    

    order_book_response = get_order_book(AUTH_TOKEN)
    print(f"Order book response: {order_book_response}")
    if order_book_response.get("type") != "success":
        return [], []  # Return empty lists indicating failure to retrieve the order book
    
    orders = order_book_response.get("result", [])

     # Filter orders that are in 'open' or 'trigger_pending' state
    #print(f"Orders: {orders}")
    orders_to_cancel = [
        order for order in orders 
        if order["OrderStatus"] in ["New", "Trigger Pending"]
    ]
    print(f"Orders to cancel: {orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['AppOrderID']
        cancel_response, status_code = cancel_order(orderid,auth)
        if status_code == 200:
            print(f"Canceled order {orderid}")
            canceled_orders.append(orderid)
        else:
            print(f"Failed to cancel order {orderid}")
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations
