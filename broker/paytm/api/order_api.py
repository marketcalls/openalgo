import json
import os
import urllib.parse
import httpx
from utils.httpx_client import get_httpx_client
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_oa_symbol
from broker.paytm.mapping.transform_data import (
    transform_data,
    map_product_type,
    reverse_map_product_type,
    transform_modify_order_data,
    map_exchange,
    reverse_map_order_type
)


def get_api_response(endpoint, auth, method="GET", payload='', max_retries=3, retry_delay=2):
    base_url = "https://developer.paytmmoney.com"
    headers = {
        'x-jwt-token': auth,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    client = get_httpx_client()
    
    for attempt in range(max_retries):
        try:
            if method == "GET":
                response = client.get(f"{base_url}{endpoint}", headers=headers, timeout=30.0)
            else:
                response = client.post(f"{base_url}{endpoint}", headers=headers, content=payload, timeout=30.0)

            # Try to parse response JSON even if status code is error
            try:
                response_json = response.json()
            except Exception:
                response_json = {}

            # Check if it's an error response
            if not response.is_success:
                error_msg = response_json.get('message', response.text)
                print(f"API Error: Status {response.status_code} - {error_msg}")
                # Don't retry on 4xx errors as they are client errors
                if response.status_code < 500:
                    return {
                        "status": "error", 
                        "message": error_msg,
                        "error_code": response.status_code,
                        "response": response_json
                    }
                raise httpx.HTTPError(f"HTTP {response.status_code}")

            return response_json

        except (httpx.RequestError, httpx.HTTPError) as e:
            print(f"Request error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(retry_delay)
                continue
            return {"status": "error", "message": "Request failed after retries", "error": str(e)}

        except Exception as e:
            print(f"Unexpected error: {e}")
            return {"status": "error", "message": "Unexpected error", "error": str(e)}

def get_order_book(auth):
    return get_api_response("/orders/v1/user/orders", auth)

# PAYTM does not provide all tradebook details. every tradebook call needs orderID


def get_trade_book(auth):
    return get_api_response("/orders/v1/user/orders", auth)


def get_positions(auth):
    return get_api_response("/orders/v1/position", auth)


def get_holdings(auth):
    return get_api_response("/holdings/v1/get-user-holdings-data", auth)


def get_open_position(tradingsymbol, exchange, product, auth):

    # Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)

    positions_data = get_positions(auth)
    net_qty = '0'
    # print(positions_data['data']['net'])

    if positions_data and positions_data.get('status') and positions_data.get('data'):
        for position in positions_data['data']['net']:
            if position.get('tradingsymbol') == tradingsymbol and position.get('exchange') == exchange and position.get('product') == product:
                net_qty = position.get('quantity', '0')
                print(f'Net Quantity {net_qty}')
                break  # Assuming you need the first match

    return net_qty


def place_order_api(data, auth):
    payload = transform_data(data)
    payload = json.dumps(payload)
    print(f"Order payload: {payload}")

    response = get_api_response(
        endpoint="/orders/v1/place/regular",
        auth=auth,
        method="POST",
        payload=payload
    )

    print(f"Response: {response}")

    # Create a response object with status code
    res = type('Response', (), {'status': 200 if response.get('status') == 'success' else 500})()
    
    if response.get('status') == 'success':
        orderid = response['data'][0]['order_no']
    else:
        orderid = None

    return res, response, orderid

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
    
def close_all_positions(current_api_key, auth):

    AUTH_TOKEN = auth
    # Fetch the current open positions
    positions_response = get_positions(AUTH_TOKEN)

    print(f"Positions retrieved response : {positions_response}")
    
    # First check if the API request was successful
    if positions_response.get('status') == 'error':
        return {"status": "error", "message": positions_response.get('message', 'Failed to fetch positions')}, 500
        
    # Check if the positions data is null or empty
    if not positions_response.get('data'):
        return {"status": "success", "message": "No Open Positions Found"}, 200

    if positions_response['status'] == 'success':
        # Loop through each position to close
        for position in positions_response['data']:
            # Skip if net quantity is zero
            if int(position['net_qty']) == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if int(position['net_qty']) > 0 else 'BUY'
            quantity = abs(int(position['net_qty']))

            # Use security_id directly as it's already in Paytm's format
            security_id = position.get('security_id')
            if not security_id:
                print(f"Skipping position due to missing security_id: {position}")
                continue

            # Create order payload directly in Paytm's format
            txn_type = "S" if action == "SELL" else "B"
            segment = "E" if position['exchange'] in ['NSE', 'BSE'] else "D"
            
            order_payload = {
                "security_id": security_id,
                "exchange": position['exchange'],
                "txn_type": txn_type,
                "order_type": "MKT",  # Market order
                "quantity": str(quantity),
                "product": position['product'],
                "price": "0",
                "validity": "DAY",
                "segment": segment,
                "source": "M"
            }
            
            print(f"Placing Order: {order_payload}")
            
            # Place the order directly without transform
            response = get_api_response(
                endpoint="/orders/v1/place/regular",
                auth=AUTH_TOKEN,
                method="POST",
                payload=json.dumps(order_payload)
            )
            
            print(f"Order Response: {response}")
            
            if response.get('status') != 'success':
                print(f"Failed to close position for {security_id}: {response.get('message')}")
                continue

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    orders_list = get_order_book(auth)
    for order in orders_list['data']:
        if order['order_no'] == orderid:
            if order['status'] == 'Pending':
                print("Cancelling order:", orderid)
                payload = json.dumps({
                    "order_no": orderid,
                    "source": "N",
                    "txn_type": order['txn_type'],
                    "exchange": order['exchange'],
                    "segment": order['segment'],
                    "product": order['product'],
                    "security_id": order['security_id'],
                    "quantity": order['quantity'],
                    "validity": order['validity'],
                    "order_type": order['order_type'],
                    "price": order['price'],
                    "off_mkt_flag": order['off_mkt_flag'],
                    "mkt_type": order['mkt_type'],
                    "serial_no": order['serial_no'],
                    "group_id": order['group_id'],
                })

                response = get_api_response(
                    endpoint="/orders/v1/cancel/regular",
                    auth=auth,
                    method="POST",
                    payload=payload
                )

                if response.get("status"):
                    # Return a success response
                    return {"status": "success", "orderid": response['data'][0]['order_no']}, 200
                else:
                    # Return an error response
                    return {"status": "error", "message": response.get("message", "Failed to cancel order")}, 500

# As long as an order is pending in the system, certain attributes of it can be modified.
# Price, quantity, validity, product are some of the variables that can be modified by the user.
# You have to pass "order_no", "serial_no" "group_id" as compulsory to modify the order.


def modify_order(data, auth):
    orderid = data['orderid']
    orders_list = get_order_book(auth)
    
    if not orders_list or 'data' not in orders_list:
        return {"status": "error", "message": "Failed to fetch order book"}, 500
        
    order_found = False
    for order in orders_list['data']:
        if order['order_no'] == orderid:
            order_found = True
            if order['status'] != 'Pending':
                return {"status": "error", "message": f"Order {orderid} is not in Pending status"}, 400
                
            print("Modifying order:", orderid)
            
            # Prepare modification payload
            payload = {
                "order_no": orderid,
                "exchange": order['exchange'],
                "segment": order['segment'],
                "security_id": order['security_id'],
                "quantity": data.get('quantity', order['quantity']),
                "price": data.get('price', order['price']),
                "trigger_price": data.get('trigger_price', order.get('trigger_price', '0')),
                "validity": "DAY",
                "product": reverse_map_product_type(data.get('product', order['product'])),
                "order_type": order['order_type'],
                "txn_type": order['txn_type'],
                "source": "N",
                "off_mkt_flag": order.get('off_mkt_flag', 'N'),
                "serial_no": order['serial_no'],
                "group_id": order['group_id']
            }
            
            print(f"Modification payload: {payload}")
            
            response = get_api_response(
                endpoint="/orders/v1/modify/regular",
                auth=auth,
                method="POST",
                payload=json.dumps(payload)
            )
            
            print(f"Modification response: {response}")
            
            response = get_api_response(
                endpoint="/orders/v1/modify/regular",
                auth=auth,
                method="POST",
                payload=json.dumps(payload)
            )
            
            print(f"Modify order response: {response}")

            if response.get("status") == "success":
                return {
                    "status": "success",
                    "message": "Order modified successfully",
                    "orderid": response['data'][0].get('order_no', orderid)
                }, 200
            else:
                return {
                    "status": "error",
                    "message": response.get("message", "Failed to modify order")
                }, 500
                
    if not order_found:
        return {"status": "error", "message": f"Order {orderid} not found"}, 404
        return {"status": "error", "message": f"Order {orderid} not found"}, 404


def cancel_all_orders_api(data, auth):
    # Get the order book
    order_book_response = get_order_book(auth)
    if order_book_response['status'] != 'success':
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response.get('data', [])
                        if order['status'] in ['Pending']]
    print(orders_to_cancel)
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['order_no']
        cancel_response, status_code = cancel_order(orderid, auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
