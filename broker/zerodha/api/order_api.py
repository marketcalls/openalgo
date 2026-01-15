import http.client
import json
import os
import urllib.parse
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_oa_symbol
from broker.zerodha.mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)




def get_api_response(endpoint, auth, method="GET", payload=None):
    """
    Make an API request to Zerodha's API using shared httpx client with connection pooling.
    
    Args:
        endpoint (str): API endpoint (e.g., '/orders')
        auth (str): Authentication token
        method (str): HTTP method (GET, POST, etc.)
        payload (dict/str, optional): Request payload
        
    Returns:
        dict: API response data
    """
    AUTH_TOKEN = auth
    base_url = 'https://api.kite.trade'
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'X-Kite-Version': '3',
        'Authorization': f'token {AUTH_TOKEN}'
    }
    
    url = f"{base_url}{endpoint}"
    
    try:
        # Handle different HTTP methods
        if method.upper() == 'GET':
            response = client.get(
                url,
                headers=headers
            )
        elif method.upper() == 'POST':
            if isinstance(payload, str):
                # For form-urlencoded data
                headers['Content-Type'] = 'application/x-www-form-urlencoded'
                response = client.post(
                    url,
                    headers=headers,
                    content=payload
                )
            else:
                # For JSON data
                headers['Content-Type'] = 'application/json'
                response = client.post(
                    url,
                    headers=headers,
                    json=payload
                )
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
            
        # Parse and return JSON response
        response.raise_for_status()
        return response.json()
        
    except Exception as e:
        error_msg = str(e)
        # Try to extract more error details if available
        try:
            if hasattr(e, 'response') and e.response is not None:
                error_detail = e.response.json()
                error_msg = error_detail.get('message', error_msg)
        except:
            pass
            
        logger.exception(f"API request failed: {error_msg}")
        raise

def get_order_book(auth):
    return get_api_response("/orders",auth)

def get_trade_book(auth):
    return get_api_response("/trades",auth)

def get_positions(auth):
    return get_api_response("/portfolio/positions",auth)

def get_holdings(auth):
    return get_api_response("/portfolio/holdings",auth)

def get_open_position(tradingsymbol, exchange, product,auth):

    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    

    positions_data = get_positions(auth)
    net_qty = '0'


    if positions_data and positions_data.get('status') and positions_data.get('data'):
        for position in positions_data['data']['net']:
            if position.get('tradingsymbol') == tradingsymbol and position.get('exchange') == exchange and position.get('product') == product:
                net_qty = position.get('quantity', '0')
                logger.info(f"Net Quantity {net_qty}")
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data,auth):
    AUTH_TOKEN = auth
    
    BROKER_API_KEY = os.getenv('BROKER_API_KEY')
    data['apikey'] = BROKER_API_KEY
    #token = get_token(data['symbol'], data['exchange'])
    newdata = transform_data(data)
    
    # Prepare the payload
    payload = {
        'tradingsymbol': newdata['tradingsymbol'],
        'exchange': newdata['exchange'],
        'transaction_type': newdata['transaction_type'],
        'order_type': newdata['order_type'],
        'quantity': newdata['quantity'],
        'product': newdata['product'],
        'price': newdata['price'],
        'trigger_price': newdata['trigger_price'],
        'disclosed_quantity': newdata['disclosed_quantity'],
        'validity': newdata['validity'],
        'tag': newdata['tag']
    }

    logger.info(f"Payload for place_order_api: {payload}")
    
    # URL-encode the payload
    payload_encoded = urllib.parse.urlencode(payload)
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'X-Kite-Version': '3',
        'Authorization': f'token {AUTH_TOKEN}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    # Make the request using the shared client
    response = client.post(
        'https://api.kite.trade/orders/regular',
        headers=headers,
        content=payload_encoded
    )
    
    # Parse the response
    response_data = response.json()
    logger.info(f"Response from place_order_api: {response_data}")
    
    # Handle the response
    if response_data['status'] == 'success':
        orderid = response_data['data']['order_id']
    else:
        orderid = None
        
    # Add status attribute to maintain backward compatibility with the caller
    response.status = response.status_code
    
    # Return the response object, response data, and order ID
    return response, response_data, orderid

def place_smartorder_api(data,auth):
    AUTH_TOKEN = auth

    # Initialize default return values
    res = None
    response_data = {"status": "error", "message": "No action required or invalid parameters"}
    orderid = None

    try:
        # Extract necessary info from data
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        product = data.get("product")
        
        if not all([symbol, exchange, product]):
            logger.info("Missing required parameters in place_smartorder_api")
            return res, response_data, orderid
            
        position_size = int(data.get("position_size", "0"))

        # Get current open position for the symbol
        current_position = int(get_open_position(symbol, exchange, map_product_type(product), AUTH_TOKEN))

        logger.info(f"position_size: {position_size}")
        logger.info(f"Open Position: {current_position}")

        # Determine action based on position_size and current_position
        action = None
        quantity = 0

        if position_size == 0 and current_position > 0:
            action = "SELL"
            quantity = abs(current_position)
        elif position_size == 0 and current_position < 0:
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

        if action and quantity > 0:
            # Prepare data for placing the order
            order_data = data.copy()
            order_data["action"] = action
            order_data["quantity"] = str(quantity)


            # Place the order
            res, response, orderid = place_order_api(order_data, AUTH_TOKEN)
            return res, response, orderid
        else:
            logger.info("No action required or invalid quantity")
            response_data = {"status": "success", "message": "No action required"}
            return res, response_data, orderid
            
    except Exception as e:
        error_msg = f"Error in place_smartorder_api: {e}"
        logger.exception(error_msg)
        response_data = {"status": "error", "message": error_msg}
        return res, response_data, orderid
    
    # Final fallback return (should not be reached due to the returns above)
    return res, response_data, orderid
    



def close_all_positions(current_api_key,auth):

    AUTH_TOKEN = auth
    # Fetch the current open positions
    positions_response = get_positions(AUTH_TOKEN)


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

            logger.info(f"Close position payload: {place_order_payload}")

            # Place the order to close the position
            _, api_response, _ =   place_order_api(place_order_payload,AUTH_TOKEN)

            logger.info(f"Close position response: {api_response}")
            
            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    """
    Cancel an existing order using the shared httpx client with connection pooling.
    
    Args:
        orderid (str): The ID of the order to cancel
        auth (str): Authentication token
        
    Returns:
        tuple: (response data, status code)
    """
    AUTH_TOKEN = auth
    
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        # Set up the request headers
        headers = {
            'X-Kite-Version': '3',
            'Authorization': f'token {AUTH_TOKEN}'
        }
        
        # Make the DELETE request using the shared client
        response = client.delete(
            f'https://api.kite.trade/orders/regular/{orderid}',
            headers=headers
        )
        
        response.raise_for_status()
        data = response.json()
        logger.info(f"Cancel order response: {data}")
        
        # Check if the request was successful
        if data.get("status"):
            return {"status": "success", "orderid": data['data']['order_id']}, 200
        else:
            return {"status": "error", "message": data.get("message", "Failed to cancel order")}, response.status_code
            
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Error canceling order {orderid}: {error_msg}")
        return {"status": "error", "message": f"Failed to cancel order: {error_msg}"}, 500

def modify_order(data,auth):
    AUTH_TOKEN = auth
    
    newdata = transform_modify_order_data(data)  # You need to implement this function
    
    # Prepare the payload with proper handling of numeric fields
    payload = {
        'order_type': newdata['order_type'],
        'quantity': str(newdata['quantity']),
        'price': str(newdata['price']) if newdata['price'] else '0',
        'disclosed_quantity': str(newdata['disclosed_quantity']) if newdata['disclosed_quantity'] else '0',
        'validity': newdata['validity']
    }
    
    # Only include trigger_price if it has a value
    if newdata.get('trigger_price'):
        payload['trigger_price'] = str(newdata['trigger_price'])
    
    logger.info(f"Modify order payload: {payload}")
    
    # URL-encode the payload
    payload_encoded = urllib.parse.urlencode(payload)
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'X-Kite-Version': '3',
        'Authorization': f'token {AUTH_TOKEN}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    # Make the request using the shared client
    response = client.put(
        f'https://api.kite.trade/orders/regular/{data["orderid"]}',
        headers=headers,
        content=payload_encoded
    )
    
    # Parse the response
    response_data = response.json()
    logger.info(f"Modify order response: {response_data}")
    
    # Add status attribute to maintain backward compatibility
    response.status = response.status_code
    
    if response_data.get("status") == "success" or response_data.get("message") == "SUCCESS":
        return {"status": "success", "orderid": response_data["data"]["order_id"]}, 200
    else:
        return {"status": "error", "message": response_data.get("message", "Failed to modify order")}, response.status_code
    

def cancel_all_orders_api(data,auth):

    AUTH_TOKEN = auth
    # Get the order book
    order_book_response = get_order_book(AUTH_TOKEN)
    if order_book_response['status'] != 'success':
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response.get('data', [])
                        if order['status'] in ['OPEN', 'TRIGGER PENDING']]
    logger.info(f"{orders_to_cancel}")
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

