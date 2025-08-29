import traceback
import copy
import requests
import json
import random
from datetime import datetime
from typing import Tuple, Dict, Any, Optional

from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor as log_executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer, AnalyzerLog, db_session
from extensions import socketio
from utils.logging import get_logger
from utils.config import get_host_server

# Initialize logger
logger = get_logger(__name__)

def generate_realistic_order_status(orderid: str) -> Dict[str, str]:
    """
    Generate realistic order status data for simulation
    
    Args:
        orderid: Order ID to generate status for
        
    Returns:
        Dictionary with realistic order status values
    """
    # Determine order status based on orderid hash for consistency
    order_hash = hash(orderid) % 100
    
    # Realistic status distribution
    if order_hash < 60:  # 60% completed
        order_status = 'COMPLETE'
        filled_qty_ratio = 1.0
    elif order_hash < 75:  # 15% pending
        order_status = 'PENDING'
        filled_qty_ratio = 0.0
    elif order_hash < 85:  # 10% partial fill
        order_status = 'PARTIAL'
        filled_qty_ratio = random.uniform(0.2, 0.8)
    elif order_hash < 92:  # 7% rejected
        order_status = 'REJECTED'
        filled_qty_ratio = 0.0
    elif order_hash < 97:  # 5% cancelled
        order_status = 'CANCELLED'
        filled_qty_ratio = 0.0
    else:  # 3% triggered (for stop orders)
        order_status = 'TRIGGERED'
        filled_qty_ratio = 0.0
    
    # Generate realistic timestamp (current time or recent past)
    if order_status in ['COMPLETE', 'REJECTED', 'CANCELLED']:
        # Completed orders have timestamps in past
        minutes_ago = random.randint(1, 120)
        timestamp = datetime.now()
        timestamp = timestamp.replace(second=random.randint(0, 59))
        formatted_time = timestamp.strftime('%d-%b-%Y %H:%M:%S')
    else:
        # Pending orders have recent timestamps
        timestamp = datetime.now()
        formatted_time = timestamp.strftime('%d-%b-%Y %H:%M:%S')
    
    return {
        'order_status': order_status,
        'filled_qty_ratio': filled_qty_ratio,
        'timestamp': formatted_time
    }

def calculate_realistic_average_price(price: float, pricetype: str, action: str) -> float:
    """
    Calculate realistic average execution price based on order type
    
    Args:
        price: Order price
        pricetype: Type of order (LIMIT, MARKET, etc.)
        action: BUY or SELL
        
    Returns:
        Realistic average execution price
    """
    if price == 0 or price is None:
        return 0.0
    
    # Market orders have more slippage
    if pricetype == 'MARKET':
        slippage = random.uniform(0.001, 0.005)  # 0.1% to 0.5% slippage
        if action == 'BUY':
            return price * (1 + slippage)
        else:
            return price * (1 - slippage)
    
    # Limit orders execute at or better than limit price
    elif pricetype == 'LIMIT':
        improvement = random.uniform(0, 0.002)  # 0% to 0.2% price improvement
        if action == 'BUY':
            return price * (1 - improvement)
        else:
            return price * (1 + improvement)
    
    # Stop orders have negative slippage
    elif pricetype in ['SL', 'SL-M', 'STOPLOSS']:
        slippage = random.uniform(0.001, 0.003)  # 0.1% to 0.3% slippage
        if action == 'BUY':
            return price * (1 + slippage)
        else:
            return price * (1 - slippage)
    
    # Default case
    else:
        variation = random.uniform(-0.002, 0.002)  # +/- 0.2% variation
        return price * (1 + variation)

def get_original_order_data(orderid: str) -> Dict[str, Any]:
    """
    Retrieve original order data from analyzer database using orderid
    
    Args:
        orderid: Order ID to search for
        
    Returns:
        Original order data dictionary or empty dict if not found
    """
    try:
        # Query analyzer database for the most recent placeorder entry with this orderid
        analyzer_log = db_session.query(AnalyzerLog).filter(
            AnalyzerLog.api_type == 'placeorder'
        ).order_by(AnalyzerLog.created_at.desc()).all()
        
        logger.info(f"[AnalyzerDB] Searching analyzer DB for orderid {orderid}, found {len(analyzer_log)} placeorder entries")
        
        for idx, log in enumerate(analyzer_log):
            try:
                response_data = json.loads(log.response_data) if isinstance(log.response_data, str) else log.response_data
                request_data = json.loads(log.request_data) if isinstance(log.request_data, str) else log.request_data
                
                # Debug: Log what we're comparing
                stored_orderid = response_data.get('data', {}).get('orderid') or response_data.get('data', {}).get('order_id')
                
                # Log first 5 entries for debugging
                if idx < 5:
                    logger.debug(f"[AnalyzerDB] Entry {idx+1}: stored orderid '{stored_orderid}', symbol: {request_data.get('symbol')}")
                
                # Check if this log entry contains our orderid (as string comparison)
                if (str(response_data.get('data', {}).get('orderid')) == str(orderid) or 
                    str(response_data.get('data', {}).get('order_id')) == str(orderid)):
                    
                    logger.info(f"[AnalyzerDB] Found original order data for orderid {orderid}: symbol={request_data.get('symbol')}, price={request_data.get('price')}")
                    return request_data
            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning(f"[AnalyzerDB] Error parsing analyzer log entry {idx}: {e}")
                continue
                
        logger.warning(f"[AnalyzerDB] No original order data found for orderid {orderid} in analyzer database after checking {len(analyzer_log)} entries")
        return {}
        
    except Exception as e:
        logger.error(f"[AnalyzerDB] Error retrieving original order data: {e}", exc_info=True)
        return {}
    finally:
        db_session.remove()

def emit_analyzer_error(request_data: Dict[str, Any], error_message: str) -> Dict[str, Any]:
    """
    Helper function to emit analyzer error events
    
    Args:
        request_data: Original request data
        error_message: Error message to emit
        
    Returns:
        Error response dictionary
    """
    error_response = {
        'mode': 'analyze',
        'status': 'error',
        'message': error_message
    }
    
    # Store complete request data without apikey
    analyzer_request = request_data.copy()
    if 'apikey' in analyzer_request:
        del analyzer_request['apikey']
    analyzer_request['api_type'] = 'orderstatus'
    
    # Log to analyzer database
    log_executor.submit(async_log_analyzer, analyzer_request, error_response, 'orderstatus')
    
    # Emit socket event
    socketio.emit('analyzer_update', {
        'request': analyzer_request,
        'response': error_response
    })
    
    return error_response

def get_order_status_with_auth(
    status_data: Dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get status of a specific order using provided auth token.
    
    Args:
        status_data: Status data containing orderid
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    request_data = copy.deepcopy(original_data)
    if 'apikey' in request_data:
        request_data.pop('apikey', None)
    
    # Log the mode and order details
    is_analyze_mode = get_analyze_mode()
    orderid = status_data.get('orderid')
    logger.info(f"[OrderStatus] Processing order status request - Mode: {'ANALYZE' if is_analyze_mode else 'LIVE'}, OrderID: {orderid}, Broker: {broker}")
    
    # In analyze mode, check if this is a simulated order from analyzer database first
    if is_analyze_mode and orderid:
        # Check if order exists in analyzer database (simulated orders)
        simulated_order_data = get_original_order_data(orderid)
        
        # If this is a simulated order (short ID like "25082900001"), return simulated response
        if simulated_order_data and len(str(orderid)) <= 12:  # Simulated orders have shorter IDs
            logger.info(f"[OrderStatus] Found simulated order in analyzer database for OrderID {orderid}")
            
            # Generate a simulated order status response
            symbol = simulated_order_data.get('symbol', 'UNKNOWN')
            exchange = simulated_order_data.get('exchange', 'NSE')
            action = simulated_order_data.get('action', 'BUY')
            product = simulated_order_data.get('product', 'MIS')
            quantity = simulated_order_data.get('quantity', '1')
            price = simulated_order_data.get('price', '0')
            pricetype = simulated_order_data.get('pricetype', 'LIMIT')
            trigger_price = simulated_order_data.get('trigger_price', '0')
            
            # Generate timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime('%d-%b-%Y %H:%M:%S')
            
            # Simulate order status (most simulated orders would be complete)
            order_status = 'COMPLETE'
            
            # Calculate average price (slight variation from order price)
            try:
                price_float = float(price)
                if price_float > 0 and order_status == 'COMPLETE':
                    import random
                    variation = random.uniform(-0.002, 0.002)  # +/- 0.2% variation
                    average_price = round(price_float * (1 + variation), 2)
                else:
                    average_price = 0.0
            except (ValueError, TypeError):
                average_price = 0.0
            
            response_data = {
                'mode': 'analyze',
                'status': 'success',
                'data': {
                    'action': action,
                    'exchange': exchange,
                    'order_status': order_status,
                    'orderid': orderid,
                    'price': str(price),
                    'pricetype': pricetype,
                    'product': product,
                    'quantity': str(quantity),
                    'filled_quantity': str(quantity) if order_status == 'COMPLETE' else '0',
                    'pending_quantity': '0' if order_status == 'COMPLETE' else str(quantity),
                    'symbol': symbol,
                    'timestamp': timestamp,
                    'trigger_price': str(trigger_price),
                    'average_price': average_price
                }
            }
            
            logger.info(f"[OrderStatus] Returning simulated order status for OrderID {orderid} - Symbol: {symbol}, Status: {order_status}")
            
            # Store complete request data without apikey
            analyzer_request = request_data.copy()
            analyzer_request['api_type'] = 'orderstatus'
            
            # Log to analyzer database
            log_executor.submit(async_log_analyzer, analyzer_request, response_data, 'orderstatus')
            
            # Emit socket event for toast notification
            socketio.emit('analyzer_update', {
                'request': analyzer_request,
                'response': response_data
            })
            
            return True, response_data, 200
    
    # For live mode or real orders in analyze mode, fetch from orderbook
    # Both analyze mode and live mode use the same logic - fetch from orderbook
    # This ensures consistent behavior and real data in both modes
    
    # Prepare orderbook request with apikey
    orderbook_request = {'apikey': status_data.get('apikey')}
    logger.debug(f"[OrderStatus] Preparing orderbook request for OrderID: {orderid}")
    
    # Make request to orderbook API using HOST_SERVER from config
    host_server = get_host_server()
    orderbook_url = f'{host_server}/api/v1/orderbook'
    logger.debug(f"[OrderStatus] Making orderbook API call to: {orderbook_url}")
    
    orderbook_response = requests.post(orderbook_url, json=orderbook_request)
    logger.debug(f"[OrderStatus] Orderbook API response status: {orderbook_response.status_code}")
    
    if orderbook_response.status_code != 200:
        logger.error(f"[OrderStatus] Failed to fetch orderbook - Status Code: {orderbook_response.status_code}, OrderID: {orderid}")
        error_response = {
            'status': 'error',
            'message': 'Failed to fetch orderbook'
        }
        if is_analyze_mode:
            error_response['mode'] = 'analyze'
            # Log to analyzer database
            log_executor.submit(async_log_analyzer, request_data, error_response, 'orderstatus')
            # Emit socket event
            socketio.emit('analyzer_update', {
                'request': request_data,
                'response': error_response
            })
        else:
            log_executor.submit(async_log_order, 'orderstatus', original_data, error_response)
        return False, error_response, orderbook_response.status_code

    orderbook_data = orderbook_response.json()
    logger.debug(f"[OrderStatus] Orderbook API response: status={orderbook_data.get('status')}")
    
    if orderbook_data.get('status') != 'success':
        logger.error(f"[OrderStatus] Orderbook API returned error - Message: {orderbook_data.get('message')}, OrderID: {orderid}")
        error_response = {
            'status': 'error',
            'message': orderbook_data.get('message', 'Error fetching orderbook')
        }
        if is_analyze_mode:
            error_response['mode'] = 'analyze'
            # Log to analyzer database
            log_executor.submit(async_log_analyzer, request_data, error_response, 'orderstatus')
            # Emit socket event
            socketio.emit('analyzer_update', {
                'request': request_data,
                'response': error_response
            })
        else:
            log_executor.submit(async_log_order, 'orderstatus', original_data, error_response)
        return False, error_response, 500

    # Find the specific order in the orderbook
    order_found = None
    orders_list = orderbook_data.get('data', {}).get('orders', [])
    logger.info(f"[OrderStatus] Searching for OrderID {orderid} in {len(orders_list)} orders from orderbook")
    
    for idx, order in enumerate(orders_list):
        current_orderid = str(order.get('orderid'))
        if idx < 5:  # Log first 5 order IDs for debugging
            logger.debug(f"[OrderStatus] Order {idx+1}: OrderID={current_orderid}, Symbol={order.get('symbol')}, Status={order.get('order_status')}")
        
        if current_orderid == str(orderid):
            order_found = order
            logger.info(f"[OrderStatus] Found matching order - Symbol: {order.get('symbol')}, Status: {order.get('order_status')}, Price: {order.get('price')}")
            break
    
    if not order_found:
        logger.warning(f"[OrderStatus] Order {orderid} not found in orderbook after searching {len(orders_list)} orders")
        error_response = {
            'status': 'error',
            'message': f'Order {status_data["orderid"]} not found'
        }
        if is_analyze_mode:
            error_response['mode'] = 'analyze'
            # Log to analyzer database
            log_executor.submit(async_log_analyzer, request_data, error_response, 'orderstatus')
            # Emit socket event
            socketio.emit('analyzer_update', {
                'request': request_data,
                'response': error_response
            })
        else:
            log_executor.submit(async_log_order, 'orderstatus', original_data, error_response)
        return False, error_response, 404

    # Fetch average_price from tradebook if order is executed
    average_price = 0.0
    order_status = order_found.get('order_status', '')
    
    logger.debug(f"[OrderStatus] Order status is '{order_status}', checking if tradebook lookup needed")
    
    if order_status in ['COMPLETE', 'PARTIAL', 'EXECUTED', 'FILLED']:
        logger.info(f"[OrderStatus] Order is executed ({order_status}), fetching average price from tradebook")
        try:
            # Make request to tradebook API to get executed price
            tradebook_url = f'{host_server}/api/v1/tradebook'
            logger.debug(f"[OrderStatus] Making tradebook API call to: {tradebook_url}")
            
            tradebook_response = requests.post(tradebook_url, json=orderbook_request)
            logger.debug(f"[OrderStatus] Tradebook API response status: {tradebook_response.status_code}")
            
            if tradebook_response.status_code == 200:
                tradebook_data = tradebook_response.json()
                logger.debug(f"[OrderStatus] Tradebook API response: status={tradebook_data.get('status')}")
                
                if tradebook_data.get('status') == 'success':
                    # Handle different tradebook response structures
                    trades_data = tradebook_data.get('data', [])
                    
                    # If data is a dict with 'trades' key, use that
                    if isinstance(trades_data, dict) and 'trades' in trades_data:
                        trades_list = trades_data['trades']
                        logger.debug(f"[OrderStatus] Tradebook data structure: dict with 'trades' key, {len(trades_list)} trades")
                    # If data is directly a list, use it
                    elif isinstance(trades_data, list):
                        trades_list = trades_data
                        logger.debug(f"[OrderStatus] Tradebook data structure: direct list, {len(trades_list)} trades")
                    else:
                        trades_list = []
                        logger.warning(f"[OrderStatus] Unexpected tradebook data structure: {type(trades_data)}")
                    
                    # Find matching trade by orderid and get executed price
                    logger.debug(f"[OrderStatus] Searching for OrderID {orderid} in {len(trades_list)} trades")
                    for trade_idx, trade in enumerate(trades_list):
                        trade_orderid = str(trade.get('orderid'))
                        if trade_idx < 3:  # Log first 3 trades for debugging
                            logger.debug(f"[OrderStatus] Trade {trade_idx+1}: OrderID={trade_orderid}, Symbol={trade.get('symbol')}")
                        
                        if trade_orderid == str(orderid):
                            # Try different field names for executed price
                            executed_price = (trade.get('fillprice') or 
                                            trade.get('averageprice') or 
                                            trade.get('average_price') or 
                                            trade.get('price') or 0.0)
                            average_price = float(executed_price)
                            logger.info(f"[OrderStatus] Found trade for OrderID {orderid}, average_price: {average_price}")
                            break
                    else:
                        logger.warning(f"[OrderStatus] No trade found for OrderID {orderid} in tradebook")
                else:
                    logger.warning(f"[OrderStatus] Tradebook API returned error: {tradebook_data.get('message')}")
            else:
                logger.warning(f"[OrderStatus] Tradebook API call failed with status: {tradebook_response.status_code}")
        except Exception as e:
            logger.error(f"[OrderStatus] Exception while fetching tradebook: {e}", exc_info=True)
            # Continue without average price if tradebook fetch fails
    else:
        logger.debug(f"[OrderStatus] Order status '{order_status}' does not require tradebook lookup")

    # Add average_price to the order data
    order_found['average_price'] = average_price
    logger.debug(f"[OrderStatus] Final average_price set to: {average_price}")

    # Prepare response data
    response_data = {
        'status': 'success',
        'data': order_found
    }
    
    # Add mode indicator for analyze mode
    if is_analyze_mode:
        response_data['mode'] = 'analyze'
        logger.info(f"[OrderStatus] ANALYZE mode - Preparing response for OrderID {orderid} with status: {order_found.get('order_status')}")
        
        # Store complete request data without apikey
        analyzer_request = request_data.copy()
        analyzer_request['api_type'] = 'orderstatus'
        
        # Log to analyzer database
        log_executor.submit(async_log_analyzer, analyzer_request, response_data, 'orderstatus')
        logger.debug(f"[OrderStatus] Logged to analyzer database")
        
        # Emit socket event for toast notification
        socketio.emit('analyzer_update', {
            'request': analyzer_request,
            'response': response_data
        })
        logger.debug(f"[OrderStatus] Emitted socket event for analyzer update")
    else:
        logger.info(f"[OrderStatus] LIVE mode - Preparing response for OrderID {orderid} with status: {order_found.get('order_status')}")
        log_executor.submit(async_log_order, 'orderstatus', request_data, response_data)
        logger.debug(f"[OrderStatus] Logged to order database")

    logger.info(f"[OrderStatus] Successfully processed order status for OrderID {orderid} - Status: {order_found.get('order_status')}, Symbol: {order_found.get('symbol')}, Average Price: {average_price}")
    return True, response_data, 200

def get_order_status(
    status_data: Dict[str, Any],
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get status of a specific order.
    Supports both API-based authentication and direct internal calls.
    
    Args:
        status_data: Status data containing orderid
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(status_data)
    if api_key:
        original_data['apikey'] = api_key
    
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Add API key to status data
        status_data['apikey'] = api_key
        
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {
                'status': 'error',
                'message': 'Invalid openalgo apikey'
            }
            if not get_analyze_mode():
                log_executor.submit(async_log_order, 'orderstatus', original_data, error_response)
            return False, error_response, 403
        
        return get_order_status_with_auth(status_data, AUTH_TOKEN, broker_name, original_data)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_order_status_with_auth(status_data, auth_token, broker, original_data)
    
    # Case 3: Invalid parameters
    else:
        error_response = {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }
        return False, error_response, 400
