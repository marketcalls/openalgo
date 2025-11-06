# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Kotak Neo Margin API

from database.token_db import get_token
from broker.kotak.mapping.transform_data import reverse_map_exchange, map_order_type, map_product_type
from utils.logging import get_logger

logger = get_logger(__name__)

def transform_margin_position(position):
    """
    Transform a single OpenAlgo margin position to Kotak margin format.

    Note: Kotak margin API accepts only one order at a time, not a batch.

    Args:
        position: Position in OpenAlgo format

    Returns:
        Dict in Kotak margin format or None if transformation fails
    """
    try:
        # Get the token for the symbol
        token = get_token(position['symbol'], position['exchange'])

        if not token:
            logger.warning(f"Token not found for symbol: {position['symbol']} on exchange: {position['exchange']}")
            return None

        # Map exchange segment
        exchange_segment = reverse_map_exchange(position['exchange'])
        if not exchange_segment:
            logger.warning(f"Invalid exchange: {position['exchange']}")
            return None

        # Map transaction type
        transaction_type = 'B' if position['action'].upper() == 'BUY' else 'S'

        # Transform the position (all values must be strings for Kotak API)
        transformed = {
            "brkName": "KOTAK",
            "brnchId": "ONLINE",
            "exSeg": exchange_segment,
            "prc": str(position.get('price', '0')),
            "prcTp": map_order_type(position['pricetype']),
            "prod": map_product_type(position['product']),
            "qty": str(position['quantity']),
            "tok": str(token),
            "trnsTp": transaction_type
        }

        return transformed

    except Exception as e:
        logger.error(f"Error transforming position: {position}, Error: {e}")
        return None

def parse_margin_response(response_data):
    """
    Parse Kotak margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Kotak API

    Returns:
        Standardized margin response
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {
                'status': 'error',
                'message': 'Invalid response from broker'
            }

        # Check if the response status is Ok
        if response_data.get('stat') != 'Ok':
            error_message = response_data.get('errMsg', 'Failed to calculate margin')
            return {
                'status': 'error',
                'message': error_message
            }

        # Extract margin data
        # Kotak returns: avlMrgn, reqdMrgn, ordMrgn, mrgnUsd, rmsVldtd, etc.

        # Return standardized format
        return {
            'status': 'success',
            'data': {
                'available_margin': float(response_data.get('avlMrgn', 0)),
                'required_margin': float(response_data.get('reqdMrgn', 0)),
                'order_margin': float(response_data.get('ordMrgn', 0)),
                'margin_used': float(response_data.get('mrgnUsd', 0)),
                'total_margin_used': float(response_data.get('totMrgnUsd', 0)),
                'available_cash': float(response_data.get('avlCash', 0)),
                'insufficient_fund': float(response_data.get('insufFund', 0)),
                'rms_validated': response_data.get('rmsVldtd', ''),
                'raw_response': response_data  # Include raw response for debugging
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
    Parse multiple Kotak margin responses and aggregate them.

    Args:
        responses: List of individual margin responses

    Returns:
        Aggregated margin response
    """
    try:
        total_required_margin = 0
        total_order_margin = 0
        total_margin_used = 0
        available_margin = 0
        available_cash = 0
        total_insufficient = 0
        all_rms_valid = True
        all_responses = []

        for response in responses:
            if response.get('status') == 'success':
                data = response.get('data', {})
                total_required_margin += data.get('required_margin', 0)
                total_order_margin += data.get('order_margin', 0)
                total_margin_used += data.get('total_margin_used', 0)
                # Take minimum available margin (most restrictive)
                if available_margin == 0:
                    available_margin = data.get('available_margin', 0)
                else:
                    available_margin = min(available_margin, data.get('available_margin', 0))
                # Take max available cash (should be same for all)
                available_cash = max(available_cash, data.get('available_cash', 0))
                total_insufficient += data.get('insufficient_fund', 0)
                if data.get('rms_validated', '') != 'OK':
                    all_rms_valid = False
                all_responses.append(data.get('raw_response', {}))

        return {
            'status': 'success',
            'data': {
                'total_required_margin': total_required_margin,
                'total_order_margin': total_order_margin,
                'available_margin': available_margin,
                'available_cash': available_cash,
                'total_margin_used': total_margin_used,
                'total_insufficient_fund': total_insufficient,
                'rms_validated': 'OK' if all_rms_valid else 'NOT_OK',
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
