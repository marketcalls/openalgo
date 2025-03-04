import http.client
import json
import os
import urllib.parse
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_oa_symbol
from broker.paytm.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data



def get_api_response(endpoint, auth, method="GET", payload=''):
    
    AUTH_TOKEN = auth
    conn = http.client.HTTPSConnection("developer.paytmmoney.com")
    headers = {
        'x-jwt-token': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    conn.request(method, endpoint, payload, headers)
    res = conn.getresponse()
    data = res.read()
    return json.loads(data.decode("utf-8"))

def get_order_book(auth):
    return get_api_response("/orders/v1/user/orders",auth)

#PAYTM does not provide all tradebook details. every tradebook call needs orderID
def get_trade_book(auth):
    return get_api_response("/orders/v1/user/orders",auth)

def get_positions(auth):
    return get_api_response("/orders/v1/position",auth)

def get_holdings(auth):
    return get_api_response("/holdings/v1/get-user-holdings-data",auth)

def get_open_position(tradingsymbol, exchange, product,auth):

    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    

    positions_data = get_positions(auth)
    net_qty = '0'
    #print(positions_data['data']['net'])

    if positions_data and positions_data.get('status') and positions_data.get('data'):
        for position in positions_data['data']['net']:
            if position.get('tradingsymbol') == tradingsymbol and position.get('exchange') == exchange and position.get('product') == product:
                net_qty = position.get('quantity', '0')
                print(f'Net Quantity {net_qty}')
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data,auth):
    
    AUTH_TOKEN = auth
    conn = http.client.HTTPSConnection("developer.paytmmoney.com")
    headers = {
        'x-jwt-token': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    
    payload = transform_data(data)  

    payload = json.dumps(payload)

    #payload =  urllib.parse.urlencode(payload)
    print(payload)

    conn.request("POST", "/orders/v1/place/regular", payload, headers)
    res = conn.getresponse()
    response_data = json.loads(res.read().decode("utf-8"))


    print(response_data)

    if response_data['status'] == 'success':
        orderid = response_data['data'][0]['order_no']
    else:
        orderid = None
    return res, response_data, orderid


def close_all_positions(current_api_key,auth):

    AUTH_TOKEN = auth
    # Fetch the current open positions
    positions_response = get_positions(AUTH_TOKEN)

    #print(positions_response)
    # Check if the positions data is null or empty
    if positions_response['data'] is None or not positions_response['data']:
        return {"message": "No Open Positions Found"}, 200

    if positions_response['status']:
        # Loop through each position to close
        for position in positions_response['data']['net']:
            # Skip if net quantity is zero
            if int(position['quantity']) == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if int(position['quantity']) > 0 else 'BUY'
            quantity = abs(int(position['quantity']))

            #Get OA Symbol before sending to Place Order
            symbol = get_oa_symbol(position['tradingsymbol'],position['exchange'])
            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position['exchange'],
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position['exchange'],position['product']),
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
    
    # Set up the request headers
    headers = {
        'X-Kite-Version': '3',
        'Authorization': f'token {AUTH_TOKEN}',
    }
    
    # Prepare the payload
    payload = ''
    
    # Establish the connection and send the request
    conn = http.client.HTTPSConnection("api.kite.trade")  # Adjust the URL as necessary
    conn.request("DELETE", f"/orders/regular/{orderid}", payload, headers)
    res = conn.getresponse()
    data = json.loads(res.read().decode("utf-8"))
    print(data)
    
    # Check if the request was successful
    if data.get("status"):
        # Return a success response
        return {"status": "success", "orderid": data['data']['order_id']}, 200
    else:
        # Return an error response
        return {"status": "error", "message": data.get("message", "Failed to cancel order")}, res.status


def modify_order(data,auth):

    

    AUTH_TOKEN = auth
    
    newdata = transform_modify_order_data(data)  # You need to implement this function
    
  
    # Set up the request headers
    headers = {
        'X-Kite-Version': '3',
        'Authorization': f'token {AUTH_TOKEN}',
        'Content-Type': 'application/x-www-form-urlencoded' 
    }
    payload = {
        'order_type': newdata['order_type'],
        'quantity': newdata['quantity'],
        'price': newdata['price'],
        'trigger_price': newdata['trigger_price'],
        'disclosed_quantity': newdata['disclosed_quantity'],
        'validity': newdata['validity']
      }

    print(payload)

    payload =  urllib.parse.urlencode(payload)

    conn = http.client.HTTPSConnection("api.kite.trade")
    conn.request("PUT", f"/orders/regular/{data['orderid']}", payload, headers)
    res = conn.getresponse()
    data = json.loads(res.read().decode("utf-8"))
    print(data)

    if data.get("status") == "success" or data.get("message") == "SUCCESS":
        return {"status": "success", "orderid": data["data"]["order_id"]}, 200
    else:
        return {"status": "error", "message": data.get("message", "Failed to modify order")}, res.status
    

def cancel_all_orders_api(data,auth):

    AUTH_TOKEN = auth
    # Get the order book
    order_book_response = get_order_book(AUTH_TOKEN)
    #print(order_book_response)
    if order_book_response['status'] != 'success':
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response.get('data', [])
                        if order['status'] in ['OPEN', 'TRIGGER PENDING']]
    print(orders_to_cancel)
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['order_id']
        cancel_response, status_code = cancel_order(orderid,AUTH_TOKEN)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations

