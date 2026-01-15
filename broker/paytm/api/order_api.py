import json
import os
import urllib.parse
import httpx
from utils.httpx_client import get_httpx_client
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_oa_symbol, get_token
from broker.paytm.mapping.transform_data import (
    transform_data,
    map_product_type,
    reverse_map_product_type,
    transform_modify_order_data,
    map_exchange,
    reverse_map_order_type
)
from utils.logging import get_logger

logger = get_logger(__name__)

def get_api_response(endpoint, auth, method="GET", payload='', max_retries=3, retry_delay=2):
    base_url = "https://developer.paytmmoney.com"
    headers = {
        'x-jwt-token': auth,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    client = get_httpx_client()
    
    for attempt in range(max_retries):
        try:
            if method == "GET":
                response = client.get(f"{base_url}{endpoint}", headers=headers, timeout=30.0)
            else:
                response = client.post(f"{base_url}{endpoint}", headers=headers, content=payload, timeout=30.0)

            # Try to parse response JSON even if status code is error
            try:
                response_json = response.json()
            except Exception:
                response_json = {}

            # Check if it's an error response
            if not response.is_success:
                error_msg = response_json.get('message', response.text)
                logger.error(f"API Error: Status {response.status_code} - {error_msg}")
                # Don't retry on 4xx errors as they are client errors
                if response.status_code < 500:
                    return {
                        "status": "error", 
                        "message": error_msg,
                        "error_code": response.status_code,
                        "response": response_json
                    }
                raise httpx.HTTPError(f"HTTP {response.status_code}")

            return response_json

        except (httpx.RequestError, httpx.HTTPError) as e:
            logger.error(f"Request error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(retry_delay)
                continue
            return {"status": "error", "message": "Request failed after retries", "error": str(e)}

        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            return {"status": "error", "message": "Unexpected error", "error": str(e)}

def get_order_book(auth):
    return get_api_response("/orders/v1/user/orders", auth)

# PAYTM does not provide all tradebook details. every tradebook call needs orderID


def get_trade_book(auth):
    return get_api_response("/orders/v1/user/orders", auth)


def get_positions(auth):
    return get_api_response("/orders/v1/position", auth)


def get_holdings(auth):
    return get_api_response("/holdings/v1/get-user-holdings-data", auth)



def get_open_positionss(tradingsymbol, exchange, product, auth):
    logger.debug(f"Entering get_open_positionss for {tradingsymbol}")
    # Convert Trading Symbol from OpenAlgo Format to Broker Format (Token ID)
    logger.debug(f"Calling get_token with symbol: {tradingsymbol}, exchange: {exchange}")
    target_security_id = get_token(tradingsymbol, exchange)
    if target_security_id.isdigit():
        target_security_id = target_security_id
    else:
        if exchange =='NFO':
            exchange = 'NSE'
        elif exchange =='BFO':
            exchange = 'BSE'
        target_security_id = get_token(tradingsymbol, exchange)
        # Use original exchange
    logger.debug(f"Initial Target Security ID (using exchange '{exchange}'): {target_security_id}")
    # Check if the initial lookup failed (returned non-numeric ID)
    # We assume valid security IDs are numeric strings
    
    # Get raw positions data first
    positions_data = get_positions(auth)
    net_qty = '0'
    
    logger.debug("=== Position Check Details ===")
    logger.debug(f"Looking for position: symbol={tradingsymbol}, exchange={exchange}, product={product}, target_id={target_security_id}")
    
    logger.debug("=== Position Check Details ===")
    logger.debug(f"Looking for position:")
    logger.debug(f"Symbol: {tradingsymbol}")
    logger.debug(f"Exchange: {exchange}")
    logger.debug(f"Product: {product} (Broker format: {reverse_map_product_type(product)})")
    logger.debug(f"Target Security ID: {target_security_id}")

    if positions_data and positions_data.get('status') == 'success' and positions_data.get('data'):
        logger.debug(f"Found {len(positions_data['data'])} positions in account")
        
        for idx, position in enumerate(positions_data['data'], 1):
            pos_security_id = position.get('security_id') # This is the token ID from Paytm API
            pos_exchange = position.get('exchange')
            pos_product = position.get('product')

            logger.debug(f"\nChecking Position #{idx}:")
            logger.debug(f"API Security ID: {pos_security_id}")
            logger.debug(f"API Exchange: {pos_exchange}")
            logger.debug(f"API Product: {pos_product}")
            logger.debug(f"API Instrument: {position.get('instrument')}")
            logger.debug(f"API Net Qty: {position.get('net_qty', position.get('netQty', '0'))}")
            
            # Map API exchange (NSE for both Eq/F&O) to our internal representation (NFO for F&O)
            our_exchange = exchange # Default to the requested exchange
            if pos_exchange == 'NSE' and (
                'OPT' in position.get('instrument', '') or                 'FUT' in position.get('instrument', '')
            ):
                our_exchange = 'NFO'
                logger.debug(f"Mapped to Internal Exchange: {our_exchange} (based on instrument type)")

            # --- Match Criteria --- 
            # 1. Security ID (Token) match
            # Compare the token ID from our DB (target_security_id) with the token ID from Paytm (pos_security_id)
            security_match = str(pos_security_id) == str(target_security_id)
            
            # 2. Exchange Match (using our mapped internal exchange)
            exchange_match = our_exchange == exchange

            # 3. Product Match (comparing API product with our reversed product type)
            product_match = pos_product == reverse_map_product_type(product)
            
            logger.debug("\nMatching Criteria:")
            logger.debug(f"Target Security ID: {target_security_id}, API Security ID: {pos_security_id} -> Match: {security_match}")
            logger.debug(f"Target Exchange: {exchange}, API Mapped Exchange: {our_exchange} -> Match: {exchange_match}")
            logger.debug(f"Target Product: {reverse_map_product_type(product)}, API Product: {pos_product} -> Match: {product_match}")
            
            if security_match and exchange_match and product_match:
                net_qty = str(position.get('net_qty', position.get('netQty', '0')))
                logger.info(f"✓ Found matching position for {tradingsymbol}!")
                logger.debug(f"Net Quantity: {net_qty}")
                break
            else:
                logger.debug("✗ Position does not match criteria")
    else:
        logger.warning(f"No positions data available or error in API response: {positions_data}")
    
    logger.debug("=== Position Check Complete ===")
    return net_qty

def get_open_position(tradingsymbol, exchange, producttype,auth):
    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    logger.debug(f"Entering get_open_position for {tradingsymbol}")
    # Convert Trading Symbol from OpenAlgo Format to Broker Format (Token ID)
    logger.debug(f"Calling get_token with symbol: {tradingsymbol}, exchange: {exchange}")
    target_security_id = get_token(tradingsymbol, exchange)
    
    # Save original exchange for matching later
    original_exchange = exchange
    
    # Handle exchange mapping for token lookup
    if exchange =='NFO':
        exchange = 'NSE'
    elif exchange =='BFO':
        exchange = 'BSE'
    
    # Get the token again with the mapped exchange if needed
    if not target_security_id.isdigit():
        target_security_id = get_token(tradingsymbol, exchange)
        
    logger.debug(f"Target Security ID: {target_security_id}, Original Exchange: {original_exchange}, Mapped Exchange: {exchange}")
    
    # Also save the original symbol for direct symbol matching
    target_symbol = tradingsymbol
    
    #tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    positions_data = get_positions(auth)

    net_qty = '0'

    if positions_data and positions_data.get('status') and positions_data.get('data'):
        logger.debug(f"Checking positions data for security_id={target_security_id}, exchange={exchange}, symbol={target_symbol}")
        logger.debug(f"Found {len(positions_data['data'])} positions")
        
        for position in positions_data['data']:
            pos_security_id = position.get('security_id')
            pos_exchange = position.get('exchange')
            pos_product = position.get('product')
            pos_qty = position.get('net_qty', position.get('netQty', '0'))
            pos_display_name = position.get('display_name', '')
            pos_instrument = position.get('instrument', '')
            
            logger.debug(f"Checking Position: security_id={pos_security_id}, exchange={pos_exchange}, product={pos_product}, qty={pos_qty}, instrument={pos_instrument}, display_name={pos_display_name}")
            
            # Map Paytm's exchange to our internal exchange (NFO for derivatives)
            internal_exchange = pos_exchange
            if pos_exchange == 'NSE' and ('OPT' in pos_instrument or 'FUT' in pos_instrument or pos_instrument == 'OPTIDX'):
                internal_exchange = 'NFO'
            elif pos_exchange == 'BSE' and ('OPT' in pos_instrument or 'FUT' in pos_instrument):
                internal_exchange = 'BFO'
                
            product = reverse_map_product_type(pos_product)
            
            logger.debug(f"Mapped to: internal_exchange={internal_exchange}, product={product}")
            logger.debug(f"Comparing with target exchange: {internal_exchange}=={original_exchange}")
            
            # Multiple ways to match a position:
            # 1. Direct security_id match
            security_id_match = str(pos_security_id) == str(target_security_id)
            
            # 2. Symbol-based match for derivatives (using target_symbol)
            # Clean up display name for comparison (remove spaces)
            clean_display_name = ''.join(pos_display_name.split())
            symbol_match = (target_symbol.upper() in clean_display_name.upper() or 
                           target_symbol.upper() in str(pos_security_id).upper())
            
            # 3. Exchange match
            exchange_match = internal_exchange == original_exchange
            
            logger.debug(f"Match criteria: security_id={security_id_match}, symbol={symbol_match}, exchange={exchange_match}")
            
            # If either security_id matches or symbol matches with the correct exchange, we've found our position
            if (security_id_match or symbol_match) and exchange_match:
                logger.debug(f"Match found! Quantity: {pos_qty}")
                net_qty = pos_qty
                break  # Assuming you need the first match
        
    return net_qty


def place_order_api(data, auth):
    payload = transform_data(data)
    payload = json.dumps(payload)
    logger.debug(f"Order payload: {payload}")

    response = get_api_response(
        endpoint="/orders/v1/place/regular",
        auth=auth,
        method="POST",
        payload=payload
    )

    logger.debug(f"Response: {response}")

    # Create a response object with status code
    res = type('Response', (), {'status': 200 if response.get('status') == 'success' else 500})()
    
    if response.get('status') == 'success':
        orderid = response['data'][0]['order_no']
    else:
        orderid = None

    return res, response, orderid

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


    logger.debug(f"position_size: {position_size}") 
    logger.debug(f"Open Position: {current_position}") 
    
    # Determine action based on position_size and current_position
    action = None
    quantity = 0


    # If both position_size and current_position are 0, do nothing
    if position_size == 0 and current_position == 0 and int(data['quantity'])!=0:
        action = data['action']
        quantity = data['quantity']
        logger.debug(f"Action: {action}, Quantity: {quantity}")
        res, response, orderid = place_order_api(data,AUTH_TOKEN)
        logger.debug(f"Response: {response}")
        
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
            logger.debug(f"Smart buy quantity: {quantity}")
        elif position_size < current_position:
            action = "SELL"
            quantity = current_position - position_size
            logger.debug(f"Smart sell quantity: {quantity}")

    if action:
        # Prepare data for placing the order
        order_data = data.copy()
        order_data["action"] = action
        order_data["quantity"] = str(quantity)

        logger.info(f"Placing smart order: {order_data}")
        # Place the order
        res, response, orderid = place_order_api(order_data,auth)
        logger.debug(f"Smart order response: {response}")
        logger.info(f"Smart order ID: {orderid}")
        
        return res , response, orderid
    
def close_all_positions(current_api_key, auth):

    AUTH_TOKEN = auth
    # Fetch the current open positions
    positions_response = get_positions(AUTH_TOKEN)

    logger.debug(f"Positions retrieved response: {positions_response}")
    
    # First check if the API request was successful
    if positions_response.get('status') == 'error':
        logger.error(f"Failed to fetch positions: {positions_response.get('message', 'Unknown error')}")
        return {"status": "error", "message": positions_response.get('message', 'Failed to fetch positions')}, 500
        
    # Check if the positions data is null or empty
    if not positions_response.get('data'):
        return {"status": "success", "message": "No Open Positions Found"}, 200

    successful_closes = 0
    failed_closes = 0
    
    if positions_response['status'] == 'success':
        total_positions = len(positions_response['data'])
        logger.info(f"Found {total_positions} positions")
        
        # Loop through each position to close
        for position in positions_response['data']:
            # Get quantity - handle different field names
            net_qty = position.get('net_qty', position.get('netQty', '0'))
            # Skip if net quantity is zero
            if int(net_qty) == 0:
                logger.info(f"Skipping position with zero quantity: {position.get('security_id')}")
                continue

            # Determine action based on net quantity
            action = 'SELL' if int(net_qty) > 0 else 'BUY'
            quantity = abs(int(net_qty))
            
            # Get all the position details
            pos_security_id = position.get('security_id')
            pos_exchange = position.get('exchange')
            pos_instrument = position.get('instrument', '')
            pos_display_name = position.get('display_name', '')
            
            # For Paytm, we'll ALWAYS use the security_id directly from the position data
            # rather than trying to look it up in our database
            
            # Print detailed position info
            logger.info(f"Processing position: security_id={pos_security_id}, exchange={pos_exchange}, instrument={pos_instrument}, display_name={pos_display_name}, qty={net_qty}, action={action}")

            # Skip if no security ID
            if not pos_security_id:
                logger.info(f"Skipping position due to missing security_id: {position}")
                failed_closes += 1
                continue

            # Create order payload directly in Paytm's format
            txn_type = "S" if action == "SELL" else "B"
            
            # Use original exchange from Paytm (no need to map back to NFO)
            exchange = pos_exchange
            
            # Properly determine segment based on instrument type
            is_derivative = (pos_instrument == 'OPTIDX' or
                           pos_instrument == 'OPTSTK' or
                           pos_instrument == 'FUTIDX' or
                           pos_instrument == 'FUTSTK' or
                           'OPT' in pos_instrument or
                           'FUT' in pos_instrument)
                           
            segment = "D" if is_derivative else "E"
            
            order_payload = {
                "security_id": pos_security_id,  # Use pos_security_id variable
                "exchange": exchange,  # Use the exchange variable we set above
                "txn_type": txn_type,
                "order_type": "MKT",  # Market order
                "quantity": str(quantity),
                "product": position['product'],
                "price": "0",
                "validity": "DAY",
                "segment": segment,
                "source": "M"
            }
            
            logger.info(f"Placing Order: {order_payload}")
            
            # Place the order directly without transform
            response = get_api_response(
                endpoint="/orders/v1/place/regular",
                auth=AUTH_TOKEN,
                method="POST",
                payload=json.dumps(order_payload)
            )
            
            logger.debug(f"Payload for closing order: {json.dumps(order_payload)}")
            logger.debug(f"Response from closing order: {response}")
            
            if response.get('status') == 'success':
                logger.info(f"Successfully closed position for {pos_security_id} ({pos_display_name})")
                successful_closes += 1
            else:
                logger.error(f"Failed to close position for {pos_security_id} ({pos_display_name}): {response.get('message', 'Unknown error')}")
                failed_closes += 1

    # Report on success/failures
    if successful_closes > 0 and failed_closes == 0:
        return {'status': 'success', "message": f"Successfully closed all {successful_closes} open positions"}, 200
    elif successful_closes > 0 and failed_closes > 0:
        return {'status': 'partial', "message": f"Closed {successful_closes} positions, failed to close {failed_closes} positions"}, 200
    elif successful_closes == 0 and failed_closes > 0:
        return {'status': 'error', "message": f"Failed to close all {failed_closes} positions"}, 500
    else:
        return {'status': 'success', "message": "No positions to close"}, 200


def cancel_order(orderid, auth):
    orders_list = get_order_book(auth)
    for order in orders_list['data']:
        if order['order_no'] == orderid:
            if order['status'] == 'Pending':
                logger.info(f"Cancelling order: {orderid}")
                payload = json.dumps({
                    "order_no": orderid,
                    "source": "N",
                    "txn_type": order['txn_type'],
                    "exchange": order['exchange'],
                    "segment": order['segment'],
                    "product": order['product'],
                    "security_id": order['security_id'],
                    "quantity": order['quantity'],
                    "validity": order['validity'],
                    "order_type": order['order_type'],
                    "price": order['price'],
                    "off_mkt_flag": order['off_mkt_flag'],
                    "mkt_type": order['mkt_type'],
                    "serial_no": order['serial_no'],
                    "group_id": order['group_id'],
                })

                response = get_api_response(
                    endpoint="/orders/v1/cancel/regular",
                    auth=auth,
                    method="POST",
                    payload=payload
                )

                if response.get("status"):
                    # Return a success response
                    return {"status": "success", "orderid": response['data'][0]['order_no']}, 200
                else:
                    # Return an error response
                    return {"status": "error", "message": response.get("message", "Failed to cancel order")}, 500

# As long as an order is pending in the system, certain attributes of it can be modified.
# Price, quantity, validity, product are some of the variables that can be modified by the user.
# You have to pass "order_no", "serial_no" "group_id" as compulsory to modify the order.


def modify_order(data, auth):
    orderid = data['orderid']
    orders_list = get_order_book(auth)
    
    if not orders_list or 'data' not in orders_list:
        return {"status": "error", "message": "Failed to fetch order book"}, 500
        
    order_found = False
    for order in orders_list['data']:
        if order['order_no'] == orderid:
            order_found = True
            # Check if order is in a modifiable state
            MODIFIABLE_STATUSES = ['OPEN', 'TRIGGER PENDING', 'MODIFIED', 'PENDING']
            if order['status'].upper() not in MODIFIABLE_STATUSES:
                return {"status": "error", "message": f"Order {orderid} cannot be modified. Current status: {order['status']}"}, 400
                
            logger.info(f"Modifying order: {orderid}")
            
            # Prepare modification payload
            payload = {
                "order_no": orderid,
                "exchange": order['exchange'],
                "segment": order['segment'],
                "security_id": order['security_id'],
                "quantity": data.get('quantity', order['quantity']),
                "price": '0' if data.get('pricetype') == 'MARKET' else data.get('price', order['price']),
                "trigger_price": data.get('trigger_price', order.get('trigger_price', '0')),
                "validity": "DAY",
                "product": reverse_map_product_type(data.get('product', order['product'])),
                "order_type": 'MKT' if data.get('pricetype') == 'MARKET' else order['order_type'],
                "txn_type": order['txn_type'],
                "source": "N",
                "off_mkt_flag": order.get('off_mkt_flag', 'N'),
                "serial_no": order['serial_no'],
                "group_id": order['group_id']
            }
            
            logger.info(f"Modification payload: {payload}")
            
            response = get_api_response(
                endpoint="/orders/v1/modify/regular",
                auth=auth,
                method="POST",
                payload=json.dumps(payload)
            )
            
            logger.info(f"Modification response: {response}")

            if response.get("status") == "success":
                return {
                    "status": "success",
                    "message": "Order modified successfully",
                    "orderid": response['data'][0].get('order_no', orderid)
                }, 200
            else:
                return {
                    "status": "error",
                    "message": response.get("message", "Failed to modify order")
                }, 500
                
    if not order_found:
        return {"status": "error", "message": f"Order {orderid} not found"}, 404


def cancel_all_orders_api(data, auth):
    # Get the order book
    order_book_response = get_order_book(auth)
    if order_book_response['status'] != 'success':
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response.get('data', [])
                        if order['status'] in ['Pending']]
    logger.info(f"{orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['order_no']
        cancel_response, status_code = cancel_order(orderid, auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
