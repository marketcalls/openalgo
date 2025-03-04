import http.client
import json
import os
import urllib.parse
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_oa_symbol
from broker.paytm.mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data


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

    AUTH_TOKEN = auth
    conn = http.client.HTTPSConnection("developer.paytmmoney.com")
    headers = {
        'x-jwt-token': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    payload = transform_data(data)

    payload = json.dumps(payload)

    # payload =  urllib.parse.urlencode(payload)
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


def close_all_positions(current_api_key, auth):

    AUTH_TOKEN = auth
    # Fetch the current open positions
    positions_response = get_positions(AUTH_TOKEN)

    # print(positions_response)
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

            # Get OA Symbol before sending to Place Order
            symbol = get_oa_symbol(
                position['tradingsymbol'], position['exchange'])
            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position['exchange'],
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position['exchange'], position['product']),
                "quantity": str(quantity)
            }

            print(place_order_payload)

            # Place the order to close the position
            _, api_response, _ = place_order_api(
                place_order_payload, AUTH_TOKEN)

            print(api_response)

            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):

    AUTH_TOKEN = auth
    conn = http.client.HTTPSConnection("developer.paytmmoney.com")
    headers = {
        'x-jwt-token': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    orders_list = get_order_book(AUTH_TOKEN)
    for order in orders_list['data']:
        if order['order_no'] == orderid:
            if order['status'] == 'Pending':
                print("Cancelling order:", orderid)
                payload = json.dumps({"order_no": orderid, "source": "N",
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
                conn.request("POST", "/orders/v1/cancel/regular",
                             payload, headers)
                res = conn.getresponse()
                response_data = json.loads(res.read().decode("utf-8"))
                if response_data.get("status"):
                    # Return a success response
                    return {"status": "success", "orderid": response_data['data'][0]['order_no']}, 200
                else:
                    # Return an error response
                    return {"status": "error", "message": response_data.get("message", "Failed to cancel order")}, res.status

# As long as an order is pending in the system, certain attributes of it can be modified.
# Price, quantity, validity, product are some of the variables that can be modified by the user.
# You have to pass "order_no", "serial_no" "group_id" as compulsory to modify the order.


def modify_order(data, auth):

    AUTH_TOKEN = auth
    conn = http.client.HTTPSConnection("developer.paytmmoney.com")
    headers = {
        'x-jwt-token': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    # You need to implement this function
    orderid = data['orderid']
    newdata = transform_modify_order_data(data)
    orders_list = get_order_book(AUTH_TOKEN)
    for order in orders_list['data']:
        if order['order_no'] == orderid:
            if order['status'] == 'Pending':
                print("Modifying order:", orderid)
                payload = json.dumps({"order_no": orderid, "source": "N",
                                      "txn_type": order['txn_type'],
                                      "exchange": order['exchange'],
                                      "segment": order['segment'],
                                      "security_id": order['security_id'],
                                      "order_type": order['order_type'],
                                      "off_mkt_flag": order['off_mkt_flag'],
                                      "mkt_type": order['mkt_type'],
                                      "serial_no": order['serial_no'],
                                      "group_id": order['group_id'],
                                      "product": newdata['product'],
                                      "quantity": newdata['quantity'],
                                      "validity": newdata['validity'],
                                      "price": newdata['price'],


                                      })
                conn.request("POST", "/orders/v1/modify/regular",
                             payload, headers)
                res = conn.getresponse()
                response_data = json.loads(res.read().decode("utf-8"))
                if response_data.get("status"):
                    # Return a success response
                    return {"status": "success", "orderid": response_data['data'][0]['order_no']}, 200
                else:
                    # Return an error response
                    return {"status": "error", "message": response_data.get("message", "Failed to cancel order")}, res.status


def cancel_all_orders_api(data, auth):

    AUTH_TOKEN = auth
    # Get the order book
    order_book_response = get_order_book(AUTH_TOKEN)
    # print(order_book_response)
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
        cancel_response, status_code = cancel_order(orderid, AUTH_TOKEN)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
