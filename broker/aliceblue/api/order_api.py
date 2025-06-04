import json
import os
import urllib.parse
import logging
import httpx
from utils.httpx_client import get_httpx_client
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_oa_symbol
from broker.aliceblue.mapping.transform_data import transform_data , map_product_type, reverse_map_product_type, transform_modify_order_data
from utils.config import get_broker_api_key , get_broker_api_secret

# Set up logger
logger = logging.getLogger(__name__)


def get_api_response(endpoint, auth, method="GET", payload=None):
    """Make API requests to AliceBlue API using shared connection pooling."""
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        AUTH_TOKEN = auth
        url = f"https://ant.aliceblueonline.com{endpoint}"
        
        headers = {
            'Authorization': f'Bearer {get_broker_api_secret()} {AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        logger.debug(f"Making {method} request to AliceBlue API: {url}")
        
        if method.upper() == "GET":
            response = client.get(url, headers=headers)
        elif method.upper() == "POST":
            response = client.post(url, json=json.loads(payload) if isinstance(payload, str) and payload else payload, headers=headers)
        elif method.upper() == "PUT":
            response = client.put(url, json=json.loads(payload) if isinstance(payload, str) and payload else payload, headers=headers)
        elif method.upper() == "DELETE":
            response = client.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        
        response.raise_for_status()
        response_data = response.json()
        logger.debug(f"API response: {json.dumps(response_data, indent=2)}")
        return response_data
        
    except httpx.HTTPError as e:
        logger.error(f"HTTP error during API request: {str(e)}")
        return {"stat": "Not_Ok", "emsg": f"HTTP error: {str(e)}"}
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        return {"stat": "Not_Ok", "emsg": f"Invalid JSON response: {str(e)}"}
    except Exception as e:
        logger.error(f"Error during API request: {str(e)}")
        return {"stat": "Not_Ok", "emsg": f"General error: {str(e)}"}


def get_order_book(auth):

    return get_api_response("/rest/AliceBlueAPIService/api/placeOrder/fetchOrderBook",auth)

def get_trade_book(auth):

    return get_api_response("/rest/AliceBlueAPIService/api/placeOrder/fetchTradeBook",auth)

def get_positions(auth):
    payload = json.dumps({
    "ret": "NET"
    })
    
    return get_api_response("/rest/AliceBlueAPIService/api/positionAndHoldings/positionBook",auth,"POST",payload=payload)

def get_holdings(auth):
    return get_api_response("/rest/AliceBlueAPIService/api/positionAndHoldings/holdings",auth)

def get_open_position(tradingsymbol, exchange, product,auth):

    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    

    position_data = get_positions(auth)

    if isinstance(position_data, dict):
        if position_data['stat'] == 'Not_Ok' :
            # Handle the case where there is an error in the data
            # For example, you might want to display an error message to the user
            # or pass an empty list or dictionary to the template.
            print(f"Error fetching order data: {position_data['emsg']}")
            position_data = {}
    else:
        position_data = position_data

    net_qty = '0'
    #print(positions_data['data']['net'])

    if position_data :
        for position in position_data:
            if position.get('Tsym') == tradingsymbol and position.get('Exchange') == exchange and position.get('Pcode') == product:
                net_qty = position.get('Netqty', '0')
                print(f'Net Quantity {net_qty}')
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data, auth):
    """Place an order using the AliceBlue API with shared connection pooling."""
    try:
        # Get the shared httpx client
        client = get_httpx_client()
        
        AUTH_TOKEN = auth
        newdata = transform_data(data)
        
        # Prepare headers and payload
        headers = {
            'Authorization': f'Bearer {get_broker_api_secret()} {AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        payload = [newdata]
        logger.debug(f"Place order payload: {json.dumps(payload, indent=2)}")
        
        # Make the API request
        url = "https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/placeOrder/executePlaceOrder"
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        
        response_data = response.json()
        logger.debug(f"Place order response: {json.dumps(response_data, indent=2)}")
        
        # Process the response
        response_data = response_data[0]
        print(f"Place order response: {response_data}")
        if response_data['stat'] == 'Ok':
            orderid = response_data['NOrdNo']
        else:
            # Extract error message if present
            error_msg = response_data.get('emsg', 'No error message provided by API')
            logger.error(f"Order placement failed: {error_msg}")
            print(f"Order placement error: {error_msg}")
            orderid = None
        
        # Add status attribute to response object to match what PlaceOrder endpoint expects
        response.status = response.status_code
            
        return response, response_data, orderid
        
    except httpx.HTTPError as e:
        logger.error(f"HTTP error during place order: {str(e)}")
        response_data = {"stat": "Not_Ok", "emsg": f"HTTP error: {str(e)}"}
        # Create a simple object with status attribute set to 500
        response = type('', (), {'status': 500, 'status_code': 500})()
        return response, response_data, None
    except Exception as e:
        logger.error(f"Error during place order: {str(e)}")
        response_data = {"stat": "Not_Ok", "emsg": f"General error: {str(e)}"}
        # Create a simple object with status attribute set to 500
        response = type('', (), {'status': 500, 'status_code': 500})()
        return response, response_data, None

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


    # If both position_size and current_position are 0, do nothing
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

    if isinstance(positions_response, dict):
        if positions_response['stat'] == 'Not_Ok' :
            # Handle the case where there is an error in the data
            # For example, you might want to display an error message to the user
            # or pass an empty list or dictionary to the template.
            print(f"Error fetching order data: {positions_response['emsg']}")
            positions_response = {}
    else:
        positions_response = positions_response


    #print(positions_response)
    # Check if the positions data is null or empty
    if positions_response is None or not positions_response:
        return {"message": "No Open Positions Found"}, 200



    if positions_response:
        # Loop through each position to close
        for position in positions_response:
            # Skip if net quantity is zero
            if int(position['Netqty']) == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if int(position['Netqty']) > 0 else 'BUY'
            quantity = abs(int(position['Netqty']))

            #Get OA Symbol before sending to Place Order
            symbol = get_oa_symbol(position['Tsym'],position['Exchange'])
            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position['Exchange'],
                "pricetype": "MARKET",
                "product": position['Pcode'],
                "quantity": str(quantity)
            }

            print(place_order_payload)

            # Place the order to close the position
            _, api_response, _ =   place_order_api(place_order_payload,AUTH_TOKEN)

            print(api_response)
            
            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    """Cancel an order using the AliceBlue API with shared connection pooling."""
    try:
        # Get the shared httpx client
        client = get_httpx_client()
        
        AUTH_TOKEN = auth
        order_book_response = get_order_book(AUTH_TOKEN)
        
        # Find the order details
        Trading_symbol = ""
        Exchange = ""
        orders = order_book_response
        for order in orders:
            if order.get("Nstordno") == orderid:
                Trading_symbol = order.get("Trsym")
                Exchange = order.get("Exchange")
        
        # Prepare headers and payload
        headers = {
            'Authorization': f'Bearer {get_broker_api_secret()} {AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            "exch": Exchange,
            "nestOrderNumber": orderid,
            "trading_symbol": Trading_symbol
        }
        
        logger.debug(f"Cancel order payload: {json.dumps(payload, indent=2)}")
        
        # Make the API request
        url = "https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/placeOrder/cancelOrder"
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        
        response_data = response.json()
        logger.debug(f"Cancel order response: {json.dumps(response_data, indent=2)}")
        
        # Check if the request was successful
        if response_data.get("stat") == "Ok":
            # Return a success response
            return {"status": "success", "orderid": response_data["nestOrderNumber"]}, 200
        else:
            # Return an error response
            return {"status": "error", "message": response_data.get("emsg", "Failed to cancel order")}, response.status_code
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error during cancel order: {str(e)}")
        return {"status": "error", "message": f"HTTP error: {str(e)}"}, 500
    except Exception as e:
        logger.error(f"Error during cancel order: {str(e)}")
        return {"status": "error", "message": f"General error: {str(e)}"}, 500


def modify_order(data, auth):
    """Modify an order using the AliceBlue API with shared connection pooling."""
    try:
        # Get the shared httpx client
        client = get_httpx_client()
        
        AUTH_TOKEN = auth
        newdata = transform_modify_order_data(data)
        
        # Prepare headers
        headers = {
            'Authorization': f'Bearer {get_broker_api_secret()} {AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        logger.debug(f"Modify order payload: {json.dumps(newdata, indent=2)}")
        
        # Make the API request
        url = "https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/placeOrder/modifyOrder"
        response = client.post(url, json=newdata, headers=headers)
        response.raise_for_status()
        
        response_data = response.json()
        logger.debug(f"Modify order response: {json.dumps(response_data, indent=2)}")
        
        # Process the response
        if response_data.get("stat") == "Ok":
            return {"status": "success", "orderid": response_data["nestOrderNumber"]}, 200
        else:
            return {"status": "error", "message": response_data.get("emsg", "Failed to modify order")}, response.status_code
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error during modify order: {str(e)}")
        return {"status": "error", "message": f"HTTP error: {str(e)}"}, 500
    except Exception as e:
        logger.error(f"Error during modify order: {str(e)}")
        return {"status": "error", "message": f"General error: {str(e)}"}, 500
    

def cancel_all_orders_api(data,auth):

    AUTH_TOKEN = auth
    # Get the order book
    order_book_response = get_order_book(AUTH_TOKEN)
    #print(order_book_response)
    if isinstance(order_book_response, dict):
        if order_book_response['stat'] == 'Not_Ok':
            return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [order for order in order_book_response
                        if order['Status'] in ['open', 'trigger pending']]
    print(orders_to_cancel)
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order['Nstordno']
        cancel_response, status_code = cancel_order(orderid,AUTH_TOKEN)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)
    
    return canceled_orders, failed_cancellations
