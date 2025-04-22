
import json
from flask import session
from utils.httpx_client import get_httpx_client
from database.token_db import get_br_symbol, get_oa_symbol
from database.auth_db import Auth, db_session
from broker.pocketful.mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data



# Pocketful API endpoints
BASE_URL = 'https://trade.pocketful.in'
ORDER_ENDPOINT = f"{BASE_URL}/api/v1/orders"

def get_api_response(endpoint, auth_token, method="GET", payload=None):
    """
    Make API request to Pocketful's endpoints using the shared httpx client.
    Supports GET, POST, PUT, DELETE methods.
    """
    # Get the shared httpx client
    client = get_httpx_client()
    
    # Set up headers with authorization token
    headers = {
        'Authorization': f'Bearer {auth_token}',
        'Content-Type': 'application/json'
    }
    
    # Add debugging information for the URL construction
    full_url = endpoint
    if not endpoint.startswith('http'):
        if endpoint.startswith('/'):
            full_url = f"{BASE_URL}{endpoint}"
        else:
            full_url = f"{BASE_URL}/{endpoint}"
    
    print(f"DEBUG - API Request Details:")
    print(f"DEBUG - Method: {method}")
    print(f"DEBUG - Endpoint param: {endpoint}")
    print(f"DEBUG - Constructed URL: {full_url}")
    if payload:
        print(f"DEBUG - Payload: {json.dumps(payload, indent=2)}")
        if 'oms_order_id' in payload:
            print(f"DEBUG - Order ID in payload: {payload['oms_order_id']}")
    
    try:
        if method == "GET":
            print(f"DEBUG - Executing GET request to {full_url}")
            response = client.get(full_url, headers=headers)
        elif method == "POST":
            print(f"DEBUG - Executing POST request to {full_url}")
            response = client.post(full_url, headers=headers, json=payload)
        elif method == "PUT":
            print(f"DEBUG - Executing PUT request to {full_url}")
            response = client.put(full_url, headers=headers, json=payload)
        elif method == "DELETE":
            print(f"DEBUG - Executing DELETE request to {full_url}")
            response = client.delete(full_url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
            
        # Add status attribute for compatibility
        response.status = response.status_code
        print(f"DEBUG - Response status code: {response.status_code}")
        print(f"DEBUG - Response URL (final): {response.url}")
        print("DEBUG - Response content:", response.text)
        response.raise_for_status()
        
        try:
            return response.json()
        except ValueError:
            # Handle case where response is not JSON
            print("DEBUG - Response is not valid JSON")
            return {"status": "success" if response.status_code < 400 else "error", 
                    "message": response.text}
    except Exception as e:
        print(f"API request error: {str(e)}")
        return {"status": "error", "message": str(e)}

def get_order_book(auth):
    """
    Get the order book from Pocketful API by combining both completed and pending orders.
    
    Args:
        auth: Authentication token for Pocketful API
        
    Returns:
        Dictionary with combined order book data in standard format
    """
    print(f"DEBUG - Fetching Pocketful order book (completed and pending orders)")
    
    # Get client_id needed for API requests
    client_id = get_client_id(auth)
    if not client_id:
        return {"status": "error", "message": "Client ID not found"}
    
    print(f"DEBUG - Using client_id: {client_id}")
    
    # Fetch completed orders
    completed_orders = fetch_orders(auth, client_id, "completed")
    if completed_orders.get("status") == "error":
        print(f"DEBUG - Error fetching completed orders: {completed_orders.get('message')}")
        completed_orders = {"data": {"orders": []}}
    
    # Fetch pending orders
    pending_orders = fetch_orders(auth, client_id, "pending")
    if pending_orders.get("status") == "error":
        print(f"DEBUG - Error fetching pending orders: {pending_orders.get('message')}")
        pending_orders = {"data": {"orders": []}}
    
    # Combine the orders
    combined_orders = []
    if "data" in completed_orders and "orders" in completed_orders["data"]:
        combined_orders.extend(completed_orders["data"]["orders"])
    if "data" in pending_orders and "orders" in pending_orders["data"]:
        combined_orders.extend(pending_orders["data"]["orders"])
    
    # Create a response in the expected format
    response_data = {
        "status": "success",
        "data": combined_orders,
        "message": ""
    }
    
    return response_data


def get_client_id(auth):
    """
    Get the client_id for Pocketful API requests.
    First tries to get it from the database, then from the API if not found.
    
    Args:
        auth: Authentication token for Pocketful API
        
    Returns:
        client_id string or None if not found
    """
    # Get the username from the session
    username = session.get('username')
    print(f"DEBUG - Session username: {username}")
    
    # Get client_id from auth database
    client_id = None
    if username:
        auth_obj = Auth.query.filter_by(name=username, broker='pocketful').first()
        if auth_obj and auth_obj.user_id:
            client_id = auth_obj.user_id
            print(f"DEBUG - Found client_id in database: {client_id}")
    
    # If client_id not in database, try to get it from trading_info endpoint
    if not client_id:
        print(f"DEBUG - Fetching client_id from trading_info endpoint")
        info_response = get_api_response(f"{BASE_URL}/api/v1/user/trading_info", auth)
        if info_response.get('status') == 'success':
            client_id = info_response.get('data', {}).get('client_id')
            print(f"DEBUG - Got client_id from API: {client_id}")
            
            # Store the client_id in the database for future use
            if client_id and username:
                auth_obj = Auth.query.filter_by(name=username, broker='pocketful').first()
                if auth_obj:
                    auth_obj.user_id = client_id
                    db_session.commit()
                    print(f"DEBUG - Stored client_id in database")
    
    return client_id


def fetch_orders(auth, client_id, order_type):
    """
    Fetch orders of a specific type (completed or pending) from Pocketful API.
    
    Args:
        auth: Authentication token for Pocketful API
        client_id: The client ID for the request
        order_type: Type of orders to fetch ('completed' or 'pending')
        
    Returns:
        API response with orders data
    """
    print(f"DEBUG - Fetching {order_type} orders for client_id: {client_id}")
    
    # API endpoint for orders
    endpoint = f"{BASE_URL}/api/v1/orders"
    
    # Setup headers and parameters
    headers = {
        'Authorization': f'Bearer {auth}',
        'Content-Type': 'application/json'
    }
    
    # Add client_id and type as query parameters
    params = {
        "client_id": client_id,
        "type": order_type
    }
    
    try:
        print(f"DEBUG - Making GET request to {endpoint} with params: {params}")
        client = get_httpx_client()
        response = client.get(endpoint, headers=headers, params=params)
        print(f"DEBUG - Response status for {order_type} orders: {response.status_code}")
        
        # Show limited response data to avoid overwhelming logs
        preview = response.text[:200] + "..." if len(response.text) > 200 else response.text
        print(f"DEBUG - {order_type} orders response preview: {preview}")
        
        response.raise_for_status()
        
        try:
            return response.json()
        except ValueError:
            return {"status": "error", "message": f"Invalid JSON response for {order_type} orders"}
    except Exception as e:
        print(f"DEBUG - API request error for {order_type} orders: {str(e)}")
        return {"status": "error", "message": str(e)}



def get_trade_book(auth):
    """
    Get the trade book from Pocketful API.
    
    Args:
        auth: Authentication token for Pocketful API
        
    Returns:
        Dictionary with trade book data in standard format
    """
    print(f"DEBUG - Fetching Pocketful trade book")
    
    # Get client_id needed for API requests
    client_id = get_client_id(auth)
    if not client_id:
        return {"status": "error", "message": "Client ID not found"}
    
    print(f"DEBUG - Using client_id: {client_id}")
    
    # API endpoint for tradebook
    endpoint = f"{BASE_URL}/api/v1/trades"
    
    # Setup parameters with client_id
    params = {
        "client_id": client_id
    }
    
    try:
        print(f"DEBUG - Making GET request to {endpoint} with params: {params}")
        client = get_httpx_client()
        
        # Set up headers with authorization token
        headers = {
            'Authorization': f'Bearer {auth}',
            'Content-Type': 'application/json'
        }
        
        # Make the request
        response = client.get(endpoint, headers=headers, params=params)
        response.status = response.status_code
        print(f"DEBUG - Response status code: {response.status_code}")
        
        # Check if request was successful
        if response.status_code == 200:
            try:
                trade_data = response.json()
                print(f"DEBUG - Trade data received: {json.dumps(trade_data, indent=2)}")
                
                # Extract trades directly from the nested structure to make processing easier
                trades = []
                if trade_data.get('status') == 'success' and 'data' in trade_data:
                    if isinstance(trade_data['data'], dict) and 'trades' in trade_data['data']:
                        trades = trade_data['data']['trades']
                
                # Create a response in the expected format
                response_data = {
                    "status": "success",
                    "data": trades,  # Provide trades array directly
                    "message": ""
                }
                
                return response_data
            except ValueError:
                error_msg = "Invalid JSON response from Pocketful API"
                print(f"DEBUG - {error_msg}")
                return {"status": "error", "message": error_msg}
        else:
            error_msg = f"Error fetching tradebook: {response.text}"
            print(f"DEBUG - {error_msg}")
            return {"status": "error", "message": error_msg}
    except Exception as e:
        error_msg = f"Exception fetching tradebook: {str(e)}"
        print(f"DEBUG - {error_msg}")
        return {"status": "error", "message": error_msg}

def get_positions(auth):
    return get_api_response("/portfolio/positions",auth)

def get_holdings(auth):
    return get_api_response("/portfolio/holdings",auth)

def get_open_position(tradingsymbol, exchange, product,auth):

    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    

    positions_data = get_positions(auth)
    net_qty = '0'
    #print(positions_data['data']['net'])

    if positions_data and positions_data.get('status') and positions_data.get('data'):
        for position in positions_data['data']['net']:
            if position.get('tradingsymbol') == tradingsymbol and position.get('exchange') == exchange and position.get('product') == product:
                net_qty = position.get('quantity', '0')
                print(f'Net Quantity {net_qty}')
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data, auth_token):
    """
    Place an order using Pocketful's API.
    """
    # Get the username from the session
    username = session.get('username')
    
    # Get client_id from auth database
    client_id = None
    if username:
        auth_obj = Auth.query.filter_by(name=username, broker='pocketful').first()
        if auth_obj and auth_obj.user_id:
            client_id = auth_obj.user_id
    
    # If client_id not in database, try to get it from trading_info endpoint
    if not client_id:
        info_response = get_api_response(f"{BASE_URL}/api/v1/user/trading_info", auth_token)
        if info_response.get('status') == 'success':
            client_id = info_response.get('data', {}).get('client_id')
            
            # Store the client_id in the database for future use
            if client_id and username:
                auth_obj = Auth.query.filter_by(name=username, broker='pocketful').first()
                if auth_obj:
                    auth_obj.user_id = client_id
                    db_session.commit()
            
            if not client_id:
                return None, {"status": "error", "message": "Client ID not found"}, None
        else:
            return None, info_response, None
    print(f"Client ID: {client_id}")
    # Transform OpenAlgo order format to Pocketful format
    newdata = transform_data(data, client_id=client_id)
    print(f"Transformed data: {newdata}")
    # Make the API request
    response_data = get_api_response(ORDER_ENDPOINT, auth_token, method="POST", payload=newdata)
    
    # Create a response object for compatibility
    class DummyResponse:
        def __init__(self, status_code):
            self.status = status_code
    
    res = DummyResponse(200 if response_data.get('status') == 'success' else 500)
    
    # Extract order ID if successful
    if response_data.get('status') == 'success':
        orderid = response_data.get('data', {}).get('oms_order_id')
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


    print(f"position_size : {position_size}") 
    print(f"Open Position : {current_position}") 
    
    # Determine action based on position_size and current_position
    action = None
    quantity = 0


    

   
   

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

    #print(positions_response)
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

            print(place_order_payload)

            # Place the order to close the position
            _, api_response, _ =   place_order_api(place_order_payload,AUTH_TOKEN)

            print(api_response)
            
            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    """
    Cancel an order using Pocketful's API.
    
    Args:
        orderid: The order ID to cancel
        auth: Authentication token for Pocketful API
        
    Returns:
        Tuple of (response_data, status_code)
    """
    # Use the authenticated httpx client through get_api_response
    AUTH_TOKEN = auth
    
    # Get client_id as it's required for the API call
    client_id = get_client_id(auth)
    if not client_id:
        return {"status": "error", "message": "Client ID not found"}, 400
    
    # Define the endpoint for canceling the order with client_id as query parameter
    # According to Pocketful API docs, client_id is required
    CANCEL_ORDER_ENDPOINT = f"{ORDER_ENDPOINT}/{orderid}?client_id={client_id}"
    
    # According to Pocketful API docs, the expected response format is:
    # {
    #   "status": "success",
    #   "message": "Order cancelled successfully",
    #   "data": {
    #     "oms_order_id": "<order_id>"
    #   }
    # }
    
    # Add debug information
    print(f"DEBUG - Cancelling order {orderid} for client {client_id}")
    print(f"DEBUG - Using endpoint: {CANCEL_ORDER_ENDPOINT}")
    
    # Make the DELETE request using the httpx client
    response = get_api_response(CANCEL_ORDER_ENDPOINT, AUTH_TOKEN, method="DELETE")
    
    # Check if the request was successful
    if response.get("status") == "success":
        # Return a success response with the order ID
        oms_order_id = response.get("data", {}).get("oms_order_id", orderid)
        print(f"DEBUG - Order {orderid} cancelled successfully, oms_order_id: {oms_order_id}")
        return {
            "status": "success", 
            "orderid": oms_order_id,
            "message": response.get("message", "Order cancelled successfully")
        }, 200
    else:
        # Return an error response
        error_message = response.get("message", "Failed to cancel order")
        print(f"DEBUG - Failed to cancel order {orderid}: {error_message}")
        return {"status": "error", "message": error_message}, 400


def modify_order(data, auth):
    """
    Modify an order using Pocketful's API.
    """
    # Get the username from the session
    username = session.get('username')
    
    # Get client_id from auth database
    client_id = None
    if username:
        auth_obj = Auth.query.filter_by(name=username, broker='pocketful').first()
        if auth_obj and auth_obj.user_id:
            client_id = auth_obj.user_id
    
    # If client_id not in database, try to get it from trading_info endpoint
    if not client_id:
        info_response = get_api_response(f"{BASE_URL}/api/v1/user/trading_info", auth)
        if info_response.get('status') == 'success':
            client_id = info_response.get('data', {}).get('client_id')
            
            # Store the client_id in the database for future use
            if client_id and username:
                auth_obj = Auth.query.filter_by(name=username, broker='pocketful').first()
                if auth_obj:
                    auth_obj.user_id = client_id
                    db_session.commit()
            
            if not client_id:
                return {"status": "error", "message": "Client ID not found"}, 400
        else:
            return info_response, 400
    
    print(f"Client ID: {client_id}")
    print(f"Original order data: {data}")
    
    # Transform OpenAlgo modify order format to Pocketful format
    transformed_data = transform_modify_order_data(data, client_id=client_id)
    print(f"Transformed order data: {transformed_data}")
    
    # Use manual httpx client request to avoid URL path manipulation issues
    client = get_httpx_client()
    
    # Setup correct URL and headers
    url = f"{BASE_URL}/api/v1/orders"
    headers = {
        'Authorization': f'Bearer {auth}',
        'Content-Type': 'application/json'
    }
    
    print(f"Making direct PUT request to: {url}")
    print(f"With payload: {json.dumps(transformed_data, indent=2)}")
    
    try:
        # Make direct request using httpx client - bypass get_api_response to have more control
        response = client.put(url, headers=headers, json=transformed_data)
        print(f"Response status: {response.status_code}")
        print(f"Response URL: {response.url}")
        print(f"Response content: {response.text}")
        
        response.raise_for_status()
        
        try:
            response_data = response.json()
            if response_data.get("status") == "success":
                return {"status": "success", "orderid": response_data.get("data", {}).get("oms_order_id", "")}, 200
            else:
                return {"status": "error", "message": response_data.get("message", "Failed to modify order")}, 400
        except ValueError:
            return {"status": "error", "message": "Invalid JSON response: " + response.text}, 400
    
    except Exception as e:
        print(f"Error making request: {str(e)}")
        return {"status": "error", "message": f"Request error: {str(e)}"}, 400
    

def cancel_all_orders_api(data, auth):
    """
    Cancel all open orders for the Pocketful broker.
    
    Args:
        data: Request data (not used for this function)
        auth: Authentication token for Pocketful API
        
    Returns:
        Tuple of (canceled_orders, failed_cancellations) lists
    """
    print("DEBUG - Cancelling all open orders for Pocketful broker")
    
    AUTH_TOKEN = auth
    
    # Get the client_id as it may be needed for logging
    client_id = get_client_id(AUTH_TOKEN)
    if not client_id:
        print("DEBUG - Failed to get client_id for cancelling all orders")
        return [], []
        
    print(f"DEBUG - Cancelling all open orders for client: {client_id}")
    
    # Get the order book
    order_book_response = get_order_book(AUTH_TOKEN)
    if order_book_response['status'] != 'success':
        print(f"DEBUG - Failed to retrieve order book: {order_book_response.get('message', 'Unknown error')}")
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # According to Pocketful API, we need to look for orders with status 'OPEN' or 'TRIGGER PENDING'
    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response.get('data', [])
                        if order.get('status') in ['OPEN', 'TRIGGER PENDING']]
    
    print(f"DEBUG - Found {len(orders_to_cancel)} open orders to cancel")
    if orders_to_cancel:
        print(f"DEBUG - Order IDs to cancel: {[order.get('order_id', 'Unknown') for order in orders_to_cancel]}")
    
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        # Use oms_order_id if available, otherwise fall back to order_id
        orderid = order.get('oms_order_id', order.get('order_id'))
        if not orderid:
            print(f"DEBUG - Could not find valid order ID in order: {order}")
            continue
            
        print(f"DEBUG - Attempting to cancel order: {orderid}")
        cancel_response, status_code = cancel_order(orderid, AUTH_TOKEN)
        
        if status_code == 200:
            print(f"DEBUG - Successfully cancelled order: {orderid}")
            canceled_orders.append(orderid)
        else:
            print(f"DEBUG - Failed to cancel order {orderid}: {cancel_response.get('message', 'Unknown error')}")
            failed_cancellations.append(orderid)
    
    print(f"DEBUG - Cancel all orders summary: {len(canceled_orders)} cancelled, {len(failed_cancellations)} failed")
    return canceled_orders, failed_cancellations

