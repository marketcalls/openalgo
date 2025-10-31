# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Paytm Order Margin Calculator API

from database.token_db import get_token
from broker.paytm.mapping.transform_data import (
    map_exchange,
    reverse_map_product_type,
    get_segment_from_exchange
)
from utils.logging import get_logger

logger = get_logger(__name__)

def transform_margin_position(position):
    """
    Transform a single OpenAlgo margin position to Paytm query parameters format.

    Note: Paytm margin calculator API accepts only one order at a time via GET request.

    Args:
        position: Position in OpenAlgo format

    Returns:
        Dict of query parameters for Paytm margin API or None if transformation fails
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

        # Get segment
        segment = get_segment_from_exchange(position['exchange'])

        # Prepare query parameters
        params = {
            "source": "M",  # mWeb
            "exchange": exchange,
            "segment": segment,
            "security_id": str(security_id),
            "txn_type": position['action'].upper(),  # BUY or SELL
            "quantity": str(int(position['quantity'])),
            "product": reverse_map_product_type(position['product']),
            "price": str(float(position.get('price', 0)))
        }

        # Add trigger price if present
        trigger_price = position.get('trigger_price', 0)
        if trigger_price and float(trigger_price) > 0:
            params['trigger_price'] = str(float(trigger_price))

        return params

    except Exception as e:
        logger.error(f"Error transforming position: {position}, Error: {e}")
        return None

def parse_margin_response(response_data):
    """
    Parse Paytm margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Paytm API

    Returns:
        Standardized margin response
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {
                'status': 'error',
                'message': 'Invalid response from broker'
            }

        # Check for errors in meta
        meta = response_data.get('meta', {})
        if 'error' in meta:
            error_message = meta.get('error', {}).get('message', 'Failed to calculate margin')
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

        # Return standardized format
        return {
            'status': 'success',
            'data': {
                'total_margin_required': float(data.get('t_total_margin', 0)),
                'span_margin': float(data.get('t_span_margin', 0)),
                'exposure_margin': float(data.get('t_exposure_margin', 0)),
                'available_balance': float(data.get('available_bal', 0)),
                'variable_margin': float(data.get('t_var_margin', 0)),
                'insufficient_balance': float(data.get('insufficient_bal', 0)),
                'brokerage': float(data.get('brokerage', 0)),
                'raw_response': data  # Include raw response for debugging
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
        Aggregated margin response
    """
    try:
        total_margin = 0
        total_span = 0
        total_exposure = 0
        total_var_margin = 0
        total_brokerage = 0
        available_balance = 0
        insufficient_balance = 0
        all_responses = []

        for response in responses:
            if response.get('status') == 'success':
                data = response.get('data', {})
                total_margin += data.get('total_margin_required', 0)
                total_span += data.get('span_margin', 0)
                total_exposure += data.get('exposure_margin', 0)
                total_var_margin += data.get('variable_margin', 0)
                total_brokerage += data.get('brokerage', 0)
                # Take the max available balance (it should be same for all)
                available_balance = max(available_balance, data.get('available_balance', 0))
                all_responses.append(data.get('raw_response', {}))

        # Calculate total insufficient balance
        insufficient_balance = max(0, total_margin - available_balance)

        return {
            'status': 'success',
            'data': {
                'total_margin_required': total_margin,
                'span_margin': total_span,
                'exposure_margin': total_exposure,
                'variable_margin': total_var_margin,
                'available_balance': available_balance,
                'total_brokerage': total_brokerage,
                'insufficient_balance': insufficient_balance,
                'total_positions': len(responses),
                'individual_margins': all_responses
            }
        }

    except Exception as e:
        logger.error(f"Error parsing batch margin response: {e}")
        return {
            'status': 'error',
            'message': f'Failed to parse batch margin response: {str(e)}'
        }
