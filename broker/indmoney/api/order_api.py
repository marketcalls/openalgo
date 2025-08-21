import httpx
import json
import os
from database.auth_db import get_auth_token
from database.token_db import get_token
from database.token_db import get_br_symbol , get_oa_symbol, get_symbol
from broker.indmoney.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data
from broker.indmoney.mapping.transform_data import map_exchange_type, map_exchange, map_segment
from utils.httpx_client import get_httpx_client
from broker.indmoney.api.baseurl import get_url
from utils.logging import get_logger

logger = get_logger(__name__)



def get_api_response(endpoint, auth, method="GET", payload=''):

    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_KEY')

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'Authorization': AUTH_TOKEN,
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
        
        # Check if response is successful
        if response.status_code not in [200, 201]:
            logger.error(f"HTTP Error {response.status_code} for {url}: {response.text}")
            return {'status': 'error', 'message': f'HTTP {response.status_code}: {response.text}'}
        
        # Check if response has content
        if not response.text.strip():
            logger.error(f"Empty response from {url}")
            return {'status': 'error', 'message': 'Empty response from API'}
        
        # Parse the response JSON
        try:
            response_data = json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response from {url}: {e}")
            logger.error(f"Raw response: {response.text[:500]}...")  # Log first 500 chars
            return {'status': 'error', 'message': f'Invalid JSON response: {str(e)}'}
        
        # Check for API errors in the response
        if isinstance(response_data, dict):
            # Indmoney API errors come in this format
            if response_data.get('status') in ['error', 'failure']:
                # Handle both 'error' and 'failure' status
                if response_data.get('status') == 'failure' and 'error' in response_data:
                    error_message = response_data.get('error', {}).get('msg', 'Unknown error')
                else:
                    error_message = response_data.get('message', 'Unknown error')
                logger.error(f"API Error: {error_message}")
                # Return the error response for further handling
                return response_data
            
            # For successful responses, return the data array directly for list endpoints
            if response_data.get('status') == 'success' and 'data' in response_data:
                logger.info(f"Successfully fetched data from {endpoint}")
                return response_data['data']
        
        logger.info(f"Response data: {response_data}")
        return response_data
        
    except Exception as e:
        # Handle connection or parsing errors
        logger.exception(f"Error in API request to {url}: {e}")
        return {'status': 'error', 'message': str(e)}

def get_order_book(auth):
    try:
        result = get_api_response("/order-book", auth)
        # Ensure we never return None
        if result is None:
            logger.warning("get_api_response returned None, returning empty list")
            return []
        return result
    except Exception as e:
        logger.error(f"Exception in get_order_book: {e}")
        return []

def get_trade_book(auth):
    return get_api_response("/tradebook",auth)

def get_positions(auth):
    try:
        result = get_api_response("/portfolio/positions", auth)
        # Ensure we never return None
        if result is None:
            logger.warning("get_api_response returned None for positions, returning empty list")
            return []
        return result
    except Exception as e:
        logger.error(f"Exception in get_positions: {e}")
        return []

def get_holdings(auth):
    try:
        result = get_api_response("/portfolio/holdings", auth)
        # Ensure we never return None
        if result is None:
            logger.warning("get_api_response returned None for holdings, returning empty list")
            return []
        return result
    except Exception as e:
        logger.error(f"Exception in get_holdings: {e}")
        return []

def get_open_position(tradingsymbol, exchange, product, auth):

    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    positions_response = get_positions(auth)
    net_qty = '0'
    # logger.info(f"Positions response: {positions_response}")
    
    # Check if positions_response is an error response
    if isinstance(positions_response, dict) and positions_response.get('status') == 'error':
        logger.error(f"Error getting positions for {tradingsymbol}: {positions_response.get('message', 'API Error')}")
        return net_qty
    
    # Handle the actual flat array format from IndMoney API
    all_positions = []
    if isinstance(positions_response, list):
        # Direct flat list from actual API
        all_positions = positions_response
    elif isinstance(positions_response, dict) and 'net_positions' in positions_response:
        # Fallback to documented format if it changes back
        net_positions = positions_response.get('net_positions', [])
        day_positions = positions_response.get('day_positions', [])
        all_positions = net_positions + day_positions
    
    # Only process if all_positions is valid and not empty
    if all_positions and isinstance(all_positions, list):
        for position in all_positions:
            if not isinstance(position, dict):
                continue
                
            # Map the actual IndMoney API fields
            position_symbol = position.get('symbol')  # Actual field name from API
            position_segment = position.get('segment', '')
            
            # Map segment to exchange format for comparison
            if position_segment == 'F&O' or position_segment == 'FUTURES':
                mapped_exchange = 'NFO'
            elif position_segment == 'EQUITY':
                mapped_exchange = 'NSE'  # Default for equity
            elif position_segment == 'COMMODITY':
                mapped_exchange = 'MCX'
            else:
                mapped_exchange = position_segment
            
            # Check if this position matches our search criteria
            if (position_symbol == tradingsymbol and 
                mapped_exchange == map_exchange_type(exchange)):
                net_qty = str(position.get('net_qty', 0))
                break  # Return the first match

    return net_qty

def place_order_api(data,auth):
    AUTH_TOKEN = auth
    BROKER_API_KEY = os.getenv('BROKER_API_KEY')
    data['apikey'] = BROKER_API_KEY
    token = get_token(data['symbol'], data['exchange'])
    logger.info(f"Original order data: {data}")
    logger.info(f"Security token: {token}")
    newdata = transform_data(data, token)  
    logger.info(f"Transformed data: {newdata}")
    headers = {
        'Authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    payload = json.dumps(newdata)

    logger.debug(f"Placing order with payload: {payload}")
    logger.info(f"Indmoney API URL: {get_url('/order')}")
    logger.info(f"Indmoney API Headers: {headers}")
    logger.info(f"Indmoney API Payload: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    url = get_url("/order")
    res = client.post(url, headers=headers, content=payload)
    # Add status attribute for compatibility with existing codebase
    res.status = res.status_code
    
    try:
        response_data = json.loads(res.text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        return res, {"error": "Invalid JSON response"}, None
    
    logger.debug(f"Place order response: {response_data}")
    
    # Check if the API call was successful before accessing order ID
    orderid = None
    if res.status_code == 200 or res.status_code == 201:
        if response_data and response_data.get('status') == 'success':
            # Indmoney returns order ID in data.order_id field
            orderid = response_data.get('data', {}).get('order_id')
            logger.info(f"Order placed successfully with ID: {orderid}")
            # Format response to match OpenAlgo API standard
            response_data = {
                'orderid': orderid,
                'status': 'success'
            }
        elif response_data and response_data.get('status') in ['error', 'failure']:
            # Handle API errors/failures - but check if order was actually placed
            if response_data.get('status') == 'failure' and 'error' in response_data:
                error_msg = response_data.get('error', {}).get('msg', 'Unknown error')
                # Check if this is just a response parsing issue but order was placed
                if 'no order number in rs response' in error_msg.lower():
                    logger.warning(f"Order likely placed successfully despite error: {error_msg}")
                    # Create a mock successful response since order appears in orderbook
                    response_data = {'orderid': 'ORDER_PLACED', 'status': 'success'}
                    orderid = 'ORDER_PLACED'  # Placeholder since actual ID not available
                else:
                    logger.error(f"Order placement failed: {error_msg}")
            else:
                error_msg = response_data.get('message', 'Unknown error')
                logger.error(f"Order placement failed: {error_msg}")
        else:
            logger.error(f"Order placement failed: {response_data}")
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
    else:
        # No action determined - should not happen with current logic
        response = {"status": "success", "message": "No action needed"}
        return res, response, None
    



def close_all_positions(current_api_key,auth):
    AUTH_TOKEN = auth
    # Fetch the current open positions
    positions_response = get_positions(AUTH_TOKEN)
    logger.debug(f"Positions response for closing all: {positions_response}")
    
    # Handle the actual flat array format from IndMoney API
    all_positions = []
    if isinstance(positions_response, list):
        # Direct flat list from actual API
        all_positions = positions_response
    elif isinstance(positions_response, dict):
        # Fallback to handle documented nested format if it changes back
        net_positions = positions_response.get('net_positions', [])
        day_positions = positions_response.get('day_positions', [])
        all_positions = net_positions + day_positions
    
    # Check if the positions data is null or empty
    if not all_positions:
        return {"message": "No Open Positions Found"}, 200

    if all_positions:
        # Loop through each position to close
        for position in all_positions:
            if not isinstance(position, dict):
                continue
                
            # Skip if net quantity is zero - using actual API field name
            net_qty = position.get('net_qty', 0)
            if int(net_qty) == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if int(net_qty) > 0 else 'BUY'
            quantity = abs(int(net_qty))

            # Map segment to standard exchange format - using actual API field name
            segment = position.get('segment', '')
            if segment == 'F&O' or segment == 'FUTURES':
                exchange = 'NFO'
            elif segment == 'EQUITY':
                exchange = 'NSE'
            elif segment == 'COMMODITY':
                exchange = 'MCX'
            else:
                exchange = segment

            #get openalgo symbol to send to placeorder function
            symbol = get_symbol(position['security_id'], exchange)
            logger.info(f"The Symbol is {symbol}")

            # Determine product type based on actual API response
            api_product = position.get('product', '')
            if api_product == 'INTRADAY':
                product = 'MIS'
            elif api_product == 'DELIVERY':
                product = 'CNC'
            elif exchange in ['NFO', 'MCX', 'BFO', 'CDS']:
                product = 'NRML'
            else:
                product = 'MIS'

            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": exchange,
                "pricetype": "MARKET",
                "product": product,
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
        'Authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    # Prepare the payload for Indmoney cancel order API
    payload = {
        "segment": "DERIVATIVE" if orderid.startswith("DRV-") else "EQUITY",
        "order_id": orderid
    }
    
    # Make the POST request to cancel order using httpx
    url = get_url("/order/cancel")
    res = client.post(url, headers=headers, content=json.dumps(payload))
    
    # Add status attribute for compatibility with existing codebase
    res.status = res.status_code
    
    # Parse the response
    data = json.loads(res.text)

    
    # Check if the request was successful
    if res.status_code == 200 and data.get("status") == "success":
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Handle error response - check for both error message formats
        if data.get("status") == "failure" and "error" in data:
            error_msg = data.get("error", {}).get("msg", "Failed to cancel order")
        else:
            error_msg = data.get("message", "Failed to cancel order")
        # Return an error response
        return {"status": "error", "message": error_msg}, res.status


def modify_order(data,auth):

    

    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    BROKER_API_KEY = os.getenv('BROKER_API_KEY')
    data['apikey'] = BROKER_API_KEY

    orderid = data["orderid"];
    transformed_order_data = transform_modify_order_data(data)  # You need to implement this function
    
  
    # Set up the request headers
    headers = {
        'Authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    payload = json.dumps(transformed_order_data)

    logger.debug(f"Modify order payload: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    # Construct the URL for modifying the order
    url = get_url("/order/modify")
    
    # Make the POST request using httpx
    res = client.post(url, headers=headers, content=payload)
    
    # Add status attribute for compatibility with existing codebase
    res.status = res.status_code
    
    # Parse the response
    data = json.loads(res.text)
    logger.debug(f"Modify order response: {data}")
    #return {"status": "error", "message": data.get("message", "Failed to modify order")}, res.status

    if res.status_code == 200 and data.get("status") == "success":
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Handle error response - check for both error message formats
        if data.get("status") == "failure" and "error" in data:
            error_msg = data.get("error", {}).get("msg", "Failed to modify order")
        else:
            error_msg = data.get("message", "Failed to modify order")
        return {"status": "error", "message": error_msg}, res.status
    

def cancel_all_orders_api(data,auth):
    # Get the order book
    AUTH_TOKEN = auth
    order_book_response = get_order_book(AUTH_TOKEN)
    logger.debug(f"Order book for cancel all: {order_book_response}")
    if order_book_response is None:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response
                        if order['status'] in ['PENDING', 'O-PENDING', 'SL-PENDING']]
    logger.info(f"Orders to cancel: {orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['id']
        cancel_response, status_code = cancel_order(orderid,AUTH_TOKEN)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations
