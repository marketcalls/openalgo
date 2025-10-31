# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Zerodha Margin API https://kite.trade/docs/connect/v3/margins/

from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to Zerodha margin format.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        List of positions in Zerodha format
    """
    transformed_positions = []

    for position in positions:
        try:
            # Get the broker symbol for Zerodha
            symbol = get_br_symbol(position['symbol'], position['exchange'])

            if not symbol:
                logger.warning(f"Symbol not found for: {position['symbol']} on exchange: {position['exchange']}")
                # Try to use the original symbol if broker symbol not found
                symbol = position['symbol']

            # Transform the position
            transformed_position = {
                "exchange": position['exchange'],
                "tradingsymbol": symbol,
                "transaction_type": position['action'].upper(),
                "variety": "regular",  # Default variety for margin calculation
                "product": map_product_type(position['product']),
                "order_type": map_order_type(position['pricetype']),
                "quantity": int(position['quantity']),
                "price": float(position.get('price', 0)),
                "trigger_price": float(position.get('trigger_price', 0))
            }

            transformed_positions.append(transformed_position)

        except Exception as e:
            logger.error(f"Error transforming position: {position}, Error: {e}")
            continue

    return transformed_positions

def map_product_type(product):
    """
    Maps OpenAlgo product type to Zerodha product type.

    OpenAlgo: CNC, NRML, MIS
    Zerodha: CNC, NRML, MIS (Direct mapping - no transformation needed)
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return product_type_mapping.get(product, "MIS")

def map_order_type(pricetype):
    """
    Maps OpenAlgo price type to Zerodha order type.

    OpenAlgo: MARKET, LIMIT, SL, SL-M
    Zerodha: MARKET, LIMIT, SL, SL-M (Direct mapping - no transformation needed)
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SL-M": "SL-M"
    }
    return order_type_mapping.get(pricetype, "MARKET")

def parse_margin_response(response_data):
    """
    Parse Zerodha margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Zerodha API

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
        if response_data.get('status') != 'success':
            return {
                'status': 'error',
                'message': response_data.get('message', 'Failed to calculate margin')
            }

        # Extract margin data
        data = response_data.get('data', {})

        # Calculate total margin required
        total_margin = 0
        if isinstance(data, dict):
            # For single order margin calculation
            total_margin = data.get('total', 0)
        elif isinstance(data, list):
            # For basket margin calculation - sum all order margins
            total_margin = sum(order.get('total', 0) for order in data)

        # Extract detailed margin breakdown if available
        margin_breakdown = {}
        if isinstance(data, dict) and 'final' in data:
            final = data['final']
            margin_breakdown = {
                'span': final.get('span', 0),
                'exposure': final.get('exposure', 0),
                'option_premium': final.get('option_premium', 0),
                'additional': final.get('additional', 0),
                'bo': final.get('bo', 0),
                'cash': final.get('cash', 0),
                'var': final.get('var', 0),
                'pnl': final.get('pnl', {}).get('realised', 0) + final.get('pnl', {}).get('unrealised', 0),
                'total': final.get('total', 0),
                'leverage': final.get('leverage', 1),
                'charges': final.get('charges', {})
            }
        elif isinstance(data, list):
            # For basket - provide aggregated view
            margin_breakdown = {
                'total_orders': len(data),
                'orders': data
            }

        # Return standardized format
        return {
            'status': 'success',
            'data': {
                'total_margin_required': total_margin,
                'margin_breakdown': margin_breakdown,
                'raw_response': data  # Include raw response for debugging
            }
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {
            'status': 'error',
            'message': f'Failed to parse margin response: {str(e)}'
        }
