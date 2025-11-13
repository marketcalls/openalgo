"""
Place Options Order Service

This service places option orders by:
1. Resolving the option symbol using offset from ATM
2. Placing the order in either live or analyze mode

Supports both live trading and sandbox (analyze) mode, just like place_order_service.
"""

import copy
from typing import Tuple, Dict, Any, Optional
from utils.logging import get_logger
from services.option_symbol_service import get_option_symbol
from services.place_order_service import place_order
from database.settings_db import get_analyze_mode

# Initialize logger
logger = get_logger(__name__)


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
            - strike_int: Strike interval
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
        strike_int = options_data.get('strike_int')
        offset = options_data.get('offset')
        option_type = options_data.get('option_type')

        # Validate required option parameters
        if not all([underlying, exchange, strike_int, offset, option_type]):
            return False, {
                'status': 'error',
                'message': 'Missing required option parameters: underlying, exchange, strike_int, offset, option_type'
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

        # Step 2: Construct regular order data with the resolved symbol
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
            'disclosed_quantity': options_data.get('disclosed_quantity', 0)
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
