import json
import os
from database.auth_db import get_auth_token
from database.token_db import get_token, get_br_symbol, get_symbol
from broker.firstock.mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data
from utils.logging import get_logger
from utils.httpx_client import get_httpx_client

# Initialize logger
logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="POST", payload=None):
    """
    Generic API response handler for Firstock API using shared httpx client with connection pooling
    """
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        api_key = os.getenv('BROKER_API_KEY')
        if not api_key:
            raise Exception("BROKER_API_KEY not found in environment variables")
            
        api_key = api_key[:-4]  # Remove last 4 characters
        
        if payload is None:
            payload = {
                "jKey": auth,
                "userId": api_key
            }
        
        headers = {'Content-Type': 'application/json'}
        url = f"https://api.firstock.in/V1{endpoint}"
        
        # Make request using shared httpx client
        response = client.request(method, url, json=payload, headers=headers, timeout=30)
        
        # Add status attribute for compatibility
        response.status = response.status_code
        
        return response.json()
        
    except Exception as e:
        if "timeout" in str(e).lower():
            logger.error("Request timeout while calling Firstock API")
            return {"status": "failed", "error": "Request timeout - please try again"}
        elif "connection" in str(e).lower():
            logger.error("Connection error while calling Firstock API")
            return {"status": "failed", "error": "Connection error - please check your internet connection"}
        else:
            logger.error(f"Error in API call: {str(e)}")
            return {"status": "failed", "error": str(e)}


def get_order_book(auth):
    """Get order book from Firstock"""
    return get_api_response("/orderBook", auth)

def get_trade_book(auth):
    """Get trade book from Firstock"""
    return get_api_response("/tradeBook", auth)

def get_positions(auth):
    """
    Get position book from Firstock
    
    Returns:
        dict: Position book data in the format:
        {
            "status": "success",
            "data": {
                "userId": "AA0011",
                "exchange": "NSE",
                "tradingSymbol": "ITC-EQ",
                "product": "I",
                "netQuantity": "0",
                ...
            }
        }
    """
    return get_api_response("/positionBook", auth)

def get_ltp(auth, exchange, token):
    """Get Last Traded Price from Firstock"""
    payload = {
        "jKey": auth,
        "userId": os.getenv('BROKER_API_KEY')[:-4],
        "exchange": exchange,
        "token": token
    }
    return get_api_response("/getLtp", auth, payload=payload)

def get_holdings(auth):
    """Get holdings from Firstock"""
    response = get_api_response("/holdings", auth)
    logger.info(f"Raw holdings response: {json.dumps(response, indent=2)}")
    
    # If successful, get LTP for each holding
    if response.get('status') == 'success':
        for holding in response.get('data', []):
            nse_entries = [exch for exch in holding.get('exchangeTradingSymbol', []) if exch.get('exchange') == 'NSE']
            if nse_entries:
                nse_entry = nse_entries[0]
                ltp_response = get_ltp(auth, nse_entry['exchange'], nse_entry['token'])
                logger.info("LTP response for {nse_entry['tradingSymbol']}:", json.dumps(ltp_response, indent=2))
                if ltp_response.get('status') == 'success':
                    nse_entry['ltp'] = ltp_response.get('data', {}).get('ltp', '0.00')
                else:
                    logger.info(f"Failed to get LTP for {nse_entry['tradingSymbol']}")
                    nse_entry['ltp'] = '0.00'
    
    return response

def get_open_position(tradingsymbol, exchange, producttype, auth):
    """
    Get open position for a specific symbol
    
    Args:
        tradingsymbol (str): Trading symbol in OpenAlgo format
        exchange (str): Exchange (NSE, BSE, etc.)
        producttype (str): Product type in OpenAlgo format (CNC, MIS, NRML)
        auth (str): Authentication token (jKey)
    
    Returns:
        str: Net quantity as string, '0' if no position found
    """
    # Convert Trading Symbol from OpenAlgo Format to Broker Format
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    if '&' in tradingsymbol:
        tradingsymbol = tradingsymbol.replace('&', '%26')
    
    # Convert product type to Firstock format
    producttype = map_product_type(producttype)
    
    positions_data = get_positions(auth)
    net_qty = '0'
    
    if positions_data.get('status') == 'success':
        positions = positions_data.get('data', [])
        if isinstance(positions, list):
            for position in positions:
                if (position.get('tradingSymbol') == tradingsymbol and 
                    position.get('exchange') == exchange and 
                    position.get('product') == producttype):
                    net_qty = position.get('netQuantity', '0')
                    break
        elif isinstance(positions, dict):
            # Handle case where single position is returned as dict
            if (positions.get('tradingSymbol') == tradingsymbol and 
                positions.get('exchange') == exchange and 
                positions.get('product') == producttype):
                net_qty = positions.get('netQuantity', '0')
    
    return net_qty

def place_order_api(data, auth):
    """
    Place order through Firstock API
    Returns: response, response_data, orderid
    """
    api_key = os.getenv('BROKER_API_KEY')
    api_key = api_key[:-4]
    
    token = get_token(data['symbol'], data['exchange'])
    transformed_data = transform_data(data, token)
    transformed_data.update({
        "jKey": auth,
        "userId": api_key
    })

    logger.info(f"{transformed_data}")
    
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        headers = {'Content-Type': 'application/json'}
        url = f"https://api.firstock.in/V1/placeOrder"
        
        # Make request using shared httpx client
        response = client.request("POST", url, json=transformed_data, headers=headers, timeout=30)
        
        # Add status attribute for compatibility
        response.status = response.status_code
        
        response_data = response.json()
        logger.info(f"Response Status: {response.status}")
        logger.info(f"Response Data: {response_data}")
        
        if response_data.get('status') == 'success':
            orderid = response_data.get('data', {}).get('orderNumber')
        else:
            orderid = None
            
        return response, response_data, orderid
        
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return None, {"status": "failed", "error": str(e)}, None


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
    



def close_all_positions(current_api_key, auth):
    """
    Close all open positions for the user
    
    Args:
        current_api_key (str): API key for the user
        auth (str): Authentication token (jKey)
    
    Returns:
        tuple: (dict with status and message, HTTP status code)
    """
    positions_response = get_positions(auth)
    
    # Initialize counters for summary
    positions_closed = 0
    positions_failed = 0
    error_messages = []

    # Check if the positions data is null or empty
    if not positions_response or positions_response.get('status') != 'success':
        return {
            "status": "error",
            "message": "Failed to fetch positions",
            "error": positions_response.get('error', {}).get('message', 'Unknown error')
        }, 400

    positions = positions_response.get('data', [])
    if not positions:
        return {"status": "success", "message": "No Open Positions Found"}, 200

    # Convert to list if single position is returned as dict
    if isinstance(positions, dict):
        positions = [positions]

    # Loop through each position to close
    for position in positions:
        try:
            net_qty = position.get('netQuantity', '0')
            if not net_qty or int(net_qty) == 0:
                continue

            # Determine action based on net quantity
            quantity = abs(int(net_qty))
            action = 'SELL' if int(net_qty) > 0 else 'BUY'

            # Get OpenAlgo symbol
            symbol = get_symbol(position.get('token'), position.get('exchange'))
            if not symbol:
                positions_failed += 1
                error_messages.append(f"Failed to get symbol for token {position.get('token')}")
                continue

            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position.get('exchange'),
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position.get('product')),
                "quantity": str(quantity),
                "price": "0",
                "trigger_price": "0",
                "disclosed_quantity": "0"
            }

            # Place the order to close the position
            res, response, orderid = place_order_api(place_order_payload, auth)
            
            if response and response.get('status') == 'success':
                positions_closed += 1
            else:
                positions_failed += 1
                error_msg = response.get('error', {}).get('message') if response else 'Unknown error'
                error_messages.append(f"Failed to close position for {symbol}: {error_msg}")

        except Exception as e:
            positions_failed += 1
            error_messages.append(f"Error processing position: {str(e)}")

    # Prepare response message
    response = {
        "status": "success" if positions_failed == 0 else "partial",
        "message": f"Closed {positions_closed} positions" + 
                  (f", {positions_failed} failed" if positions_failed > 0 else ""),
        "details": {
            "positions_closed": positions_closed,
            "positions_failed": positions_failed,
            "errors": error_messages if error_messages else None
        }
    }

    return response, 200 if positions_closed > 0 or positions_failed == 0 else 400


def cancel_order(orderid, auth):
    """
    Cancel an existing order
    
    Args:
        orderid (str): Order number to cancel
        auth (str): Authentication token (jKey)
    
    Returns:
        tuple: (response dict, status code)
        
    Success Response:
    {
        "status": "success",
        "orderid": "1234567890111",
        "details": {
            "requestTime": "14:45:38 15-02-2023",
            "orderNumber": "1234567890111"
        }
    }
    
    Error Response:
    {
        "status": "error",
        "message": "Order not found to cancel",
        "code": "404",
        "name": "ORDER_NOT_FOUND",
        "field": "orderNumber"
    }
    """
    api_key = os.getenv('BROKER_API_KEY')
    api_key = api_key[:-4]  # Remove last 4 characters
    
    # Prepare request data
    request_data = {
        "jKey": auth,
        "userId": api_key,
        "orderNumber": str(orderid)  # Ensure orderid is string
    }
    
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        headers = {'Content-Type': 'application/json'}
        url = f"https://api.firstock.in/V1/cancelOrder"
        
        # Make request using shared httpx client
        response = client.request("POST", url, json=request_data, headers=headers, timeout=30)
        
        # Add status attribute for compatibility
        response.status = response.status_code
        
        response_data = response.json()
        
        if response_data.get("status") == "success":
            return {
                "status": "success",
                "orderid": orderid,
                "details": response_data.get("data", {})
            }, 200
        else:
            # Extract error details
            error = response_data.get("error", {})
            return {
                "status": "error",
                "message": error.get("message", "Failed to cancel order"),
                "code": response_data.get("code"),
                "name": response_data.get("name"),
                "field": error.get("field")
            }, int(response_data.get("code", 400))
            
    except Exception as e:
        logger.error(f"Error cancelling order: {e}")
        return {
            "status": "error",
            "message": f"Failed to cancel order: {str(e)}"
        }, 500


def modify_order(data, auth):
    """
    Modify an existing order
    
    Args:
        data (dict): Order modification data in OpenAlgo format
        auth (str): Authentication token (jKey)
    
    Returns:
        tuple: (response dict, status code)
        
    Response format:
    Success: {"status": "success", "orderid": "1234567890111"}
    Error: {"status": "error", "message": "error message"}
    """
    api_key = os.getenv('BROKER_API_KEY')
    api_key = api_key[:-4]  # Remove last 4 characters

    # Get token and transform symbol
    token = get_token(data['symbol'], data['exchange'])
    data['symbol'] = get_br_symbol(data['symbol'], data['exchange'])

    # Transform the data to Firstock format
    transformed_data = transform_modify_order_data(data, token)
    transformed_data.update({
        "jKey": auth,
        "userId": api_key
    })

    # Set up the request
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        headers = {'Content-Type': 'application/json'}
        url = f"https://api.firstock.in/V1/modifyOrder"
        
        # Make request using shared httpx client
        response = client.request("POST", url, json=transformed_data, headers=headers, timeout=30)
        
        # Add status attribute for compatibility
        response.status = response.status_code
        
        response_data = response.json()
        
        if response_data.get("status") == "success":
            return {
                "status": "success",
                "orderid": data["orderid"],
                "details": response_data.get("data", {})
            }, 200
        else:
            error_msg = (response_data.get("error", {}).get("message") or 
                        response_data.get("message", "Failed to modify order"))
            return {
                "status": "error",
                "message": error_msg,
                "code": response_data.get("code"),
                "name": response_data.get("name")
            }, response.status or 400
            
    except Exception as e:
        logger.error(f"Error modifying order: {e}")
        return {
            "status": "error",
            "message": f"Failed to modify order: {str(e)}"
        }, 500


def cancel_all_orders_api(data,auth):
    # Get the order book

    AUTH_TOKEN = auth
    

    order_book_response = get_order_book(AUTH_TOKEN)
    #logger.info(f"{order_book_response}")
    if order_book_response is None:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response.get('data', [])
                        if order['status'] in ['OPEN', 'TRIGGER_PENDING']]
    #logger.info(f"{orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['orderNumber']
        cancel_response, status_code = cancel_order(orderid,auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations


def placeorder(data, auth):
    """
    Place an order through Firstock API
    
    Parameters:
        data (dict): Order data in OpenAlgo format
        auth (str): Authentication token (jKey)
    
    Returns:
        dict: API response with order details
    """
    api_key = os.getenv('BROKER_API_KEY')
    api_key = api_key[:-4]  # Remove last 4 characters
    
    token = get_token(data['symbol'], data['exchange'])
    transformed_data = transform_data(data, token)
    transformed_data.update({
        "jKey": auth,
        "userId": api_key
    })
    
    return get_api_response("/placeOrder", auth, payload=transformed_data)
