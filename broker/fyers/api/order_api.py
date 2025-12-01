import json
import os
import httpx
from database.token_db import get_br_symbol, get_oa_symbol
from broker.fyers.mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)



def get_api_response(endpoint, auth, method="GET", payload=''):
    """
    Make API requests to Fyers API using shared connection pooling.
    
    Args:
        endpoint: API endpoint (e.g., /api/v3/orders)
        auth: Authentication token
        method: HTTP method (GET, POST, etc.)
        payload: Request payload as a string or dict
        
    Returns:
        dict: Parsed JSON response from the API
    """
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        AUTH_TOKEN = auth
        api_key = os.getenv('BROKER_API_KEY')
        
        url = f"https://api-t1.fyers.in{endpoint}"
        headers = {
            'Authorization': f'{api_key}:{AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        logger.debug(f"Making {method} request to Fyers API: {url}")
        
        # Make the request
        if method == "GET":
            response = client.get(url, headers=headers)
        elif method == "POST":
            response = client.post(url, headers=headers, json=payload if isinstance(payload, dict) else json.loads(payload))
        else:
            response = client.request(method, url, headers=headers, json=payload if isinstance(payload, dict) else json.loads(payload))
        
        # Add status attribute for compatibility
        response.status = response.status_code
        
        # Raise HTTPError for bad responses (4xx, 5xx)
        response.raise_for_status()
        
        # Parse and return the JSON response
        response_data = response.json()
        logger.debug(f"API response: {json.dumps(response_data, indent=2)}")
        return response_data
        
    except httpx.HTTPError as e:
        logger.error(f"HTTP error during API request: {e}")
        return {"s": "error", "message": f"HTTP error: {e}"}
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return {"s": "error", "message": f"Invalid JSON response: {e}"}
    except Exception as e:
        logger.exception("Error during API request")
        return {"s": "error", "message": f"General error: {e}"}

def get_order_book(auth):
    return get_api_response("/api/v3/orders",auth)

def get_trade_book(auth):
    return get_api_response("/api/v3/tradebook",auth)

def get_positions(auth):
    return get_api_response("/api/v3/positions",auth)

def get_holdings(auth):
    return get_api_response("/api/v3/holdings",auth)

def get_open_position(tradingsymbol, exchange, product,auth):

    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    

    positions_data = get_positions(auth)
    net_qty = '0'

    if positions_data and positions_data.get('s') and positions_data.get('netPositions'):
        for position in positions_data['netPositions']:

            if position.get('symbol') == tradingsymbol  and position.get("productType") == product:
                net_qty = position.get('netQty', '0')
                logger.debug(f"Net Quantity {net_qty}")
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data, auth):
    """
    Place a new order using the Fyers API with shared connection pooling.
    
    Args:
        data: Order details
        auth: Authentication token
        
    Returns:
        tuple: (response object, response data, order ID)
    """
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        AUTH_TOKEN = auth
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        data['apikey'] = BROKER_API_KEY
        
        url = "https://api-t1.fyers.in/api/v3/orders/sync"
        headers = {
            'Authorization': f'{BROKER_API_KEY}:{AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        # Transform the order data
        payload = transform_data(data)
        logger.debug(f"Placing order with payload: {json.dumps(payload, indent=2)}")
        
        # Make the POST request
        response = client.post(url, headers=headers, json=payload)
        response_data = response.json()
        
        # Add status attribute for compatibility
        response.status = response.status_code
        
        # Parse the response
        if response_data.get('s') == 'ok':
            orderid = response_data['id']
            logger.info(f"Order placed successfully. Order ID: {orderid}")
        elif response_data.get('s') == 'error':
            orderid = response_data.get('id')
            if not orderid:
                orderid = None
            error_msg = response_data.get('message', 'Unknown error')
            logger.warning(f"Order placement failed: {error_msg}")
            logger.debug(f"Failed order payload: {json.dumps(payload, indent=2)}")
            logger.debug(f"Failed order response: {json.dumps(response_data, indent=2)}")
        else:
            orderid = None
            logger.warning(f"Unexpected response format: {response_data}")
            logger.debug(f"Unexpected response payload: {json.dumps(payload, indent=2)}")
            
        return response, response_data, orderid
        
    except httpx.HTTPError as e:
        logger.error(f"HTTP error during order placement: {e}")
        response = type('obj', (object,), {'status_code': 500, 'status': 500})
        return response, {"s": "error", "message": f"HTTP error: {e}"}, None
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error during order placement: {e}")
        response = type('obj', (object,), {'status_code': 500, 'status': 500})
        return response, {"s": "error", "message": f"Invalid JSON response: {e}"}, None
    except Exception as e:
        logger.exception("Error during order placement")
        response = type('obj', (object,), {'status_code': 500, 'status': 500})
        return response, {"s": "error", "message": f"General error: {e}"}, None

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


    logger.debug(f"position_size : {position_size}") 
    logger.debug(f"Open Position : {current_position}") 
    
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
            logger.info("No open position found. Not placing exit order.")
            response = {"status": "success", "message": "No OpenPosition Found. Not placing Exit order."}
        else:
            logger.info("No action needed. Position size matches current position.")
            response = {"status": "success", "message": "No action needed. Position size matches current position"}
        orderid = None
        return res, response, orderid
   
   

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
    



def close_all_positions(current_api_key, auth):
    """
    Close all open positions using the Fyers API with shared connection pooling.
    
    Args:
        current_api_key: The API key (currently unused)
        auth: Authentication token
        
    Returns:
        tuple: (response data, status code)
    """
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        AUTH_TOKEN = auth
        api_key = os.getenv('BROKER_API_KEY')
        
        url = "https://api-t1.fyers.in/api/v3/positions"
        headers = {
            'Authorization': f'{api_key}:{AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        # Prepare the payload to close all positions
        payload = {"exit_all": 1}
        logger.debug("Closing all positions")
        
        # Make the DELETE request with the payload
        response = client.request("DELETE", url, headers=headers, json=payload)
        response_data = response.json()
        
        logger.debug(f"Close all positions response: {json.dumps(response_data, indent=2)}")
        
        # Check if the request was successful
        if response_data.get("s") == "ok":
            return {"status": "success", "message": "All positions closed successfully"}, 200
        else:
            error_msg = response_data.get("message", "Failed to close positions")
            logger.warning(f"Failed to close all positions: {error_msg}")
            return {"status": "error", "message": error_msg}, response.status_code
            
    except httpx.HTTPError as e:
        logger.exception("HTTP error during close all positions")
        return {"status": "error", "message": f"HTTP error: {e}"}, 500
    except json.JSONDecodeError as e:
        logger.exception("JSON decode error during close all positions")
        return {"status": "error", "message": f"JSON decode error: {e}"}, 500
    except Exception as e:
        logger.exception("Unexpected error during close all positions")
        return {"status": "error", "message": f"General error: {e}"}, 500

def cancel_order(orderid, auth):
    """
    Cancel an order using the Fyers API with shared connection pooling.
    
    Args:
        orderid: ID of the order to cancel
        auth: Authentication token
        
    Returns:
        tuple: (response data, status code)
    """
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        AUTH_TOKEN = auth
        api_key = os.getenv('BROKER_API_KEY')
        
        url = "https://api-t1.fyers.in/api/v3/orders/sync"
        headers = {
            'Authorization': f'{api_key}:{AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        # Prepare the payload with order ID
        payload = {"id": orderid}
        logger.debug(f"Cancelling order {orderid} with payload: {payload}")
        
        # Make the DELETE request with the order ID in the JSON body
        response = client.request("DELETE", url, headers=headers, json=payload)
        response_data = response.json()
        
        logger.debug(f"Cancel order response: {json.dumps(response_data, indent=2)}")
        
        # Check if the request was successful
        if response_data.get("s") == "ok":
            return {"status": "success", "orderid": response_data['id']}, 200
        else:
            error_msg = response_data.get("message", "Failed to cancel order")
            logger.warning(f"Failed to cancel order {orderid}: {error_msg}")
            return {"status": "error", "message": error_msg}, response.status_code
            
    except httpx.HTTPError as e:
        logger.exception("HTTP error during order cancellation")
        return {"status": "error", "message": f"HTTP error: {e}"}, 500
    except json.JSONDecodeError as e:
        logger.exception("JSON decode error during order cancellation")
        return {"status": "error", "message": f"JSON decode error: {e}"}, 500
    except Exception as e:
        logger.exception("Unexpected error during order cancellation")
        return {"status": "error", "message": f"General error: {e}"}, 500


def modify_order(data, auth):
    """
    Modify an existing order using the Fyers API with shared connection pooling.
    
    Args:
        data: Order modification details
        auth: Authentication token
        
    Returns:
        tuple: (response data, status code)
    """
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        AUTH_TOKEN = auth
        api_key = os.getenv('BROKER_API_KEY')
        
        url = "https://api-t1.fyers.in/api/v3/orders/sync"
        headers = {
            'Authorization': f'{api_key}:{AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        # Transform the order data
        payload = transform_modify_order_data(data)
        logger.debug(f"Modifying order with payload: {json.dumps(payload, indent=2)}")
        
        # Make the PATCH request
        response = client.patch(url, headers=headers, json=payload)
        response_data = response.json()
        
        logger.debug(f"Modify order response: {json.dumps(response_data, indent=2)}")
        
        # Check if the request was successful
        if response_data.get("s") in ["ok", "OK"]:
            return {"status": "success", "orderid": response_data["id"]}, 200
        else:
            error_msg = response_data.get("message", "Failed to modify order")
            logger.warning(f"Failed to modify order: {error_msg}")
            return {"status": "error", "message": error_msg}, response.status_code
            
    except httpx.HTTPError as e:
        logger.exception("HTTP error during order modification")
        return {"status": "error", "message": f"HTTP error: {e}"}, 500
    except json.JSONDecodeError as e:
        logger.exception("JSON decode error during order modification")
        return {"status": "error", "message": f"JSON decode error: {e}"}, 500
    except Exception as e:
        logger.exception("Unexpected error during order modification")
        return {"status": "error", "message": f"General error: {e}"}, 500
    except Exception as e:
        error_msg = f"Error during order modification: {str(e)}"
        logger.error(error_msg)
        return {"status": "error", "message": error_msg}, 500
    

def cancel_all_orders_api(data, auth):
    """
    Cancel all open orders.
    
    Args:
        data: (unused)
        auth: Authentication token
        
    Returns:
        tuple: (list of canceled order IDs, list of failed order IDs)
    """
    AUTH_TOKEN = auth
    order_book_response = get_order_book(AUTH_TOKEN)
    
    if order_book_response.get('s') != 'ok':
        error_msg = order_book_response.get('message', 'Failed to retrieve order book')
        logger.error(f"Could not fetch order book to cancel all orders: {error_msg}")
        return [], []

    orders_to_cancel = [
        order for order in order_book_response.get('orderBook', [])
        if order.get('status') in [4, 6]  # 4: Trigger-pending, 6: Open
    ]
    
    if not orders_to_cancel:
        logger.info("No open orders to cancel.")
        return [], []

    logger.debug(f"Found {len(orders_to_cancel)} open orders to cancel.")
    
    canceled_orders = []
    failed_cancellations = []

    for order in orders_to_cancel:
        orderid = order.get('id')
        if not orderid:
            logger.warning(f"Skipping order with no ID: {order}")
            continue
            
        cancel_response, status_code = cancel_order(orderid, AUTH_TOKEN)
        if status_code == 200:
            logger.info(f"Successfully canceled order {orderid}.")
            canceled_orders.append(orderid)
        else:
            logger.warning(f"Failed to cancel order {orderid}: {cancel_response.get('message', 'Unknown reason')}")
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations

