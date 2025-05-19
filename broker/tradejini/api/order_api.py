import httpx
import json
import os
from database.auth_db import get_auth_token
from database.token_db import get_token, get_br_symbol, get_oa_symbol
from ..mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data
from ..mapping.order_data import transform_tradebook_data, transform_holdings_data

from utils.httpx_client import get_httpx_client

def get_api_response(endpoint, auth, method="GET", data=None, params=None):
    """
    Make API request to Tradejini API with proper authentication.
    
    Args:
        endpoint (str): API endpoint path
        auth (str): Authentication token
        method (str): HTTP method (GET/POST/PUT/DELETE)
        data (dict): Request data
        params (dict): Query parameters
        
    Returns:
        dict: API response data
    """
    try:
        # Get API key from environment
        api_key = os.getenv('BROKER_API_SECRET')
        if not api_key:
            raise ValueError("Error: BROKER_API_SECRET not set")
            
        # Create auth header
        auth_header = f"{api_key}:{auth}"
        print(f"[DEBUG] get_api_response - Using auth header: {auth_header}")
        
        headers = {
            'Authorization': f'Bearer {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Make API request
        if method == "GET":
            response = client.get(
                f"https://api.tradejini.com/v2{endpoint}",
                headers=headers,
                params=params if params else data
            )
        elif method == "DELETE":
            response = client.delete(
                f"https://api.tradejini.com/v2{endpoint}",
                headers=headers,
                params=params
            )
        else:  # POST/PUT
            # Convert data to x-www-form-urlencoded format
            if data:
                data_str = '&'.join([f'{k}={v}' for k, v in data.items()])
                print(f"[DEBUG] get_api_response - Sending data: {data_str}")
            
            response = client.put(
                f"https://api.tradejini.com/v2{endpoint}",
                headers=headers,
                data=data_str if data else None
            )
            
        print(f"[DEBUG] get_api_response - Response status: {response.status_code}")
        print(f"[DEBUG] get_api_response - Response headers: {dict(response.headers)}")
        print(f"[DEBUG] get_api_response - Response body: {response.text}")
        
        # Handle 404 differently since it's a common error
        if response.status_code == 404:
            print("[WARNING] get_api_response - API endpoint not found. Trying without /v2 prefix")
            if method == "GET":
                response = client.get(
                    f"https://api.tradejini.com{endpoint}",
                    headers=headers,
                    params=params if params else data
                )
            elif method == "DELETE":
                response = client.delete(
                    f"https://api.tradejini.com{endpoint}",
                    headers=headers,
                    params=params
                )
            else:
                response = client.put(
                    f"https://api.tradejini.com{endpoint}",
                    headers=headers,
                    data=data_str if data else None
                )
            
            print(f"[DEBUG] get_api_response - Second attempt status: {response.status_code}")
            print(f"[DEBUG] get_api_response - Second attempt body: {response.text}")
            
        response.raise_for_status()  # Raise exception for bad status codes
        return response.json()
        
    except Exception as e:
        import traceback
        print(f"[ERROR] get_api_response - Exception occurred: {str(e)}")
        print(f"[ERROR] get_api_response - Traceback: {traceback.format_exc()}")
        raise

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
        
        # Create auth header
        auth_header = f"{api_key}:{auth}"
        headers = {
            'Authorization': f'Bearer {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        #print(f"[DEBUG] get_order_book - Making request to: {client.base_url}/v2/api/oms/orders")
        #print(f"[DEBUG] get_order_book - Headers: {headers}")
        #print(f"[DEBUG] get_order_book - Query params: {{'symDetails': 'true'}}")
        
        # Make API request
        response = client.get(
            "https://api.tradejini.com/v2/api/oms/orders",
            headers=headers,
            params={"symDetails": "true"}
        )
        
        #print(f"[DEBUG] get_order_book - Response status: {response.status_code}")
        #print(f"[DEBUG] get_order_book - Response headers: {dict(response.headers)}")
        
        response.raise_for_status()
        
        # Transform response data to OpenAlgo format
        response_data = response.json()
        print(f"[DEBUG] get_order_book - Raw response data: {response_data}")
        
        if response_data['s'] == 'ok':
            #print(f"[DEBUG] get_order_book - Found {len(response_data['d'])} orders")
            # Transform each order to OpenAlgo format
            transformed_orders = []
            for order in response_data['d']:
                #print(f"[DEBUG] get_order_book - Processing order: {order}")
                try:
                    # Get OpenAlgo symbol using symbol and exchange
                    openalgo_symbol = get_oa_symbol(
                        symbol=order['sym']['id'],
                        exchange=order['sym']['exch']
                    )
                    #print(f"[DEBUG] get_order_book - OpenAlgo symbol lookup for symbol {order['sym']['sym']}: {openalgo_symbol}")
                    
                    transformed_order = {
                        'stat': 'Ok',  # OpenAlgo expects 'stat' field
                        'data': {
                            'tradingsymbol': openalgo_symbol if openalgo_symbol else order['sym']['sym'],  # Fallback to Tradejini symbol if OpenAlgo not found
                            'exchange': order['sym']['exch'],
                            'token': order['symId'],
                            'exch': order['sym']['exch'],
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
                    #print(f"[DEBUG] get_order_book - Transformed order: {transformed_order}")
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
        error_msg = f"Exception in get_order_book: {str(e)}"
        print(f"[ERROR] get_order_book - {error_msg}")
        import traceback
        print(f"[ERROR] get_order_book - Traceback: {traceback.format_exc()}")
        return {
            'stat': 'Not_Ok',
            'data': {
                'msg': error_msg
            }
        }

def get_trade_book(auth):
    """
    Get list of trades using Tradejini API.
    
    Args:
        auth (str): Authentication token
        
    Returns:
        dict: Trade book data in OpenAlgo format
    """
    try:
        # Get API key from environment
        api_key = os.getenv('BROKER_API_SECRET')
        if not api_key:
            raise ValueError("Error: BROKER_API_SECRET not set")
            
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Create auth header in the format used by funds.py
        auth_header = f"{api_key}:{auth}"
        headers = {
            'Authorization': f'Bearer {auth_header}',
            'Content-Type': 'application/json'  # Changed from x-www-form-urlencoded to json
        }
        
        # Make API request
        response = client.get(
            "https://api.tradejini.com/v2/api/oms/trades",
            headers=headers,
            params={"symDetails": "true"}
        )
        
        response.raise_for_status()
        
        # Transform response data to OpenAlgo format
        response_data = response.json()
        
        if response_data['s'] == 'ok':
            # Extract trade data from response
            trade_data = response_data['d']
            
            # Transform trade data using existing function
            transformed_trades = transform_tradebook_data(trade_data)
            
            return {
                'status': 'success',
                'data': transformed_trades,
                'stat': 'Ok',
                'msg': 'Successfully fetched trade book'
            }
        else:
            return {
                'status': 'error',
                'message': f"TradeJini API returned error: {response_data.get('m', 'Unknown error')}",
                'stat': 'Not_Ok',
                'msg': f"TradeJini API returned error: {response_data.get('m', 'Unknown error')}"
            }
            
    except Exception as e:
        return {
            'status': 'error',
            'message': f"Error fetching trade book: {str(e)}",
            'stat': 'Not_Ok',
            'msg': f"Error fetching trade book: {str(e)}"
        }

def get_positions(auth):
    """
    Get list of positions using Tradejini API.
    
    Args:
        auth (str): Authentication token
        
    Returns:
        dict: Positions data in OpenAlgo format
    """
    try:
        # Get API key from environment
        api_key = os.getenv('BROKER_API_SECRET')
        if not api_key:
            raise ValueError("Error: BROKER_API_SECRET not set")
            
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Create auth header
        auth_header = f"{api_key}:{auth}"
        headers = {
            'Authorization': f'Bearer {auth_header}',
            'Content-Type': 'application/json'
        }
        
        # Make API request
        response = client.get(
            "https://api.tradejini.com/v2/api/oms/positions",
            headers=headers,
            params={"symDetails": "true"}
        )
        
        response.raise_for_status()
        
        # Transform response data to OpenAlgo format
        response_data = response.json()
        
        # Debug logging
        print(f"[DEBUG] get_positions - Raw response data: {response_data}")
        
        if response_data.get('s') == 'ok':
            # Map and transform position data
            mapped_data = map_position_data(response_data.get('d', []))
            transformed_data = transform_positions_data(mapped_data)
            
            return {
                "status": "success",
                "data": transformed_data
            }
        else:
            error_msg = response_data.get('d', {}).get('msg', 'Unknown error')
            print(f"[DEBUG] get_positions - API error: {error_msg}")
            return {
                "status": "error",
                "message": error_msg
            }
            
    except httpx.HTTPStatusError as e:
        print(f"[DEBUG] get_positions - HTTP error: {e.response.status_code}")
        print(f"[DEBUG] get_positions - Response: {e.response.text}")
        return {
            "status": "error",
            "message": f"HTTP error {e.response.status_code}: {e.response.text}"
        }
    except httpx.RequestError as e:
        print(f"[DEBUG] get_positions - Network error: {str(e)}")
        return {
            "status": "error",
            "message": f"Network error: {str(e)}"
        }
    except Exception as e:
        print(f"[DEBUG] get_positions - Unexpected error: {str(e)}")
        import traceback
        print(f"[DEBUG] get_positions - Traceback: {traceback.format_exc()}")
        return {
            "status": "error",
            "message": f"Unexpected error: {str(e)}"
        }

def get_holdings(auth):
    """
    Get list of holdings using Tradejini API.
    
    Args:
        auth (str): Authentication token
        
    Returns:
        dict: Holdings data in OpenAlgo format
    """
    try:
        print("[DEBUG] Fetching holdings from Tradejini API")
        # Make API request with symDetails=true to get symbol details
        response = get_api_response(
            '/api/oms/holdings',
            auth,
            method="GET",
            data={"symDetails": "true"}
        )
        
        print(f"[DEBUG] API Response: {response}")
        
        # Get holdings data from response
        holdings_data = response.get('d', {}).get('holdings', [])
        print(f"[DEBUG] Raw holdings data: {holdings_data}")
        
        if not isinstance(holdings_data, list):
            print("[ERROR] Holdings data is not a list")
            return {"status": "error", "message": "Invalid holdings data format"}
            
        # Transform data to OpenAlgo format
        from ..mapping.order_data import transform_holdings_data
        transformed_data = transform_holdings_data(holdings_data)
        
        return transformed_data
        
    except Exception as e:
        print(f"[ERROR] Error fetching holdings: {str(e)}")
        return {"status": "error", "message": str(e)}

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
    
    # Get order book
    order_book_response = await get_order_book(auth)
    
    if not order_book_response:
        return {"status": "success", "message": "No Open Positions Found"}

    if order_book_response:
        for position in order_book_response:
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
    
    Args:
        orderid (str): Order ID to cancel
        auth (str): Authentication token
        
    Returns:
        tuple: (response_data, status_code)
    """
    try:
        print(f"[DEBUG] cancel_order - Received orderid: {orderid}")
        print(f"[DEBUG] cancel_order - Received auth: {auth}")
        
        # Prepare query parameters
        params = {"orderId": orderid}
        print(f"[DEBUG] cancel_order - Query parameters: {params}")
        
        # Make API request
        print(f"[DEBUG] cancel_order - Making API request to /api/oms/cancel-order")
        response = get_api_response(
            "/api/oms/cancel-order",
            auth=auth,
            method="DELETE",
            params=params  # Using params instead of data
        )
        print(f"[DEBUG] cancel_order - API response: {response}")
        
        # Handle response
        if response["s"] == "ok":
            print(f"[DEBUG] cancel_order - Order cancelled successfully")
            return {
                "stat": "Ok",
                "data": {
                    "msg": "Order cancelled successfully",
                    "order_id": response["d"]["orderId"]
                }
            }, 200
        elif response["s"] == "no-data":
            error_msg = f"Order cancellation failed: {response["msg"]}"
            print(f"[ERROR] cancel_order - {error_msg}")
            return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 400
        else:
            error_msg = f"Order cancellation failed: {response.get('msg', 'Unknown error')}"
            print(f"[ERROR] cancel_order - {error_msg}")
            return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 400
            
    except Exception as e:
        error_msg = f"Exception in cancel_order: {str(e)}"
        print(f"[ERROR] cancel_order - {error_msg}")
        import traceback
        print(f"[ERROR] cancel_order - Traceback: {traceback.format_exc()}")
        return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 500

def cancel_all_orders_api(data, auth):
    """
    Cancel all open orders using Tradejini API.
    
    Args:
        data (dict): Order data
        auth (str): Authentication token
        
    Returns:
        tuple: (list of canceled orders, list of failed cancellations)
    """
    try:
        print(f"[DEBUG] cancel_all_orders_api - Getting order book")
        order_book_response = get_order_book(auth)
        print(f"[DEBUG] cancel_all_orders_api - Order book response: {order_book_response}")
        
        if not order_book_response:
            print("[DEBUG] cancel_all_orders_api - No orders found")
            return [], []

        if order_book_response.get('stat') == 'Ok':
            orders = order_book_response.get('data', [])
            print(f"[DEBUG] cancel_all_orders_api - Found {len(orders)} orders")
            
            canceled_orders = []
            failed_cancellations = []
            
            for order in orders:
                if order.get('status') in ['OPEN', 'TRIGGER PENDING', 'MODIFIED']:
                    print(f"[DEBUG] cancel_all_orders_api - Cancelling order: {order.get('orderId')}")
                    cancel_response, status_code = cancel_order(order.get('orderId'), auth)
                    print(f"[DEBUG] cancel_all_orders_api - Cancel response: {cancel_response}")
                    
                    if cancel_response[0].get('stat') == 'Ok':
                        canceled_orders.append(order.get('orderId'))
                    else:
                        error_msg = f"Failed to cancel order {order.get('orderId')}: {cancel_response[0].get('data', {}).get('msg', 'Unknown error')}"
                        print(f"[ERROR] cancel_all_orders_api - {error_msg}")
                        failed_cancellations.append({"orderId": order.get('orderId'), "error": error_msg})
            
            return canceled_orders, failed_cancellations
        else:
            error_msg = f"Failed to get order book: {order_book_response.get('data', {}).get('msg', 'Unknown error')}"
            print(f"[ERROR] cancel_all_orders_api - {error_msg}")
            return [], []
            
    except Exception as e:
        error_msg = f"Exception in cancel_all_orders_api: {str(e)}"
        print(f"[ERROR] cancel_all_orders_api - {error_msg}")
        import traceback
        print(f"[ERROR] cancel_all_orders_api - Traceback: {traceback.format_exc()}")
        return [], []

def modify_order(data, auth):
    """
    Modify an order using Tradejini API.
    
    Args:
        data (dict): Order modification data
        auth (str): Authentication token
        
    Returns:
        tuple: (response_data, status_code)
    """
    try:
        print(f"[DEBUG] modify_order - Received data: {data}")
        print(f"[DEBUG] modify_order - Received auth: {auth}")
        
        # Get broker symbol token
        token = get_token(data["symbol"], data["exchange"])
        print(f"[DEBUG] modify_order - Token lookup result: {token}")
        
        if not token:
            error_msg = "Symbol not found in token database"
            print(f"[ERROR] modify_order - {error_msg}")
            return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 400
            
        # Transform data to Tradejini format
        try:
            transformed_data = transform_modify_order_data(data, token)
            print(f"[DEBUG] modify_order - Transformed data: {transformed_data}")
        except ValueError as e:
            error_msg = str(e)
            print(f"[ERROR] modify_order - {error_msg}")
            return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 400
        
        # Make API request
        print(f"[DEBUG] modify_order - Making API request to /api/oms/modify-order")
        response = get_api_response(
            "/api/oms/modify-order",
            auth=auth,
            method="PUT",
            data=transformed_data
        )
        print(f"[DEBUG] modify_order - API response: {response}")
        
        # Handle different response formats
        if response["s"] == "ok":
            print(f"[DEBUG] modify_order - Order modified successfully")
            return {
                "stat": "Ok",
                "data": {
                    "msg": "Order modified successfully",
                    "order_id": response["d"]["orderId"]
                }
            }, 200
        elif response["s"] == "no-data":
            error_msg = f"Order modification failed: {response["msg"]}"
            print(f"[ERROR] modify_order - {error_msg}")
            return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 400
        else:
            error_msg = f"Order modification failed: {response.get('msg', 'Unknown error')}"
            print(f"[ERROR] modify_order - {error_msg}")
            return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 400
            
    except Exception as e:
        error_msg = f"Exception in modify_order: {str(e)}"
        print(f"[ERROR] modify_order - {error_msg}")
        import traceback
        print(f"[ERROR] modify_order - Traceback: {traceback.format_exc()}")
        return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 500
