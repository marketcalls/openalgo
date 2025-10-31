# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Angel Broking Margin API https://smartapi.angelbroking.com/docs/Margin

from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)

def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to Angel Broking margin format.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        List of positions in Angel Broking format
    """
    transformed_positions = []

    for position in positions:
        try:
            # Get the token for the symbol
            token = get_token(position['symbol'], position['exchange'])

            if not token:
                logger.warning(f"Token not found for symbol: {position['symbol']} on exchange: {position['exchange']}")
                continue

            # Transform the position
            transformed_position = {
                "exchange": position['exchange'],
                "qty": int(position['quantity']),
                "price": float(position.get('price', 0)),
                "productType": map_product_type(position['product']),
                "token": str(token),
                "tradeType": position['action'].upper(),
                "orderType": map_order_type(position['pricetype'])
            }

            transformed_positions.append(transformed_position)

        except Exception as e:
            logger.error(f"Error transforming position: {position}, Error: {e}")
            continue

    return transformed_positions

def map_product_type(product):
    """
    Maps OpenAlgo product type to Angel Broking product type.

    OpenAlgo: CNC, NRML, MIS
    Angel: DELIVERY, CARRYFORWARD, INTRADAY, MARGIN
    """
    product_type_mapping = {
        "CNC": "DELIVERY",
        "NRML": "CARRYFORWARD",
        "MIS": "INTRADAY",
    }
    return product_type_mapping.get(product, "INTRADAY")

def map_order_type(pricetype):
    """
    Maps OpenAlgo price type to Angel Broking order type.

    OpenAlgo: MARKET, LIMIT, SL, SL-M
    Angel: MARKET, LIMIT, STOPLOSS_LIMIT, STOPLOSS_MARKET
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOPLOSS_LIMIT",
        "SL-M": "STOPLOSS_MARKET"
    }
    return order_type_mapping.get(pricetype, "MARKET")

def parse_margin_response(response_data):
    """
    Parse Angel Broking margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Angel Broking API

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
        if response_data.get('status') is False:
            return {
                'status': 'error',
                'message': response_data.get('message', 'Failed to calculate margin')
            }

        # Extract margin data
        data = response_data.get('data', {})

        # Return standardized format
        return {
            'status': 'success',
            'data': {
                'available_margin': data.get('availablecash', 0),
                'used_margin': data.get('m2munrealized', 0),
                'collateral': data.get('collateral', 0),
                'total_margin_required': data.get('marginused', 0),
                'raw_response': data  # Include raw response for debugging
            }
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {
            'status': 'error',
            'message': f'Failed to parse margin response: {str(e)}'
        }
