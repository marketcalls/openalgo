# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Samco Span Margin API https://docs-tradeapi.samco.in/span-margin.html

from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_position(position):
    """
    Transform a single OpenAlgo margin position to Samco span margin format.

    Samco spanMargin API expects:
    - exchange: Name of the exchange (NFO, MCX, CDS, BFO)
    - tradingSymbol: Trading symbol of the scrip
    - qty: Quantity
    - transactionType: BUY or SELL (optional, default SELL)
    - price: Price (optional, for single scrip)

    Args:
        position: Position in OpenAlgo format
            - symbol: OpenAlgo symbol
            - exchange: Exchange (NFO, MCX, CDS, BFO)
            - quantity: Quantity
            - action: BUY or SELL
            - price: Price (optional)

    Returns:
        Dict in Samco margin format or None if transformation fails
    """
    try:
        symbol = position.get('symbol')
        exchange = position.get('exchange')
        quantity = position.get('quantity')
        action = position.get('action', 'SELL').upper()
        price = position.get('price', 0)
        product = position.get('product', 'NRML').upper()

        if not symbol or not exchange or not quantity:
            logger.warning(f"Missing required fields in position: {position}")
            return None

        # Validate exchange - spanMargin only works for derivatives
        valid_exchanges = ['NFO', 'MCX', 'CDS', 'BFO', 'MFO']
        if exchange not in valid_exchanges:
            logger.warning(f"Exchange {exchange} not valid for span margin. Valid: {valid_exchanges}")
            return None

        # Get broker symbol (trading symbol)
        br_symbol = get_br_symbol(symbol, exchange)
        if not br_symbol:
            logger.warning(f"Could not get broker symbol for: {symbol} on {exchange}")
            return None

        # Map product type to Samco format
        product_map = {
            'NRML': 'NRML',
            'MIS': 'MIS',
            'CNC': 'CNC',
            'INTRADAY': 'MIS',
            'CARRYFORWARD': 'NRML',
            'MARGIN': 'NRML'
        }
        samco_product = product_map.get(product, 'NRML')

        # Build the transformed position
        transformed = {
            "exchange": exchange,
            "tradingSymbol": br_symbol,
            "qty": str(int(quantity)),
            "productType": samco_product,
            "orderType": "L"  # Limit order - mandatory field
        }

        # Add optional fields
        if action:
            transformed["transactionType"] = action

        if price and float(price) > 0:
            transformed["price"] = str(float(price))
        else:
            # Price is required for limit orders
            transformed["price"] = "0"

        logger.debug(f"Transformed position: {transformed}")
        return transformed

    except Exception as e:
        logger.error(f"Error transforming position: {position}, Error: {e}")
        return None


def parse_margin_response(response_data):
    """
    Parse Samco span margin response to OpenAlgo standard format.

    Samco spanMargin API returns:
    - status: Success or Failure
    - statusMessage: Description
    - spanDetails:
        - totalRequirement: Total margin required
        - spanRequirement: SPAN margin
        - exposureMargin: Exposure margin
        - spreadBenefit: Spread/hedge benefit (reduction in margin)

    For single scrip, it may also return:
    - estimatedBrokerage: Projected brokerage
    - estimatedExpenses: Other expenses
    - estimatedOrderValue: Total order value
    - marginRequired: Margin needed
    - totalMargin: Total margin

    Args:
        response_data: Raw response from Samco API

    Returns:
        Standardized margin response matching OpenAlgo format
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {
                'status': 'error',
                'message': 'Invalid response from broker'
            }

        # Check for error response
        if response_data.get('status') != 'Success':
            error_message = response_data.get('statusMessage', 'Failed to calculate margin')
            return {
                'status': 'error',
                'message': error_message
            }

        # Extract span details
        span_details = response_data.get('spanDetails', {})

        if span_details:
            # Samco returns: totalMargin, marginRequired, exposureMargin, spreadBenefit
            # totalMargin = marginRequired + exposureMargin
            total_margin = safe_float(span_details.get('totalMargin', 0)) or safe_float(span_details.get('totalRequirement', 0))
            span_margin = safe_float(span_details.get('marginRequired', 0)) or safe_float(span_details.get('spanRequirement', 0))
            exposure_margin = safe_float(span_details.get('exposureMargin', 0))
            spread_benefit = safe_float(span_details.get('spreadBenefit', 0))
        else:
            # Single scrip response (fallback)
            total_margin = safe_float(response_data.get('totalMargin', 0)) or safe_float(response_data.get('marginRequired', 0))
            span_margin = safe_float(response_data.get('marginRequired', 0))
            exposure_margin = safe_float(response_data.get('exposureMargin', 0))
            spread_benefit = 0

        # Return standardized format
        return {
            'status': 'success',
            'data': {
                'total_margin_required': total_margin,
                'span_margin': span_margin,
                'exposure_margin': exposure_margin,
                'spread_benefit': spread_benefit
            }
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {
            'status': 'error',
            'message': f'Failed to parse margin response: {str(e)}'
        }


def safe_float(value, default=0):
    """Convert string to float, handling commas and empty values"""
    if value is None or value == '':
        return default
    try:
        if isinstance(value, str):
            value = value.replace(',', '')
        return float(value)
    except (ValueError, TypeError):
        return default
