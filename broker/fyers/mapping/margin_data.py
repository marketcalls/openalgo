# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Fyers Margin API

from database.token_db import get_br_symbol
from broker.fyers.mapping.transform_data import map_product_type, map_action, map_order_type
from utils.logging import get_logger

logger = get_logger(__name__)

def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to Fyers margin format.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        List of positions in Fyers format
    """
    transformed_positions = []

    for position in positions:
        try:
            # Get the broker symbol for Fyers
            symbol = get_br_symbol(position['symbol'], position['exchange'])

            if not symbol:
                logger.warning(f"Symbol not found for: {position['symbol']} on exchange: {position['exchange']}")
                # Try to use the original symbol if broker symbol not found
                symbol = position['symbol']

            # Transform the position
            transformed_position = {
                "symbol": symbol,
                "qty": int(position['quantity']),
                "side": map_action(position['action'].upper()),
                "type": map_order_type(position['pricetype']),
                "productType": map_product_type(position['product']),
                "limitPrice": float(position.get('price', 0.0)),
                "stopLoss": 0.0,
                "stopPrice": float(position.get('trigger_price', 0.0)),
                "takeProfit": 0.0
            }

            transformed_positions.append(transformed_position)

        except Exception as e:
            logger.error(f"Error transforming position: {position}, Error: {e}")
            continue

    return transformed_positions

def parse_margin_response(response_data):
    """
    Parse Fyers margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Fyers API

    Returns:
        Standardized margin response
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {
                'status': 'error',
                'message': 'Invalid response from broker'
            }

        # Check if the response has the expected structure
        # Fyers uses 's' field for status: 'ok' for success
        if response_data.get('s') != 'ok':
            error_message = response_data.get('message', 'Failed to calculate margin')
            return {
                'status': 'error',
                'message': error_message
            }

        # Extract margin data
        data = response_data.get('data', {})

        # Fyers returns:
        # - margin_avail: Available margin
        # - margin_total: Total margin required
        # - margin_new_order: Margin required for new order

        # Return standardized format
        return {
            'status': 'success',
            'data': {
                'available_margin': data.get('margin_avail', 0),
                'total_margin_required': data.get('margin_new_order', 0),
                'total_margin_utilized': data.get('margin_total', 0),
                'raw_response': data  # Include raw response for debugging
            }
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {
            'status': 'error',
            'message': f'Failed to parse margin response: {str(e)}'
        }
