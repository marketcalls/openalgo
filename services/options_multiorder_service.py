"""
Options Multi-Order Service

Places multiple option legs with common underlying, resolving symbols based on offset.
BUY legs are executed first, then SELL legs for margin efficiency.
"""

import copy
from typing import Tuple, Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor as log_executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from services.option_symbol_service import get_option_symbol
from services.place_order_service import place_order
from services.telegram_alert_service import telegram_alert_service
from utils.logging import get_logger

logger = get_logger(__name__)


def emit_analyzer_error(request_data: Dict[str, Any], error_message: str) -> Dict[str, Any]:
    """Helper function to emit analyzer error events"""
    error_response = {
        'mode': 'analyze',
        'status': 'error',
        'message': error_message
    }

    analyzer_request = request_data.copy()
    if 'apikey' in analyzer_request:
        del analyzer_request['apikey']
    analyzer_request['api_type'] = 'optionsmultiorder'

    log_executor.submit(async_log_analyzer, analyzer_request, error_response, 'optionsmultiorder')

    socketio.start_background_task(
        socketio.emit,
        'analyzer_update',
        {
            'request': analyzer_request,
            'response': error_response
        }
    )

    return error_response


def resolve_and_place_leg(
    leg_data: Dict[str, Any],
    common_data: Dict[str, Any],
    api_key: str,
    leg_index: int,
    total_legs: int,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None,
    underlying_ltp: Optional[float] = None
) -> Dict[str, Any]:
    """
    Resolve option symbol and place order for a single leg.

    Args:
        leg_data: Leg-specific data (offset, option_type, action, quantity, etc.)
        common_data: Common data (underlying, exchange, expiry_date, strike_int, strategy)
        api_key: OpenAlgo API key
        leg_index: Index of this leg
        total_legs: Total number of legs
        auth_token: Direct broker auth token (optional)
        broker: Broker name (optional)
        underlying_ltp: Pre-fetched underlying LTP to avoid redundant quote requests

    Returns:
        Result dictionary with leg details and order status
    """
    try:
        # Step 1: Resolve option symbol
        # Use leg-specific expiry_date if provided, otherwise fall back to common expiry_date
        leg_expiry = leg_data.get('expiry_date') or common_data.get('expiry_date')

        success, symbol_response, status_code = get_option_symbol(
            underlying=common_data.get('underlying'),
            exchange=common_data.get('exchange'),
            expiry_date=leg_expiry,
            strike_int=common_data.get('strike_int'),
            offset=leg_data.get('offset'),
            option_type=leg_data.get('option_type'),
            api_key=api_key,
            underlying_ltp=underlying_ltp
        )

        if not success:
            return {
                'leg': leg_index + 1,
                'offset': leg_data.get('offset'),
                'option_type': leg_data.get('option_type', '').upper(),
                'action': leg_data.get('action', '').upper(),
                'status': 'error',
                'message': symbol_response.get('message', 'Failed to resolve option symbol')
            }

        resolved_symbol = symbol_response.get('symbol')
        resolved_exchange = symbol_response.get('exchange')
        underlying_ltp = symbol_response.get('underlying_ltp')

        # Step 2: Construct order data
        order_data = {
            'apikey': api_key,
            'strategy': common_data.get('strategy'),
            'exchange': resolved_exchange,
            'symbol': resolved_symbol,
            'action': leg_data.get('action'),
            'quantity': leg_data.get('quantity'),
            'pricetype': leg_data.get('pricetype', 'MARKET'),
            'product': leg_data.get('product', 'MIS'),
            'price': leg_data.get('price', 0.0),
            'trigger_price': leg_data.get('trigger_price', 0.0),
            'disclosed_quantity': leg_data.get('disclosed_quantity', 0)
        }

        # Step 3: Place the order
        success, order_response, status_code = place_order(
            order_data=order_data,
            api_key=api_key,
            auth_token=auth_token,
            broker=broker
        )

        if success:
            result = {
                'leg': leg_index + 1,
                'symbol': resolved_symbol,
                'exchange': resolved_exchange,
                'offset': leg_data.get('offset'),
                'option_type': leg_data.get('option_type', '').upper(),
                'action': leg_data.get('action', '').upper(),
                'status': 'success',
                'orderid': order_response.get('orderid'),
                'mode': order_response.get('mode', 'live')
            }

            # Note: Toast notification is emitted once at the end of multiorder processing
            # to avoid multiple toast messages for each leg

            return result
        else:
            return {
                'leg': leg_index + 1,
                'symbol': resolved_symbol,
                'exchange': resolved_exchange,
                'offset': leg_data.get('offset'),
                'option_type': leg_data.get('option_type', '').upper(),
                'action': leg_data.get('action', '').upper(),
                'status': 'error',
                'message': order_response.get('message', 'Order placement failed')
            }

    except Exception as e:
        logger.error(f"Error processing leg {leg_index + 1}: {e}")
        return {
            'leg': leg_index + 1,
            'offset': leg_data.get('offset', 'Unknown'),
            'option_type': leg_data.get('option_type', '').upper(),
            'action': leg_data.get('action', '').upper(),
            'status': 'error',
            'message': f'Internal error: {str(e)}'
        }


def process_multiorder_with_auth(
    multiorder_data: Dict[str, Any],
    auth_token: str,
    broker: str,
    api_key: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Process options multi-order with provided authentication.
    BUY legs execute first, then SELL legs.
    """
    # Prepare common data
    common_data = {
        'underlying': multiorder_data.get('underlying'),
        'exchange': multiorder_data.get('exchange'),
        'expiry_date': multiorder_data.get('expiry_date'),
        'strike_int': multiorder_data.get('strike_int'),
        'strategy': multiorder_data.get('strategy')
    }

    legs = multiorder_data.get('legs', [])
    total_legs = len(legs)

    # Separate BUY and SELL legs
    buy_legs = [(i, leg) for i, leg in enumerate(legs) if leg.get('action', '').upper() == 'BUY']
    sell_legs = [(i, leg) for i, leg in enumerate(legs) if leg.get('action', '').upper() == 'SELL']

    results = []
    underlying_ltp = None

    # Get underlying LTP from first symbol resolution
    if legs:
        first_leg = legs[0]
        # Use leg-specific expiry_date if provided, otherwise fall back to common expiry_date
        first_leg_expiry = first_leg.get('expiry_date') or common_data.get('expiry_date')
        success, symbol_response, _ = get_option_symbol(
            underlying=common_data.get('underlying'),
            exchange=common_data.get('exchange'),
            expiry_date=first_leg_expiry,
            strike_int=common_data.get('strike_int'),
            offset=first_leg.get('offset'),
            option_type=first_leg.get('option_type'),
            api_key=api_key
        )
        if success:
            underlying_ltp = symbol_response.get('underlying_ltp')

    # Process BUY legs first (in parallel)
    if buy_legs:
        with ThreadPoolExecutor(max_workers=10) as executor:
            buy_futures = []
            for orig_idx, leg in buy_legs:
                buy_futures.append(
                    executor.submit(
                        resolve_and_place_leg,
                        leg,
                        common_data,
                        api_key,
                        orig_idx,
                        total_legs,
                        auth_token,
                        broker,
                        underlying_ltp
                    )
                )

            for future in as_completed(buy_futures):
                result = future.result()
                if result:
                    results.append(result)

    # Then process SELL legs (in parallel)
    if sell_legs:
        with ThreadPoolExecutor(max_workers=10) as executor:
            sell_futures = []
            for orig_idx, leg in sell_legs:
                sell_futures.append(
                    executor.submit(
                        resolve_and_place_leg,
                        leg,
                        common_data,
                        api_key,
                        orig_idx,
                        total_legs,
                        auth_token,
                        broker,
                        underlying_ltp
                    )
                )

            for future in as_completed(sell_futures):
                result = future.result()
                if result:
                    results.append(result)

    # Sort results by leg number
    results.sort(key=lambda x: x.get('leg', 0))

    # Count successful and failed legs
    successful_legs = sum(1 for r in results if r.get('status') == 'success')
    failed_legs = len(results) - successful_legs

    # Emit single summary toast notification
    mode = 'analyze' if get_analyze_mode() else 'live'
    socketio.start_background_task(
        socketio.emit,
        'order_event',
        {
            'symbol': common_data.get('underlying'),
            'action': f"{common_data.get('strategy', 'Multi-Order')}",
            'orderid': f"{successful_legs}/{len(results)} legs",
            'exchange': common_data.get('exchange'),
            'price_type': 'MULTI',
            'product_type': 'OPTIONS',
            'mode': mode,
            'batch_order': True,
            'is_last_order': True,
            'multiorder_summary': True,
            'successful_legs': successful_legs,
            'failed_legs': failed_legs
        }
    )

    # Build response
    response_data = {
        'status': 'success',
        'underlying': common_data.get('underlying'),
        'underlying_ltp': underlying_ltp,
        'results': results
    }

    # Add mode if in analyze mode
    if get_analyze_mode():
        response_data['mode'] = 'analyze'

        # Log to analyzer
        analyzer_request = original_data.copy()
        if 'apikey' in analyzer_request:
            del analyzer_request['apikey']
        analyzer_request['api_type'] = 'optionsmultiorder'

        log_executor.submit(async_log_analyzer, analyzer_request, response_data, 'optionsmultiorder')

        socketio.start_background_task(
            socketio.emit,
            'analyzer_update',
            {
                'request': analyzer_request,
                'response': response_data
            }
        )
    else:
        # Log to order log
        request_log = original_data.copy()
        if 'apikey' in request_log:
            del request_log['apikey']
        log_executor.submit(async_log_order, 'optionsmultiorder', request_log, response_data)

    # Send Telegram alert
    telegram_alert_service.send_order_alert('optionsmultiorder', multiorder_data, response_data, api_key)

    return True, response_data, 200


def place_options_multiorder(
    multiorder_data: Dict[str, Any],
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Place multiple option legs with common underlying.
    BUY legs are executed first for margin efficiency.

    Args:
        multiorder_data: Multi-order data containing underlying, exchange, legs, etc.
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker auth token (for internal calls)
        broker: Broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(multiorder_data)
    if api_key:
        original_data['apikey'] = api_key
        multiorder_data['apikey'] = api_key

    # Validate legs exist
    legs = multiorder_data.get('legs', [])
    if not legs:
        error_msg = 'No legs provided in the request'
        if get_analyze_mode():
            return False, emit_analyzer_error(original_data, error_msg), 400
        return False, {'status': 'error', 'message': error_msg}, 400

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Check if order should be routed to Action Center
        from services.order_router_service import should_route_to_pending, queue_order

        if should_route_to_pending(api_key, 'optionsmultiorder'):
            return queue_order(api_key, original_data, 'optionsmultiorder')

        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {
                'status': 'error',
                'message': 'Invalid openalgo apikey'
            }
            return False, error_response, 403

        return process_multiorder_with_auth(multiorder_data, AUTH_TOKEN, broker_name, api_key, original_data)

    # Case 2: Direct internal call
    elif auth_token and broker:
        return process_multiorder_with_auth(multiorder_data, auth_token, broker, api_key or '', original_data)

    # Case 3: Invalid parameters
    else:
        error_response = {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }
        return False, error_response, 400
