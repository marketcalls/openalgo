import json
import os
import httpx
from database.auth_db import get_auth_token
from database.token_db import get_token , get_br_symbol, get_symbol, get_symbol_info
from broker.motilal.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data, map_exchange, reverse_map_exchange
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="GET", payload=''):
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_SECRET')

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Motilal Oswal Header Parameters as per documentation
    headers = {
      'Authorization': AUTH_TOKEN,
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'User-Agent': 'MOSL/V.1.1.0',
      'ApiKey': api_key,
      'ClientLocalIp': '1.2.3.4',
      'ClientPublicIp': '1.2.3.4',
      'MacAddress': '00:00:00:00:00:00',
      'SourceId': 'WEB',
      'vendorinfo': os.getenv('BROKER_VENDOR_CODE', ''),
      'osname': 'Windows 10',
      'osversion': '10.0.19041',
      'devicemodel': 'AHV',
      'manufacturer': 'DELL',
      'productname': 'OpenAlgo',
      'productversion': '1.0.0',
      'browsername': 'Chrome',
      'browserversion': '120.0'
    }

    # Use Production or UAT URL based on environment
    base_url = os.getenv('BROKER_API_URL', 'https://openapi.motilaloswal.com')
    url = f"{base_url}{endpoint}"

    if method == "GET":
        response = client.get(url, headers=headers)
    elif method == "POST":
        response = client.post(url, headers=headers, content=payload)
    else:
        response = client.request(method, url, headers=headers, content=payload)

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    # Handle empty response
    if not response.text:
        return {}

    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from {endpoint}: {response.text}")
        return {}

def get_order_book(auth):
    return get_api_response("/rest/book/v2/getorderbook", auth, method="POST")

def get_trade_book(auth):
    return get_api_response("/rest/book/v1/gettradebook", auth, method="POST")

def get_positions(auth):
    return get_api_response("/rest/book/v1/getposition", auth, method="POST")

def get_holdings(auth):
    """
    Fetch holdings/DP holdings from Motilal Oswal.
    Motilal API endpoint: /rest/report/v1/getdpholding (POST)
    Request body: {} (empty JSON for non-dealer accounts)
    """
    # Motilal requires POST with JSON body (empty for non-dealer accounts)
    payload = json.dumps({})

    logger.info("Fetching holdings from Motilal API...")
    response = get_api_response("/rest/report/v1/getdpholding", auth, method="POST", payload=payload)

    # Log the raw response for debugging
    logger.info(f"Motilal Holdings API raw response: status={response.get('status')}, message={response.get('message')}, data_length={len(response.get('data', [])) if response.get('data') else 0}")

    if response.get('status') == 'SUCCESS' and response.get('data'):
        logger.info(f"Successfully fetched {len(response.get('data', []))} holdings from Motilal")
    elif response.get('status') == 'SUCCESS' and not response.get('data'):
        logger.warning("Motilal API returned SUCCESS but data is null/empty. This might indicate no holdings or an API issue.")
    else:
        logger.error(f"Motilal Holdings API error: {response.get('message', 'Unknown error')}, errorcode: {response.get('errorcode', '')}")

    return response

def get_open_position(tradingsymbol, exchange, producttype,auth):
    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    # Map exchange from OpenAlgo format to Motilal format for comparison
    motilal_exchange = map_exchange(exchange)
    positions_data = get_positions(auth)

    logger.debug(f"{positions_data}")

    net_qty = '0'

    # Motilal returns status as "SUCCESS" string, not boolean
    if positions_data and positions_data.get('status') == 'SUCCESS' and positions_data.get('data'):
        for position in positions_data['data']:
            # Motilal uses 'symbol' not 'tradingsymbol' and 'productname' not 'producttype'
            # Since Motilal uses DELIVERY for both CNC and MIS in cash segment,
            # we need to match positions based on Motilal's product type
            # Compare with motilal_exchange since positions are in Motilal format
            if position.get('symbol') == tradingsymbol and position.get('exchange') == motilal_exchange and position.get('productname') == producttype:
                # Calculate net quantity from buy and sell quantities
                buyqty = int(position.get('buyquantity', 0))
                sellqty = int(position.get('sellquantity', 0))
                net_qty = str(buyqty - sellqty)
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data,auth):
    AUTH_TOKEN = auth
    BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
    data['apikey'] = BROKER_API_SECRET
    token = get_token(data['symbol'], data['exchange'])

    logger.info(f"Placing order for symbol: {data['symbol']}, exchange: {data['exchange']}, token: {token}")

    if not token:
        logger.error(f"Failed to get token for symbol: {data['symbol']}, exchange: {data['exchange']}")
        return None, {"status": "ERROR", "message": "Invalid symbol or token not found", "errorcode": "TOKEN_NOT_FOUND"}, None

    # Get symbol info to get lot size for quantity conversion
    symbol_info = get_symbol_info(data['symbol'], data['exchange'])
    lotsize = 1  # Default to 1 for cash segment
    if symbol_info and symbol_info.lotsize:
        lotsize = symbol_info.lotsize
        logger.debug(f"Lot size for {data['symbol']}: {lotsize}")

    newdata = transform_data(data, token)

    # Motilal Oswal Header Parameters
    headers = {
        'Authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'MOSL/V.1.1.0',
        'ApiKey': BROKER_API_SECRET,
        'ClientLocalIp': '1.2.3.4',
        'ClientPublicIp': '1.2.3.4',
        'MacAddress': '00:00:00:00:00:00',
        'SourceId': 'WEB',
        'vendorinfo': os.getenv('BROKER_VENDOR_CODE', ''),
        'osname': 'Windows 10',
        'osversion': '10.0.19041',
        'devicemodel': 'AHV',
        'manufacturer': 'DELL',
        'productname': 'OpenAlgo',
        'productversion': '1.0.0',
        'browsername': 'Chrome',
        'browserversion': '120.0'
    }

    # Motilal Oswal Place Order Payload
    # Build payload with only non-empty optional fields
    # Convert quantity to lots (Motilal requires quantity in lots, not shares)
    actual_quantity = int(newdata['quantity'])

    # Validate that quantity is a multiple of lot size
    if actual_quantity % lotsize != 0:
        error_msg = f"Invalid quantity: {actual_quantity} shares is not a multiple of lot size {lotsize}. " \
                    f"Valid quantities: {lotsize}, {lotsize*2}, {lotsize*3}, etc."
        logger.error(error_msg)
        return None, {
            "status": "ERROR",
            "message": error_msg,
            "errorcode": "INVALID_QUANTITY"
        }, None

    quantity_in_lots = actual_quantity // lotsize  # Integer division to get number of lots
    logger.info(f"Quantity conversion: {actual_quantity} shares / {lotsize} lot size = {quantity_in_lots} lots")

    payload_dict = {
        "exchange": newdata['exchange'],
        "symboltoken": int(newdata['symboltoken']),  # Must be integer
        "buyorsell": newdata['buyorsell'],
        "ordertype": newdata.get('ordertype', 'MARKET'),
        "producttype": newdata.get('producttype', 'NORMAL'),
        "orderduration": newdata.get('orderduration', 'DAY'),
        "price": float(newdata.get('price', '0')),
        "triggerprice": float(newdata.get('triggerprice', '0')),
        "quantityinlot": quantity_in_lots,  # Converted to lots
        "disclosedquantity": int(newdata.get('disclosedquantity', '0')),
        "amoorder": newdata.get('amoorder', 'N')
    }

    # Add optional fields only if they have values
    if newdata.get('algoid'):
        payload_dict['algoid'] = newdata['algoid']
    if newdata.get('goodtilldate'):
        payload_dict['goodtilldate'] = newdata['goodtilldate']
    if newdata.get('tag'):
        payload_dict['tag'] = newdata['tag']
    if newdata.get('participantcode'):
        payload_dict['participantcode'] = newdata['participantcode']

    payload = json.dumps(payload_dict)

    logger.debug(f"Motilal Place Order Request Payload: {payload_dict}")
    logger.debug(f"Payload JSON: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Use Production or UAT URL based on environment
    base_url = os.getenv('BROKER_API_URL', 'https://openapi.motilaloswal.com')

    # Make the request using the shared client
    response = client.post(
        f"{base_url}/rest/trans/v1/placeorder",
        headers=headers,
        content=payload
    )

    # Add status attribute to make response compatible with http.client response
    # as the rest of the codebase expects .status instead of .status_code
    response.status = response.status_code

    # Parse the JSON response
    response_data = response.json()

    # Log the full response for debugging
    logger.info(f"Motilal Place Order Response: {response_data}")
    logger.info(f"Response Status Code: {response.status_code}")

    # Motilal returns status as "SUCCESS" string, not boolean
    if response_data.get('status') == 'SUCCESS':
        orderid = response_data.get('uniqueorderid')
        logger.info(f"Order placed successfully. Order ID: {orderid}")
    else:
        orderid = None
        logger.error(f"Order placement failed. Status: {response_data.get('status')}, Message: {response_data.get('message')}, Error Code: {response_data.get('errorcode')}")

    return response, response_data, orderid

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


    # If both position_size and current_position are 0, do nothing
    if position_size == 0 and current_position == 0 and int(data['quantity'])!=0:
        action = data['action']
        quantity = data['quantity']
        #logger.info(f"action : {action}")
        #logger.info(f"Quantity : {quantity}")
        res, response, orderid = place_order_api(data,AUTH_TOKEN)
        #logger.info(f"{res}")
        #logger.info(f"{response}")
        
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
        res, response, orderid = place_order_api(order_data,auth)
        #logger.info(f"{res}")
        logger.info(f"{response}")
        logger.info(f"{orderid}")
        
        return res , response, orderid
    



def close_all_positions(current_api_key,auth):
    # Fetch the current open positions
    AUTH_TOKEN = auth

    positions_response = get_positions(AUTH_TOKEN)

    # Check if the positions data is null or empty - Motilal uses 'SUCCESS' string
    if positions_response.get('status') != 'SUCCESS' or positions_response.get('data') is None or not positions_response['data']:
        return {"message": "No Open Positions Found"}, 200

    if positions_response.get('status') == 'SUCCESS':
        # Loop through each position to close
        for position in positions_response['data']:
            # Calculate net quantity from buy and sell quantities
            buyqty = int(position.get('buyquantity', 0))
            sellqty = int(position.get('sellquantity', 0))
            net_qty = buyqty - sellqty

            # Skip if net quantity is zero
            if net_qty == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if net_qty > 0 else 'BUY'
            quantity = abs(net_qty)

            # Convert Motilal exchange to OpenAlgo exchange for symbol lookup
            motilal_exchange = position['exchange']
            openalgo_exchange = reverse_map_exchange(motilal_exchange)

            # Get openalgo symbol to send to placeorder function
            symbol = get_symbol(position['symboltoken'], openalgo_exchange)
            logger.info(f"The Symbol is {symbol}")

            if not symbol:
                logger.error(f"Symbol not found for token {position['symboltoken']} and exchange {openalgo_exchange}")
                continue

            # Prepare the order payload - Motilal uses 'productname' instead of 'producttype'
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": openalgo_exchange,  # Use OpenAlgo exchange format
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position['productname'], openalgo_exchange),
                "quantity": str(quantity)
            }

            logger.info(f"{place_order_payload}")

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
    api_key = os.getenv('BROKER_API_SECRET')

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Motilal Oswal Header Parameters
    headers = {
        'Authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'MOSL/V.1.1.0',
        'ApiKey': api_key,
        'ClientLocalIp': '1.2.3.4',
        'ClientPublicIp': '1.2.3.4',
        'MacAddress': '00:00:00:00:00:00',
        'SourceId': 'WEB',
        'vendorinfo': os.getenv('BROKER_VENDOR_CODE', ''),
        'osname': 'Windows 10',
        'osversion': '10.0.19041',
        'devicemodel': 'AHV',
        'manufacturer': 'DELL',
        'productname': 'OpenAlgo',
        'productversion': '1.0.0',
        'browsername': 'Chrome',
        'browserversion': '120.0'
    }

    # Prepare the payload - Motilal uses uniqueorderid
    payload = json.dumps({
        "uniqueorderid": orderid
    })

    # Use Production or UAT URL based on environment
    base_url = os.getenv('BROKER_API_URL', 'https://openapi.motilaloswal.com')

    # Make the request using the shared client
    response = client.post(
        f"{base_url}/rest/trans/v1/cancelorder",
        headers=headers,
        content=payload
    )

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    data = json.loads(response.text)

    # Motilal returns status as "SUCCESS" string
    if data.get("status") == "SUCCESS":
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Return an error response
        return {"status": "error", "message": data.get("message", "Failed to cancel order")}, response.status


def modify_order(data,auth):
    """
    Modifies an existing order for Motilal Oswal.

    Motilal API requires lastmodifiedtime and qtytradedtoday fields which must be fetched
    from the order book before modifying.

    Args:
        data: Order modification data containing orderid, symbol, exchange, quantity, price, etc.
        auth: Authentication token

    Returns:
        Tuple of (response_dict, status_code)
    """
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_SECRET')

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # First, fetch the order details from order book to get lastmodifiedtime and qtytradedtoday
    orderid = data.get("orderid")
    logger.info(f"Fetching order details for orderid: {orderid}")

    order_book_response = get_order_book(AUTH_TOKEN)

    # Check if order book was fetched successfully
    if order_book_response.get('status') != 'SUCCESS' or not order_book_response.get('data'):
        logger.error("Failed to fetch order book")
        return {"status": "error", "message": "Failed to fetch order book"}, 500

    # Find the order in the order book
    order_details = None
    for order in order_book_response.get('data', []):
        if order.get('uniqueorderid') == orderid:
            order_details = order
            break

    if not order_details:
        logger.error(f"Order with orderid {orderid} not found in order book")
        return {"status": "error", "message": f"Order {orderid} not found in order book"}, 404

    # Extract required fields from order book
    lastmodifiedtime = order_details.get('lastmodifiedtime', '')
    qtytradedtoday = int(order_details.get('qtytradedtoday', 0))  # Motilal uses 'qtytradedtoday'

    logger.info(f"Order details: lastmodifiedtime={lastmodifiedtime}, qtytradedtoday={qtytradedtoday}")

    token = get_token(data['symbol'], data['exchange'])

    # Get symbol info to get lot size for quantity conversion
    symbol_info = get_symbol_info(data['symbol'], data['exchange'])
    lotsize = 1  # Default to 1 for cash segment
    if symbol_info and symbol_info.lotsize:
        lotsize = symbol_info.lotsize
        logger.debug(f"Lot size for {data['symbol']}: {lotsize}")

    # Convert quantity to lots for modify order
    if 'quantity' in data:
        actual_quantity = int(data['quantity'])

        # Validate that quantity is a multiple of lot size
        if actual_quantity % lotsize != 0:
            error_msg = f"Invalid quantity for modify order: {actual_quantity} shares is not a multiple of lot size {lotsize}. " \
                        f"Valid quantities: {lotsize}, {lotsize*2}, {lotsize*3}, etc."
            logger.error(error_msg)
            return {
                "status": "error",
                "message": error_msg,
                "errorcode": "INVALID_QUANTITY"
            }, 400

        quantity_in_lots = actual_quantity // lotsize
        data['quantity'] = str(quantity_in_lots)  # Convert to lots
        logger.info(f"Modify quantity conversion: {actual_quantity} shares / {lotsize} lot size = {quantity_in_lots} lots")

    data['symbol'] = get_br_symbol(data['symbol'],data['exchange'])

    # Pass the order details to the transformation function
    transformed_data = transform_modify_order_data(data, token, lastmodifiedtime, qtytradedtoday)

    # Motilal Oswal Header Parameters
    headers = {
        'Authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'MOSL/V.1.1.0',
        'ApiKey': api_key,
        'ClientLocalIp': '1.2.3.4',
        'ClientPublicIp': '1.2.3.4',
        'MacAddress': '00:00:00:00:00:00',
        'SourceId': 'WEB',
        'vendorinfo': os.getenv('BROKER_VENDOR_CODE', ''),
        'osname': 'Windows 10',
        'osversion': '10.0.19041',
        'devicemodel': 'AHV',
        'manufacturer': 'DELL',
        'productname': 'OpenAlgo',
        'productversion': '1.0.0',
        'browsername': 'Chrome',
        'browserversion': '120.0'
    }
    payload = json.dumps(transformed_data)

    logger.info(f"Motilal Modify Order Request Payload: {transformed_data}")
    logger.debug(f"Payload JSON: {payload}")

    # Use Production or UAT URL based on environment
    base_url = os.getenv('BROKER_API_URL', 'https://openapi.motilaloswal.com')

    # Make the request using the shared client
    response = client.post(
        f"{base_url}/rest/trans/v2/modifyorder",
        headers=headers,
        content=payload
    )

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    response_data = json.loads(response.text)

    # Log the response for debugging
    logger.info(f"Motilal Modify Order Response: {response_data}")
    logger.info(f"Response Status Code: {response.status_code}")

    # Motilal returns status as "SUCCESS" string
    if response_data.get("status") == "SUCCESS":
        return {"status": "success", "orderid": response_data.get("uniqueorderid")}, 200
    else:
        return {"status": "error", "message": response_data.get("message", "Failed to modify order")}, response.status


def cancel_all_orders_api(data,auth):
    # Get the order book

    AUTH_TOKEN = auth


    order_book_response = get_order_book(AUTH_TOKEN)
    #logger.info(f"{order_book_response}")
    # Motilal returns status as "SUCCESS" string
    if order_book_response.get('status') != 'SUCCESS':
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger pending' state
    # Motilal uses 'orderstatus' field and 'Confirm', 'Sent' statuses for open orders
    orders_to_cancel = [order for order in order_book_response.get('data', [])
                        if order.get('orderstatus', '').lower() in ['confirm', 'sent', 'open']]
    #logger.info(f"{orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        # Motilal uses uniqueorderid
        orderid = order['uniqueorderid']
        cancel_response, status_code = cancel_order(orderid,auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
