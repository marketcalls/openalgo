# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Shoonya Span Calculator API

from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

def transform_margin_positions(positions, account_id):
    """
    Transform OpenAlgo margin positions to Shoonya margin format.

    Args:
        positions: List of positions in OpenAlgo format
        account_id: Shoonya account ID (API key without last 2 chars)

    Returns:
        Dict in Shoonya margin format with actid and pos array
    """
    transformed_positions = []

    for position in positions:
        try:
            # Get the broker symbol for Shoonya
            symbol = get_br_symbol(position['symbol'], position['exchange'])

            if not symbol:
                logger.warning(f"Symbol not found for: {position['symbol']} on exchange: {position['exchange']}")
                continue

            # Handle special characters in symbol (like &)
            if symbol and '&' in symbol:
                symbol = symbol.replace('&', '%26')

            # Determine instrument name based on symbol pattern
            instname = determine_instrument_name(symbol, position['exchange'])

            # Extract symbol name (without suffix for options/futures)
            symname = extract_symbol_name(symbol)

            # Extract expiry date, option type, and strike price if applicable
            exd, optt, strprc = extract_derivative_details(symbol, position['exchange'])

            # Calculate quantities based on action
            quantity = int(position['quantity'])
            if position['action'].upper() == 'BUY':
                buyqty = quantity
                sellqty = 0
                netqty = quantity
            else:
                buyqty = 0
                sellqty = quantity
                netqty = -quantity

            # Transform the position (note: "exd" instead of "expd" for Shoonya)
            transformed_position = {
                "exch": position['exchange'],
                "instname": instname,
                "symname": symname,
                "exd": exd,  # Note: Shoonya uses "exd" not "expd"
                "optt": optt,
                "strprc": strprc,
                "buyqty": buyqty,
                "sellqty": sellqty,
                "netqty": netqty
            }

            transformed_positions.append(transformed_position)

        except Exception as e:
            logger.error(f"Error transforming position: {position}, Error: {e}")
            continue

    return {
        "actid": account_id,
        "pos": transformed_positions
    }

def determine_instrument_name(symbol, exchange):
    """
    Determine instrument name based on symbol and exchange.

    Returns: FUTSTK, FUTIDX, OPTSTK, OPTIDX, FUTCUR, etc.
    """
    # For equity exchanges
    if exchange in ['NSE', 'BSE']:
        return 'EQ'

    # For derivative exchanges
    if exchange == 'NFO':
        if 'FUT' in symbol or symbol.endswith('F'):
            if any(idx in symbol for idx in ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']):
                return 'FUTIDX'
            else:
                return 'FUTSTK'
        elif 'CE' in symbol or 'PE' in symbol:
            if any(idx in symbol for idx in ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']):
                return 'OPTIDX'
            else:
                return 'OPTSTK'

    # For currency
    if exchange == 'CDS':
        if 'FUT' in symbol:
            return 'FUTCUR'
        elif 'CE' in symbol or 'PE' in symbol:
            return 'OPTCUR'

    # For commodity
    if exchange == 'MCX':
        if 'FUT' in symbol:
            return 'FUTCOM'
        elif 'CE' in symbol or 'PE' in symbol:
            return 'OPTCOM'

    # Default
    return 'EQ'

def extract_symbol_name(symbol):
    """
    Extract base symbol name from trading symbol.
    E.g., NIFTY25NOV25FUT -> NIFTY
    """
    # Common patterns to remove
    patterns = ['FUT', 'CE', 'PE', '-EQ']

    # Start with the full symbol
    base = symbol

    # Remove common suffixes
    for pattern in patterns:
        if pattern in base:
            base = base.split(pattern)[0]

    # Remove date patterns (e.g., 25NOV25, 2025-11-28, etc.)
    import re
    base = re.sub(r'\d{2}[A-Z]{3}\d{2}', '', base)
    base = re.sub(r'\d{4}-\d{2}-\d{2}', '', base)
    base = re.sub(r'\d{5,}', '', base)  # Remove strike prices

    return base.strip()

def extract_derivative_details(symbol, exchange):
    """
    Extract expiry date, option type, and strike price from symbol.

    Returns: (exd, optt, strprc)
    """
    exd = ""
    optt = ""
    strprc = ""

    # For equity exchanges, no derivatives
    if exchange in ['NSE', 'BSE']:
        return exd, optt, strprc

    import re

    # Extract expiry date (format: DDMMMYY to YYYY-MM-DD)
    date_match = re.search(r'(\d{2})([A-Z]{3})(\d{2})', symbol)
    if date_match:
        day = date_match.group(1)
        month_str = date_match.group(2)
        year = '20' + date_match.group(3)

        # Map month abbreviation to number
        month_map = {
            'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
            'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
            'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'
        }
        month = month_map.get(month_str, '01')
        exd = f"{year}-{month}-{day}"

    # Extract option type (CE or PE)
    if 'CE' in symbol:
        optt = 'CE'
        # Extract strike price before CE
        strike_match = re.search(r'(\d+\.?\d*)CE', symbol)
        if strike_match:
            strprc = strike_match.group(1)
    elif 'PE' in symbol:
        optt = 'PE'
        # Extract strike price before PE
        strike_match = re.search(r'(\d+\.?\d*)PE', symbol)
        if strike_match:
            strprc = strike_match.group(1)

    return exd, optt, strprc

def parse_margin_response(response_data):
    """
    Parse Shoonya margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Shoonya API

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
            error_message = response_data.get('emsg', 'Failed to calculate margin')
            return {
                'status': 'error',
                'message': error_message
            }

        # Extract margin data
        # Shoonya returns: span, expo, span_trade, expo_trade

        span = float(response_data.get('span', 0))
        expo = float(response_data.get('expo', 0))
        total_margin = span + expo

        # Return standardized format
        return {
            'status': 'success',
            'data': {
                'total_margin_required': total_margin,
                'span_margin': span,
                'exposure_margin': expo,
                'span_trade': float(response_data.get('span_trade', 0)),
                'expo_trade': float(response_data.get('expo_trade', 0)),
                'raw_response': response_data  # Include raw response for debugging
            }
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {
            'status': 'error',
            'message': f'Failed to parse margin response: {str(e)}'
        }
