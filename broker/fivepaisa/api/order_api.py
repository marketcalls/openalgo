import json
import os
from typing import Dict, Any, Optional
import httpx
from utils.httpx_client import get_httpx_client
from database.auth_db import get_auth_token
from database.token_db import get_token, get_br_symbol, get_symbol, get_oa_symbol
from broker.fivepaisa.mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data
from broker.fivepaisa.mapping.transform_data import map_exchange, map_exchange_type, reverse_map_exchange

# Base URL for 5Paisa API
BASE_URL = "https://Openapi.5paisa.com"

# Retrieve the BROKER_API_KEY and BROKER_API_SECRET environment variables
broker_api_key = os.getenv('BROKER_API_KEY')
api_secret = os.getenv('BROKER_API_SECRET')
api_key, user_id, client_id = broker_api_key.split(':::')

json_data = {
    "head": {
        "key": api_key
    },
    "body": {
        "ClientCode": client_id
    }
}

def get_api_response(endpoint: str, auth: str, method: str = "GET", payload: str = '') -> Dict[str, Any]:
    """Generic function to make API calls to 5Paisa using shared httpx client
    
    Args:
        endpoint (str): API endpoint path
        auth (str): Authentication token
        method (str, optional): HTTP method. Defaults to "GET".
        payload (str, optional): Request payload. Defaults to ''.
        
    Returns:
        Dict[str, Any]: JSON response from the API
    """
    try:
        # Get the shared httpx client
        client = get_httpx_client()
        
        headers = {
            'Authorization': f'bearer {auth}',
            'Content-Type': 'application/json'
        }
        
        # Make request based on method
        if method.upper() == "GET":
            response = client.get(
                f"{BASE_URL}{endpoint}",
                headers=headers
            )
        else:  # POST
            response = client.post(
                f"{BASE_URL}{endpoint}",
                content=payload,  # Use content since payload is already JSON string
                headers=headers
            )
            
        response.raise_for_status()
        return response.json()
        
    except httpx.HTTPStatusError as e:
        print(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
        raise
    except httpx.RequestError as e:
        print(f"Request error occurred: {str(e)}")
        raise
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        raise

def get_order_book(auth: str) -> Dict[str, Any]:
    """Get order book for the client
    
    Args:
        auth (str): Authentication token
        
    Returns:
        Dict[str, Any]: Order book data
    """
    try:
        payload = json.dumps(json_data)
        return get_api_response("/VendorsAPI/Service1.svc/V3/OrderBook", auth, method="POST", payload=payload)
    except Exception as e:
        print(f"Error getting order book: {str(e)}")
        raise

def get_trade_book(auth: str) -> Dict[str, Any]:
    """Get trade book for the client
    
    Args:
        auth (str): Authentication token
        
    Returns:
        Dict[str, Any]: Trade book data
    """
    try:
        payload = json.dumps(json_data)
        return get_api_response("/VendorsAPI/Service1.svc/V1/TradeBook", auth, method="POST", payload=payload)
    except Exception as e:
        print(f"Error getting trade book: {str(e)}")
        raise

def get_positions(auth: str) -> Dict[str, Any]:
    """Get net positions for the client
    
    Args:
        auth (str): Authentication token
        
    Returns:
        Dict[str, Any]: Net positions data
    """
    try:
        payload = json.dumps(json_data)
        return get_api_response("/VendorsAPI/Service1.svc/V2/NetPositionNetWise", auth, method="POST", payload=payload)
    except Exception as e:
        print(f"Error getting positions: {str(e)}")
        raise

def get_holdings(auth: str) -> Dict[str, Any]:
    """Get holdings for the client
    
    Args:
        auth (str): Authentication token
        
    Returns:
        Dict[str, Any]: Holdings data
    """
    try:
        payload = json.dumps(json_data)
        return get_api_response("/VendorsAPI/Service1.svc/V3/Holding", auth, method="POST", payload=payload)
    except Exception as e:
        print(f"Error getting holdings: {str(e)}")
        raise

def get_open_position(tradingsymbol: str, exchange: str, Exch: str, ExchType: str, producttype: str, auth: str) -> Optional[Dict[str, Any]]:
    #Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    token = int(get_token(tradingsymbol, exchange))  # Convert token to integer
    tradingsymbol = get_br_symbol(tradingsymbol,exchange)
    positions_data = get_positions(auth)
    print("Token : ",token)
    print("Product Type : ",producttype)
    print(positions_data)



    net_qty = '0'

    if positions_data and positions_data.get('body'):
        for position in positions_data['body']['NetPositionDetail']:

            if position.get('ScripCode') == token and position.get('Exch') == Exch and position.get('ExchType') == ExchType and position.get('OrderFor') == producttype:
                net_qty = position.get('NetQty', '0')
                break  # Assuming you need the first match

    return net_qty

def place_order_api(data: Dict[str, Any], auth: str) -> Dict[str, Any]:
    AUTH_TOKEN = auth
    

    token = get_token(data['symbol'], data['exchange'])
    newdata = transform_data(data, token)  
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'bearer {AUTH_TOKEN}'
    }
    

    json_data = {
            "head": {
                "key": api_key
            },
            "body": newdata
        }

    payload = json.dumps(json_data)



    try:
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Make API request
        response = client.post(
            f"{BASE_URL}/VendorsAPI/Service1.svc/V1/PlaceOrderRequest",
            content=payload,
            headers=headers
        )
        response.raise_for_status()
        response_data = response.json()
        
        print(f"Order Response: {response_data}")
        
        if response_data['head']['statusDescription'] == "Success":
            orderid = response_data['body']['BrokerOrderID']
        else:
            orderid = None
            
        # Add status attribute to make it compatible with place_order.py
        response.status = response.status_code
            
        return response, response_data, orderid
        
    except Exception as e:
        print(f"Error placing order: {str(e)}")
        raise

def place_smartorder_api(data: Dict[str, Any], auth: str) -> Dict[str, Any]:

    AUTH_TOKEN = auth

    #If no API call is made in this function then res will return None
    res = None

    # Extract necessary info from data
    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")
    position_size = int(data.get("position_size", "0"))

    exch = map_exchange(exchange)
    exchtype = map_exchange_type(exchange)




    # Get current open position for the symbol
    current_position = int(get_open_position(symbol, exchange, exch, exchtype, map_product_type(product),AUTH_TOKEN))


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
        res, response, orderid = place_order_api(order_data,auth)
        #print(res)
        print(response)
        print(orderid)
        
        return res , response, orderid
    



def close_all_positions(current_api_key: str, auth: str) -> Dict[str, Any]:
    # Fetch the current open positions
    AUTH_TOKEN = auth

    positions_response = get_positions(AUTH_TOKEN)
    print(positions_response)
    # Check if the positions data is null or empty
    if positions_response['body']['NetPositionDetail'] is None or not positions_response['body']['NetPositionDetail']:
        return {"message": "No Open Positions Found"}, 200

    if positions_response['body']['NetPositionDetail']:
        # Loop through each position to close
        for position in positions_response['body']['NetPositionDetail']:
            # Skip if net quantity is zero
            if int(position['NetQty']) == 0:
                continue

            # Determine action based on net quantity
            action = 'SELL' if int(position['NetQty']) > 0 else 'BUY'
            quantity = abs(int(position['NetQty']))

            exchange = reverse_map_exchange(position['Exch'],position['ExchType'])
            #get openalgo symbol to send to placeorder function
    
            symbol = get_symbol(position['ScripCode'],exchange)

            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": exchange,
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position['OrderFor'],exchange),
                "quantity": str(quantity)
            }

            print(place_order_payload)

            # Place the order to close the position
            res, response, orderid =   place_order_api(place_order_payload,auth)

            # print(res)
            # print(response)
            # print(orderid)


            
            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid: str, auth: str) -> Dict[str, Any]:
    """Cancel an order using its order ID
    
    Args:
        orderid (str): Order ID to cancel
        auth (str): Authentication token
        
    Returns:
        Dict[str, Any]: Response with status and message
    """
    try:
        AUTH_TOKEN = auth

        # First get the order details from orderbook
        orderbook_data = get_order_book(AUTH_TOKEN)
        order_details = None
        
        # Find the order in orderbook
        for order in orderbook_data['body']['OrderBookDetail']:
            if order['ExchOrderID'] == orderid:
                order_details = order
                break
        
        if not order_details:
            return {"status": "error", "message": "Order not found"}, 404

        # Prepare the cancel order request
        cancel_data = {
            "head": {
                "key": api_key
            },
            "body": {
                "ClientCode": client_id,
                "OrdStatusReqList": [
                    {
                        "Exch": order_details['Exch'],
                        "ExchType": order_details['ExchType'],
                        "ScripCode": order_details['ScripCode'],
                        "RemoteOrderID": order_details['ExchOrderID']
                    }
                ]
            }
        }

        # Get the shared httpx client
        client = get_httpx_client()
        
        # Make API request
        headers = {
            'Authorization': f'bearer {AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        response = client.post(
            f"{BASE_URL}/VendorsAPI/Service1.svc/V1/CancelOrderRequest",
            json=cancel_data,
            headers=headers
        )
        response.raise_for_status()
        data = response.json()

        # Check the response
        if data['head']['statusDescription'] == "Success":
            return {"status": "success", "message": "Order cancelled successfully"}, response.status_code
        else:
            return {"status": "error", "message": data.get('body', {}).get('Message', 'Failed to cancel order')}, response.status_code
            
    except Exception as e:
        print(f"Error cancelling order: {str(e)}")
        raise


def modify_order(data: Dict[str, Any], auth: str) -> Dict[str, Any]:
    """Modify an existing order
    
    Args:
        data (Dict[str, Any]): Order modification data
        auth (str): Authentication token
        
    Returns:
        Dict[str, Any]: Response with status and order ID
    """
    try:
        AUTH_TOKEN = auth
        transformed_data = transform_modify_order_data(data)
        
        # Prepare request data
        json_data = {
            "head": {
                "key": api_key
            },
            "body": transformed_data
        }

        # Get the shared httpx client
        client = get_httpx_client()
        
        # Make API request
        headers = {
            'Authorization': f'bearer {AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        response = client.post(
            f"{BASE_URL}/VendorsAPI/Service1.svc/V1/ModifyOrderRequest",
            json=json_data,
            headers=headers
        )
        response.raise_for_status()
        data = response.json()
        
        print(f"Modify Order Response: {data}")

        if data['body']['Message'] == "Success" or data['body']['Message'] == "SUCCESS":
            return {"status": "success", "orderid": data["body"]["BrokerOrderID"]}, response.status_code
        else:
            return {"status": "error", "message": data.get('body', {}).get('Message', 'Failed to Modify order')}, response.status_code
            
    except Exception as e:
        print(f"Error modifying order: {str(e)}")
        raise



def cancel_all_orders_api(data: Dict[str, Any], auth: str) -> Dict[str, Any]:
    """Cancel all open orders
    
    Args:
        data (Dict[str, Any]): Additional data for cancellation
        auth (str): Authentication token
        
    Returns:
        Dict[str, Any]: Lists of successfully canceled and failed order IDs
    """
    try:
        AUTH_TOKEN = auth
        
        # Get the order book using shared client
        order_book_response = get_order_book(AUTH_TOKEN)
        
        if order_book_response['body']['OrderBookDetail'] is None:
            return [], []  # Return empty lists if no orders found

        # Filter orders that are in 'open' or 'trigger_pending' state
        orders_to_cancel = [
            order for order in order_book_response['body']['OrderBookDetail']
            if order['OrderStatus'] in ['Pending', 'Modified']
        ]
        
        canceled_orders = []
        failed_cancellations = []

        # Cancel each filtered order using shared client
        for order in orders_to_cancel:
            try:
                orderid = order['BrokerOrderId']
                cancel_response, status_code = cancel_order(orderid, auth)
                
                if status_code == 200:
                    canceled_orders.append(orderid)
                else:
                    failed_cancellations.append(orderid)
                    print(f"Failed to cancel order {orderid}: {cancel_response.get('message')}")
                    
            except Exception as e:
                print(f"Error cancelling order {order['BrokerOrderId']}: {str(e)}")
                failed_cancellations.append(order['BrokerOrderId'])
        
        return canceled_orders, failed_cancellations
        
    except Exception as e:
        print(f"Error in cancel_all_orders: {str(e)}")
        raise
