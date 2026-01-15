import httpx
import json
import os
from database.auth_db import get_auth_token
from database.token_db import get_token
from database.token_db import get_br_symbol , get_oa_symbol, get_symbol
from broker.dhan_sandbox.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data
from broker.dhan_sandbox.mapping.transform_data import map_exchange_type, map_exchange
from utils.httpx_client import get_httpx_client
from broker.dhan_sandbox.api.baseurl import get_url
from utils.logging import get_logger

logger = get_logger(__name__)



def get_api_response(endpoint, auth, method="GET", payload=''):

    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_KEY')

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'access-token': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    
    url = get_url(endpoint)
    
    try:
        if method == "GET":
            response = client.get(url, headers=headers)
        elif method == "POST":
            response = client.post(url, headers=headers, content=payload)
        else:
            response = client.request(method, url, headers=headers, content=payload)
        
        # Add status attribute for compatibility with existing codebase
        response.status = response.status_code
        
        # Parse the response JSON
        response_data = json.loads(response.text)
        
        # Check for API errors in the response
        if isinstance(response_data, dict):
            # Some Dhan API errors come in this format
            if response_data.get('status') == 'failed' or response_data.get('status') == 'error':
                error_data = response_data.get('data', {})
                if error_data:
                    error_code = list(error_data.keys())[0] if error_data else 'unknown'
                    error_message = error_data.get(error_code, 'Unknown error')
                    logger.error(f"API Error: {error_code} - {error_message}")
                    # Return the error response for further handling
                    return response_data
            
            # Other Dhan API errors might come in this format
            if response_data.get('errorType'):
                logger.error(f"API Error: {response_data.get('errorCode')} - {response_data.get('errorMessage')}")
                # Return the error response for further handling
                return response_data
        
        return response_data
        
    except Exception as e:
        # Handle connection or parsing errors
        logger.exception(f"Error in API request to {url}: {e}")
        return {'errorType': 'ConnectionError', 'errorMessage': str(e)}

def get_order_book(auth):
    return get_api_response("/v2/orders",auth)

def get_trade_book(auth):
    return get_api_response("/v2/trades",auth)

def get_positions(auth):
    return get_api_response("/v2/positions",auth)

def get_holdings(auth):
    return get_api_response("/v2/holdings",auth)

def get_open_position(tradingsymbol, exchange, product, auth):

    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    positions_data = get_positions(auth)
    net_qty = '0'
    
    # Check if positions_data is an error response
    if isinstance(positions_data, dict) and (positions_data.get('errorType') or positions_data.get('status') == 'failed' or positions_data.get('status') == 'error'):
        logger.error(f"Error getting positions for {tradingsymbol}: {positions_data.get('errorMessage', 'API Error')}")
        return net_qty
    
    # Only process if positions_data is valid and not an error
    if positions_data and isinstance(positions_data, list):
        for position in positions_data:
            if position.get('tradingSymbol') == tradingsymbol and position.get('exchangeSegment') == map_exchange_type(exchange) and position.get('productType') == product:
                net_qty = position.get('netQty', '0')
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data,auth):
    AUTH_TOKEN = auth
    BROKER_API_KEY = os.getenv('BROKER_API_KEY')
    data['apikey'] = BROKER_API_KEY
    token = get_token(data['symbol'], data['exchange'])
    newdata = transform_data(data, token)  
    headers = {
        'access-token': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    payload = json.dumps(newdata)

    logger.debug(f"Placing order with payload: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    url = get_url("/v2/orders")
    res = client.post(url, headers=headers, content=payload)
    # Add status attribute for compatibility with existing codebase
    res.status = res.status_code
    
    try:
        response_data = json.loads(res.text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        return res, {"error": "Invalid JSON response"}, None
    
    logger.debug(f"Place order response: {response_data}")
    
    # Check if the API call was successful before accessing orderId
    orderid = None
    if res.status_code == 200 or res.status_code == 201:
        if response_data and 'orderId' in response_data:
            orderid = response_data['orderId']
        else:
            logger.error(f"orderId not found in response: {response_data}")
    else:
        logger.error(f"API call failed with status {res.status_code}: {response_data}")
    
    return res, response_data, orderid

def place_smartorder_api(data,auth):

    AUTH_TOKEN = auth
    BROKER_API_KEY = os.getenv('BROKER_API_KEY')
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
        res, response, orderid = place_order_api(data,AUTH_TOKEN)
        
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
        elif position_size < current_position:
            action = "SELL"
            quantity = current_position - position_size




    if action:
        # Prepare data for placing the order
        order_data = data.copy()
        order_data["action"] = action
        order_data["quantity"] = str(quantity)

        # Place the order
        res, response, orderid = place_order_api(order_data,AUTH_TOKEN)
        
        return res , response, orderid
    



def close_all_positions(current_api_key,auth):
    AUTH_TOKEN = auth
    # Fetch the current open positions
    positions_response = get_positions(AUTH_TOKEN)
    logger.debug(f"Positions response for closing all: {positions_response}")
    
    # Check if the positions data is null or empty
    if positions_response is None or not positions_response:
        return {"message": "No Open Positions Found"}, 200

    if positions_response:
        # Loop through each position to close
        for position in positions_response:
            # Skip if net quantity is zero
            if int(position['netQty']) == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if int(position['netQty']) > 0 else 'BUY'
            quantity = abs(int(position['netQty']))

            #print(f"Trading Symbol : {position['tradingsymbol']}")
            #print(f"Exchange : {position['exchange']}")

            #get openalgo symbol to send to placeorder function
            symbol = get_symbol(position['securityId'],map_exchange(position['exchangeSegment']))
            logger.info(f"The Symbol is {symbol}")

            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": map_exchange(position['exchangeSegment']),
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position['productType']),
                "quantity": str(quantity)
            }

            logger.debug(f"Close position payload: {place_order_payload}")

            # Place the order to close the position
            _, api_response, _ =   place_order_api(place_order_payload,AUTH_TOKEN)

            logger.debug(f"Close position response: {api_response}")
            
            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid,auth):
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    
    # Set up the request headers
    headers = {
        'access-token': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    # Construct the URL for deleting the order
    url = get_url(f"/v2/orders/{orderid}")
    
    # Make the DELETE request using httpx
    res = client.delete(url, headers=headers)
    
    # Add status attribute for compatibility with existing codebase
    res.status = res.status_code
    
    # Parse the response
    data = json.loads(res.text)

    
    # Check if the request was successful
    if data:
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Return an error response
        return {"status": "error", "message": data.get("message", "Failed to cancel order")}, res.status


def modify_order(data,auth):

    

    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    BROKER_API_KEY = os.getenv('BROKER_API_KEY')
    data['apikey'] = BROKER_API_KEY

    orderid = data["orderid"];
    transformed_order_data = transform_modify_order_data(data)  # You need to implement this function
    
  
    # Set up the request headers
    headers = {
        'access-token': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    payload = json.dumps(transformed_order_data)

    logger.debug(f"Modify order payload: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    # Construct the URL for modifying the order
    url = get_url(f"/v2/orders/{orderid}")
    
    # Make the PUT request using httpx
    res = client.put(url, headers=headers, content=payload)
    
    # Add status attribute for compatibility with existing codebase
    res.status = res.status_code
    
    # Parse the response
    data = json.loads(res.text)
    logger.debug(f"Modify order response: {data}")
    #return {"status": "error", "message": data.get("message", "Failed to modify order")}, res.status

    if data["orderId"]:
        return {"status": "success", "orderid": data["orderId"]}, 200
    else:
        return {"status": "error", "message": data.get("message", "Failed to modify order")}, res.status
    

def cancel_all_orders_api(data,auth):
    # Get the order book
    AUTH_TOKEN = auth
    order_book_response = get_order_book(AUTH_TOKEN)
    logger.debug(f"Order book for cancel all: {order_book_response}")
    if order_book_response is None:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response
                        if order['orderStatus'] in ['PENDING']]
    logger.info(f"Orders to cancel: {orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['orderId']
        cancel_response, status_code = cancel_order(orderid,AUTH_TOKEN)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations
