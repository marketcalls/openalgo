import httpx
import json
import os
from database.auth_db import get_auth_token
from database.token_db import get_token , get_br_symbol, get_symbol
from broker.flattrade.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)



def get_api_response(endpoint, auth, method="GET", payload=''):

    AUTH_TOKEN = auth

    full_api_key = os.getenv('BROKER_API_KEY')
    api_key = full_api_key.split(':::')[0]

    data = f'{{"uid": "{api_key}", "actid": "{api_key}"}}'

    if(endpoint == "/PiConnectTP/Holdings"):
        data = f'{{"uid": "{api_key}", "actid": "{api_key}", "prd": "C"}}'

    payload = "jData=" + data + "&jKey=" + AUTH_TOKEN

    # Get the shared httpx client
    client = get_httpx_client()
    
    if endpoint == "/PiConnectTP/Holdings":
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    else:
        headers = {'Content-Type': 'application/json'}

    url = f"https://piconnect.flattrade.in{endpoint}"
    response = client.request(method, url, content=payload, headers=headers)
    data = response.text
    
    return json.loads(data)

def get_order_book(auth):
    return get_api_response("/PiConnectTP/OrderBook",auth,method="POST")

def get_trade_book(auth):
    return get_api_response("/PiConnectTP/TradeBook",auth,method="POST")

def get_positions(auth):
    return get_api_response("/PiConnectTP/PositionBook",auth,method="POST")

def get_holdings(auth):
    return get_api_response("/PiConnectTP/Holdings",auth,method="POST")

def get_open_position(tradingsymbol, exchange, producttype,auth):
    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    positions_data = get_positions(auth)

    logger.info(f"{positions_data}")

    net_qty = '0'

    if positions_data is None or (isinstance(positions_data, dict) and (positions_data['stat'] == "Not_Ok")):
        # Handle the case where there is no data
        logger.info("No data available.")
        net_qty = '0'

    if positions_data and isinstance(positions_data, list):
        for position in positions_data:
            if position.get('tsym') == tradingsymbol and position.get('exch') == exchange and position.get('prd') == producttype:
                net_qty = position.get('netqty', '0')
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data,auth):
    AUTH_TOKEN = auth

    full_api_key = os.getenv('BROKER_API_KEY')
    BROKER_API_KEY = full_api_key.split(':::')[0]
    data['apikey'] = BROKER_API_KEY
    token = get_token(data['symbol'], data['exchange'])
    newdata = transform_data(data, token)  
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    payload = "jData=" + json.dumps(newdata) + "&jKey=" + AUTH_TOKEN

    logger.info(f"{payload}")
    # Get the shared httpx client
    client = get_httpx_client()
    
    url = "https://piconnect.flattrade.in/PiConnectTP/PlaceOrder"
    res = client.post(url, content=payload, headers=headers)
    response_data = res.json()
    
    # Add status attribute for backward compatibility
    res.status = res.status_code
    
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


    logger.info(f"position_size : {position_size}") 
    logger.info(f"Open Position : {current_position}") 
    
    # Determine action based on position_size and current_position
    action = None
    quantity = 0


    # If both position_size and current_position are 0, do nothing
    if position_size == 0 and current_position == 0 and int(data['quantity'])!=0:
        action = data['action']
        quantity = data['quantity']
        #logger.info(f"action : {action}")
        #logger.info(f"Quantity : {quantity}")
        res, response, orderid = place_order_api(data,AUTH_TOKEN)
        #logger.info(f"{res}")
        #logger.info(f"{response}")
        
        return res , response, orderid
        
    elif position_size == current_position:
        if int(data['quantity'])==0:
            response = {"status": "success", "message": "No OpenPosition Found. Not placing Exit order."}
        else:
            response = {"status": "success", "message": "No action needed. Position size matches current position"}
        orderid = None
        return res, response, orderid  # res remains None as no API call was made
   
   

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
            #logger.info(f"smart buy quantity : {quantity}")
        elif position_size < current_position:
            action = "SELL"
            quantity = current_position - position_size
            #logger.info(f"smart sell quantity : {quantity}")




    if action:
        # Prepare data for placing the order
        order_data = data.copy()
        order_data["action"] = action
        order_data["quantity"] = str(quantity)

        #logger.info(f"{order_data}")
        # Place the order
        res, response, orderid = place_order_api(order_data,auth)
        #logger.info(f"{res}")
        logger.info(f"{response}")
        logger.info(f"{orderid}")
        
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
            logger.info(f"The Symbol is {symbol}")

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

            logger.info(f"{place_order_payload}")

            # Place the order to close the position
            res, response, orderid =   place_order_api(place_order_payload,auth)

            # logger.info(f"{res}")
            # logger.info(f"{response}")
            # logger.info(f"{orderid}")


            
            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid,auth):
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    full_api_key = os.getenv('BROKER_API_KEY')
    api_key = full_api_key.split(':::')[0]
    data = {"uid": api_key, "norenordno": orderid}
    

    payload = "jData=" + json.dumps(data) + "&jKey=" + AUTH_TOKEN
    # Set up the request headers
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    

    
    # Get the shared httpx client and send the request
    client = get_httpx_client()
    
    url = "https://piconnect.flattrade.in/PiConnectTP/CancelOrder"
    res = client.post(url, content=payload, headers=headers)
    data = res.json()
    logger.info(f"{data}")
    
    # Check if the request was successful
    if data.get("stat")=='Ok':
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Return an error response
        return {"status": "error", "message": data.get("message", "Failed to cancel order")}, res.status_code


def modify_order(data,auth):

    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    full_api_key = os.getenv('BROKER_API_KEY')
    api_key = full_api_key.split(':::')[0]

    token = get_token(data['symbol'], data['exchange'])
    data['symbol'] = get_br_symbol(data['symbol'],data['exchange'])
    data["apikey"] = api_key

    transformed_data = transform_modify_order_data(data, token)  # You need to implement this function
    # Set up the request headers
    headers = {'Content-Type': 'application/json'}
    payload = "jData=" + json.dumps(transformed_data) + "&jKey=" + AUTH_TOKEN


    # Get the shared httpx client
    client = get_httpx_client()
    
    url = "https://piconnect.flattrade.in/PiConnectTP/ModifyOrder"
    res = client.post(url, content=payload, headers=headers)
    response = res.json()

    if response.get("stat")=='Ok':
        return {"status": "success", "orderid": data["orderid"]}, 200
    else:
        return {"status": "error", "message": response.get("emsg", "Failed to modify order")}, res.status_code



def cancel_all_orders_api(data,auth):
    # Get the order book

    AUTH_TOKEN = auth
    

    order_book_response = get_order_book(AUTH_TOKEN)
    #logger.info(f"{order_book_response}")
    if order_book_response is None:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response
                        if order['status'] in ['OPEN', 'TRIGGER_PENDING']]
    #logger.info(f"{orders_to_cancel}")
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

