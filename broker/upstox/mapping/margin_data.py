# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Upstox Margin API https://upstox.com/developer/api-documentation/margin

from database.token_db import get_br_symbol
from broker.upstox.mapping.transform_data import map_product_type
from utils.logging import get_logger

logger = get_logger(__name__)

def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to Upstox margin format.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        List of positions in Upstox format
    """
    transformed_positions = []

    for position in positions:
        try:
            # Get the broker symbol/instrument key for Upstox
            instrument_key = get_br_symbol(position['symbol'], position['exchange'])

            if not instrument_key:
                logger.warning(f"Instrument key not found for: {position['symbol']} on exchange: {position['exchange']}")
                continue

            # Transform the position
            transformed_position = {
                "instrument_key": instrument_key,
                "quantity": int(position['quantity']),
                "transaction_type": position['action'].upper(),
                "product": map_product_type(position['product'])
            }

            # Add price if provided (optional field)
            if position.get('price') and float(position['price']) > 0:
                transformed_position['price'] = float(position['price'])

            transformed_positions.append(transformed_position)

        except Exception as e:
            logger.error(f"Error transforming position: {position}, Error: {e}")
            continue

    return transformed_positions

def parse_margin_response(response_data):
    """
    Parse Upstox margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Upstox API

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
            # Check for errors array
            if 'errors' in response_data:
                errors = response_data['errors']
                if isinstance(errors, list) and len(errors) > 0:
                    error_message = errors[0].get('message', error_message)
            return {
                'status': 'error',
                'message': error_message
            }

        # Extract margin data
        data = response_data.get('data', {})

        # Extract margin breakdown (array of margins per instrument)
        margins = data.get('margins', [])

        # Calculate aggregated margin breakdown
        total_span = 0
        total_exposure = 0
        total_equity = 0
        total_net_premium = 0
        total_additional = 0
        total_tender = 0

        for margin in margins:
            total_span += margin.get('span_margin', 0)
            total_exposure += margin.get('exposure_margin', 0)
            total_equity += margin.get('equity_margin', 0)
            total_net_premium += margin.get('net_buy_premium', 0)
            total_additional += margin.get('additional_margin', 0)
            total_tender += margin.get('tender_margin', 0)

        # Return standardized format
        return {
            'status': 'success',
            'data': {
                'required_margin': data.get('required_margin', 0),
                'final_margin': data.get('final_margin', 0),
                'span_margin': total_span,
                'exposure_margin': total_exposure,
                'equity_margin': total_equity,
                'net_buy_premium': total_net_premium,
                'additional_margin': total_additional,
                'tender_margin': total_tender,
                'total_instruments': len(margins),
                'individual_margins': margins,
                'raw_response': data  # Include raw response for debugging
            }
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {
            'status': 'error',
            'message': f'Failed to parse margin response: {str(e)}'
        }
