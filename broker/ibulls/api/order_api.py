import json
import os
from tokenize import Token
import httpx
from database.auth_db import get_auth_token
from database.token_db import get_token , get_br_symbol, get_symbol
from broker.ibulls.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data
from utils.httpx_client import get_httpx_client
from broker.ibulls.baseurl import INTERACTIVE_URL
from utils.logging import get_logger

logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="GET",  payload=''):
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_KEY')

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
      'authorization': AUTH_TOKEN,
      'Content-Type': 'application/json',
    }
    
    url = f"{INTERACTIVE_URL}{endpoint}"

    logger.info(f"Request URL: {url}")
    logger.info(f"Headers: {headers}")
    logger.info(f'Payload: {json.dumps(payload, indent=2) if payload else "None"}')
    
    if method == "GET":
        response = client.get(url, headers=headers)
    elif method == "POST":
        response = client.post(url, headers=headers, json=payload)
    else:
        response = client.request(method, url, headers=headers, json=payload)
    
    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code
    logger.info(f"Response Status Code: {response.status_code}")
    logger.info(f"Response Content: {response.text}")
    return response.json()

def get_order_book(auth):
    return get_api_response("/orders",auth)

def get_trade_book(auth):
    return get_api_response("/orders/trades",auth)

def get_positions(auth):
    return get_api_response("/portfolio/positions?dayOrNet=NetWise",auth)

def get_holdings(auth):
    return get_api_response("/portfolio/holdings",auth)

def get_open_position(tradingsymbol, exchange, producttype, auth):
    """
    Get the net quantity for a given symbol from the position book.
    This should return the NetQty which represents the net position (positive for long, negative for short).
    """
    # Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    positions_data = get_positions(auth)

    net_qty = '0'

    logger.info(f"Searching position for: symbol={tradingsymbol}, exchange={exchange}, product={producttype}")
    
    if positions_data and positions_data.get('type') == 'success' and positions_data.get('result'):
        position_list = positions_data['result'].get('positionList', [])
        logger.info(f"Found {len(position_list)} positions in position book")
        
        for position in position_list:
            # Log position details for debugging
            logger.info(f"Position: {position}")
            
            # Try different possible field names for NetQty
            possible_qty_fields = ['NetQty', 'Quantity', 'netQty', 'NetQuantity', 'net_qty']
            
            # Match by symbol and product type 
            pos_symbol = position.get('TradingSymbol', position.get('tradingsymbol', ''))
            pos_product = position.get('ProductType', position.get('producttype', ''))
            
            if pos_symbol == tradingsymbol and pos_product == producttype:
                # Find the correct NetQty field
                for field in possible_qty_fields:
                    if field in position:
                        net_qty = str(position[field])
                        logger.info(f"Found NetQty in field '{field}': {net_qty}")
                        break
                else:
                    # If no standard field found, log all available fields
                    logger.warning(f"NetQty field not found. Available fields: {list(position.keys())}")
                break
        
    logger.info(f"Returning net_qty: {net_qty}")
    return net_qty

def place_order_api(data,auth):
    AUTH_TOKEN = auth   
    logger.info(f"Data: {data}")

    # Check if this is a direct instrument ID payload or needs transformation
    if all(key in data for key in ['exchangeSegment', 'exchangeInstrumentID', 'productType', 'orderType']):
        newdata = data
    else:
        # Traditional symbol-based payload that needs transformation
        token = get_token(data['symbol'], data['exchange'])
        logger.info(f"token: {token}")
        newdata = transform_data(data, token)

    headers = {
        'authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
    }
   
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    # Make the request using the shared client
    response = client.post(
        f"{INTERACTIVE_URL}/orders",
        headers=headers,
        json=newdata
    )
    
    # Add status attribute for compatibility
    response.status = response.status_code
    
    # Parse the JSON response
    try:
        response_data = response.json()
    except json.JSONDecodeError:
        response_data = {"error": "Invalid JSON response from server", "raw_response": response.text}

    orderid = response_data.get("result", {}).get("AppOrderID") if response_data.get("type") == "success" else None
    
    logger.info(f"Response Data: {response_data}")
    logger.info(f"Order ID: {orderid}")
    
    return response, response_data, orderid


def place_smartorder_api(data: dict, auth: str) -> tuple:
    """
    Place a smart order to achieve target position size based on the OpenAlgo specification.
    
    The function compares the target position_size with current position and places
    appropriate BUY/SELL orders to match the target position.
    
    Args:
        data (dict): Must contain:
            - symbol: Trading symbol
            - exchange: Exchange name
            - product: Product type (CNC, NRML, MIS, etc.)
            - action: BUY or SELL
            - quantity: Order quantity
            - position_size: Target position size (positive for long, negative for short)
        auth (str): Authentication token
        
    Returns:
        tuple: (response object, response data, order id)
    """
    AUTH_TOKEN = auth
    res = None
    
    try:
        # Log incoming request
        logger.debug(f"PlaceSmartOrder request: {data}")
        
        # Extract and validate required parameters
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        product = data.get("product")
        action = data.get("action", "").upper()
        
        if not all([symbol, exchange, product, action]):
            error_msg = "Missing required parameters (symbol, exchange, product, action)"
            logger.error(error_msg)
            return None, {"status": "error", "message": error_msg}, None
            
        if action not in ["BUY", "SELL"]:
            error_msg = f"Invalid action: {action}. Must be BUY or SELL"
            logger.error(error_msg)
            return None, {"status": "error", "message": error_msg}, None
            
        try:
            quantity = int(data.get("quantity", "0"))
            position_size = int(data.get("position_size", "0"))
        except (ValueError, TypeError) as e:
            error_msg = f"Invalid quantity or position_size: {str(e)}"
            logger.error(error_msg)
            return None, {"status": "error", "message": error_msg}, None

        # Get current position (NetQty from position book)
        try:
            mapped_product = map_product_type(product)
            current_net_qty_str = get_open_position(symbol, exchange, mapped_product, AUTH_TOKEN)
            current_position = int(current_net_qty_str or 0)
            
            logger.info(f"=== SMART ORDER ANALYSIS ===")
            logger.info(f"Symbol: {symbol}, Exchange: {exchange}, Product: {product}")
            logger.info(f"Mapped Product: {mapped_product}")
            logger.info(f"Current NetQty from position book: {current_net_qty_str}")
            logger.info(f"Current Position (parsed): {current_position}")
            logger.info(f"Target Position Size: {position_size}")
            logger.info(f"=== END ANALYSIS ===")
            
        except Exception as e:
            error_msg = f"Failed to fetch current position for {symbol}"
            logger.error(f"{error_msg}. Error: {str(e)}")
            return None, {"status": "error", "message": error_msg}, None

        # Smart order logic: Calculate required action based purely on position_size vs current_position
        # The action and quantity parameters are ignored - only position_size matters
        
        logger.info(f"Smart Order Analysis: Current={current_position}, Target={position_size}")
        
        # Calculate the position delta (difference between target and current)
        position_delta = position_size - current_position
        
        # Determine order action and quantity based purely on position delta
        order_action = None
        order_quantity = 0
        response_msg = ""
        
        if position_delta == 0:
            # Target position already achieved
            return None, {"status": "success", "message": f"Position already matches target size of {position_size}"}, None
        elif position_delta > 0:
            # Need to BUY more to reach target position
            order_action = "BUY"
            order_quantity = position_delta
            if current_position == 0:
                response_msg = f"Creating new long position: BUYing {order_quantity} shares to reach target {position_size}"
            elif current_position > 0:
                response_msg = f"Increasing long position: BUYing {order_quantity} shares (from {current_position} to {position_size})"
            else:  # current_position < 0
                response_msg = f"Covering short and going long: BUYing {order_quantity} shares (from {current_position} to {position_size})"
        else:  # position_delta < 0
            # Need to SELL to reach target position
            order_action = "SELL"
            order_quantity = abs(position_delta)
            if current_position == 0:
                response_msg = f"Creating new short position: SELLing {order_quantity} shares to reach target {position_size}"
            elif current_position > 0:
                if position_size >= 0:
                    response_msg = f"Reducing long position: SELLing {order_quantity} shares (from {current_position} to {position_size})"
                else:
                    response_msg = f"Squaring long and going short: SELLing {order_quantity} shares (from {current_position} to {position_size})"
            else:  # current_position < 0
                response_msg = f"Increasing short position: SELLing {order_quantity} shares (from {current_position} to {position_size})"

        # Place the order if needed
        if order_action and order_quantity > 0:
            order_data = data.copy()
            order_data.update({
                "action": order_action,
                "quantity": str(order_quantity)
            })
            
            logger.info(f"Placing {order_action} order for {order_quantity} shares of {symbol}")
            res, response, orderid = place_order_api(order_data, AUTH_TOKEN)
            
            if orderid:
                logger.info(f"Order placed successfully. Order ID: {orderid}")
                response_msg = f"{response_msg}. Order ID: {orderid}"
            
            return res, {"status": "success", "message": response_msg}, orderid
        
        # If we get here, no order was placed
        return None, {"status": "success", "message": response_msg or "No action needed"}, None
        
    except Exception as e:
        error_msg = f"Error in place_smartorder_api: {str(e)}"
        logger.exception(error_msg)
        return None, {"status": "error", "message": error_msg}, None
    



def close_all_positions(current_api_key,auth):
    # Fetch the current open positions
    AUTH_TOKEN = auth

    positions_response = get_positions(AUTH_TOKEN)
    logger.info(f"Open_positions : {positions_response}")

    positions_list = positions_response.get('result', {}).get('positionList', [])
    if not positions_list:
        return {"message": "No Open Positions Found"}, 200

    # If response has positions
    for position in positions_list:
        # Skip if net quantity is zero
        if int(position['Quantity']) == 0:
            continue

        # Determine action based on net quantity
        action = 'SELL' if int(position['Quantity']) > 0 else 'BUY'
        quantity = abs(int(position['Quantity']))

        exchange_segment = position['ExchangeSegment']
        instrument_id = position['ExchangeInstrumentId']
        
        logger.info(f"Exchange Segment: {exchange_segment}")
        logger.info(f"Exchange Instrument ID: {instrument_id}")

        # Prepare the order payload
        place_order_payload = {
            "exchangeSegment": exchange_segment,
            "exchangeInstrumentID": instrument_id,
            "productType": position['ProductType'],
            "orderType": "MARKET",
            "orderSide": action,
            "timeInForce": "DAY",
            "disclosedQuantity": "0",
            "orderQuantity": str(quantity),
            "limitPrice": "0",
            "stopPrice": "0",
            "orderUniqueIdentifier": "openalgo"
        }

        # Place the order to close the position
        res, response, orderid =   place_order_api(place_order_payload,auth)

        # logger.info(f"{res}")
        # logger.info(f"{response}")
        # logger.info(f"{orderid}")


            
            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid,auth):
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    #logger.info(f"{orderid}")
    # Set up the request headers
    headers = {
        'authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
    }
    
    # Prepare the payload
    payload = json.dumps({
        "appOrderID": orderid,
        "orderUniqueIdentifier": "openalgo"
    })
    
    # Make the request using the shared client
    response = client.delete(
    f"{INTERACTIVE_URL}/orders?appOrderID={orderid}",
    headers=headers
)
    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code
    
    data = json.loads(response.text)
    
    # Check if the request was successful
    if data.get("status"):
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Return an error response
        return {"status": "error", "message": data.get("message", "Failed to cancel order")}, response.status


def modify_order(data,auth):

    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    token = get_token(data['symbol'], data['exchange'])
    data['symbol'] = get_br_symbol(data['symbol'],data['exchange'])

    transformed_data = transform_modify_order_data(data, token)  # You need to implement this function
    # Set up the request headers
    headers = {
        'authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
    }
    payload = json.dumps(transformed_data)

    # Make the request using the shared client
    response = client.put(f"{INTERACTIVE_URL}/orders",
        headers=headers,
        content=payload
    )
    
    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code
    logger.info(f"Response of modify order :{response.status}")
    data = json.loads(response.text)

    if data.get("status") == "true" or data.get("message") == "SUCCESS":
        return {"status": "success", "orderid": data["data"]["orderid"]}, 200
    else:
        return {"status": "error", "message": data.get("message", "Failed to modify order")}, response.status


def cancel_all_orders_api(data,auth):
    # Get the order book

    AUTH_TOKEN = auth
    

    order_book_response = get_order_book(AUTH_TOKEN)
    logger.info(f"Order book response: {order_book_response}")
    if order_book_response.get("type") != "success":
        return [], []  # Return empty lists indicating failure to retrieve the order book
    
    orders = order_book_response.get("result", [])

     # Filter orders that are in 'open' or 'trigger_pending' state
    #logger.info(f"Orders: {orders}")
    orders_to_cancel = [
        order for order in orders 
        if order["OrderStatus"] in ["New", "Trigger Pending"]
    ]
    logger.info(f"Orders to cancel: {orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['AppOrderID']
        cancel_response, status_code = cancel_order(orderid,auth)
        if status_code == 200:
            logger.info(f"Canceled order {orderid}")
            canceled_orders.append(orderid)
        else:
            logger.error(f"Failed to cancel order {orderid}")
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations
