import copy
from typing import Tuple, Dict, Any, Optional

from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor as log_executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from utils.logging import get_logger
from services.tradebook_service import get_tradebook

# Initialize logger
logger = get_logger(__name__)


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
    
    # In analyze mode, return hardcoded response for any order ID
    if is_analyze_mode and orderid:
        # Return hardcoded response for any order ID in analyzer mode
        logger.info(f"[OrderStatus] Returning hardcoded response for order ID {orderid} in analyzer mode")
        
        response_data = {
            'mode': 'analyze',
            'status': 'success',
            'data': {
                'action': 'BUY',
                'average_price': 100.00,
                'exchange': 'NSE',
                'order_status': 'complete',
                'orderid': str(orderid),  # Use the actual order ID from request
                'price': 100.00,
                'pricetype': 'MARKET',
                'product': 'MIS',
                'quantity': '1',
                'symbol': 'SBIN',
                'timestamp': '28-Aug-2025 09:59:10',
                'trigger_price': 99.75
            }
        }
        
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
    
    # Use orderbook_service to get order data
    from services.orderbook_service import get_orderbook
    
    logger.debug(f"[OrderStatus] Fetching orderbook for OrderID: {orderid}")
    
    success, orderbook_response, status_code = get_orderbook(
        auth_token=auth_token,
        broker=broker
    )
    
    logger.debug(f"[OrderStatus] Orderbook service response: success={success}, status_code={status_code}")
    
    if not success or orderbook_response.get('status') != 'success':
        logger.error(f"[OrderStatus] Failed to fetch orderbook - Message: {orderbook_response.get('message', 'Unknown error')}, OrderID: {orderid}")
        error_response = {
            'status': 'error',
            'message': orderbook_response.get('message', 'Failed to fetch orderbook')
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
        return False, error_response, status_code

    # Find the specific order in the orderbook
    order_found = None
    orderbook_data = orderbook_response.get('data', {})
    
    # Handle different orderbook response structures
    if isinstance(orderbook_data, dict) and 'orders' in orderbook_data:
        orders_list = orderbook_data.get('orders', [])
    elif isinstance(orderbook_data, list):
        orders_list = orderbook_data
    else:
        orders_list = []
    
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
    
    logger.info(f"[OrderStatus] Order status is '{order_status}', checking if tradebook lookup needed")
    
    # Only fetch average_price for complete orders
    # Order statuses can be: open, complete, rejected
    if order_status.lower() == 'complete':
        logger.info(f"[OrderStatus] Order is complete, fetching average price from tradebook")
        try:
            # Use tradebook_service to get trade data
            success, tradebook_response, status_code = get_tradebook(
                auth_token=auth_token,
                broker=broker
            )
            
            logger.debug(f"[OrderStatus] Tradebook service response: success={success}, status_code={status_code}")
            
            if success and tradebook_response.get('status') == 'success':
                # Get trades list from response
                trades_list = tradebook_response.get('data', [])
                logger.debug(f"[OrderStatus] Tradebook returned {len(trades_list)} trades")
                
                # Find matching trade by orderid and get average_price
                logger.info(f"[OrderStatus] Searching for OrderID {orderid} in {len(trades_list)} trades")
                for trade_idx, trade in enumerate(trades_list):
                    trade_orderid = str(trade.get('orderid'))
                    # Log all trades for better debugging
                    logger.debug(f"[OrderStatus] Trade {trade_idx+1}: OrderID={trade_orderid}, Symbol={trade.get('symbol')}, AvgPrice={trade.get('average_price')}")
                    
                    if trade_orderid == str(orderid):
                        # Extract average_price from trade data
                        avg_price_raw = trade.get('average_price', 0.0)
                        average_price = float(avg_price_raw) if avg_price_raw else 0.0
                        logger.info(f"[OrderStatus] Found trade for OrderID {orderid}, average_price: {average_price} (raw: {avg_price_raw})")
                        break
                else:
                    logger.warning(f"[OrderStatus] No trade found for OrderID {orderid} in tradebook. Available order IDs: {[str(t.get('orderid')) for t in trades_list[:5]]}")
            else:
                logger.warning(f"[OrderStatus] Tradebook service call failed: {tradebook_response.get('message', 'Unknown error')}")
        except Exception as e:
            logger.error(f"[OrderStatus] Exception while fetching tradebook: {e}", exc_info=True)
            # Continue without average price if tradebook fetch fails
    else:
        logger.info(f"[OrderStatus] Order status '{order_status}' is not complete (open/rejected/other) - skipping average_price fetch")

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
            # Skip logging for invalid API keys to prevent database flooding
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
