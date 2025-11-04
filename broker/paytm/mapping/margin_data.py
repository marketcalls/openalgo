# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Paytm Order Margin Calculator API

from database.token_db import get_token
from broker.paytm.mapping.transform_data import (
    map_exchange,
    reverse_map_product_type
)
from utils.logging import get_logger

logger = get_logger(__name__)

def get_segment_from_exchange(exchange):
    """
    Determines the segment type based on exchange.
    E → Equity Cash (NSE, BSE)
    D → Equity Derivative (NFO, BFO)
    """
    if exchange in ['NSE', 'BSE']:
        return 'E'
    elif exchange in ['NFO', 'BFO']:
        return 'D'
    return 'E'  # Default to equity

def get_instrument_type(exchange):
    """
    Determines the instrument type based on exchange.
    EQUITY → Equity Cash (NSE, BSE)
    FUTSTK → Futures Stock (NFO, BFO)
    OPTSTK → Options Stock (NFO, BFO)

    Note: For derivatives, we default to OPTSTK as most margin calculations
    are for options. If needed, this can be enhanced to detect from symbol.
    """
    if exchange in ['NSE', 'BSE']:
        return 'EQUITY'
    elif exchange in ['NFO', 'BFO']:
        # Default to OPTSTK for derivatives
        return 'OPTSTK'
    return 'EQUITY'

def transform_margin_position(position):
    """
    Transform a single OpenAlgo margin position to Paytm request body format.

    According to Paytm API docs, the margin calculator accepts POST requests with:
    - source, exchange, segment, security_id, txn_type, quantity,
      strike_price, trigger_price, instrument

    Args:
        position: Position in OpenAlgo format

    Returns:
        Dict of request body for Paytm margin API or None if transformation fails
    """
    try:
        # Get the security token for the symbol
        security_id = get_token(position['symbol'], position['exchange'])

        if not security_id:
            logger.warning(f"Token not found for symbol: {position['symbol']} on exchange: {position['exchange']}")
            return None

        # Map exchange
        exchange = map_exchange(position['exchange'])
        if not exchange:
            logger.warning(f"Invalid exchange: {position['exchange']}")
            return None

        # Get segment (E for equity, D for derivative)
        segment = get_segment_from_exchange(position['exchange'])

        # Get instrument type (EQUITY, FUTSTK, OPTSTK)
        instrument = get_instrument_type(position['exchange'])

        # Prepare request body according to API docs
        body = {
            "source": "M",  # mWeb - can be W, M, N, I, R, O
            "exchange": exchange,
            "segment": segment,
            "security_id": str(security_id),
            "txn_type": position['action'].upper(),  # BUY or SELL
            "quantity": str(int(position['quantity'])),
            "strike_price": "0",  # Default to 0 for non-options
            "trigger_price": str(float(position.get('trigger_price', 0))),
            "instrument": instrument
        }

        logger.debug(f"Transformed position for {position['symbol']}: {body}")
        return body

    except Exception as e:
        logger.error(f"Error transforming position: {position}, Error: {e}")
        return None

def parse_margin_response(response_data):
    """
    Parse Paytm margin response to OpenAlgo standard format.

    According to Paytm API docs, response includes:
    - span_margin: SPAN margin as per exchange
    - exposure_margin: Exposure margin required
    - option_premium: Option premium value
    - total_margin: Total margin required for execution

    Args:
        response_data: Raw response from Paytm API

    Returns:
        Standardized margin response matching OpenAlgo format
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {
                'status': 'error',
                'message': 'Invalid response from broker'
            }

        # Check for errors in the response
        if response_data.get('status') == 'error' or 'error' in response_data:
            error_message = response_data.get('message', 'Failed to calculate margin')
            return {
                'status': 'error',
                'message': error_message
            }

        # Extract margin data
        data = response_data.get('data', {})

        if not data:
            return {
                'status': 'error',
                'message': 'No data in response'
            }

        # Extract margin components according to API docs
        span_margin = float(data.get('span_margin', 0))
        exposure_margin = float(data.get('exposure_margin', 0))
        option_premium = float(data.get('option_premium', 0))
        total_margin = float(data.get('total_margin', 0))

        # Return standardized format (without margin_benefit and option_premium)
        return {
            'status': 'success',
            'data': {
                'total_margin_required': total_margin,
                'span_margin': span_margin,
                'exposure_margin': exposure_margin
            }
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {
            'status': 'error',
            'message': f'Failed to parse margin response: {str(e)}'
        }

def parse_batch_margin_response(responses):
    """
    Parse multiple Paytm margin responses and aggregate them.

    Args:
        responses: List of individual margin responses

    Returns:
        Aggregated margin response matching OpenAlgo format
    """
    try:
        total_margin = 0
        total_span = 0
        total_exposure = 0

        for response in responses:
            if response.get('status') == 'success':
                data = response.get('data', {})
                total_margin += data.get('total_margin_required', 0)
                total_span += data.get('span_margin', 0)
                total_exposure += data.get('exposure_margin', 0)

        return {
            'status': 'success',
            'data': {
                'total_margin_required': total_margin,
                'span_margin': total_span,
                'exposure_margin': total_exposure
            }
        }

    except Exception as e:
        logger.error(f"Error parsing batch margin response: {e}")
        return {
            'status': 'error',
            'message': f'Failed to parse batch margin response: {str(e)}'
        }
