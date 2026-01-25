import copy
from typing import Tuple, Dict, Any, Optional
from database.auth_db import get_auth_token_broker
from database.token_db import get_symbol_info
from services.quotes_service import get_quotes
from services.margin_service import calculate_margin
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


def resolve_quantity(symbol: str, exchange: str, user_quantity: Optional[int]) -> Tuple[int, Optional[int]]:
    """
    Resolve the quantity to use for margin calculation based on exchange and user input.

    Args:
        symbol: Trading symbol
        exchange: Exchange (NSE, BSE, NFO, etc.)
        user_quantity: User-provided quantity (None if not provided)

    Returns:
        Tuple of (resolved_quantity, lot_size)
        - resolved_quantity: The quantity to use for calculation
        - lot_size: The lot size from database (None if not defined or equals 1)
    """
    # Priority 1: User explicitly provided quantity - always honor it
    if user_quantity is not None:
        # Fetch lot size for metadata (for ALL exchanges)
        symbol_info = get_symbol_info(symbol, exchange)
        lot_size = symbol_info.lotsize if (symbol_info and symbol_info.lotsize and symbol_info.lotsize > 1) else None
        return user_quantity, lot_size

    # Priority 2: Auto-fetch lot size from database (for ALL exchanges)
    symbol_info = get_symbol_info(symbol, exchange)
    if symbol_info and symbol_info.lotsize and symbol_info.lotsize > 1:
        # Use lot size as default quantity if defined and > 1
        logger.debug(f"Auto-fetched lot size for {exchange}:{symbol}: {symbol_info.lotsize}")
        return symbol_info.lotsize, symbol_info.lotsize

    # Priority 3: Default to 1 if no lot size or lot size = 1
    logger.debug(f"Using default quantity=1 for {exchange}:{symbol}")
    return 1, None


def calculate_scrip_margin_with_auth(
    scrip_data: Dict[str, Any],
    auth_token: str,
    feed_token: Optional[str],
    broker: str
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Calculate margin and leverage for a single symbol using provided auth tokens.

    Args:
        scrip_data: Scrip data containing symbol, exchange, product, quantity, etc.
        auth_token: Authentication token for the broker API
        feed_token: Feed token for market data (if required by broker)
        broker: Name of the broker

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    symbol = scrip_data.get('symbol')
    exchange = scrip_data.get('exchange')
    product = scrip_data.get('product')
    user_quantity = scrip_data.get('quantity')  # May be None
    action = scrip_data.get('action', 'BUY').upper()
    pricetype = scrip_data.get('pricetype', 'MARKET')
    price = scrip_data.get('price', '0')

    # Resolve quantity using smart logic
    quantity, lot_size = resolve_quantity(symbol, exchange, user_quantity)

    logger.info(f"Calculating margin for {exchange}:{symbol} - Quantity: {quantity}, Lot Size: {lot_size}")

    # Step 1: Fetch LTP via get_quotes
    ltp = None
    ltp_error = None
    try:
        success, quotes_response, status_code = get_quotes(
            symbol=symbol,
            exchange=exchange,
            auth_token=auth_token,
            feed_token=feed_token,
            broker=broker
        )

        if success and status_code == 200:
            quote_data = quotes_response.get('data', {})
            ltp = quote_data.get('ltp')
            if ltp is not None:
                try:
                    ltp = float(ltp)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid LTP value for {exchange}:{symbol}: {ltp}")
                    ltp = None
        else:
            ltp_error = quotes_response.get('message', 'Failed to fetch LTP')
            logger.debug(f"LTP fetch failed for {exchange}:{symbol}: {ltp_error}")
    except Exception as e:
        ltp_error = str(e)
        logger.debug(f"Exception fetching LTP for {exchange}:{symbol}: {e}")

    # Step 2: Build single-position array for margin calculation
    position = {
        'exchange': exchange,
        'symbol': symbol,
        'action': action,
        'quantity': quantity,
        'product': product,
        'pricetype': pricetype,
        'price': price
    }

    margin_request = {
        'apikey': scrip_data.get('apikey'),
        'positions': [position]
    }

    # Step 3: Calculate margin using the margin service
    try:
        success, margin_response, status_code = calculate_margin(
            margin_data=margin_request,
            auth_token=auth_token,
            broker=broker
        )

        if not success or status_code != 200:
            error_msg = margin_response.get('message', 'Failed to calculate margin')
            return False, {
                'status': 'error',
                'message': error_msg
            }, status_code

    except Exception as e:
        logger.error(f"Error calculating margin for {exchange}:{symbol}: {e}")
        return False, {
            'status': 'error',
            'message': f'Failed to calculate margin: {str(e)}'
        }, 500

    # Step 4: Extract margin data from response
    margin_data = margin_response.get('data', {})
    total_margin_required = margin_data.get('total_margin_required')
    margin_breakdown = margin_data.get('margin_breakdown', {})

    # Handle case where total_margin_required is None or invalid
    if total_margin_required is None:
        return False, {
            'status': 'error',
            'message': 'Broker did not return margin requirement'
        }, 500

    try:
        total_margin_required = float(total_margin_required)
    except (ValueError, TypeError):
        logger.error(f"Invalid total_margin_required: {total_margin_required}")
        return False, {
            'status': 'error',
            'message': 'Invalid margin data received from broker'
        }, 500

    # Step 5: Calculate per-unit values
    margin_per_unit = total_margin_required / quantity if quantity > 0 else 0

    # Step 6: Calculate leverage and margin percentage (requires LTP)
    leverage = None
    margin_percent = None

    if ltp is not None and ltp > 0 and margin_per_unit > 0:
        leverage = round(ltp / margin_per_unit, 2)
        margin_percent = round((margin_per_unit / ltp) * 100, 2)

    # Step 7: Build response
    response_data = {
        'status': 'success',
        'data': {
            'symbol': symbol,
            'exchange': exchange,
            'product': product,
            'ltp': ltp,
            'margin_per_unit': round(margin_per_unit, 2),
            'leverage': leverage,
            'margin_percent': margin_percent,
            'quantity': quantity,
            'lot_size': lot_size,
            'total_margin_required': round(total_margin_required, 2),
            'margin_breakdown': {
                'span_margin': margin_breakdown.get('span_margin', 0),
                'exposure_margin': margin_breakdown.get('exposure_margin', 0),
                'option_premium': margin_breakdown.get('option_premium', 0),
                'additional_margin': margin_breakdown.get('additional_margin', 0)
            }
        }
    }

    # Add warning if LTP was unavailable
    if ltp is None and ltp_error:
        response_data['data']['ltp_warning'] = f"LTP unavailable: {ltp_error}"

    return True, response_data, 200


def calculate_scrip_margin(
    scrip_data: Dict[str, Any],
    api_key: str
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Calculate margin and leverage for a single symbol.
    Entry point for the scrip margin calculation service.

    Args:
        scrip_data: Scrip data containing symbol, exchange, product, quantity, etc.
        api_key: OpenAlgo API key

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Create a copy of the data for logging
    original_data = copy.deepcopy(scrip_data)

    # Get authentication tokens and broker name
    AUTH_TOKEN, FEED_TOKEN, broker_name = get_auth_token_broker(api_key, include_feed_token=True)

    if AUTH_TOKEN is None:
        return False, {
            'status': 'error',
            'message': 'Invalid openalgo apikey'
        }, 403

    # Call the main calculation function with auth tokens
    return calculate_scrip_margin_with_auth(
        scrip_data=scrip_data,
        auth_token=AUTH_TOKEN,
        feed_token=FEED_TOKEN,
        broker=broker_name
    )
