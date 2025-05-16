import httpx
import json
import os
from database.auth_db import get_auth_token
from database.token_db import get_token, get_br_symbol, get_symbol
from ..mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data

from utils.httpx_client import get_httpx_client

def get_api_response(endpoint, auth, method="GET", data=None):
    """
    Make API request to Tradejini API with proper authentication.
    """
    AUTH_TOKEN = auth
    
    # Get API key from environment
    api_key = os.getenv('BROKER_API_SECRET')
    if not api_key:
        raise ValueError("Error: BROKER_API_SECRET not set")
        
    # Extract auth token from auth
    auth_token = AUTH_TOKEN.split(':')[1]
    
    # Set up authentication header
    auth_header = f"{api_key}:{auth_token}"
    
    headers = {
        'Authorization': f'Bearer {auth_header}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    # Get the shared httpx client
    client = get_httpx_client()
    
    if method == "GET":
        response = client.get(
            f"https://api.tradejini.com/v2{endpoint}",
            headers=headers,
            params=data
        )
    else:  # POST
        response = client.post(
            f"https://api.tradejini.com/v2{endpoint}",
            headers=headers,
            data=data
        )
        
    response.raise_for_status()  # Raise exception for bad status codes
    return response.json()

def get_order_book(auth):
    """
    Get list of orders placed using Tradejini API.
    
    Args:
        auth (str): Authentication token
        
    Returns:
        dict: Order book data in OpenAlgo format
    """
    try:
        # Get API key from environment
        api_key = os.getenv('BROKER_API_SECRET')
        if not api_key:
            raise ValueError("Error: BROKER_API_SECRET not set")
            
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Set up authentication header
        auth_header = f"{api_key}:{auth}"
        headers = {
            'Authorization': f'Bearer {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        print(f"[DEBUG] get_order_book - Making request to: {client.base_url}/v2/api/oms/orders")
        print(f"[DEBUG] get_order_book - Headers: {headers}")
        print(f"[DEBUG] get_order_book - Query params: {{'symDetails': 'true'}}")
        
        # Make API request
        response = client.get(
            "https://api.tradejini.com/v2/api/oms/orders",
            headers=headers,
            params={"symDetails": "true"}
        )
        
        print(f"[DEBUG] get_order_book - Response status: {response.status_code}")
        print(f"[DEBUG] get_order_book - Response headers: {dict(response.headers)}")
        
        response.raise_for_status()
        
        # Transform response data to OpenAlgo format
        response_data = response.json()
        print(f"[DEBUG] get_order_book - Raw response data: {response_data}")
        
        if response_data['s'] == 'ok':
            print(f"[DEBUG] get_order_book - Found {len(response_data['d'])} orders")
            # Transform each order to OpenAlgo format
            transformed_orders = []
            for order in response_data['d']:
                print(f"[DEBUG] get_order_book - Processing order: {order}")
                try:
                    transformed_order = {
                        'stat': 'Ok',  # OpenAlgo expects 'stat' field
                        'data': {
                            'tradingsymbol': order['sym']['sym'],  # Changed from 'symbol' to 'sym'
                            'exchange': order['sym']['exch'],      # Changed from 'exchange' to 'exch'
                            'token': order['symId'],
                            'exch': order['sym']['exch'],         # Changed from 'exchange' to 'exch'
                            'quantity': order['qty'],
                            'side': order['side'],
                            'type': order['type'],
                            'product': order['product'],
                            'order_id': order['orderId'],
                            'order_time': order['orderTime'],
                            'status': order['status'],
                            'avg_price': order['avgPrice'],
                            'limit_price': order['limitPrice'],
                            'fill_quantity': order['fillQty'],
                            'pending_quantity': order['pendingQty'],
                            'validity': order['validity'],
                            'valid_till': order['validTill']
                        }
                    }
                    print(f"[DEBUG] get_order_book - Transformed order: {transformed_order}")
                    transformed_orders.append(transformed_order)
                except KeyError as e:
                    print(f"[ERROR] get_order_book - Missing field in order: {str(e)}")
                    print(f"[ERROR] get_order_book - Order data: {order}")
                    continue
            
            return {
                'stat': 'Ok',
                'data': transformed_orders
            }
        else:
            print(f"[DEBUG] get_order_book - API error: {response_data.get('d', {}).get('msg', 'Unknown error')}")
            return {
                'stat': 'Not_Ok',
                'data': {
                    'msg': response_data.get('d', {}).get('msg', 'Unknown error')
                }
            }
            
    except Exception as e:
        print(f"[ERROR] get_order_book - Exception occurred: {str(e)}")
        import traceback
        print(f"[ERROR] get_order_book - Traceback: {traceback.format_exc()}")
        return {
            'stat': 'Not_Ok',
            'data': {
                'msg': str(e)
            }
        }

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

    print(positions_data)

    net_qty = '0'

    if positions_data is None or (isinstance(positions_data, dict) and (positions_data['stat'] == "Not_Ok")):
        # Handle the case where there is no data
        print("No data available.")
        net_qty = '0'

    if positions_data and isinstance(positions_data, list):
        for position in positions_data:
            if position.get('tsym') == tradingsymbol and position.get('exch') == exchange and position.get('prd') == producttype:
                net_qty = position.get('netqty', '0')
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data, auth):
    """
    Place an order using Tradejini API.
    
    Args:
        data (dict): Order data
        auth (str): Authentication token
        
    Returns:
        tuple: (None, response_data, order_id)
    """
    try:
        AUTH_TOKEN = auth
        api_key = os.getenv('BROKER_API_KEY')
        
        # Log input parameters for debugging
        print(f"[DEBUG] place_order_api - Input data: {data}")
        print(f"[DEBUG] place_order_api - AUTH_TOKEN: {AUTH_TOKEN}")
        print(f"[DEBUG] place_order_api - BROKER_API_KEY: {api_key}")
        
        # Get token and transform data
        token = get_token(data['symbol'], data['exchange'])
        transformed_data = transform_data(data, token)
        
        # Convert transformed data to x-www-form-urlencoded format
        payload = '&'.join([f'{k}={v}' for k, v in transformed_data.items()])
        print(f"[DEBUG] place_order_api - Payload: {payload}")
        print(f"[DEBUG] place_order_api - Input auth: {AUTH_TOKEN}")
        
        # Get API key from environment
        api_key = os.getenv('BROKER_API_SECRET')
        if not api_key:
            raise ValueError("Error: BROKER_API_SECRET not set")
            
        # Use the auth token directly
        auth_token = AUTH_TOKEN
        auth_header = f"{api_key}:{auth_token}"
        
        print(f"[DEBUG] place_order_api - API Key: {api_key}")
        print(f"[DEBUG] place_order_api - Auth Token: {auth_token}")
        print(f"[DEBUG] place_order_api - Auth Header: {auth_header}")
        
        headers = {
            'Authorization': f'Bearer {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Make API request
        print(f"[DEBUG] place_order_api - Making request to: https://api.tradejini.com/v2/oms/place-order")
        response = client.post(
            "https://api.tradejini.com/v2/oms/place-order",
            headers=headers,
            data=payload
        )
        
        # Log response details
        print(f"[DEBUG] place_order_api - Response status: {response.status_code}")
        print(f"[DEBUG] place_order_api - Response headers: {dict(response.headers)}")
        
        response.raise_for_status()
        response_data = response.json()
        print(f"[DEBUG] place_order_api - Response data: {response_data}")
        
        if response_data['s'] == 'ok':
            # Create a response-like object with status attribute
            class ResponseLike:
                def __init__(self, status_code):
                    self.status = status_code
            
            response_obj = ResponseLike(200)
            return response_obj, {"status": "success", "message": response_data['d']['msg'], "orderid": response_data['d']['orderId']}, response_data['d']['orderId']
        else:
            # Create a response-like object with error status
            class ResponseLike:
                def __init__(self, status_code):
                    self.status = status_code
            
            response_obj = ResponseLike(response.status_code)
            return response_obj, {"status": "error", "message": response_data.get('d', {}).get('msg', 'Order placement failed')}, None
            
    except Exception as e:
        print(f"[ERROR] place_order_api - Exception occurred: {str(e)}")
        import traceback
        print(f"[ERROR] place_order_api - Traceback: {traceback.format_exc()}")
        return None, {"status": "error", "message": f"Order placement failed: {str(e)}"}, None

async def place_smartorder_api(data, auth):
    """
    Place a smart order using Tradejini API.
    """
    AUTH_TOKEN = auth

    # Extract necessary info from data
    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")
    position_size = int(data.get("position_size", "0"))

    # Get current open position for the symbol
    current_position = int(get_open_position(symbol, exchange, map_product_type(product), AUTH_TOKEN))

    print(f"position_size: {position_size}")
    print(f"Open Position: {current_position}")
    
    # Determine action based on position_size and current_position
    action = None
    quantity = 0

    # If both position_size and current_position are 0, do nothing
    if position_size == 0 and current_position == 0 and int(data['quantity']) != 0:
        action = data['action']
        quantity = data['quantity']
        res, response, orderid = await place_order_api(data, auth)
        return res, response, orderid
        
    elif position_size == current_position:
        if int(data['quantity']) == 0:
            response = {"status": "success", "message": "No OpenPosition Found. Not placing Exit order."}
        else:
            response = {"status": "success", "message": "No action needed. Position size matches current position"}
        orderid = None
        return None, response, orderid
   
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

    if action:
        # Prepare data for placing the order
        order_data = data.copy()
        order_data["action"] = action
        order_data["quantity"] = str(quantity)

        # Place the order
        res, response, orderid = await place_order_api(order_data, auth)
        return res, response, orderid

async def close_all_positions(current_api_key, auth):
    """
    Close all open positions using Tradejini API.
    """
    AUTH_TOKEN = auth

    positions_response = await get_positions(auth)

    if positions_response is None or positions_response.get('stat') == "Not_Ok":
        return {"status": "success", "message": "No Open Positions Found"}

    if positions_response:
        for position in positions_response:
            if int(position.get('netqty', 0)) == 0:
                continue

            action = 'SELL' if int(position['netqty']) > 0 else 'BUY'
            quantity = abs(int(position['netqty']))

            symbol = get_symbol(position['token'], position['exch'])
            print(f'The Symbol is {symbol}')

            order_data = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position['exch'],
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position['prd']),
                "quantity": str(quantity)
            }

            print(order_data)
            res, response, orderid = await place_order_api(order_data, auth)

    return {"status": "success", "message": "All Open Positions SquaredOff"}

def cancel_order(orderid, auth):
    """
    Cancel an order using Tradejini API.
    """
    AUTH_TOKEN = auth
    
    # Get API key from environment
    api_key = os.getenv('BROKER_API_SECRET')
    if not api_key:
        raise ValueError("Error: BROKER_API_SECRET not set")
        
    # Extract auth token from auth
    auth_token = AUTH_TOKEN.split(':')[1]
    
    # Set up authentication header
    auth_header = f"{api_key}:{auth_token}"
    
    headers = {
        'Authorization': f'Bearer {auth_header}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    # Get the shared httpx client
    client = get_httpx_client()
    
    # Make API request
    response = client.post(
        "https://api.tradejini.com/v2/oms/cancel-order",
        headers=headers,
        data=f"orderId={orderid}"
    )
    response.raise_for_status()
    response_data = response.json()
    
    if response_data['s'] == 'ok':
        return None, {"status": "success", "message": response_data['d']['msg']}, 200
    else:
        return None, {"status": "error", "message": response_data.get('d', {}).get('msg', 'Order cancellation failed')}, response.status_code

def modify_order(data, auth):
    """
    Modify an order using Tradejini API.
    """
    # Get API key from environment
    api_key = os.getenv('BROKER_API_SECRET')
    if not api_key:
        raise ValueError("Error: BROKER_API_SECRET not set")
        
    # Set up authentication header
    auth_header = f"{api_key}:{auth_token}"
    headers = {
        'Authorization': f'Bearer {auth_header}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    # Get token and transform data
    token = get_token(data['symbol'], data['exchange'])
    transformed_data = transform_modify_order_data(data, token)
    
    # Convert transformed data to x-www-form-urlencoded format
    payload = '&'.join([f'{k}={v}' for k, v in transformed_data.items()])
    
    # Get the shared httpx client
    client = get_httpx_client()
    
    # Make API request
    response = client.post(
        "https://api.tradejini.com/v2/oms/modify-order",
        headers=headers,
        data=payload
    )
    response.raise_for_status()
    response_data = response.json()
    
    if response_data['s'] == 'ok':
        return None, {"status": "success", "message": response_data['d']['msg']}, 200
    else:
        return None, {"status": "error", "message": response_data.get('d', {}).get('msg', 'Order modification failed')}, response.status_code



async def cancel_all_orders_api(data, auth):
    """
    Cancel all open orders using Tradejini API.
    """
    AUTH_TOKEN = auth
    
    # Get order book
    order_book_response = await get_order_book(auth)
    
    if order_book_response is None:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response
                        if order['status'] in ['OPEN', 'TRIGGER_PENDING']]
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['norenordno']
        cancel_response, status_code = await cancel_order(orderid, auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations

