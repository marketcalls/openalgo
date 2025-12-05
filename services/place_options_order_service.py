"""
Place Options Order Service

This service places option orders by:
1. Resolving the option symbol using offset from ATM
2. Placing the order in either live or analyze mode
3. Optionally splitting large orders into multiple smaller orders (if splitsize is specified)

Supports both live trading and sandbox (analyze) mode, just like place_order_service.
"""

import copy
import time
import os
from typing import Tuple, Dict, Any, Optional, List
from utils.logging import get_logger
from services.option_symbol_service import get_option_symbol
from services.place_order_service import place_order
from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from database.apilog_db import async_log_order, executor as log_executor
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from services.telegram_alert_service import telegram_alert_service

# Initialize logger
logger = get_logger(__name__)

# Maximum number of split orders allowed
MAX_SPLIT_ORDERS = 100

# Get rate limit from environment (default: 10 per second)
def get_order_rate_limit():
    """Parse ORDER_RATE_LIMIT and return delay in seconds between orders"""
    rate_limit_str = os.getenv('ORDER_RATE_LIMIT', '10 per second')
    try:
        rate = int(rate_limit_str.split()[0])
        return 1.0 / rate if rate > 0 else 0.1
    except (ValueError, IndexError):
        return 0.1  # Default 100ms delay


def place_single_split_order(
    order_data: Dict[str, Any],
    api_key: str,
    order_num: int,
    total_orders: int,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Dict[str, Any]:
    """
    Place a single split order and return result.

    Args:
        order_data: Order data with symbol, exchange, action, quantity, etc.
        api_key: OpenAlgo API key
        order_num: Order number in the sequence
        total_orders: Total number of orders
        auth_token: Direct broker auth token (optional)
        broker: Broker name (optional)

    Returns:
        Result dictionary with order status
    """
    try:
        # Pass emit_event=False to suppress per-order socket events
        # A summary event is emitted at the end of all split orders
        success, order_response, status_code = place_order(
            order_data=order_data,
            api_key=api_key,
            auth_token=auth_token,
            broker=broker,
            emit_event=False
        )

        if success:
            return {
                'order_num': order_num,
                'quantity': int(order_data['quantity']),
                'status': 'success',
                'orderid': order_response.get('orderid')
            }
        else:
            return {
                'order_num': order_num,
                'quantity': int(order_data['quantity']),
                'status': 'error',
                'message': order_response.get('message', 'Failed to place order')
            }
    except Exception as e:
        logger.error(f"Error placing split order {order_num}: {e}")
        return {
            'order_num': order_num,
            'quantity': int(order_data['quantity']),
            'status': 'error',
            'message': 'Failed to place order due to internal error'
        }


def place_options_order(
    options_data: Dict[str, Any],
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Place an options order by first resolving the symbol, then placing the order.
    Works in both live and analyze mode.

    Args:
        options_data: Options order data containing:
            - underlying: Underlying symbol
            - exchange: Exchange
            - expiry_date: Expiry date (optional if embedded in underlying)
            - strike_int: Strike interval (OPTIONAL - if not provided, uses actual strikes from database)
            - offset: Strike offset (ATM, ITM1-ITM50, OTM1-OTM50)
            - option_type: CE or PE
            - action: BUY or SELL
            - quantity: Order quantity
            - pricetype: MARKET, LIMIT, SL, SL-M
            - product: MIS or NRML
            - price: Limit price (if applicable)
            - trigger_price: Trigger price (if applicable)
            - disclosed_quantity: Disclosed quantity
            - strategy: Strategy name
            - apikey: API key
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    try:
        # Store original data for potential queuing
        original_data = copy.deepcopy(options_data)
        if api_key:
            original_data['apikey'] = api_key

        # Add API key to options data if provided (needed for validation and symbol resolution)
        if api_key:
            options_data['apikey'] = api_key

        # Check if order should be routed to Action Center (semi-auto mode)
        if api_key and not (auth_token and broker):
            from services.order_router_service import should_route_to_pending, queue_order
            if should_route_to_pending(api_key, 'optionsorder'):
                return queue_order(api_key, original_data, 'optionsorder')

        # Extract option-specific parameters
        underlying = options_data.get('underlying')
        exchange = options_data.get('exchange')
        expiry_date = options_data.get('expiry_date')
        strike_int = options_data.get('strike_int')  # Optional - if not provided, actual strikes from database will be used
        offset = options_data.get('offset')
        option_type = options_data.get('option_type')

        # Validate required option parameters (strike_int is now optional)
        if not all([underlying, exchange, offset, option_type]):
            return False, {
                'status': 'error',
                'message': 'Missing required option parameters: underlying, exchange, offset, option_type'
            }, 400

        # Log the option order request
        logger.info(
            f"Options order request: underlying={underlying}, exchange={exchange}, "
            f"expiry={expiry_date}, strike_int={strike_int}, offset={offset}, type={option_type}"
        )

        # Step 1: Get the option symbol using option_symbol_service
        # Pass api_key or use the one from options_data
        symbol_api_key = api_key or options_data.get('apikey')
        if not symbol_api_key:
            return False, {
                'status': 'error',
                'message': 'API key required for option symbol resolution'
            }, 400

        success, symbol_response, status_code = get_option_symbol(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_int=strike_int,
            offset=offset,
            option_type=option_type,
            api_key=symbol_api_key
        )

        if not success:
            # Option symbol not found or error occurred
            logger.error(f"Failed to get option symbol: {symbol_response.get('message')}")
            return False, symbol_response, status_code

        # Extract the resolved symbol and exchange
        resolved_symbol = symbol_response.get('symbol')
        resolved_exchange = symbol_response.get('exchange')
        underlying_ltp = symbol_response.get('underlying_ltp')

        if not resolved_symbol or not resolved_exchange:
            return False, {
                'status': 'error',
                'message': 'Failed to extract symbol from option_symbol response'
            }, 500

        logger.info(
            f"Resolved option symbol: {resolved_symbol} on {resolved_exchange}, "
            f"Underlying LTP: {underlying_ltp}"
        )

        # Check if split order is requested
        splitsize = options_data.get('splitsize', 0) or 0
        total_quantity = int(options_data.get('quantity', 0))

        # Step 2: Handle split orders if splitsize > 0
        if splitsize > 0:
            # Validate split parameters
            num_full_orders = total_quantity // splitsize
            remaining_qty = total_quantity % splitsize
            total_orders = num_full_orders + (1 if remaining_qty > 0 else 0)

            if total_orders > MAX_SPLIT_ORDERS:
                return False, {
                    'status': 'error',
                    'message': f'Total number of orders would exceed maximum limit of {MAX_SPLIT_ORDERS}'
                }, 400

            logger.info(
                f"Split order requested: total_qty={total_quantity}, splitsize={splitsize}, "
                f"orders={total_orders}"
            )

            # Base order data template - include underlying_ltp for execution reference
            base_order_data = {
                'apikey': options_data.get('apikey'),
                'strategy': options_data.get('strategy'),
                'exchange': resolved_exchange,
                'symbol': resolved_symbol,
                'action': options_data.get('action'),
                'pricetype': options_data.get('pricetype', 'MARKET'),
                'product': options_data.get('product', 'MIS'),
                'price': options_data.get('price', 0.0),
                'trigger_price': options_data.get('trigger_price', 0.0),
                'disclosed_quantity': options_data.get('disclosed_quantity', 0),
                'underlying_ltp': underlying_ltp  # Pass LTP for execution reference
            }

            # Process split orders sequentially with rate limiting
            results = []
            order_delay = get_order_rate_limit()

            # Place full-size orders
            for i in range(num_full_orders):
                if i > 0:
                    time.sleep(order_delay)  # Rate limit delay between orders
                order_data = copy.deepcopy(base_order_data)
                order_data['quantity'] = splitsize
                result = place_single_split_order(
                    order_data,
                    api_key,
                    i + 1,
                    total_orders,
                    auth_token,
                    broker
                )
                results.append(result)

            # Place remaining quantity order if any
            if remaining_qty > 0:
                if num_full_orders > 0:
                    time.sleep(order_delay)  # Rate limit delay
                order_data = copy.deepcopy(base_order_data)
                order_data['quantity'] = remaining_qty
                result = place_single_split_order(
                    order_data,
                    api_key,
                    total_orders,
                    total_orders,
                    auth_token,
                    broker
                )
                results.append(result)

            # Build split order response
            response_data = {
                'status': 'success',
                'symbol': resolved_symbol,
                'exchange': resolved_exchange,
                'underlying': underlying,
                'underlying_ltp': underlying_ltp,
                'offset': offset,
                'option_type': option_type.upper(),
                'total_quantity': total_quantity,
                'split_size': splitsize,
                'results': results
            }

            # Add mode if in analyze mode
            if get_analyze_mode():
                response_data['mode'] = 'analyze'

            # Emit toast notification for split orders
            mode = 'analyze' if get_analyze_mode() else 'live'
            successful_orders = sum(1 for r in results if r.get('status') == 'success')
            socketio.start_background_task(
                socketio.emit,
                'order_event',
                {
                    'symbol': resolved_symbol,
                    'action': options_data.get('action'),
                    'orderid': f"{successful_orders}/{len(results)} orders",
                    'exchange': resolved_exchange,
                    'price_type': options_data.get('pricetype', 'MARKET'),
                    'product_type': options_data.get('product', 'MIS'),
                    'mode': mode,
                    'batch_order': True,
                    'is_last_order': True
                }
            )

            # Log the split order
            request_log = original_data.copy()
            if 'apikey' in request_log:
                del request_log['apikey']

            if get_analyze_mode():
                request_log['api_type'] = 'optionsorder'
                log_executor.submit(async_log_analyzer, request_log, response_data, 'optionsorder')
                socketio.start_background_task(
                    socketio.emit,
                    'analyzer_update',
                    {
                        'request': request_log,
                        'response': response_data
                    }
                )
            else:
                log_executor.submit(async_log_order, 'optionsorder', request_log, response_data)

            # Send Telegram alert
            telegram_alert_service.send_order_alert('optionsorder', options_data, response_data, api_key)

            logger.info(f"Split options order completed: {successful_orders}/{len(results)} successful")
            return True, response_data, 200

        # Step 2 (non-split): Construct regular order data with the resolved symbol
        # Include underlying_ltp for execution reference
        order_data = {
            'apikey': options_data.get('apikey'),
            'strategy': options_data.get('strategy'),
            'exchange': resolved_exchange,  # Use resolved exchange (NFO/BFO)
            'symbol': resolved_symbol,  # Use resolved option symbol
            'action': options_data.get('action'),
            'quantity': options_data.get('quantity'),
            'pricetype': options_data.get('pricetype', 'MARKET'),
            'product': options_data.get('product', 'MIS'),
            'price': options_data.get('price', 0.0),
            'trigger_price': options_data.get('trigger_price', 0.0),
            'disclosed_quantity': options_data.get('disclosed_quantity', 0),
            'underlying_ltp': underlying_ltp  # Pass LTP for execution reference
        }

        # Step 3: Place the order using the standard place_order service
        # This automatically handles live vs analyze mode
        success, order_response, status_code = place_order(
            order_data=order_data,
            api_key=api_key,
            auth_token=auth_token,
            broker=broker
        )

        if success:
            # Enhance response with option details
            enhanced_response = {
                'status': 'success',
                'orderid': order_response.get('orderid'),
                'symbol': resolved_symbol,
                'exchange': resolved_exchange,
                'underlying': underlying,
                'underlying_ltp': underlying_ltp,
                'offset': offset,
                'option_type': option_type.upper()
            }

            # Add mode if present (analyze or live)
            if 'mode' in order_response:
                enhanced_response['mode'] = order_response['mode']

            logger.info(f"Options order placed successfully: {enhanced_response.get('orderid')}")
            return True, enhanced_response, status_code
        else:
            # Order placement failed, return the error
            logger.error(f"Failed to place options order: {order_response.get('message')}")
            return False, order_response, status_code

    except Exception as e:
        logger.exception(f"Error in place_options_order: {e}")
        return False, {
            'status': 'error',
            'message': f'An error occurred while processing options order: {str(e)}'
        }, 500
