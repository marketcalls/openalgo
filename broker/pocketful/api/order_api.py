
import json
from flask import session
from utils.httpx_client import get_httpx_client
from database.token_db import get_br_symbol, get_oa_symbol
from database.auth_db import Auth, db_session
from broker.pocketful.mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data
from utils.logging import get_logger

logger = get_logger(__name__)




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
    
    logger.debug("DEBUG - API Request Details:")
    logger.debug(f"DEBUG - Method: {method}")
    logger.debug(f"DEBUG - Endpoint param: {endpoint}")
    logger.debug(f"DEBUG - Constructed URL: {full_url}")
    if payload:
        logger.debug(f"DEBUG - Payload: {json.dumps(payload, indent=2)}")
        if 'oms_order_id' in payload:
            logger.info(f"DEBUG - Order ID in payload: {payload['oms_order_id']}")
    
    try:
        if method == "GET":
            logger.debug(f"DEBUG - Executing GET request to {full_url}")
            response = client.get(full_url, headers=headers)
        elif method == "POST":
            logger.debug(f"DEBUG - Executing POST request to {full_url}")
            response = client.post(full_url, headers=headers, json=payload)
        elif method == "PUT":
            logger.debug(f"DEBUG - Executing PUT request to {full_url}")
            response = client.put(full_url, headers=headers, json=payload)
        elif method == "DELETE":
            logger.debug(f"DEBUG - Executing DELETE request to {full_url}")
            response = client.delete(full_url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
            
        # Add status attribute for compatibility
        response.status = response.status_code
        logger.debug(f"DEBUG - Response status code: {response.status_code}")
        logger.debug(f"DEBUG - Response URL (final): {response.url}")
        logger.debug(f"DEBUG - Response content: {response.text}")
        response.raise_for_status()
        
        try:
            return response.json()
        except ValueError:
            # Handle case where response is not JSON
            logger.debug("DEBUG - Response is not valid JSON")
            return {"status": "success" if response.status_code < 400 else "error", 
                    "message": response.text}
    except Exception as e:
        logger.error(f"API request error: {e}")
        return {"status": "error", "message": str(e)}

def get_order_book(auth):
    """
    Get the order book from Pocketful API by combining both completed and pending orders.
    
    Args:
        auth: Authentication token for Pocketful API
        
    Returns:
        Dictionary with combined order book data in standard format
    """
    logger.debug("DEBUG - Fetching Pocketful order book (completed and pending orders)")
    
    # Get client_id needed for API requests
    client_id = get_client_id(auth)
    if not client_id:
        return {"status": "error", "message": "Client ID not found"}
    
    logger.debug(f"DEBUG - Using client_id: {client_id}")
    
    # Fetch completed orders
    completed_orders = fetch_orders(auth, client_id, "completed")
    if completed_orders.get("status") == "error":
        logger.info(f"DEBUG - Error fetching completed orders: {completed_orders.get('message')}")
        completed_orders = {"data": {"orders": []}}
    
    # Fetch pending orders
    pending_orders = fetch_orders(auth, client_id, "pending")
    if pending_orders.get("status") == "error":
        logger.info(f"DEBUG - Error fetching pending orders: {pending_orders.get('message')}")
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
    logger.debug(f"DEBUG - Session username: {username}")
    
    # Get client_id from auth database
    client_id = None
    if username:
        auth_obj = Auth.query.filter_by(name=username, broker='pocketful').first()
        if auth_obj and auth_obj.user_id:
            client_id = auth_obj.user_id
            logger.debug(f"DEBUG - Found client_id in database: {client_id}")
    
    # If client_id not in database, try to get it from trading_info endpoint
    if not client_id:
        logger.debug("DEBUG - Fetching client_id from trading_info endpoint")
        info_response = get_api_response(f"{BASE_URL}/api/v1/user/trading_info", auth)
        if info_response.get('status') == 'success':
            client_id = info_response.get('data', {}).get('client_id')
            logger.debug(f"DEBUG - Got client_id from API: {client_id}")
            
            # Store the client_id in the database for future use
            if client_id and username:
                auth_obj = Auth.query.filter_by(name=username, broker='pocketful').first()
                if auth_obj:
                    auth_obj.user_id = client_id
                    db_session.commit()
                    logger.debug("DEBUG - Stored client_id in database")
    
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
    logger.debug(f"DEBUG - Fetching {order_type} orders for client_id: {client_id}")
    
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
        logger.debug(f"DEBUG - Making GET request to {endpoint} with params: {params}")
        client = get_httpx_client()
        response = client.get(endpoint, headers=headers, params=params)
        logger.debug(f"DEBUG - Response status for {order_type} orders: {response.status_code}")
        
        # Show limited response data to avoid overwhelming logs
        preview = response.text[:200] + "..." if len(response.text) > 200 else response.text
        logger.debug(f"DEBUG - {order_type} orders response preview: {preview}")
        
        response.raise_for_status()
        
        try:
            return response.json()
        except ValueError:
            return {"status": "error", "message": f"Invalid JSON response for {order_type} orders"}
    except Exception as e:
        logger.error(f"DEBUG - API request error for {order_type} orders: {e}")
        return {"status": "error", "message": str(e)}



def get_trade_book(auth):
    """
    Get the trade book from Pocketful API.
    
    Args:
        auth: Authentication token for Pocketful API
        
    Returns:
        Dictionary with trade book data in standard format
    """
    logger.debug("DEBUG - Fetching Pocketful trade book")
    
    # Get client_id needed for API requests
    client_id = get_client_id(auth)
    if not client_id:
        return {"status": "error", "message": "Client ID not found"}
    
    logger.debug(f"DEBUG - Using client_id: {client_id}")
    
    # API endpoint for tradebook
    endpoint = f"{BASE_URL}/api/v1/trades"
    
    # Setup parameters with client_id
    params = {
        "client_id": client_id
    }
    
    try:
        logger.debug(f"DEBUG - Making GET request to {endpoint} with params: {params}")
        client = get_httpx_client()
        
        # Set up headers with authorization token
        headers = {
            'Authorization': f'Bearer {auth}',
            'Content-Type': 'application/json'
        }
        
        # Make the request
        response = client.get(endpoint, headers=headers, params=params)
        response.status = response.status_code
        logger.debug(f"DEBUG - Response status code: {response.status_code}")
        
        # Check if request was successful
        if response.status_code == 200:
            try:
                trade_data = response.json()
                logger.debug(f"DEBUG - Trade data received: {json.dumps(trade_data, indent=2)}")
                
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
                logger.error(f"DEBUG - {error_msg}")
                return {"status": "error", "message": error_msg}
        else:
            error_msg = f"Error fetching tradebook: {response.text}"
            logger.error(f"DEBUG - {error_msg}")
            return {"status": "error", "message": error_msg}
    except Exception as e:
        error_msg = f"Exception fetching tradebook: {str(e)}"
        logger.error(f"DEBUG - {error_msg}")
        return {"status": "error", "message": error_msg}

def get_positions(auth):
    """
    Get the position book from Pocketful API.
    
    Args:
        auth: Authentication token for Pocketful API
        
    Returns:
        Dictionary with position data in standard format
    """
    logger.debug("DEBUG - Fetching Pocketful positions")
    
    # Get client_id needed for API requests
    client_id = get_client_id(auth)
    if not client_id:
        return {"status": "error", "message": "Client ID not found"}
    
    logger.debug(f"DEBUG - Using client_id: {client_id}")
    
    # API endpoint for positions - using the netwise position endpoint
    endpoint = f"{BASE_URL}/api/v1/positions"
    
    # Setup parameters with client_id and type=netwise
    params = {
        "client_id": client_id,
        "type": "live"  # Correct parameter name is 'type' not 'position_type'
    }
    
    try:
        logger.debug(f"DEBUG - Making GET request to {endpoint} with params: {params}")
        client = get_httpx_client()
        
        # Set up headers with authorization token
        headers = {
            'Authorization': f'Bearer {auth}',
            'Content-Type': 'application/json'
        }
        
        # Make the request
        response = client.get(endpoint, headers=headers, params=params)
        response.status = response.status_code
        logger.debug(f"DEBUG - Response status code: {response.status_code}")
        
        # Check if request was successful
        if response.status_code == 200:
            try:
                position_data = response.json()
                logger.debug(f"DEBUG - Position data received: {json.dumps(position_data, indent=2)}")
                
                # The response structure is different - positions are directly in the 'data' array
                positions = []
                if position_data.get('status') == 'success' and 'data' in position_data:
                    # Handle case where data is the positions array directly (type=live)
                    if isinstance(position_data['data'], list):
                        positions = position_data['data']
                    # Handle nested structure if present (netwise or other types)
                    elif isinstance(position_data['data'], dict) and 'positions' in position_data['data']:
                        positions = position_data['data']['positions']
                
                logger.debug(f"DEBUG - Found {len(positions)} positions in response")
                
                # Create a response in the expected format
                response_data = {
                    "status": "success",
                    "data": positions,  # Provide positions array directly
                    "message": ""
                }
                
                return response_data
            except ValueError:
                error_msg = "Invalid JSON response from Pocketful API"
                logger.error(f"DEBUG - {error_msg}")
                return {"status": "error", "message": error_msg}
        else:
            error_msg = f"Error fetching positions: {response.text}"
            logger.error(f"DEBUG - {error_msg}")
            return {"status": "error", "message": error_msg}
    except Exception as e:
        error_msg = f"Exception fetching positions: {str(e)}"
        logger.error(f"DEBUG - {error_msg}")
        return {"status": "error", "message": error_msg}

def get_holdings(auth):
    """
    Get the holdings from Pocketful API.
    
    Args:
        auth: Authentication token for Pocketful API
        
    Returns:
        Dictionary with holdings data in standard format
    """
    logger.debug("DEBUG - Fetching Pocketful holdings")
    
    # Get client_id needed for API requests
    client_id = get_client_id(auth)
    if not client_id:
        return {"status": "error", "message": "Client ID not found"}
    
    logger.debug(f"DEBUG - Using client_id: {client_id}")
    
    # The Pocketful holdings endpoint with client_id parameter
    endpoint = f"{BASE_URL}/api/v1/holdings?client_id={client_id}"
    
    logger.debug(f"DEBUG - Using holdings endpoint: {endpoint}")
    
    # Make the API request
    holdings_response = get_api_response(endpoint, auth)
    
    # Check if response is HTML (likely a login page)
    if isinstance(holdings_response, dict) and holdings_response.get("message") and "<!doctype html>" in holdings_response.get("message", ""):
        logger.debug("DEBUG - Received HTML response instead of JSON. Likely not authenticated or wrong endpoint.")
        return {"status": "error", "message": "Received HTML response instead of JSON. Please check authentication.", "data": []}
    
    # Check if there was an error in the API response
    if holdings_response.get("status") == "error":
        logger.info(f"DEBUG - Error fetching holdings: {holdings_response.get('message')}")
        return holdings_response
    
    # Transform the holdings data into the standard format
    from broker.pocketful.mapping.order_data import transform_holdings_data
    
    # Print debug information about the response
    logger.debug(f"DEBUG - Holdings response type: {type(holdings_response)}")
    logger.info(f"DEBUG - Holdings response keys: {holdings_response.keys() if isinstance(holdings_response, dict) else 'Not a dictionary'}")
    
    # Handle different possible response structures
    holdings_data = []
    
    # From the logs, we can see the structure is {"data":{"holdings":[...]}}
    try:
        if isinstance(holdings_response, dict):
            # Case 1: data -> holdings -> array (this is the actual structure from the API)
            if ("data" in holdings_response and 
                isinstance(holdings_response["data"], dict) and 
                "holdings" in holdings_response["data"] and
                isinstance(holdings_response["data"]["holdings"], list)):
                
                holdings_data = holdings_response["data"]["holdings"]
                logger.debug(f"DEBUG - Found {len(holdings_data)} holdings in data.holdings path")
                
            # Case 2: data -> array
            elif "data" in holdings_response and isinstance(holdings_response["data"], list):
                holdings_data = holdings_response["data"]
                logger.debug(f"DEBUG - Found {len(holdings_data)} holdings in data path (list)")
                
            # Case 3: holdings -> array
            elif "holdings" in holdings_response and isinstance(holdings_response["holdings"], list):
                holdings_data = holdings_response["holdings"]
                logger.debug(f"DEBUG - Found {len(holdings_data)} holdings in holdings path")
                
            # Case 4: data -> other field containing holdings
            elif "data" in holdings_response and isinstance(holdings_response["data"], dict):
                data_obj = holdings_response["data"]
                found = False
                for key, value in data_obj.items():
                    if isinstance(value, list):
                        holdings_data = value
                        logger.debug(f"DEBUG - Found {len(holdings_data)} holdings in data.{key} path")
                        found = True
                        break
                        
                if not found:
                    logger.debug(f"DEBUG - No list data found in data object. Keys: {data_obj.keys()}")
        
        # Handle direct list response
        if not holdings_data and isinstance(holdings_response, list):
            holdings_data = holdings_response
            logger.debug("DEBUG - Using direct list response for holdings")
    
    except Exception as e:
        logger.error(f"DEBUG - Error extracting holdings data: {e}")
        logger.debug(f"DEBUG - Response structure: {type(holdings_response)}")
        if isinstance(holdings_response, dict):
            logger.debug(f"DEBUG - Response keys: {holdings_response.keys()}")
        return {"status": "error", "message": f"Failed to extract holdings data: {str(e)}", "data": []}
    
    # Direct list response is already handled in the try block above
    
    logger.debug(f"DEBUG - Extracted {len(holdings_data)} holdings entries")
    if holdings_data and len(holdings_data) > 0:
        logger.debug(f"DEBUG - Sample holding: {holdings_data[0]}")
    else:
        logger.debug("DEBUG - No holdings data found or empty array")
        # Return empty data to avoid errors in the UI
        return {"status": "success", "data": []}
    
    transformed_holdings = transform_holdings_data(holdings_data)
    return {"status": "success", "data": transformed_holdings}

def get_open_position(tradingsymbol, exchange, product, auth):
    """
    Get open position quantity for a specific instrument.
    
    Args:
        tradingsymbol: The trading symbol to look for
        exchange: The exchange to look for the position in
        product: The product type (MIS, NRML, CNC)
        auth: Authentication token for Pocketful API
        
    Returns:
        Net quantity string (positive for long, negative for short)
    """
    # Initialize net quantity to 0
    net_qty = '0'
    
    # Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    
    logger.debug(f"DEBUG - Fetching open position for {tradingsymbol} on {exchange} with product {product}")
    
    # Get positions data
    positions_data = get_positions(auth)
    
    # Check if positions data is available and contains positions
    if positions_data and positions_data.get('status') == 'success' and positions_data.get('data'):
        for position in positions_data['data']:
            # Check for multiple possible symbol formats
            position_symbol = position.get('tradingsymbol', position.get('trading_symbol', ''))
            position_exchange = position.get('exchange', '')
            position_product = position.get('product', '')
            
            logger.debug(f"DEBUG - Comparing with position: symbol={position_symbol}, exchange={position_exchange}, product={position_product}")
            
            # Match based on all criteria
            if (position_symbol == tradingsymbol and 
                position_exchange == exchange and 
                position_product == product):
                
                # Get quantity (handle both 'quantity' and 'net_quantity' fields)
                if 'quantity' in position:
                    net_qty = str(position['quantity'])
                elif 'net_quantity' in position:
                    net_qty = str(position['net_quantity'])
                    
                logger.debug(f"DEBUG - Found match! Net Quantity: {net_qty}")
                break  # Found the position, no need to continue

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
    logger.info(f"Client ID: {client_id}")
    # Transform OpenAlgo order format to Pocketful format
    newdata = transform_data(data, client_id=client_id)
    logger.info(f"Transformed data: {newdata}")
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


    logger.info(f"position_size : {position_size}") 
    logger.info(f"Open Position : {current_position}") 
    
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
        res, response, orderid = place_order_api(order_data,AUTH_TOKEN)
        #logger.info(f"{res}")
        #logger.info(f"{response}")
        
        return res , response, orderid
    



def close_all_positions(current_api_key, auth):
    """
    Close all open positions for the Pocketful broker.
    
    Args:
        current_api_key: The API key for the current user
        auth: Authentication token for Pocketful API
        
    Returns:
        A tuple of (response_message, status_code)
    """
    logger.debug("DEBUG - Closing all open positions for Pocketful broker")
    
    # Get client_id needed for API requests
    client_id = get_client_id(auth)
    if not client_id:
        logger.error("DEBUG - Failed to get client_id")
        return {"status": "error", "message": "Client ID not found"}, 400
    
    logger.debug(f"DEBUG - Using client_id: {client_id}")
    
    # Direct API call to get positions to avoid any intermediate processing
    endpoint = f"{BASE_URL}/api/v1/positions"
    params = {"client_id": client_id, "type": "live"}
    
    try:
        # Use httpx client directly
        client = get_httpx_client()
        headers = {
            'Authorization': f'Bearer {auth}',
            'Content-Type': 'application/json'
        }
        
        logger.debug(f"DEBUG - Making direct GET request to {endpoint} with params: {params}")
        response = client.get(endpoint, headers=headers, params=params)
        
        if response.status_code != 200:
            logger.error(f"DEBUG - Error response: {response.status_code} - {response.text}")
            return {"status": "error", "message": f"API returned status {response.status_code}"}, 500
        
        # Parse JSON response
        response_data = response.json()
        logger.info(f"DEBUG - Response status: {response_data.get('status')}")
        
        # Early return if no data or error status
        if response_data.get('status') != 'success' or 'data' not in response_data:
            logger.debug("DEBUG - No positions data in response")
            return {"status": "error", "message": "No positions data"}, 500
        
        # Get positions array
        positions = response_data['data']
        if not positions or not isinstance(positions, list):
            logger.debug("DEBUG - Positions is not a list or is empty")
            return {"message": "No Open Positions Found"}, 200
        
        logger.debug(f"DEBUG - Found {len(positions)}")
        closed_count = 0
        successful_closes = []
        failed_closes = []
        
        # Process each position
        for position in positions:
            try:
                logger.debug(f"DEBUG - Position details: {position}")
                # Check if we have net quantity that's non-zero
                net_quantity = position.get('net_quantity', 0)
                symbol = position.get('trading_symbol', '')
                
                if int(net_quantity) == 0:
                    logger.debug(f"DEBUG - Skipping position {symbol} with zero quantity")
                    continue
                
                # Determine action based on net quantity
                action = 'SELL' if int(net_quantity) > 0 else 'BUY'
                quantity = abs(int(net_quantity))
                
                # Convert symbol if needed
                exchange = position.get('exchange', '')
                oa_symbol = get_oa_symbol(symbol, exchange) if symbol and exchange else symbol
            
                # Prepare the order payload
                place_order_payload = {
                    "apikey": current_api_key,
                    "strategy": "Squareoff",
                    "symbol": oa_symbol or symbol,  # Use OA symbol if available, otherwise original
                    "action": action,
                    "exchange": exchange,
                    "pricetype": "MARKET",
                    "product": reverse_map_product_type(exchange, position.get('product', 'MIS')),
                    "quantity": str(quantity)
                }
                
                logger.debug(f"DEBUG - Placing order to close position: {place_order_payload}")
                
                # Try to place the order
                try:
                    status, api_response, orderid = place_order_api(place_order_payload, auth)
                    logger.debug(f"DEBUG - Order response: {api_response}")
                    
                    if status:
                        closed_count += 1
                        successful_closes.append({
                            "symbol": symbol,
                            "orderid": orderid,
                            "quantity": quantity,
                            "action": action
                        })
                    else:
                        failed_closes.append({
                            "symbol": symbol,
                            "error": api_response.get('message', 'Unknown error')
                        })
                except Exception as order_error:
                    logger.error(f"DEBUG - Error placing order: {order_error}")
                    failed_closes.append({
                        "symbol": symbol,
                        "error": str(order_error)
                    })
            except Exception as pos_error:
                logger.error(f"DEBUG - Error processing position: {pos_error}")
                failed_closes.append({
                    "symbol": position.get('trading_symbol', 'Unknown'),
                    "error": str(pos_error)
                })
        
        # Return a summary of the operation
        if closed_count > 0:
            if len(failed_closes) == 0:
                return {"status": "success", "message": f"Successfully closed {closed_count} positions", "data": successful_closes}, 200
            else:
                return {"status": "partial", "message": f"Closed {closed_count} positions, {len(failed_closes)} failed", 
                        "data": successful_closes, "failed": failed_closes}, 200
        elif len(failed_closes) > 0:
            return {"status": "error", "message": "Failed to close any positions", "failed": failed_closes}, 500
        else:
            return {"status": "success", "message": "No positions to close"}, 200
            
    except Exception as e:
        logger.error(f"DEBUG - Unexpected error: {e}")
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}, 500


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
    logger.debug(f"DEBUG - Cancelling order {orderid} for client {client_id}")
    logger.debug(f"DEBUG - Using endpoint: {CANCEL_ORDER_ENDPOINT}")
    
    # Make the DELETE request using the httpx client
    response = get_api_response(CANCEL_ORDER_ENDPOINT, AUTH_TOKEN, method="DELETE")
    
    # Check if the request was successful
    if response.get("status") == "success":
        # Return a success response with the order ID
        oms_order_id = response.get("data", {}).get("oms_order_id", orderid)
        logger.debug(f"DEBUG - Order {orderid} cancelled successfully, oms_order_id: {oms_order_id}")
        return {
            "status": "success", 
            "orderid": oms_order_id,
            "message": response.get("message", "Order cancelled successfully")
        }, 200
    else:
        # Return an error response
        error_message = response.get("message", "Failed to cancel order")
        logger.error(f"DEBUG - Failed to cancel order {orderid}: {error_message}")
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
    
    logger.info(f"Client ID: {client_id}")
    logger.info(f"Original order data: {data}")
    
    # Transform OpenAlgo modify order format to Pocketful format
    transformed_data = transform_modify_order_data(data, client_id=client_id)
    logger.info(f"Transformed order data: {transformed_data}")
    
    # Use manual httpx client request to avoid URL path manipulation issues
    client = get_httpx_client()
    
    # Setup correct URL and headers
    url = f"{BASE_URL}/api/v1/orders"
    headers = {
        'Authorization': f'Bearer {auth}',
        'Content-Type': 'application/json'
    }
    
    logger.info(f"Making direct PUT request to: {url}")
    logger.info(f"With payload: {json.dumps(transformed_data, indent=2)}")
    
    try:
        # Make direct request using httpx client - bypass get_api_response to have more control
        response = client.put(url, headers=headers, json=transformed_data)
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response URL: {response.url}")
        logger.info(f"Response content: {response.text}")
        
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
        logger.error(f"Error making request: {e}")
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
    logger.debug("DEBUG - Cancelling all open orders for Pocketful broker")
    
    AUTH_TOKEN = auth
    
    # Get the client_id as it may be needed for logging
    client_id = get_client_id(AUTH_TOKEN)
    if not client_id:
        logger.error("DEBUG - Failed to get client_id for cancelling all orders")
        return [], []
        
    logger.debug(f"DEBUG - Cancelling all open orders for client: {client_id}")
    
    # Make a direct GET request to get pending orders
    endpoint = f"{BASE_URL}/api/v1/orders"
    params = {
        "client_id": client_id,
        "type": "pending"  # Get pending orders directly
    }
    
    try:
        logger.debug(f"DEBUG - Fetching pending orders for client_id: {client_id}")
        client = get_httpx_client()
        headers = {
            'Authorization': f'Bearer {AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        logger.debug(f"DEBUG - Making GET request to {endpoint} with params: {params}")
        response = client.get(endpoint, headers=headers, params=params)
        logger.debug(f"DEBUG - Response status for pending orders: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"DEBUG - Error response: {response.text}")
            return [], []  # Return empty lists if unable to fetch orders
            
        # Parse response to get pending orders
        response_data = response.json()
        logger.debug(f"DEBUG - pending orders response preview: {str(response_data)[:200]}...")
        
        # Handle different possible response structures
        pending_orders = []
        if response_data.get('status') == 'success':
            # Case 1: Orders in data.orders array
            if 'data' in response_data and isinstance(response_data['data'], dict) and 'orders' in response_data['data']:
                pending_orders = response_data['data']['orders']
                logger.debug(f"DEBUG - Found {len(pending_orders)} orders in data.orders structure")
            # Case 2: Orders directly in data array
            elif 'data' in response_data and isinstance(response_data['data'], list):
                pending_orders = response_data['data']
                logger.debug(f"DEBUG - Found {len(pending_orders)} orders in data array structure")
        
        # Log order statuses to better understand what we're working with
        if pending_orders:
            statuses = {}
            for order in pending_orders:
                status = order.get('status')
                if status:
                    statuses[status] = statuses.get(status, 0) + 1
            logger.debug(f"DEBUG - Order statuses found: {statuses}")
            
            # Print a sample order to understand structure
            logger.info(f"DEBUG - Sample order structure: {pending_orders[0] if pending_orders else 'No orders'}")
        
        # Accept more status values as cancelable
        valid_cancel_statuses = [
            'OPEN', 'PENDING', 'TRIGGER PENDING', 'NEW', 'RECEIVED', 'PLACED',
            'VALIDATED', 'PENDING_0', 'PENDING_1', 'PENDING_2', 'ACCEPTED'
        ]
        
        # Filter orders that can be canceled (use case-insensitive comparison)
        orders_to_cancel = [order for order in pending_orders
                            if order.get('status', '').upper() in [s.upper() for s in valid_cancel_statuses]
                            or 'PEND' in order.get('status', '').upper()
                            or 'OPEN' in order.get('status', '').upper()
                            or 'NEW' in order.get('status', '').upper()
                            or order.get('mode', '').upper() == 'NEW']
                            
        # Print orders with mode=NEW for debugging
        mode_new_orders = [order for order in pending_orders if order.get('mode', '').upper() == 'NEW']
        logger.debug(f"DEBUG - Found {len(mode_new_orders)} orders with mode=NEW")
        if mode_new_orders:
            for idx, order in enumerate(mode_new_orders):
                logger.info(f"DEBUG - Mode=NEW order {idx+1}: status={order.get('status')}, id={order.get('order_id') or order.get('id') or 'unknown'}")
                            
    except Exception as e:
        logger.error(f"DEBUG - Error fetching pending orders: {e}")
        return [], []
    
    logger.debug(f"DEBUG - Found {len(orders_to_cancel)} open orders to cancel")
    if orders_to_cancel:
        logger.info(f"DEBUG - Order IDs to cancel: {[order.get('order_id', 'Unknown') for order in orders_to_cancel]}")
    
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        # Try multiple possible order ID fields
        possible_order_id_fields = ['oms_order_id', 'order_id', 'id', 'orderId', 'nnf_id', 'exchangeOrderId']
        
        # Log available fields for debugging
        order_fields = set(order.keys())
        logger.debug(f"DEBUG - Available order fields: {order_fields}")
        
        # Find the first valid order ID
        orderid = None
        for field in possible_order_id_fields:
            if field in order and order[field]:
                orderid = order[field]
                logger.info(f"DEBUG - Using order ID from field '{field}': {orderid}")
                break
                
        if not orderid:
            logger.debug(f"DEBUG - Could not find valid order ID in order: {order}")
            failed_cancellations.append("unknown_id")
            continue
            
        logger.debug(f"DEBUG - Attempting to cancel order: {orderid}")
        try:
            cancel_response, status_code = cancel_order(orderid, AUTH_TOKEN)
            
            # Check both status code and response status
            if status_code == 200 and (cancel_response.get('status') == 'success' or 'success' in str(cancel_response).lower()):
                logger.debug(f"DEBUG - Successfully cancelled order: {orderid}")
                canceled_orders.append(orderid)
            else:
                error_msg = cancel_response.get('message', 'Unknown error')
                logger.error(f"DEBUG - Failed to cancel order {orderid}: {error_msg}")
                failed_cancellations.append(orderid)
                
        except Exception as e:
            logger.debug(f"DEBUG - Exception while cancelling order {orderid}: {e}")
            failed_cancellations.append(orderid)
    
    logger.error(f"DEBUG - Cancel all orders summary: {len(canceled_orders)} cancelled, {len(failed_cancellations)} failed")
    return canceled_orders, failed_cancellations

