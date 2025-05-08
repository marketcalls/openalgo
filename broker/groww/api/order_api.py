import json
import os
import logging
import uuid
import re
from datetime import datetime
from database.auth_db import get_auth_token
from database.token_db import get_token
from database.token_db import get_br_symbol, get_oa_symbol, get_symbol
from broker.groww.mapping.transform_data import (
    # Functions
    transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data,
    map_exchange_type, map_exchange, map_segment_type, map_validity, map_order_type, map_transaction_type,
    # Constants
    VALIDITY_DAY, VALIDITY_IOC,
    EXCHANGE_NSE, EXCHANGE_BSE, 
    SEGMENT_CASH, SEGMENT_FNO, SEGMENT_CURRENCY, SEGMENT_COMMODITY,
    PRODUCT_CNC, PRODUCT_MIS, PRODUCT_NRML,
    ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT, ORDER_TYPE_SL, ORDER_TYPE_SLM,
    TRANSACTION_TYPE_BUY, TRANSACTION_TYPE_SELL,
    ORDER_STATUS_NEW, ORDER_STATUS_ACKED, ORDER_STATUS_APPROVED, ORDER_STATUS_CANCELLED
)

# Import Groww SDK
try:
    from growwapi import GrowwAPI
except ImportError:
    logging.warning("growwapi package not found. Please install it using 'pip install growwapi'.")


def init_groww_client(auth_token):
    """
    Initialize and return Groww API client
    
    Args:
        auth_token (str): Authentication token
        
    Returns:
        GrowwAPI: Initialized Groww API client
    """
    try:
        return GrowwAPI(auth_token)
    except Exception as e:
        logging.error(f"Failed to initialize Groww API client: {e}")
        raise

def get_order_book(auth):
    """
    Get list of orders for the user from both CASH and FNO segments
    
    Args:
        auth (str): Authentication token
    
    Returns:
        dict: Order book data with combined orders from all segments
    """
    try:
        logging.info("Initializing Groww client for order book")
        groww = init_groww_client(auth)
        
        # Get orders from all segments (CASH + FNO)
        all_orders = []
        page = 0
        page_size = 25  # Maximum allowed by Groww API
        
        logging.info(f"Fetching order book with pagination (page_size={page_size})")
        
        # Keep fetching until we get all orders
        while True:
            logging.debug(f"Fetching orders page {page}")
            try:
                orders = groww.get_order_list(
                    page=page,
                    page_size=page_size
                )
                
                logging.debug(f"API Response structure: {list(orders.keys()) if orders else 'None'}")
                
                if not orders or not orders.get('order_list'):
                    logging.info(f"No orders found or empty response on page {page}")
                    break
                
                current_orders = orders['order_list']
                logging.info(f"Retrieved {len(current_orders)} orders from page {page}")
                
                # Log details about first order for debugging
                if current_orders and page == 0:
                    sample_order = current_orders[0]
                    logging.debug(f"Sample order fields: {list(sample_order.keys())}")
                    logging.debug(f"Sample order values: {sample_order}")
                    logging.debug(f"Current orders: {current_orders}")
                
                all_orders.extend(current_orders)
                
                # If we got less than page_size orders, we've reached the end
                if len(current_orders) < page_size:
                    logging.info(f"Reached last page of orders at page {page}")
                    break
                    
                page += 1
                
            except Exception as e:
                logging.error(f"Error in pagination loop at page {page}: {str(e)}")
                break
        
        logging.info(f"Successfully fetched total of {len(all_orders)} orders")
        
        # Return orders in the format expected by map_order_data
        # Keep original Groww response for reference
        response = {
            'data': all_orders,
            'order_list': all_orders,  # Include this for backward compatibility
            'raw_response': orders if orders else {}
        }
        logging.debug(f"Final response structure: {list(response.keys())}")
        return response
        
    except Exception as e:
        logging.error(f"Error fetching order book: {e}")
        logging.exception("Full stack trace:")
        # Return the same structure but with empty data
        return {
            'data': [],
            'order_list': [],
            'raw_response': {}
        }

def get_trade_book(auth):
    """
    Get list of trades for the user
    
    Args:
        auth (str): Authentication token
    
    Returns:
        dict: Trade book data
    """
    try:
        groww = init_groww_client(auth)
        trades = groww.get_trades()
        return trades
    except Exception as e:
        logging.error(f"Error fetching trade book: {e}")
        return []

def get_positions(auth):
    """
    Get current positions for the user
    
    Args:
        auth (str): Authentication token
    
    Returns:
        dict: Positions data
    """
    try:
        groww = init_groww_client(auth)
        positions = groww.get_positions()
        return positions
    except Exception as e:
        logging.error(f"Error fetching positions: {e}")
        return []

def get_holdings(auth):
    """
    Get holdings for the user
    
    Args:
        auth (str): Authentication token
    
    Returns:
        dict: Holdings data
    """
    try:
        groww = init_groww_client(auth)
        holdings = groww.get_holdings()
        return holdings
    except Exception as e:
        logging.error(f"Error fetching holdings: {e}")
        return []

def get_open_position(tradingsymbol, exchange, product, auth):
    """
    Get open position for a specific symbol
    
    Args:
        tradingsymbol (str): Trading symbol
        exchange (str): Exchange
        product (str): Product type
        auth (str): Authentication token
    
    Returns:
        str: Net quantity
    """
    # Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    positions_data = get_positions(auth)
    net_qty = '0'
    
    # Check if we received positions data in expected format
    if positions_data and isinstance(positions_data, list):
        for position in positions_data:
            if (position.get('trading_symbol') == tradingsymbol and 
                position.get('exchange') == map_exchange_type(exchange) and 
                position.get('product') == product):
                net_qty = str(position.get('net_quantity', '0'))
                break  # Found the position
    
    return net_qty

def place_order_api(data, auth):
    """
    Place an order with Groww
    
    Args:
        data (dict): Order data in OpenAlgo format
        auth (str): Authentication token
    
    Returns:
        tuple: (response object, response data, order id)
    """
    try:
        # Initialize Groww client
        groww = init_groww_client(auth)
        
        # Map parameters to Groww SDK format
        trading_symbol = data.get('symbol')
        quantity = int(data.get('quantity'))
        product = map_product_type(data.get('product', 'CNC'))
        exchange = map_exchange_type(data.get('exchange', 'NSE'))
        segment = map_segment_type(data.get('exchange', 'NSE'))
        order_type = map_order_type(data.get('pricetype', 'MARKET'))
        transaction_type = map_transaction_type(data.get('action', 'BUY'))
        validity = map_validity(data.get('validity', 'DAY'))
        
        # Optional parameters
        price = float(data.get('price', 0)) if data.get('pricetype', '').upper() == 'LIMIT' else None
        trigger_price = float(data.get('trigger_price', 0)) if data.get('pricetype', '').upper() in ['SL', 'SL-M'] else None
        
        # Generate a valid Groww order reference ID (8-20 alphanumeric with at most two hyphens)
        raw_id = data.get('order_reference_id', '')
        if not raw_id:
            # Create a reference ID based on timestamp and a partial UUID
            timestamp = datetime.now().strftime('%Y%m%d')
            uuid_part = str(uuid.uuid4()).replace('-', '')[:8]
            raw_id = f"{timestamp}-{uuid_part}"
        
        # Ensure the ID meets Groww's requirements
        # 1. Must be 8-20 characters
        # 2. Must be alphanumeric with at most two hyphens
        raw_id = re.sub(r'[^a-zA-Z0-9-]', '', raw_id)  # Remove non-alphanumeric/non-hyphen chars
        hyphen_count = raw_id.count('-')
        if hyphen_count > 2:
            # Remove excess hyphens, keeping the first two
            positions = [pos for pos, char in enumerate(raw_id) if char == '-']
            for pos in positions[2:]:
                raw_id = raw_id[:pos] + 'X' + raw_id[pos+1:]  # Replace excess hyphens with 'X'
            raw_id = raw_id.replace('X', '')  # Remove the placeholder
            
        # Ensure length is between 8-20 characters
        if len(raw_id) < 8:
            raw_id = raw_id.ljust(8, '0')  # Pad with zeros if too short
        if len(raw_id) > 20:
            raw_id = raw_id[:20]  # Truncate if too long
            
        order_reference_id = raw_id
        
        print(f"Placing {transaction_type} order for {quantity} of {trading_symbol} at {price if price else 'MARKET'}")
        print(f"SDK Parameters: exchange={exchange}, segment={segment}, product={product}, order_type={order_type}")
        print(f"Using order reference ID: {order_reference_id}")
        
        # Place order using SDK
        response = groww.place_order(
            trading_symbol=trading_symbol,
            quantity=quantity,
            validity=validity,
            exchange=exchange,
            segment=segment,
            product=product,
            order_type=order_type,
            transaction_type=transaction_type,
            price=price,
            trigger_price=trigger_price,
            order_reference_id=order_reference_id
        )
        
        print("Groww Order Response:", response)
        
        # Create a response object to maintain compatibility with existing code
        class ResponseObject:
            def __init__(self, status_code):
                self.status = status_code
        
        res = ResponseObject(200)
        
        # Extract order ID and status
        orderid = response.get('groww_order_id')
        order_status = response.get('order_status')
        
        print(f"Order ID: {orderid}, Status: {order_status}")
        
        return res, response, orderid
    
    except Exception as e:
        print(f"Error placing order: {e}")
        import traceback
        traceback.print_exc()
        class ResponseObject:
            def __init__(self, status_code):
                self.status = status_code
        
        res = ResponseObject(500)
        response_data = {"status": "error", "message": str(e)}
        return res, response_data, None


def direct_place_order(auth_token, symbol, quantity, price=None, order_type="MARKET", transaction_type="BUY", product="CNC", order_reference_id=None):
    """
    Directly place an order with Groww SDK (for testing)
    
    Args:
        auth_token (str): Authentication token
        symbol (str): Trading symbol
        quantity (int): Quantity to trade
        price (float, optional): Price for limit orders. Defaults to None.
        order_type (str, optional): Order type. Defaults to "MARKET".
        transaction_type (str, optional): BUY or SELL. Defaults to "BUY".
        product (str, optional): Product type. Defaults to "CNC".
        order_reference_id (str, optional): Custom reference ID. If None, a valid ID will be generated.
        
    Returns:
        dict: Order response
    """
    try:
        # Initialize Groww API client
        groww = init_groww_client(auth_token)
        
        # Default exchange and segment
        exchange = EXCHANGE_NSE
        segment = SEGMENT_CASH
        validity = VALIDITY_DAY
        
        # Generate a valid Groww order reference ID if not provided
        if not order_reference_id:
            timestamp = datetime.now().strftime('%Y%m%d')
            uuid_part = str(uuid.uuid4()).replace('-', '')[:8]
            order_reference_id = f"{timestamp}-{uuid_part}"
            
            # Ensure it meets Groww's requirements
            order_reference_id = re.sub(r'[^a-zA-Z0-9-]', '', order_reference_id)[:20]
            if len(order_reference_id) < 8:
                order_reference_id = order_reference_id.ljust(8, '0')
        
        print(f"Placing {transaction_type} order for {quantity} of {symbol} at {price if price else 'MARKET'}")
        print(f"SDK Parameters: exchange={exchange}, segment={segment}, product={product}, order_type={order_type}")
        print(f"Using order reference ID: {order_reference_id}")
        
        # Place order using SDK
        response = groww.place_order(
            trading_symbol=symbol,
            quantity=quantity,
            price=price,
            validity=validity,
            exchange=exchange,
            segment=segment,
            product=product,
            order_type=order_type,
            transaction_type=transaction_type,
            order_reference_id=order_reference_id
        )
        print(f"Direct order response: {response}")
        return response
    
    except Exception as e:
        print(f"Direct order error: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

def place_smartorder_api(data,auth):

    AUTH_TOKEN = auth
    BROKER_API_KEY = os.getenv('BROKER_API_KEY')
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


    # If both position_size and current_position are 0, do nothing
    if position_size == 0 and current_position == 0 and int(data['quantity'])!=0:
        action = data['action']
        quantity = data['quantity']
        #print(f"action : {action}")
        #print(f"Quantity : {quantity}")
        res, response, orderid = place_order_api(data,AUTH_TOKEN)
        #print(res)
        #print(response)
        
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
    if positions_response is None or not positions_response:
        return {"message": "No Open Positions Found"}, 200

    if positions_response:
        # Loop through each position to close
        for position in positions_response:
            # Skip if net quantity is zero
            if int(position['netQty']) == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if int(position['netQty']) > 0 else 'BUY'
            quantity = abs(int(position['netQty']))

            #print(f"Trading Symbol : {position['tradingsymbol']}")
            #print(f"Exchange : {position['exchange']}")

            #get openalgo symbol to send to placeorder function
            symbol = get_symbol(position['securityId'],map_exchange(position['exchangeSegment']))
            #print(f'The Symbol is {symbol}')

            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": map_exchange(position['exchangeSegment']),
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position['productType']),
                "quantity": str(quantity)
            }

            print(place_order_payload)

            # Place the order to close the position
            _, api_response, _ =   place_order_api(place_order_payload,AUTH_TOKEN)

            #print(api_response)
            
            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    """
    Cancel an order by its ID
    
    Args:
        orderid (str): Order ID to cancel
        auth (str): Authentication token
    
    Returns:
        tuple: (response object, response data)
    """
    try:
        # Initialize Groww client
        groww = init_groww_client(auth)
        
        # Cancel order using SDK
        response_data = groww.cancel_order(orderid)
        print("Cancel Order Response:", response_data)
        
        # Create a response object to maintain compatibility with existing code
        class ResponseObject:
            def __init__(self, status_code):
                self.status = status_code
        
        res = ResponseObject(200)
        return res, response_data
    except Exception as e:
        print(f"Error cancelling order: {e}")
        res = type('obj', (object,), {'status': 500})
        return res, {"status": "error", "message": str(e)}


def modify_order(data, auth):
    """
    Modify an existing order
    
    Args:
        data (dict): Order modification data
        auth (str): Authentication token
    
    Returns:
        tuple: (response object, response data, order id)
    """
    try:
        # Initialize Groww client
        groww = init_groww_client(auth)
        
        # Extract order ID and parameters to modify
        groww_order_id = data['orderid']  # Groww SDK expects 'groww_order_id'
        
        # Get the order type
        order_type = ORDER_TYPE_MARKET  # Default to MARKET
        if 'pricetype' in data:
            order_type = map_order_type(data['pricetype'])
        
        # Get the exchange and derive segment
        exchange = data.get('exchange', EXCHANGE_NSE)
        segment = map_segment_type(exchange)  # Map to CASH, FNO, etc.
        
        # Required parameters according to Groww SDK
        # quantity, order_type, segment, groww_order_id are required
        if 'quantity' not in data:
            raise ValueError("Quantity is required for order modification")
        
        quantity = int(data['quantity'])
        
        # Optional parameters
        price = None
        trigger_price = None
        
        if order_type == ORDER_TYPE_LIMIT and 'price' in data:
            price = float(data['price'])
        
        if order_type in [ORDER_TYPE_SL, ORDER_TYPE_SLM] and 'trigger_price' in data:
            trigger_price = float(data['trigger_price'])
        
        print(f"Modifying order {groww_order_id} with: quantity={quantity}, order_type={order_type}, segment={segment}")
        
        # Modify order using SDK - using the format from docs
        modify_params = {
            "quantity": quantity,
            "order_type": order_type,
            "segment": segment,
            "groww_order_id": groww_order_id
        }
        
        # Add optional parameters if available
        if price is not None:
            modify_params["price"] = price
        if trigger_price is not None:
            modify_params["trigger_price"] = trigger_price
        
        response_data = groww.modify_order(**modify_params)
        print("Modify Order Response:", response_data)
        
        # Create a response object to maintain compatibility with existing code
        class ResponseObject:
            def __init__(self, status_code):
                self.status = status_code
        
        res = ResponseObject(200)
        
        return res, response_data
    except Exception as e:
        print(f"Error modifying order: {e}")
        class ResponseObject:
            def __init__(self, status_code):
                self.status = status_code
        
        res = ResponseObject(500)
        response_data = {"status": "error", "message": str(e)}
        return res, response_data


def cancel_all_orders_api(data, auth):
    """
    Cancel all open orders
    
    Args:
        data (dict): Request data
        auth (str): Authentication token
    
    Returns:
        dict: Results of cancellation attempts
    """
    try:
        # Initialize Groww client
        groww = init_groww_client(auth)
        
        # Get all orders
        orders = get_order_book(auth)
        cancelled_orders = []
        failed_to_cancel = []
        
        # Check if we have open orders to cancel
        if orders and isinstance(orders, list) and len(orders) > 0:
            # Filter cancellable orders
            cancellable_statuses = ['OPEN', 'PENDING', 'TRIGGER_PENDING', 'PLACED', 'PENDING_ORDER',
                                    'NEW', 'ACKED', 'APPROVED', 'MODIFICATION_REQUESTED']
            
            for order in orders:
                order_status = order.get('order_status', order.get('status', ''))
                
                if order_status.upper() in [s.upper() for s in cancellable_statuses]:
                    try:
                        # Get order ID
                        orderid = None
                        for key in ['groww_order_id', 'orderId', 'order_id', 'id']:
                            if key in order:
                                orderid = order[key]
                                break
                        
                        if not orderid:
                            continue
                        
                        # Cancel order
                        response = groww.cancel_order(orderid)
                        
                        # Check response
                        if response and 'groww_order_id' in response:
                            cancelled_orders.append({
                                'order_id': orderid,
                                'message': 'Successfully cancelled'
                            })
                        else:
                            failed_to_cancel.append({
                                'order_id': orderid,
                                'message': 'Failed to cancel',
                                'details': response.get('message', 'Unknown error') if response else 'Unknown error'
                            })
                            
                    except Exception as e:
                        failed_to_cancel.append({
                            'order_id': orderid if orderid else 'Unknown',
                            'message': 'Failed to cancel',
                            'details': str(e)
                        })
        
        return {
            'cancelled_orders': cancelled_orders,
            'failed_to_cancel': failed_to_cancel
        }
        
    except Exception as e:
        print(f"Error cancelling all orders: {e}")
        return {
            'cancelled_orders': [],
            'failed_to_cancel': [{'order_id': 'all', 'message': 'Failed to cancel all orders', 'details': str(e)}]
        }
