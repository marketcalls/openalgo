import httpx
import json
import os
import logging
from database.auth_db import get_auth_token
from database.token_db import get_token, get_br_symbol, get_oa_symbol
from ..mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data
from ..mapping.order_data import transform_tradebook_data, transform_holdings_data, map_trade_data

from utils.httpx_client import get_httpx_client

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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
        logger.debug(f"get_api_response - Using auth header: {auth_header}")
        
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
                logger.debug(f"get_api_response - Sending data: {data_str}")
            
            response = client.put(
                f"https://api.tradejini.com/v2{endpoint}",
                headers=headers,
                data=data_str if data else None
            )
            
        logger.debug(f"get_api_response - Response status: {response.status_code}")
        logger.debug(f"get_api_response - Response headers: {dict(response.headers)}")
        logger.debug(f"get_api_response - Response body: {response.text}")
        
        # Handle 404 differently since it's a common error
        if response.status_code == 404:
            logger.warning("get_api_response - API endpoint not found. Trying without /v2 prefix")
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
            
            logger.debug(f"get_api_response - Second attempt status: {response.status_code}")
            logger.debug(f"get_api_response - Second attempt body: {response.text}")
            
        response.raise_for_status()  # Raise exception for bad status codes
        return response.json()
        
    except Exception as e:
        logger.error(f"get_api_response - Exception occurred: {str(e)}")
        import traceback
        logger.error(f"get_api_response - Traceback: {traceback.format_exc()}")
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
        logger.debug(f"get_order_book - Raw response data: {response_data}")
        
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
                    logger.error(f"get_order_book - Missing field in order: {str(e)}")
                    logger.error(f"get_order_book - Order data: {order}")
                    continue
            
            return {
                'stat': 'Ok',
                'data': transformed_orders
            }
        else:
            logger.debug(f"get_order_book - API error: {response_data.get('d', {}).get('msg', 'Unknown error')}")
            return {
                'stat': 'Not_Ok',
                'data': {
                    'msg': response_data.get('d', {}).get('msg', 'Unknown error')
                }
            }
            
    except Exception as e:
        logger.error(f"get_order_book - Exception occurred: {str(e)}")
        import traceback
        logger.error(f"get_order_book - Traceback: {traceback.format_exc()}")
        raise

def get_trade_book(auth):
    """
    Get list of trades using Tradejini API.
    
    Args:
        auth (str): Authentication token
        
    Returns:
        dict: Trade book data in OpenAlgo format {'data': [...], 'status': 'success'}
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
        logger.info("get_trade_book - Making request to TradeJini API")
        response = client.get(
            "https://api.tradejini.com/v2/api/oms/trades",
            headers=headers,
            params={"symDetails": "true"}
        )
        
        response.raise_for_status()
        
        # Get raw response data
        response_data = response.json()
        logger.info(f"get_trade_book - Raw response type: {type(response_data)}")
        logger.info(f"get_trade_book - Raw response keys: {response_data.keys() if isinstance(response_data, dict) else 'not a dict'}")
        
        # Check response format
        if not isinstance(response_data, dict) or 's' not in response_data:
            logger.error(f"get_trade_book - Invalid API response format: {response_data}")
            return {
                'status': 'error',
                'data': [],
                'message': "Invalid API response format"
            }
            
        # Check response status
        if response_data['s'] != 'ok':
            error_msg = f"API error: {response_data.get('d', {}).get('msg', 'Unknown error')}"
            logger.error(f"get_trade_book - {error_msg}")
            return {
                'status': 'error',
                'data': [],
                'message': error_msg
            }
        
        # Get trades from response
        trades_data = response_data.get('d', [])
        logger.info(f"get_trade_book - Found {len(trades_data)} trades")
        
        # Transform trades directly to OpenAlgo format
        transformed_trades = []
        for trade in trades_data:
            try:
                # Get symbol details
                symbol = trade.get('sym', {})
                
                # Get OpenAlgo symbol
                openalgo_symbol = None
                try:
                    openalgo_symbol = get_oa_symbol(
                        symbol=symbol.get('id', ''),
                        exchange=symbol.get('exch', '')
                    )
                except Exception as e:
                    logger.warning(f"get_trade_book - Symbol lookup failed: {str(e)}")
                
                # Map product type
                product = trade.get('product', '').lower()
                if product == 'intraday':
                    product = 'MIS'
                elif product == 'delivery':
                    product = 'CNC'
                elif product == 'coverorder':
                    product = 'CO'
                elif product == 'bracketorder':
                    product = 'BO'
                else:
                    product = 'NRML'
                
                # Map side to action
                side = trade.get('side', '').lower()
                action = 'BUY' if side == 'buy' else 'SELL'
                
                # Create transformed trade - match OpenAlgo format exactly
                # Determine the symbol to use (OpenAlgo symbol if available)
                final_symbol = ""  
                if openalgo_symbol:
                    final_symbol = openalgo_symbol
                else:
                    # Fallback to exchange symbol if OpenAlgo symbol isn't available
                    final_symbol = symbol.get('sym', symbol.get('trdSym', ''))
                    
                transformed_trade = {
                    "action": action,
                    "average_price": float(trade.get('fillPrice', 0.0)),
                    "exchange": symbol.get('exch', '').upper(),
                    "orderid": str(trade.get('orderId', '')),
                    "product": product,
                    "quantity": int(trade.get('fillQty', 0)),
                    "symbol": final_symbol,  # Using OpenAlgo symbol here
                    "timestamp": trade.get('time', ''),
                    "trade_value": float(trade.get('fillValue', 0.0))
                }
                
                # Exchange order ID is removed as per requirements
                
                transformed_trades.append(transformed_trade)
                logger.debug(f"get_trade_book - Transformed trade: {transformed_trade['orderid']}")
                
            except KeyError as e:
                logger.error(f"get_trade_book - Missing field in trade: {str(e)}")
                logger.error(f"get_trade_book - Trade data: {trade}")
                continue
        
        # Return ONLY the array of trades - service layer will add the wrapper
        logger.info(f"get_trade_book - Returning {len(transformed_trades)} raw trades")
        return transformed_trades
        
    except Exception as e:
        error_msg = f"Error fetching trade book: {str(e)}"
        logger.error(error_msg)
        import traceback
        logger.error(f"get_trade_book - Traceback: {traceback.format_exc()}")
        # Return empty array - service layer will handle error formatting
        return []

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
        
        # Make API request directly - not using any helper functions
        response = client.get(
            "https://api.tradejini.com/v2/api/oms/positions",
            headers=headers,
            params={"symDetails": "true"},
            timeout=10
        )
        
        response.raise_for_status()
        response_data = response.json()
        
        # Log raw response at INFO level for better visibility
        logger.info(f"Raw positions response from TradeJini API: {json.dumps(response_data, indent=2)}")
        
        # Direct transformation without using external mapping functions
        positions_list = []
        
        if response_data.get('s') == 'ok':
            positions = response_data.get('d', [])
            logger.debug(f"Found {len(positions)} positions")
            
            for position in positions:
                try:
                    # Skip positions with zero quantity
                    net_qty = position.get('netQty', 0)
                    
                    # Get symbol info from the nested sym object
                    sym = position.get('sym', {})
                    exchange_symbol = sym.get('sym', '')
                    tradingsymbol = sym.get('trdSym', '')
                    exchange = sym.get('exch', '')
                    
                    # Get symbol ID and details from the position data
                    symbol_id = position.get('symId', '')
                    
                    # Log position data for debugging
                    logger.info(f"Position data: symId={symbol_id}, tradingsymbol={tradingsymbol}, exchange={exchange}")
                    
                    # Get OpenAlgo symbol - follow same approach as TradeBook implementation
                    openalgo_symbol = None
                    try:
                        # First try with the symbol ID from sym object
                        symid_from_object = sym.get('id', '')
                        if symid_from_object:
                            openalgo_symbol = get_oa_symbol(symid_from_object, exchange)
                            logger.info(f"Symbol lookup with sym.id: {symid_from_object} -> {openalgo_symbol}")
                        
                        # If not found and we have the position symId, try that
                        if not openalgo_symbol and symbol_id:
                            openalgo_symbol = get_oa_symbol(symbol_id, '')
                            logger.info(f"Symbol lookup with position.symId: {symbol_id} -> {openalgo_symbol}")
                            
                        # If still not found, try with exchange symbol
                        if not openalgo_symbol:
                            openalgo_symbol = get_oa_symbol(exchange_symbol, exchange)
                            logger.info(f"Symbol lookup with exchange symbol: {exchange_symbol} -> {openalgo_symbol}")
                            
                    except Exception as e:
                        logger.warning(f"Symbol lookup failed: {str(e)}")
                        openalgo_symbol = None
                    
                    # Determine the final symbol to use
                    final_symbol = ""
                    if openalgo_symbol:
                        final_symbol = openalgo_symbol
                        logger.info(f"Using OpenAlgo symbol: {final_symbol}")
                    else:
                        # Fallback to exchange symbol if OpenAlgo symbol isn't available
                        final_symbol = exchange_symbol
                        logger.info(f"Fallback to exchange symbol: {final_symbol}")
                    
                    # Map product type
                    product = position.get('product', '').lower()
                    if product == 'delivery':
                        mapped_product = 'CNC'
                    elif product == 'intraday':
                        mapped_product = 'MIS'
                    elif product == 'margin':
                        mapped_product = 'NRML'
                    else:
                        mapped_product = 'MIS'  # Default
                    
                    # Format the position data according to OpenAlgo format
                    # Removing tradingsymbol field as requested
                    transformed_position = {
                        'symbol': final_symbol,  # Use final symbol (OpenAlgo or fallback)
                        'exchange': exchange,
                        'product': mapped_product,
                        'quantity': net_qty,
                        'average_price': str(round(float(position.get('netAvgPrice', 0.0)), 2))
                    }
                    
                    logger.debug(f"Position transformed: {tradingsymbol} → {openalgo_symbol}")
                    
                    positions_list.append(transformed_position)
                    logger.debug(f"Transformed position: {transformed_position}")
                    
                except Exception as e:
                    logger.error(f"Error transforming position: {str(e)}", exc_info=True)
                    continue
            
            # Return in OpenAlgo format - same pattern as orderbook and tradebook
            return {
                "status": "success",
                "data": positions_list
            }
        else:
            error_msg = response_data.get('d', {}).get('message', 'Unknown error')
            logger.error(f"Failed to fetch positions: {error_msg}")
            return {
                "status": "error",
                "message": error_msg
            }
            
    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP error {e.response.status_code}: {e.response.text}"
        logger.error(error_msg)
        return {
            "status": "error",
            "message": error_msg
        }
        
    except httpx.RequestError as e:
        error_msg = f"Request failed: {str(e)}"
        logger.error(error_msg)
        return {
            "status": "error",
            "message": error_msg
        }
        
    except Exception as e:
        logger.error(f"Unexpected error in get_positions: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "message": "An unexpected error occurred while fetching positions"
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
        logger.debug("Fetching holdings from Tradejini API")
        # Make API request with symDetails=true to get symbol details
        response = get_api_response(
            '/api/oms/holdings',
            auth,
            method="GET",
            data={"symDetails": "true"}
        )
        
        logger.debug(f"API Response: {response}")
        
        # Get holdings data from response
        holdings_data = response.get('d', {}).get('holdings', [])
        logger.debug(f"Raw holdings data: {holdings_data}")
        
        if not isinstance(holdings_data, list):
            logger.error("Holdings data is not a list")
            return {"status": "error", "message": "Invalid holdings data format"}
            
        # Transform data to OpenAlgo format
        from ..mapping.order_data import transform_holdings_data
        transformed_data = transform_holdings_data(holdings_data)
        
        return transformed_data
        
    except Exception as e:
        logger.error(f"Error fetching holdings: {str(e)}")
        return {"status": "error", "message": str(e)}

def get_open_position(tradingsymbol, exchange, producttype, auth):
    """
    Get open position quantity for a specific symbol, exchange, and product type.
    
    Args:
        tradingsymbol (str): Trading symbol
        exchange (str): Exchange
        producttype (str): Product type (e.g., 'intraday', 'delivery')
        auth (str): Authentication token
        
    Returns:
        str: Net quantity of the position or '0' if not found
    """
    try:
        logger.debug(f"get_open_position - Looking for position: {tradingsymbol}, {exchange}, {producttype}")
        
        # Convert product type to TradeJini format if needed
        mapped_product = producttype
        if producttype in ['MIS', 'CNC', 'NRML']:
            # It's already in OpenAlgo format, map it to TradeJini
            mapped_product = map_product_type(producttype)
        logger.debug(f"get_open_position - Mapped product: {mapped_product}")
        
        # Get positions from TradeJini API
        positions_response = get_positions(auth)
        logger.debug(f"get_open_position - Positions response: {positions_response}")
        
        # Set default return value
        net_qty = '0'
        
        # Check if we have a valid response
        if not positions_response or not isinstance(positions_response, dict):
            logger.debug("get_open_position - No positions data available.")
            return net_qty
            
        # Check for error in the response
        if positions_response.get('status') == 'error':
            logger.error(f"get_open_position - Error in positions response: {positions_response.get('message', 'Unknown error')}")
            return net_qty
            
        # Get the positions list from the response
        positions = positions_response.get('data', [])
        logger.debug(f"get_open_position - Found {len(positions)} positions")
        
        # Look for the matching position
        br_symbol = get_br_symbol(tradingsymbol, exchange) or tradingsymbol
        logger.debug(f"get_open_position - Looking for broker symbol: {br_symbol}")
        
        for position in positions:
            # Get symbol details from position data
            position_symbol = position.get('sym', {}).get('sym')
            position_exch = position.get('sym', {}).get('exch')
            position_product = position.get('product')
            position_tsym = position.get('sym', {}).get('trdSym')
            
            logger.debug(f"get_open_position - Checking position: {position_symbol}, {position_exch}, {position_product}")
            
            # Try different matching approaches
            symbol_match = (
                (position_symbol and position_symbol.upper() == tradingsymbol.upper()) or
                (position_tsym and position_tsym.upper() == br_symbol.upper()) or
                (position.get('symId') and position.get('symId').upper() == tradingsymbol.upper())
            )
            
            # First try exact match with product type
            if symbol_match and position_exch == exchange and position_product == mapped_product:
                net_qty = str(position.get('netQty', '0'))
                logger.debug(f"get_open_position - Found exact matching position with net quantity: {net_qty}")
                break
                
        # If we didn't find a match with product type, try just symbol and exchange
        # This handles cases where product type might be different but still the same asset
        if net_qty == '0':
            logger.debug(f"get_open_position - No exact product match found, trying symbol+exchange only match")
            for position in positions:
                position_symbol = position.get('sym', {}).get('sym')
                position_exch = position.get('sym', {}).get('exch')
                position_tsym = position.get('sym', {}).get('trdSym')
                
                # Try different matching approaches without product restriction
                symbol_match = (
                    (position_symbol and position_symbol.upper() == tradingsymbol.upper()) or
                    (position_tsym and position_tsym.upper() == br_symbol.upper()) or
                    (position.get('symId') and position.get('symId').upper() == tradingsymbol.upper())
                )
                
                if symbol_match and position_exch == exchange:
                    net_qty = str(position.get('netQty', '0'))
                    logger.debug(f"get_open_position - Found symbol+exchange match with net quantity: {net_qty}")
                    break
                
        return net_qty
        
    except Exception as e:
        logger.error(f"get_open_position - Exception: {str(e)}")
        import traceback
        logger.error(f"get_open_position - Traceback: {traceback.format_exc()}")
        return '0'

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
        logger.debug(f"place_order_api - Input data: {data}")
        logger.debug(f"place_order_api - AUTH_TOKEN: {AUTH_TOKEN}")
        logger.debug(f"place_order_api - BROKER_API_KEY: {api_key}")
        
        # Get token and transform data
        token = get_token(data['symbol'], data['exchange'])
        transformed_data = transform_data(data, token)
        
        # Convert transformed data to x-www-form-urlencoded format
        payload = '&'.join([f'{k}={v}' for k, v in transformed_data.items()])
        logger.debug(f"place_order_api - Payload: {payload}")
        logger.debug(f"place_order_api - Input auth: {AUTH_TOKEN}")
        
        # Get API key from environment
        api_key = os.getenv('BROKER_API_SECRET')
        if not api_key:
            raise ValueError("Error: BROKER_API_SECRET not set")
            
        # Use the auth token directly
        auth_token = AUTH_TOKEN
        auth_header = f"{api_key}:{auth_token}"
        
        logger.debug(f"place_order_api - API Key: {api_key}")
        logger.debug(f"place_order_api - Auth Token: {auth_token}")
        logger.debug(f"place_order_api - Auth Header: {auth_header}")
        
        headers = {
            'Authorization': f'Bearer {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Make API request
        logger.debug(f"place_order_api - Making request to: https://api.tradejini.com/v2/oms/place-order")
        response = client.post(
            "https://api.tradejini.com/v2/oms/place-order",
            headers=headers,
            data=payload
        )
        
        # Log response details
        logger.debug(f"place_order_api - Response status: {response.status_code}")
        logger.debug(f"place_order_api - Response headers: {dict(response.headers)}")
        
        response.raise_for_status()
        response_data = response.json()
        logger.debug(f"place_order_api - Response data: {response_data}")
        
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
        logger.error(f"place_order_api - Exception occurred: {str(e)}")
        import traceback
        logger.error(f"place_order_api - Traceback: {traceback.format_exc()}")
        return None, {"status": "error", "message": f"Order placement failed: {str(e)}"}, None

def place_smartorder_api(data, auth):
    """
    Place a smart order using Tradejini API.
    
    The PlaceSmartOrder API function allows traders to build intelligent trading systems
    that can automatically place orders based on existing trade positions in the position book.
    
    Args:
        data (dict): Order data with position_size parameter
        auth (str): Authentication token
        
    Returns:
        tuple: (response, response_data, order_id)
    """
    AUTH_TOKEN = auth
    res = None
    
    try:
        # Extract necessary info from data
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        product = data.get("product", "MIS")
        
        # Target position size - this is the key parameter for SmartOrder
        position_size = int(data.get("position_size", "0"))
        
        logger.info(f"place_smartorder_api - Symbol: {symbol}, Exchange: {exchange}, Position Size: {position_size}")
        
        # Direct position detection from API
        positions_response = get_positions(AUTH_TOKEN)
        current_position = 0  # Default to 0 if not found
        
        if positions_response and isinstance(positions_response, dict) and positions_response.get('status') == 'success':
            positions = positions_response.get('data', [])
            logger.info(f"place_smartorder_api - Found {len(positions)} positions in total")
            
            # Find matching position for this symbol and exchange
            for pos in positions:
                sym_obj = pos.get('sym', {})
                pos_sym = sym_obj.get('sym')
                pos_exch = sym_obj.get('exch')
                pos_qty = pos.get('netQty')
                
                logger.debug(f"place_smartorder_api - Position: {pos_sym}, Exchange: {pos_exch}, NetQty: {pos_qty}")
                
                # Check if this position matches our symbol (ignoring product type)
                if pos_sym and pos_sym.upper() == symbol.upper() and pos_exch == exchange:
                    current_position = int(pos_qty or 0)
                    logger.info(f"place_smartorder_api - Found matching position: {symbol} with quantity {current_position}")
                    break
        else:
            logger.error(f"place_smartorder_api - Could not retrieve positions: {positions_response}")
        
        # Initialize action and quantity
        final_action = None
        final_quantity = 0
        
        # --- MAIN LOGIC IMPLEMENTATION ---
        
        # CASE 1: Position size is 0 - square off any existing position
        if position_size == 0:
            logger.info(f"place_smartorder_api - SQUAREOFF MODE - current position: {current_position}")
            
            if current_position > 0:
                # We have a LONG position, need to SELL to square off
                final_action = "SELL"
                final_quantity = current_position
                message = f"Squaring off LONG position of {final_quantity} units"
                
            elif current_position < 0:
                # We have a SHORT position, need to BUY to square off
                final_action = "BUY"
                final_quantity = abs(current_position)
                message = f"Squaring off SHORT position of {final_quantity} units"
                
            else:
                # No position to square off
                logger.info("place_smartorder_api - No position found to square off")
                return None, {"status": "success", "message": "No position to squareoff."}, None
            
        # Case 2: No current position - create new position
        elif current_position == 0:
            if position_size > 0:
                final_action = "BUY"
                final_quantity = position_size
                message = f"Opening new LONG position of {final_quantity} units"
                logger.info(f"place_smartorder_api - Creating new LONG position of {final_quantity} units")
                
            elif position_size < 0:
                final_action = "SELL"
                final_quantity = abs(position_size)
                message = f"Opening new SHORT position of {final_quantity} units"
                logger.info(f"place_smartorder_api - Creating new SHORT position of {final_quantity} units")
                
            else:  # position_size == 0 && current_position == 0
                logger.info("place_smartorder_api - No position to create (position_size=0)")
                return None, {"status": "success", "message": "No position to create or modify."}, None
        
        # Case 3: Adjusting existing position - position_size is the ABSOLUTE target position
        else:
            # ABSOLUTE position mode - position_size is the exact final position we want
            logger.info(f"place_smartorder_api - ABSOLUTE POSITION MODE: Target={position_size}, Current={current_position}")
            
            if position_size > current_position:
                final_action = "BUY"
                final_quantity = position_size - current_position
                message = f"Adjusting position to {position_size} (BUY {final_quantity} more units)"
                logger.info(f"place_smartorder_api - Will BUY {final_quantity} units to reach target")
                
            elif position_size < current_position:
                final_action = "SELL"
                final_quantity = current_position - position_size
                message = f"Adjusting position to {position_size} (SELL {final_quantity} units)"
                logger.info(f"place_smartorder_api - Will SELL {final_quantity} units to reach target")
                
            else:  # position_size == current_position
                logger.info("place_smartorder_api - Current position already matches target")
                return None, {"status": "success", "message": "Positions Already Matched. No Action needed."}, None
        
        # Safety check - if no action or zero quantity, don't proceed
        if final_action is None or final_quantity <= 0:
            logger.info("place_smartorder_api - No valid action determined")
            return None, {"status": "success", "message": "No valid action determined."}, None
        
        logger.info(f"place_smartorder_api - Will place order: {final_action} {final_quantity} {symbol}")
        
        # Prepare data for placing the order
        order_data = data.copy()
        order_data["action"] = final_action
        order_data["quantity"] = str(final_quantity)
        
        # Place the order
        res, response, orderid = place_order_api(order_data, auth)
        
        # Always return success response for smart orders to maintain compatibility
        # This follows the pattern established in your memory for Groww API fixes
        wrapped_response = {
            "status": "success",
            "message": message,
            "quantity": final_quantity
        }
        
        # Include order ID if available
        if orderid:
            wrapped_response["orderid"] = orderid
            
        logger.info(f"place_smartorder_api - Original response: {response}")
        logger.info(f"place_smartorder_api - Returning: {wrapped_response}")
        
        return res, wrapped_response, orderid
        
    except Exception as e:
        logger.error(f"place_smartorder_api - Exception occurred: {str(e)}")
        import traceback
        logger.error(f"place_smartorder_api - Traceback: {traceback.format_exc()}")
        return None, {"status": "error", "message": f"Smart order placement failed: {str(e)}"}, None

def close_all_positions(current_api_key, auth):
    """
    Close all open positions using Tradejini API.
    
    Args:
        current_api_key (str): Current API key
        auth (str): Authentication token
        
    Returns:
        dict: Response with status and message in OpenAlgo format
              {
                  'status': 'success' or 'error',
                  'message': 'Descriptive message'
              }
    """
    try:
        AUTH_TOKEN = auth
        
        # Get positions instead of order book
        positions_response = get_positions(auth)
        logger.debug(f"close_all_positions - Positions response: {positions_response}")
        
        if not positions_response or positions_response.get('status') != 'success' or not positions_response.get('data'):
            logger.debug("close_all_positions - No positions found")
            return {
                'status': 'success', 
                'message': 'No open positions found to close'
            }
        
        positions = positions_response.get('data', [])
        logger.debug(f"close_all_positions - Found {len(positions)} positions")
        
        success_count = 0
        failed_count = 0
        
        for position in positions:
            try:
                net_quantity = int(position.get('netqty', position.get('quantity', 0)))
                
                if net_quantity == 0:
                    logger.debug("close_all_positions - Skipping zero quantity position")
                    continue
                
                # Determine action based on position direction
                action = 'SELL' if net_quantity > 0 else 'BUY'
                quantity = abs(net_quantity)
                
                # Get symbol from tradingsymbol or token+exchange
                symbol = position.get('tradingsymbol') or position.get('symbol')
                exchange = position.get('exchange')
                
                if not symbol:
                    token = position.get('token')
                    exchange = position.get('exchange')
                    if token and exchange:
                        logger.debug(f"close_all_positions - Looking up symbol for token {token} and exchange {exchange}")
                        symbol = get_oa_symbol(token, exchange)
                    
                if not symbol:
                    logger.error(f"close_all_positions - Cannot determine symbol for position: {position}")
                    failed_count += 1
                    continue
                    
                logger.debug(f"close_all_positions - Closing position for {symbol} with {action} {quantity}")
                
                # Prepare order data for closing position
                order_data = {
                    "apikey": current_api_key,
                    "strategy": "Squareoff",
                    "symbol": symbol,
                    "action": action,
                    "exchange": exchange,
                    "pricetype": "MARKET",
                    "product": position.get('product', 'CNC'),  # Use position's product or default to CNC
                    "quantity": str(quantity)
                }
                
                logger.debug(f"close_all_positions - Placing order: {order_data}")
                res, response, orderid = place_order_api(order_data, auth)
                
                if response.get('status') == 'success' and orderid:
                    logger.info(f"close_all_positions - Successfully closed position for {symbol} with order {orderid}")
                    success_count += 1
                else:
                    error_msg = response.get('message', 'Unknown error')
                    logger.error(f"close_all_positions - Failed to close position for {symbol}: {error_msg}")
                    failed_count += 1
                    
            except Exception as e:
                error_msg = str(e)
                logger.error(f"close_all_positions - Error processing position {position}: {error_msg}")
                failed_count += 1
        
        # Prepare final response in OpenAlgo format
        if success_count > 0 or failed_count == 0:
            message = "All Open Positions SquaredOff" if success_count > 0 else "No positions to close"
            response_data = {
                'status': 'success',
                'message': message
            }
            return response_data, 200
        else:
            response_data = {
                'status': 'error',
                'message': f'Failed to close all positions. Success: {success_count}, Failed: {failed_count}'
            }
            return response_data, 400
        
    except Exception as e:
        error_msg = f"Failed to close positions: {str(e)}"
        logger.error(f"close_all_positions - {error_msg}")
        import traceback
        logger.error(f"close_all_positions - Traceback: {traceback.format_exc()}")
        response_data = {
            'status': 'error',
            'message': error_msg
        }
        return response_data, 500

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
        logger.debug(f"cancel_order - Received orderid: {orderid}")
        logger.debug(f"cancel_order - Received auth: {auth}")
        
        # Prepare query parameters
        params = {"orderId": orderid}
        logger.debug(f"cancel_order - Query parameters: {params}")
        
        # Make API request
        logger.debug(f"cancel_order - Making API request to /api/oms/cancel-order")
        response = get_api_response(
            "/api/oms/cancel-order",
            auth=auth,
            method="DELETE",
            params=params  # Using params instead of data
        )
        logger.debug(f"cancel_order - API response: {response}")
        
        # Handle response
        if response["s"] == "ok":
            logger.debug(f"cancel_order - Order cancelled successfully")
            return {
                "stat": "Ok",
                "data": {
                    "msg": "Order cancelled successfully",
                    "order_id": response["d"]["orderId"]
                }
            }, 200
        elif response["s"] == "no-data":
            error_msg = f"Order cancellation failed: {response["msg"]}"
            logger.error(f"cancel_order - {error_msg}")
            return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 400
        else:
            error_msg = f"Order cancellation failed: {response.get('msg', 'Unknown error')}"
            logger.error(f"cancel_order - {error_msg}")
            return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 400
            
    except Exception as e:
        error_msg = f"Exception in cancel_order: {str(e)}"
        logger.error(f"cancel_order - {error_msg}")
        import traceback
        logger.error(f"cancel_order - Traceback: {traceback.format_exc()}")
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
        logger.debug(f"cancel_all_orders_api - Getting order book")
        order_book_response = get_order_book(auth)
        logger.debug(f"cancel_all_orders_api - Order book response: {order_book_response}")
        
        if not order_book_response:
            logger.debug("cancel_all_orders_api - No orders found")
            return [], []

        canceled_orders = []
        failed_cancellations = []
        
        # Get the list of orders from the transformed response
        # Make sure to log the structure for debugging
        logger.debug(f"cancel_all_orders_api - Order book response structure: {type(order_book_response)}")
        
        if order_book_response.get('stat') == 'Ok':
            orders = []
            
            # Handle different response structures
            if isinstance(order_book_response.get('data', []), list):
                # Already a list of orders
                orders = order_book_response.get('data', [])
            elif isinstance(order_book_response.get('data', {}), dict):
                # Data might be a dict containing orders
                orders = [order_book_response.get('data', {})]
                
            logger.debug(f"cancel_all_orders_api - Found {len(orders)} orders")
            logger.debug(f"cancel_all_orders_api - First order example: {orders[0] if orders else 'No orders'}")
            
            for order in orders:
                # Get order data - could be directly in order or in order['data']
                order_data = order.get('data', order)
                
                # Extract order ID - could be 'order_id' or 'orderId'
                order_id = order_data.get('order_id', order_data.get('orderId', ''))
                
                # Extract status - could be direct or nested
                status = order_data.get('status', '')
                
                logger.debug(f"cancel_all_orders_api - Processing order: {order_id}, status: {status}")
                
                # Check if order status indicates it's open and can be canceled
                # Convert status to uppercase for case-insensitive comparison
                if status.upper() in ['OPEN', 'TRIGGER PENDING', 'MODIFIED', 'PENDING']:
                    logger.debug(f"cancel_all_orders_api - Cancelling order: {order_id}")
                    
                    try:
                        cancel_response, status_code = cancel_order(order_id, auth)
                        logger.debug(f"cancel_all_orders_api - Cancel response: {cancel_response}, status: {status_code}")
                        
                        # Check for success in response
                        if cancel_response and status_code in [200, 201, 202]:
                            if (isinstance(cancel_response, list) and cancel_response[0].get('stat') == 'Ok') or \
                               (isinstance(cancel_response, dict) and cancel_response.get('stat') == 'Ok'):
                                canceled_orders.append(order_id)
                                logger.info(f"cancel_all_orders_api - Successfully canceled order: {order_id}")
                            else:
                                error_msg = "Unknown error structure"
                                if isinstance(cancel_response, list) and len(cancel_response) > 0:
                                    error_msg = cancel_response[0].get('data', {}).get('msg', 'Unknown error')
                                elif isinstance(cancel_response, dict):
                                    error_msg = cancel_response.get('data', {}).get('msg', 'Unknown error')
                                
                                logger.error(f"cancel_all_orders_api - Failed to cancel order {order_id}: {error_msg}")
                                failed_cancellations.append({"orderId": order_id, "error": error_msg})
                        else:
                            logger.error(f"cancel_all_orders_api - Failed to cancel order {order_id}: Bad status code {status_code}")
                            failed_cancellations.append({"orderId": order_id, "error": f"Bad status code: {status_code}"})
                    except Exception as e:
                        logger.error(f"cancel_all_orders_api - Exception while cancelling order {order_id}: {str(e)}")
                        failed_cancellations.append({"orderId": order_id, "error": str(e)})
            
            message = f"Canceled {len(canceled_orders)} orders. Failed to cancel {len(failed_cancellations)} orders."
            logger.info(f"cancel_all_orders_api - {message}")
            
            return canceled_orders, failed_cancellations
        else:
            error_msg = f"Failed to get order book: {order_book_response.get('data', {}).get('msg', 'Unknown error')}"
            logger.error(f"cancel_all_orders_api - {error_msg}")
            return [], []
            
    except Exception as e:
        error_msg = f"Exception in cancel_all_orders_api: {str(e)}"
        logger.error(f"cancel_all_orders_api - {error_msg}")
        import traceback
        logger.error(f"cancel_all_orders_api - Traceback: {traceback.format_exc()}")
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
        logger.debug(f"modify_order - Received data: {data}")
        logger.debug(f"modify_order - Received auth: {auth}")
        
        # Get broker symbol token
        token = get_token(data["symbol"], data["exchange"])
        logger.debug(f"modify_order - Token lookup result: {token}")
        
        if not token:
            error_msg = "Symbol not found in token database"
            logger.error(f"modify_order - {error_msg}")
            return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 400
            
        # Transform data to Tradejini format
        try:
            transformed_data = transform_modify_order_data(data, token)
            logger.debug(f"modify_order - Transformed data: {transformed_data}")
        except ValueError as e:
            error_msg = str(e)
            logger.error(f"modify_order - {error_msg}")
            return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 400
        
        # Make API request
        logger.debug(f"modify_order - Making API request to /api/oms/modify-order")
        response = get_api_response(
            "/api/oms/modify-order",
            auth=auth,
            method="PUT",
            data=transformed_data
        )
        logger.debug(f"modify_order - API response: {response}")
        
        # Handle different response formats
        if response["s"] == "ok":
            logger.debug(f"modify_order - Order modified successfully")
            return {
                "stat": "Ok",
                "data": {
                    "msg": "Order modified successfully",
                    "order_id": response["d"]["orderId"]
                }
            }, 200
        elif response["s"] == "no-data":
            error_msg = f"Order modification failed: {response["msg"]}"
            logger.error(f"modify_order - {error_msg}")
            return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 400
        else:
            error_msg = f"Order modification failed: {response.get('msg', 'Unknown error')}"
            logger.error(f"modify_order - {error_msg}")
            return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 400
            
    except Exception as e:
        error_msg = f"Exception in modify_order: {str(e)}"
        logger.error(f"modify_order - {error_msg}")
        import traceback
        logger.error(f"modify_order - Traceback: {traceback.format_exc()}")
        return {"stat": "Not_Ok", "data": {"msg": error_msg}}, 500
