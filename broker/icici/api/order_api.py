import http.client
import hashlib
import json
from datetime import datetime, timedelta
import os
from database.auth_db import get_auth_token
from database.token_db import get_token
from database.token_db import get_br_symbol , get_oa_symbol, get_symbol
from broker.icici.mapping.transform_data import transform_data , map_symbol, reverse_map_product_type, transform_modify_order_data




def get_orders(auth,exchange_code):
    api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')
    conn = http.client.HTTPSConnection("api.icicidirect.com")

    # Get today's date in UTC
    today = datetime.utcnow().date()

    # Calculate the 'from_date' and 'to_date' in UTC
    from_date_utc = datetime.combine(today - timedelta(days=1), datetime.min.time()) + timedelta(hours=18, minutes=30)
    to_date_utc = datetime.combine(today, datetime.min.time()) + timedelta(hours=18, minutes=29)

    # Convert dates to ISO format for the API call
    from_date_str = from_date_utc.isoformat() + 'Z'
    to_date_str = to_date_utc.isoformat() + 'Z'
    payload = json.dumps({"exchange_code": exchange_code, "from_date": from_date_str, "to_date": to_date_str}, separators=(',', ':'))

    # Time stamp & checksum generation for request headers
    time_stamp = datetime.utcnow().isoformat()[:19] + '.000Z'
    checksum = hashlib.sha256((time_stamp + payload + api_secret).encode("utf-8")).hexdigest()

    headers = {
        'Content-Type': 'application/json',
        'X-Checksum': 'token ' + checksum,
        'X-Timestamp': time_stamp,
        'X-AppKey': api_key,
        'X-SessionToken': auth
    }

    conn.request("GET", "/breezeapi/api/v1/order", payload, headers)
    res = conn.getresponse()
    data = res.read()

    # Convert response data to JSON
    order_data = json.loads(data.decode("utf-8"))

    return order_data



def get_order_book(auth):
    """Fetch Orderbook data from ICICI Direct's API using the provided Session token."""
    def collect_orders():
        exchanges = ["NSE", "BSE", "NFO"]
        all_orders = []
        
        for exchange in exchanges:
            orders_data = get_orders(auth, exchange)
            
            if orders_data['Success']:  # Check if there are successful orders returned
                all_orders.extend(orders_data['Success'])  # Merge successful orders into the all_orders list
        
        return all_orders

    # Collecting and printing all orders
    order_book = collect_orders()
    result = {
        "data": {
            "order_book": order_book
        },
        "Status": 200,
        "Error": None
    }
    return result

def get_trades(auth,exchange_code):
    api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')
    conn = http.client.HTTPSConnection("api.icicidirect.com")

    # Get today's date in UTC
    today = datetime.utcnow().date()

    # Calculate the 'from_date' and 'to_date' in UTC
    from_date_utc = datetime.combine(today - timedelta(days=1), datetime.min.time()) + timedelta(hours=18, minutes=30)
    to_date_utc = datetime.combine(today, datetime.min.time()) + timedelta(hours=18, minutes=29)

    # Convert dates to ISO format for the API call
    from_date_str = from_date_utc.isoformat() + 'Z'
    to_date_str = to_date_utc.isoformat() + 'Z'
    payload = json.dumps({"exchange_code": exchange_code, "from_date": from_date_str, "to_date": to_date_str}, separators=(',', ':'))

    # Time stamp & checksum generation for request headers
    time_stamp = datetime.utcnow().isoformat()[:19] + '.000Z'
    checksum = hashlib.sha256((time_stamp + payload + api_secret).encode("utf-8")).hexdigest()

    headers = {
        'Content-Type': 'application/json',
        'X-Checksum': 'token ' + checksum,
        'X-Timestamp': time_stamp,
        'X-AppKey': api_key,
        'X-SessionToken': auth
    }

    conn.request("GET", "/breezeapi/api/v1/trades", payload, headers)
    res = conn.getresponse()
    data = res.read()

    # Convert response data to JSON
    trade_data = json.loads(data.decode("utf-8"))

    return trade_data




def get_trade_book(auth):
    """Fetch Tradebook data from ICICI Direct's API using the provided Session token."""
    def collect_trades():
        exchanges = ["NSE", "BSE", "NFO"]
        all_trades = []
        
        for exchange in exchanges:
            trades_data = get_trades(auth, exchange)
            
            if trades_data['Success']:  # Check if there are successful trades returned
                all_trades.extend(trades_data['Success'])  # Merge successful trades into the all_trades list
        
        return all_trades

    # Collecting and printing all trades
    trade_book = collect_trades()
    result = {
        "data": {
            "trade_book": trade_book
        },
        "Status": 200,
        "Error": None
    }
    return result

def get_positions(auth):

    api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')
    conn = http.client.HTTPSConnection("api.icicidirect.com")


    payload = json.dumps({})

    # Time stamp & checksum generation for request headers
    time_stamp = datetime.utcnow().isoformat()[:19] + '.000Z'
    checksum = hashlib.sha256((time_stamp + payload + api_secret).encode("utf-8")).hexdigest()

    headers = {
        'Content-Type': 'application/json',
        'X-Checksum': 'token ' + checksum,
        'X-Timestamp': time_stamp,
        'X-AppKey': api_key,
        'X-SessionToken': auth
    }

    conn.request("GET", "/breezeapi/api/v1/portfoliopositions", payload, headers)
    res = conn.getresponse()
    data = res.read()

    # Convert response data to JSON
    positions_data = json.loads(data.decode("utf-8"))
    #positions_data = json.dumps(positions_data, indent=4)

    return positions_data


def get_demat(auth,exchange_code):
    api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')
    conn = http.client.HTTPSConnection("api.icicidirect.com")

    # Get today's date in UTC
    today = datetime.utcnow().date()

    # Calculate the 'from_date' and 'to_date' in UTC
    from_date_utc = datetime.combine(today - timedelta(days=1), datetime.min.time()) + timedelta(hours=18, minutes=30)
    to_date_utc = datetime.combine(today, datetime.min.time()) + timedelta(hours=18, minutes=29)

    # Convert dates to ISO format for the API call
    from_date_str = from_date_utc.isoformat() + 'Z'
    to_date_str = to_date_utc.isoformat() + 'Z'
    payload = json.dumps({"exchange_code": exchange_code, "from_date": from_date_str, "to_date": to_date_str}, separators=(',', ':'))

    # Time stamp & checksum generation for request headers
    time_stamp = datetime.utcnow().isoformat()[:19] + '.000Z'
    checksum = hashlib.sha256((time_stamp + payload + api_secret).encode("utf-8")).hexdigest()

    headers = {
        'Content-Type': 'application/json',
        'X-Checksum': 'token ' + checksum,
        'X-Timestamp': time_stamp,
        'X-AppKey': api_key,
        'X-SessionToken': auth
    }

    conn.request("GET", "/breezeapi/api/v1/portfolioholdings", payload, headers)
    res = conn.getresponse()
    data = res.read()

    # Convert response data to JSON
    trade_data = json.loads(data.decode("utf-8"))

    return trade_data



def get_holdings(auth):
    def collect_holdings():
        exchanges = ["NSE"]
        all_holdings = []
        
        for exchange in exchanges:
            holdings_data = get_demat(auth, exchange)
            
            if holdings_data['Success']:  # Check if there are successful holdings returned
                all_holdings.extend(holdings_data['Success'])  # Merge successful holdings into the all_holdings list
        
        return all_holdings

    # Collecting and printing all holdings
    holdings = collect_holdings()
    result = {
        "data": {
            "holdings": holdings
        },
        "Status": 200,
        "Error": None
    }
    return result

def safe_upper(value):
        return value.upper() if value is not None else None

def get_open_position(data, auth):

    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")

    #convert openalgo symbol to broker symbol
    br_symbol = get_br_symbol(symbol, exchange)
    br_symbol, product, expiry_date, right, strike_price = map_symbol(data,br_symbol)

    # Printing the values
    print("br_symbol:", br_symbol)
    print("Product:", product)
    print("Expiry Date:", expiry_date)
    print("Right:", right)
    print("Strike Price:", strike_price)

    positions_data = get_positions(auth)
    net_qty = '0'

    

    if positions_data and positions_data.get('Status') and positions_data.get('Success'):
        for position in positions_data['Success']:
            pb_stock_code = safe_upper(position.get('stock_code'))
            pb_exchange = safe_upper(position.get('exchange_code'))
            pb_product = safe_upper(position.get('product_type'))
            pb_expiry = safe_upper(position.get('expiry_date'))
            pb_right = safe_upper(position.get('right'))
            pb_strike = safe_upper(position.get('strike_price'))
            if (pb_stock_code == safe_upper(br_symbol) and
                pb_exchange == safe_upper(exchange) and
                pb_product == safe_upper(product) and
                pb_expiry == safe_upper(expiry_date) and
                pb_right == safe_upper(right) and
                pb_strike == safe_upper(strike_price)):

                if(position.get('action', '')=='Buy'):
                    quantity = int(position.get('quantity', 0))
                    net_qty = str(quantity)
                if(position.get('action', '')=='Sell'):
                    quantity = int(position.get('quantity', 0))*-1
                    net_qty = str(quantity)
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data,auth):
    AUTH_TOKEN = auth
    
    api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')
    


    br_symbol = get_br_symbol(data['symbol'], data['exchange'])

    newdata = transform_data(data, br_symbol)  

    

    payload = json.dumps(newdata, separators=(',', ':'))

    print(payload)

    # Time stamp & checksum generation for request headers
    time_stamp = datetime.utcnow().isoformat()[:19] + '.000Z'
    checksum = hashlib.sha256((time_stamp + payload + api_secret).encode("utf-8")).hexdigest()

    headers = {
        'Content-Type': 'application/json',
        'X-Checksum': 'token ' + checksum,
        'X-Timestamp': time_stamp,
        'X-AppKey': api_key,
        'X-SessionToken': auth
    }

    conn = http.client.HTTPSConnection("api.icicidirect.com")
    conn.request("POST", "/breezeapi/api/v1/order", payload, headers)
    res = conn.getresponse()

    response_data = json.loads(res.read().decode("utf-8"))
    print(response_data)
    if response_data['Status'] == 200:
        orderid = response_data['Success']['order_id']
    else:
        orderid = None
    return res, response_data, orderid

def place_smartorder_api(data,auth):

    AUTH_TOKEN = auth
    #If no API call is made in this function then res will return None
    res = None


    # Extract necessary info from data

    
    position_size = int(data.get("position_size", "0"))

    
    # Get current open position for the symbol
    current_position = int(get_open_position(data, AUTH_TOKEN))


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
    print(positions_response)
    
    # Check if the positions data is null or empty
    if positions_response['Success'] is None or not positions_response['Success']:
        return {"message": "No Open Positions Found"}, 200

    if positions_response['Status']==200:
        # Loop through each position to close
        for position in positions_response['Success']:
            # Skip if net quantity is zero
            if int(position['quantity']) == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if int(position['quantity']) > 0 else 'BUY'
            quantity = abs(int(position['quantity']))

            #print(f"Trading Symbol : {position['tradingsymbol']}")
            #print(f"Exchange : {position['exchange']}")
            symbol = position['stock_code']
            exchange = position['exchange_code']
            expiry_date = safe_upper(position['expiry_date'])
            strike_price = safe_upper(position['strike_price'])
            right = safe_upper(position['right'])

            #get openalgo symbol to send to placeorder function
            if(exchange=="NSE"):
                brsymbol = symbol
            if(exchange=="BSE"):
                brsymbol = symbol
            if(exchange=="NFO" and right=="OTHERS"):
                brsymbol = symbol + ':::' +  expiry_date + ':::' +  'FUT'
            if(exchange=="NFO" and right=="CALL"):
                brsymbol = symbol + ':::' +  expiry_date + ':::' +  strike_price + ':::' +  right
            if(exchange=="NFO" and right=="PUT"):
                brsymbol = symbol + ':::' +  expiry_date + ':::' +  strike_price + ':::' +  right
            symbol = get_oa_symbol(brsymbol,exchange)
            print(f'The Symbol is {symbol}')

            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": exchange,
                "pricetype": "MARKET",
                "product": reverse_map_product_type(exchange,position['product_type']),
                "quantity": str(quantity),
                "price": "0"
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

    api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')

    exchange_code = ''

    if 'data' in order_book_response and 'order_book' in order_book_response['data']:
        # Search for the order_id in the order book
        for order in order_book_response['data']['order_book']:
            if order['order_id'] == orderid:
                # If order_id is found, print the order_id and exchange_code
                exchange_code =  order['exchange_code']
                print(f"Order ID {orderid} found with Exchange Code: {exchange_code}")

    if exchange_code is not None:
        
        json_data = { 
                    "order_id": orderid, 
                    "exchange_code": exchange_code
                    }
        payload = json.dumps(json_data, separators=(',', ':'))

        print(f'Order Cancellation Request : {json_data}')

        # Time stamp & checksum generation for request headers
        time_stamp = datetime.utcnow().isoformat()[:19] + '.000Z'
        checksum = hashlib.sha256((time_stamp + payload + api_secret).encode("utf-8")).hexdigest()

        headers = {
            'Content-Type': 'application/json',
            'X-Checksum': 'token ' + checksum,
            'X-Timestamp': time_stamp,
            'X-AppKey': api_key,
            'X-SessionToken': auth
        }

        conn = http.client.HTTPSConnection("api.icicidirect.com")
        conn.request("DELETE", "/breezeapi/api/v1/order", payload, headers)
        res = conn.getresponse()

        data = json.loads(res.read().decode("utf-8"))

        print(f'Order Cancellation Response : {data}')
    
    # Check if the request was successful
    if data["Status"]==200:
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Return an error response
        return {"status": "error", "message": data.get("message", "Failed to cancel order")}, res.status


def modify_order(data,auth):

    

    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth

    api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')
    


    br_symbol = get_br_symbol(data['symbol'], data['exchange'])

    
    transformed_order_data = transform_modify_order_data(data,br_symbol)  # You need to implement this function
    
    payload = json.dumps(transformed_order_data, separators=(',', ':'))

    print(payload)

    # Time stamp & checksum generation for request headers
    time_stamp = datetime.utcnow().isoformat()[:19] + '.000Z'
    checksum = hashlib.sha256((time_stamp + payload + api_secret).encode("utf-8")).hexdigest()

    headers = {
        'Content-Type': 'application/json',
        'X-Checksum': 'token ' + checksum,
        'X-Timestamp': time_stamp,
        'X-AppKey': api_key,
        'X-SessionToken': auth
    }

    conn = http.client.HTTPSConnection("api.icicidirect.com")
    conn.request("PUT", "/breezeapi/api/v1/order", payload, headers)
    res = conn.getresponse()

  
    response_data = json.loads(res.read().decode("utf-8"))

    print(response_data)
    if response_data['Status'] == 200:
        orderid = response_data['Success']['order_id']
        return {"status": "success", "orderid": orderid}, 200
    else:
        return {"status": "error", "message": data.get("message", "Failed to modify order")}, res.status
    

def cancel_all_orders_api(data,auth):
    # Get the order book
    AUTH_TOKEN = auth
    order_book_response = get_order_book(AUTH_TOKEN)
    #print(order_book_response)
    if order_book_response['Status'] != 200:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Access the 'order_book' list from the response and filter orders based on their 'status'
    orders_to_cancel = [order for order in order_book_response.get('data', {}).get('order_book', [])
                        if order['status'] in ['Ordered']]
    print(orders_to_cancel)
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

