# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Firstock Order Margin API https://firstock.in/api/docs/order-margin/

from database.token_db import get_br_symbol
from broker.firstock.mapping.transform_data import map_product_type, map_order_type
from utils.logging import get_logger

logger = get_logger(__name__)

def transform_margin_position(position, user_id):
    """
    Transform a single OpenAlgo margin position to Firstock margin format.

    Note: Firstock margin API accepts only one order at a time, not a batch.

    Args:
        position: Position in OpenAlgo format
        user_id: Firstock user ID

    Returns:
        Dict in Firstock margin format or None if transformation fails
    """
    try:
        # Get the broker symbol for Firstock
        symbol = get_br_symbol(position['symbol'], position['exchange'])

        if not symbol:
            logger.warning(f"Symbol not found for: {position['symbol']} on exchange: {position['exchange']}")
            return None

        # Handle special characters in symbol (like &)
        if symbol and '&' in symbol:
            symbol = symbol.replace('&', '%26')

        # Map action to transaction type
        transaction_type = 'B' if position['action'].upper() == 'BUY' else 'S'

        # Transform the position
        transformed = {
            "userId": user_id,
            "exchange": position['exchange'],
            "transactionType": transaction_type,
            "product": map_product_type(position['product']),
            "tradingSymbol": symbol,
            "quantity": str(position['quantity']),
            "priceType": map_order_type(position['pricetype']),
            "price": str(position.get('price', '0'))
        }

        return transformed

    except Exception as e:
        logger.error(f"Error transforming position: {position}, Error: {e}")
        return None

def parse_margin_response(response_data):
    """
    Parse Firstock margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Firstock API

    Returns:
        Standardized margin response
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {
                'status': 'error',
                'message': 'Invalid response from broker'
            }

        # Check if the response status is success
        if response_data.get('status') != 'success':
            error_message = response_data.get('message', 'Failed to calculate margin')
            if 'error' in response_data:
                error_detail = response_data['error']
                if isinstance(error_detail, dict):
                    error_message = error_detail.get('message', error_message)
                else:
                    error_message = str(error_detail)
            return {
                'status': 'error',
                'message': error_message
            }

        # Extract margin data
        data = response_data.get('data', {})

        # Return standardized format
        return {
            'status': 'success',
            'data': {
                'available_margin': float(data.get('availableMargin', 0)),
                'cash': float(data.get('cash', 0)),
                'margin_required': float(data.get('marginOnNewOrder', 0)),
                'remarks': data.get('remarks', ''),
                'request_time': data.get('requestTime', ''),
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
    Parse multiple Firstock margin responses and aggregate them.

    Args:
        responses: List of individual margin responses

    Returns:
        Aggregated margin response
    """
    try:
        total_margin_required = 0
        available_margin = 0
        total_cash = 0
        all_remarks = []
        all_responses = []

        for response in responses:
            if response.get('status') == 'success':
                data = response.get('data', {})
                total_margin_required += data.get('margin_required', 0)
                # Take the minimum available margin (most restrictive)
                if available_margin == 0:
                    available_margin = data.get('available_margin', 0)
                else:
                    available_margin = min(available_margin, data.get('available_margin', 0))
                # Take max cash (should be same for all)
                total_cash = max(total_cash, data.get('cash', 0))
                remarks = data.get('remarks', '')
                if remarks and remarks not in all_remarks:
                    all_remarks.append(remarks)
                all_responses.append(data.get('raw_response', {}))

        return {
            'status': 'success',
            'data': {
                'total_margin_required': total_margin_required,
                'available_margin': available_margin,
                'cash': total_cash,
                'remarks': ', '.join(all_remarks) if all_remarks else '',
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
