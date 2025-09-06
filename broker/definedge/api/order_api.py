import json
import os
import httpx
from database.auth_db import get_auth_token
from database.token_db import get_token, get_br_symbol, get_oa_symbol
from broker.definedge.mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def get_api_response(endpoint, auth, method="GET", payload=None):
    """Make API requests to DefinedGe API using shared connection pooling."""
    try:
        # Parse the auth token
        api_session_key, susertoken, api_token = auth.split(":::")
        
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        url = f"https://integrate.definedgesecurities.com/dart/v1{endpoint}"
        
        headers = {
            'Authorization': api_session_key,
            'Content-Type': 'application/json'
        }
        
        logger.debug(f"Making {method} request to DefinedGe API: {url}")
        
        if method.upper() == "GET":
            response = client.get(url, headers=headers)
        elif method.upper() == "POST":
            response = client.post(url, json=payload if payload else {}, headers=headers)
        elif method.upper() == "PUT":
            response = client.put(url, json=payload if payload else {}, headers=headers)
        elif method.upper() == "DELETE":
            response = client.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        
        response.raise_for_status()
        response_data = response.json()
        logger.debug(f"API response: {json.dumps(response_data, indent=2)}")
        return response_data
        
    except Exception as e:
        logger.error(f"Error during API request: {str(e)}")
        return {"stat": "Not_Ok", "emsg": f"Error: {str(e)}"}

def get_order_book(auth):
    """Get order book from DefinedGe API."""
    response = get_api_response("/orders", auth)
    logger.info(f"Order book raw response: {json.dumps(response, indent=2) if response else 'None'}")
    return response

def get_trade_book(auth):
    """Get trade book from DefinedGe API."""
    return get_api_response("/trades", auth)

def get_positions(auth):
    """Get positions from DefinedGe API."""
    response = get_api_response("/positions", auth)
    logger.debug(f"Positions API raw response: {json.dumps(response, indent=2) if response else 'None'}")
    return response

def get_holdings(auth):
    """Get holdings from DefinedGe API."""
    return get_api_response("/holdings", auth)

def get_open_position(tradingsymbol, exchange, product, auth):
    """Get open position for a specific symbol."""
    # Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    
    logger.info(f"=== GET OPEN POSITION ===")
    logger.info(f"Looking for: Symbol={tradingsymbol}, Exchange={exchange}, Product={product}")
    
    positions_data = get_positions(auth)
    logger.info(f"Raw positions response: {positions_data}")
    
    net_qty = '0'
    
    # Check different possible response formats from Definedge
    # Definedge may return data directly as a list or under 'data' or 'positions' key
    positions_list = None
    
    if isinstance(positions_data, list):
        # Direct list response
        positions_list = positions_data
        logger.info(f"Positions data is a direct list with {len(positions_list)} positions")
    elif positions_data and isinstance(positions_data, dict):
        # Check for successful response - Definedge might use different status indicators
        if positions_data.get('stat') == 'Ok' or positions_data.get('status') == 'SUCCESS':
            # Definedge uses 'positions' key, not 'data'
            positions_list = positions_data.get('positions', positions_data.get('data', []))
            logger.info(f"Found {len(positions_list)} positions in response")
        elif 'positions' in positions_data:
            # Definedge specific: positions key
            positions_list = positions_data['positions']
            logger.info(f"Found {len(positions_list)} positions under 'positions' key")
        elif 'data' in positions_data and positions_data['data']:
            # Sometimes data is present without explicit success status
            positions_list = positions_data['data']
            logger.info(f"Found {len(positions_list)} positions under 'data' key")
        elif not positions_data.get('stat') and not positions_data.get('status'):
            # Try to use data or positions if present even without status
            positions_list = positions_data.get('positions', positions_data.get('data', []))
            if positions_list:
                logger.info(f"Using {len(positions_list)} positions despite missing status")
    
    if positions_list:
        for position in positions_list:
            # Log each position for debugging
            pos_symbol = position.get('tradingsymbol')
            pos_exchange = position.get('exchange')
            pos_product = position.get('product')
            pos_product_type = position.get('product_type')
            # Definedge uses 'net_quantity' instead of 'netqty'
            pos_netqty = position.get('net_quantity', position.get('netqty', '0'))
            
            logger.info(f"Position: Symbol={pos_symbol}, Exchange={pos_exchange}, "
                       f"Product={pos_product}, ProductType={pos_product_type}, NetQty={pos_netqty}")
            
            # Check both 'product' and 'product_type' fields as Definedge might use either
            position_product = pos_product or pos_product_type
            
            if (pos_symbol == tradingsymbol and 
                pos_exchange == exchange and 
                position_product == product):
                net_qty = pos_netqty
                logger.info(f"✓ MATCH FOUND! Net Quantity: {net_qty}")
                break
        
        if net_qty == '0':
            logger.info(f"✗ No matching position found for {tradingsymbol} with product {product}")
    else:
        logger.warning("No positions list available to process")
    
    return net_qty

def place_order_api(data, auth):
    """Place an order using the DefinedGe API with shared connection pooling."""
    try:
        logger.info("=== PLACE ORDER DEFINEDGE CALLED ===")
        logger.info(f"Input data: {data}")
        
        # Parse the auth token
        api_session_key, susertoken, api_token = auth.split(":::")
        
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Get token and transform data
        token = get_token(data['symbol'], data['exchange'])
        newdata = transform_data(data, token)
        
        # Prepare headers
        headers = {
            'Authorization': api_session_key,
            'Content-Type': 'application/json'
        }
        
        logger.info(f"Place order payload being sent to Definedge: {json.dumps(newdata, indent=2)}")
        
        # Make the API request
        url = "https://integrate.definedgesecurities.com/dart/v1/placeorder"
        response = client.post(url, json=newdata, headers=headers)
        
        # Log the raw response
        logger.info(f"Definedge API Response Status: {response.status_code}")
        logger.info(f"Definedge API Response Headers: {dict(response.headers)}")
        logger.info(f"Definedge API Raw Response Text: {response.text}")
        
        # Parse JSON response
        try:
            response_data = response.json()
            logger.info(f"Definedge API Parsed Response: {json.dumps(response_data, indent=2)}")
        except json.JSONDecodeError as je:
            logger.error(f"Failed to parse JSON response: {je}")
            logger.error(f"Raw response text: {response.text}")
            response_data = {
                "stat": "Not_Ok", 
                "emsg": f"Invalid JSON response from API: {response.text[:200]}"
            }
        
        # Process the response based on different possible response formats
        if response_data.get('stat') == 'Ok' or response_data.get('status') == 'SUCCESS':
            orderid = response_data.get('norenordno') or response_data.get('order_id')
            logger.info(f"✓ Order placed successfully. Order ID: {orderid}")
            logger.info(f"Full success response: {response_data}")
        else:
            # Extract error message if present
            error_msg = response_data.get('emsg', response_data.get('message', 'No error message provided'))
            logger.error(f"✗ Order placement failed: {error_msg}")
            logger.error(f"Full error response: {response_data}")
            orderid = None
        
        # Add status attribute to response object to match what PlaceOrder endpoint expects
        response.status = response.status_code
            
        return response, response_data, orderid
        
    except httpx.HTTPStatusError as he:
        logger.error(f"HTTP Status Error during place order: {he}")
        logger.error(f"Response status: {he.response.status_code}")
        logger.error(f"Response text: {he.response.text}")
        response_data = {
            "stat": "Not_Ok", 
            "emsg": f"HTTP {he.response.status_code}: {he.response.text[:200]}"
        }
        response = type('', (), {'status': he.response.status_code, 'status_code': he.response.status_code})()
        return response, response_data, None
        
    except Exception as e:
        logger.error(f"Unexpected error during place order: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        response_data = {"stat": "Not_Ok", "emsg": f"Error: {str(e)}"}
        # Create a simple object with status attribute set to 500
        response = type('', (), {'status': 500, 'status_code': 500})()
        return response, response_data, None

def place_smartorder_api(data, auth):
    """Place smart order based on position sizing logic."""
    
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
        current_position = int(get_open_position(symbol, exchange, map_product_type(product), auth))

        logger.info(f"=== SMART ORDER EXECUTION ===")
        logger.info(f"Symbol: {symbol}, Exchange: {exchange}, Product: {product}")
        logger.info(f"Target position_size: {position_size}")
        logger.info(f"Current Open Position: {current_position}")

        # Determine action based on position_size and current_position
        action = None
        quantity = 0

        if position_size == 0 and current_position > 0:
            # Square off long position
            action = "SELL"
            quantity = abs(current_position)
            logger.info(f"Squaring off long position: SELL {quantity}")
        elif position_size == 0 and current_position < 0:
            # Square off short position
            action = "BUY"
            quantity = abs(current_position)
            logger.info(f"Squaring off short position: BUY {quantity}")
        elif position_size == 0 and current_position == 0:
            # No position to square off
            logger.info("No position to square off (position_size=0, current_position=0)")
            response_data = {"status": "success", "message": "No position to square off"}
            return res, response_data, orderid
        elif position_size == current_position:
            # Position already matches target
            logger.info(f"Position already matches target (both are {position_size})")
            response_data = {"status": "success", "message": "Position already at target size"}
            return res, response_data, orderid
        elif current_position == 0:
            # Open new position
            action = "BUY" if position_size > 0 else "SELL"
            quantity = abs(position_size)
            logger.info(f"Opening new position: {action} {quantity}")
        else:
            # Adjust existing position
            if position_size > current_position:
                action = "BUY"
                quantity = position_size - current_position
                logger.info(f"Increasing position: BUY {quantity} (from {current_position} to {position_size})")
            elif position_size < current_position:
                action = "SELL"
                quantity = current_position - position_size
                logger.info(f"Reducing position: SELL {quantity} (from {current_position} to {position_size})")

        if action and quantity > 0:
            # Prepare data for placing the order
            order_data = data.copy()
            order_data["action"] = action
            order_data["quantity"] = str(quantity)

            logger.info(f"Placing order: {action} {quantity} {symbol}")
            
            # Place the order
            res, response, orderid = place_order_api(order_data, auth)
            logger.info(f"Order response: {response}")
            logger.info(f"Order ID: {orderid}")
            
            return res, response, orderid
        else:
            logger.info("No action required or invalid quantity")
            response_data = {"status": "success", "message": "No action required"}
            return res, response_data, orderid
            
    except Exception as e:
        error_msg = f"Error in place_smartorder_api: {e}"
        logger.error(error_msg)
        response_data = {"status": "error", "message": error_msg}
        return res, response_data, orderid

def close_all_positions(current_api_key, auth):
    """Close all open positions."""
    
    logger.info("=== CLOSE ALL POSITIONS DEFINEDGE CALLED ===")
    
    # Fetch the current open positions
    logger.info("Fetching current open positions...")
    positions_response = get_positions(auth)
    
    # Log the raw response for debugging
    logger.info(f"Positions response: {json.dumps(positions_response, indent=2) if positions_response else 'None'}")
    
    # Check if the positions data is null or empty
    if not positions_response:
        logger.error("Failed to retrieve positions - response is None")
        return {"message": "No Open Positions Found", "status": "success"}, 200
    
    # Check for successful response based on Definedge format
    is_successful = (
        positions_response.get('stat') == 'Ok' or 
        positions_response.get('status') == 'SUCCESS' or
        positions_response.get('status') == 'OK'
    )
    
    if not is_successful:
        error_msg = positions_response.get('emsg', positions_response.get('message', 'Unknown error'))
        logger.error(f"Failed to retrieve positions: {error_msg}")
        return {"message": "No Open Positions Found", "status": "success"}, 200
    
    # Get positions data - check different possible field names
    positions_data = positions_response.get('data', positions_response.get('positions', []))
    
    # If the response itself is a list, use it directly
    if isinstance(positions_response, list):
        positions_data = positions_response
        logger.info("Positions response is a list, using directly")
    
    if not positions_data:
        logger.info("No positions found in response")
        return {"message": "No Open Positions Found", "status": "success"}, 200
    
    logger.info(f"Total positions found: {len(positions_data)}")
    
    # Count positions to be closed
    positions_to_close = []
    positions_skipped = []
    
    for position in positions_data:
        # Try different field names for net quantity
        netqty = position.get('netqty', position.get('net_qty', position.get('net_quantity', 0)))
        
        try:
            netqty_int = int(netqty)
            if netqty_int == 0:
                positions_skipped.append(position.get('tradingsymbol', 'Unknown'))
                continue
            else:
                positions_to_close.append(position)
        except (ValueError, TypeError):
            logger.warning(f"Invalid net quantity value: {netqty} for position: {position}")
            continue
    
    logger.info(f"Positions to close: {len(positions_to_close)}")
    logger.info(f"Positions skipped (zero quantity): {positions_skipped}")
    
    if not positions_to_close:
        logger.info("No open positions with non-zero quantity found")
        return {"message": "No Open Positions Found", "status": "success"}, 200
    
    # Track results
    closed_positions = []
    failed_positions = []
    
    # Loop through each position to close
    for position in positions_to_close:
        try:
            # Get net quantity - try different field names
            netqty = position.get('netqty', position.get('net_qty', position.get('net_quantity', 0)))
            netqty_int = int(netqty)
            
            # Determine action based on net quantity
            action = 'SELL' if netqty_int > 0 else 'BUY'
            quantity = abs(netqty_int)
            
            # Get trading symbol and exchange
            tradingsymbol = position.get('tradingsymbol', position.get('trading_symbol', ''))
            exchange = position.get('exchange', '')
            product = position.get('product', position.get('product_type', ''))
            
            logger.info(f"Closing position: {tradingsymbol} ({exchange}) - Qty: {netqty_int}, Action: {action}")
            
            # Get openalgo symbol to send to placeorder function
            symbol = get_oa_symbol(tradingsymbol, exchange)
            
            if not symbol:
                logger.error(f"Failed to get OpenAlgo symbol for {tradingsymbol} on {exchange}")
                symbol = tradingsymbol  # Use original as fallback
            
            logger.info(f"OpenAlgo symbol: {symbol}")
            
            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": exchange,
                "pricetype": "MARKET",
                "product": reverse_map_product_type(product),
                "quantity": str(quantity)
            }
            
            logger.info(f"Square-off order payload: {place_order_payload}")
            
            # Place the order to close the position
            res, response, orderid = place_order_api(place_order_payload, auth)
            
            if orderid:
                closed_positions.append({
                    'symbol': tradingsymbol,
                    'quantity': quantity,
                    'orderid': orderid
                })
                logger.info(f"✓ Successfully placed square-off order for {tradingsymbol}, Order ID: {orderid}")
            else:
                failed_positions.append({
                    'symbol': tradingsymbol,
                    'error': response.get('message', 'Unknown error')
                })
                logger.error(f"✗ Failed to square-off {tradingsymbol}: {response}")
                
        except Exception as e:
            logger.error(f"Exception while closing position {position}: {str(e)}")
            failed_positions.append({
                'symbol': position.get('tradingsymbol', 'Unknown'),
                'error': str(e)
            })
    
    # Log summary
    logger.info("=== CLOSE ALL POSITIONS SUMMARY ===")
    logger.info(f"Positions closed: {len(closed_positions)}")
    logger.info(f"Positions failed: {len(failed_positions)}")
    
    if closed_positions:
        logger.info(f"Closed positions: {[p['symbol'] for p in closed_positions]}")
    if failed_positions:
        logger.error(f"Failed positions: {failed_positions}")
    
    # Return success even if some positions failed to close
    return {"message": "All Open Positions SquaredOff", "status": "success"}, 200

def cancel_order(orderid, auth):
    """Cancel an order using the DefinedGe API with shared connection pooling."""
    try:
        logger.info("=== CANCEL ORDER DEFINEDGE CALLED ===")
        logger.info(f"Cancel order request for Order ID: {orderid}")
        
        # Parse the auth token
        api_session_key, susertoken, api_token = auth.split(":::")
        
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Prepare headers - no Content-Type needed for GET request
        headers = {
            'Authorization': api_session_key
        }
        
        # According to API docs, cancel is a GET request with orderid in URL
        url = f"https://integrate.definedgesecurities.com/dart/v1/cancel/{orderid}"
        
        logger.info(f"Making GET request to: {url}")
        
        # Make the GET request
        response = client.get(url, headers=headers)
        
        # Log the raw response
        logger.info(f"Definedge Cancel API Response Status: {response.status_code}")
        logger.info(f"Definedge Cancel API Response Headers: {dict(response.headers)}")
        logger.info(f"Definedge Cancel API Raw Response Text: {response.text}")
        
        # Parse JSON response
        try:
            response_data = response.json()
            logger.info(f"Definedge Cancel API Parsed Response: {json.dumps(response_data, indent=2)}")
        except json.JSONDecodeError as je:
            logger.error(f"Failed to parse JSON response: {je}")
            logger.error(f"Raw response text: {response.text}")
            response_data = {
                "status": "ERROR",
                "message": f"Invalid JSON response from API: {response.text[:200]}"
            }
        
        # Check if the request was successful based on response format
        # According to docs: status will be "SUCCESS" or error
        if response_data.get("status") == "SUCCESS":
            logger.info(f"✓ Order cancelled successfully. Order ID: {orderid}")
            if response_data.get("request_time"):
                logger.info(f"Request time: {response_data['request_time']}")
            return {"status": "success", "orderid": response_data.get("order_id", orderid)}, 200
        else:
            # Return an error response
            error_msg = response_data.get("message", "Failed to cancel order")
            logger.error(f"✗ Cancel order failed: {error_msg}")
            logger.error(f"Full error response: {response_data}")
            return {"status": "error", "message": error_msg}, response.status_code if response.status_code != 200 else 400
            
    except httpx.HTTPStatusError as he:
        logger.error(f"HTTP Status Error during cancel order: {he}")
        logger.error(f"Response status: {he.response.status_code}")
        logger.error(f"Response text: {he.response.text}")
        return {
            "status": "error", 
            "message": f"HTTP {he.response.status_code}: {he.response.text[:200]}"
        }, he.response.status_code
        
    except Exception as e:
        logger.error(f"Unexpected error during cancel order: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        return {"status": "error", "message": f"Error: {str(e)}"}, 500

def modify_order(data,auth):

    logger.info(f"=== MODIFY ORDER DEFINEDGE CALLED ===")
    logger.info(f"Raw input data: {data}")
    
    # Parse the auth token for DefinedGe
    api_session_key, susertoken, api_token = auth.split(":::")
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Get token but don't overwrite the symbol in data
    token = get_token(data['symbol'], data['exchange'])
    # The transform function will handle the symbol conversion internally
    
    transformed_data = transform_modify_order_data(data, token)
    
    logger.info(f"Transformed data for API: {transformed_data}")
    
    # Set up the request headers
    headers = {
        'Authorization': api_session_key,
        'Content-Type': 'application/json'
    }
    payload = json.dumps(transformed_data)
    
    logger.info(f"Final JSON payload being sent: {payload}")

    # Make the request using the shared client
    response = client.post(
        "https://integrate.definedgesecurities.com/dart/v1/modify",
        headers=headers,
        content=payload
    )
    
    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code
    
    logger.info(f"API Response Status: {response.status_code}")
    logger.info(f"API Response Text: {response.text}")
    
    data = json.loads(response.text)

    if data.get("stat") == "Ok" or data.get("status") == "SUCCESS":
        return {"status": "success", "orderid": data.get("order_id", data.get("norenordno"))}, 200
    else:
        logger.error(f"Modify order failed - Full error response: {data}")
        return {"status": "error", "message": data.get("emsg", data.get("message", "Failed to modify order"))}, response.status

def cancel_all_orders_api(data, auth):
    """Cancel all open orders."""
    
    logger.info("=== CANCEL ALL ORDERS DEFINEDGE CALLED ===")
    logger.info(f"Cancel all orders request with strategy: {data.get('strategy', 'N/A')}")
    
    # Get the order book
    logger.info("Fetching order book to identify open orders...")
    order_book_response = get_order_book(auth)
    
    # Check if order book was retrieved successfully
    if not order_book_response:
        logger.error("Failed to retrieve order book - response is None")
        return [], []
    
    # Check for successful response based on Definedge format
    # Definedge might return status: SUCCESS or stat: Ok
    is_successful = (
        order_book_response.get('stat') == 'Ok' or 
        order_book_response.get('status') == 'SUCCESS' or
        order_book_response.get('status') == 'OK'
    )
    
    if not is_successful:
        error_msg = order_book_response.get('emsg', order_book_response.get('message', 'Unknown error'))
        logger.error(f"Failed to retrieve order book: {error_msg}")
        logger.error(f"Full response: {order_book_response}")
        return [], []

    # Get orders data - check different possible field names
    orders_data = order_book_response.get('data', order_book_response.get('orders', order_book_response.get('orderbook', [])))
    
    # If the response itself is a list, use it directly
    if isinstance(order_book_response, list):
        orders_data = order_book_response
        logger.info("Order book response is a list, using directly")
    
    if not orders_data:
        logger.info("No orders found in order book")
        logger.info(f"Checked fields: 'data', 'orders', 'orderbook' in response")
        return [], []
    
    logger.info(f"Total orders in order book: {len(orders_data)}")
    
    # Filter orders that are in 'open' or 'trigger_pending' state
    # Definedge may use different status values, so check multiple variations
    orders_to_cancel = [
        order for order in orders_data
        if order.get('status', '').lower() in ['open', 'trigger pending', 'pending', 'open pending', 'trigger_pending']
        or order.get('order_status', '').upper() in ['OPEN', 'PENDING', 'TRIGGER_PENDING']
    ]
    
    logger.info(f"Found {len(orders_to_cancel)} open orders to cancel")
    
    if orders_to_cancel:
        logger.debug(f"Orders to cancel: {[order.get('order_id') or order.get('norenordno') or order.get('orderid') for order in orders_to_cancel]}")
    
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        # Try different field names for order ID
        orderid = order.get('order_id') or order.get('norenordno') or order.get('orderid')
        
        if orderid:
            logger.info(f"Attempting to cancel order: {orderid}")
            try:
                cancel_response, status_code = cancel_order(orderid, auth)
                
                if status_code == 200:
                    canceled_orders.append(orderid)
                    logger.info(f"✓ Successfully cancelled order: {orderid}")
                else:
                    failed_cancellations.append(orderid)
                    logger.error(f"✗ Failed to cancel order: {orderid}, Response: {cancel_response}")
            except Exception as e:
                failed_cancellations.append(orderid)
                logger.error(f"✗ Exception while cancelling order {orderid}: {str(e)}")
        else:
            logger.warning(f"Order missing ID field: {order}")
    
    # Log summary
    logger.info(f"=== CANCEL ALL ORDERS SUMMARY ===")
    logger.info(f"Total orders cancelled: {len(canceled_orders)}")
    logger.info(f"Total orders failed: {len(failed_cancellations)}")
    
    if canceled_orders:
        logger.info(f"Cancelled order IDs: {canceled_orders}")
    if failed_cancellations:
        logger.error(f"Failed order IDs: {failed_cancellations}")
    
    return canceled_orders, failed_cancellations
