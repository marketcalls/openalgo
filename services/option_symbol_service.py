"""
Option Symbol Service

This service helps fetch option symbols based on underlying, expiry, strike offset, and option type.
It calculates ATM based on current LTP and returns the appropriate option symbol.

Example Usage:
    Input:
        underlying: "NIFTY"
        exchange: "NSE_INDEX"
        expiry_date: "28OCT25"
        strike_int: 50
        offset: "ITM2"
        option_type: "CE"

    Output:
        symbol: "NIFTY28OCT2523500CE"  (if ATM is 23600, ITM2 = 23600 - 2*50 = 23500)
"""

import re
import importlib
from typing import Tuple, Dict, Any, Optional
from datetime import datetime
from database.auth_db import get_auth_token_broker
from database.symbol import SymToken, db_session
from services.quotes_service import get_quotes
from utils.logging import get_logger

logger = get_logger(__name__)


def parse_underlying_symbol(underlying: str) -> Tuple[str, Optional[str]]:
    """
    Parse underlying symbol to extract base symbol and expiry date if present.

    Args:
        underlying: Symbol like "NIFTY" or "NIFTY28OCT25FUT" or "RELIANCE31JAN25FUT"

    Returns:
        Tuple of (base_symbol, expiry_date)
        e.g., ("NIFTY", "28OCT25") or ("NIFTY", None)
    """
    # Pattern to match: SYMBOL + DDMMMYY + optional FUT
    # Examples: NIFTY28OCT25FUT, BANKNIFTY31JAN25FUT, RELIANCE28MAR24FUT
    pattern = r'^([A-Z]+)(\d{2}[A-Z]{3}\d{2})(?:FUT)?$'

    match = re.match(pattern, underlying.upper())
    if match:
        base_symbol = match.group(1)
        expiry_date = match.group(2)
        logger.info(f"Parsed underlying '{underlying}' -> base: '{base_symbol}', expiry: '{expiry_date}'")
        return base_symbol, expiry_date

    # If no pattern match, treat the entire string as base symbol
    logger.info(f"Underlying '{underlying}' has no embedded expiry, using as-is")
    return underlying.upper(), None


def get_atm_strike(ltp: float, strike_int: int) -> float:
    """
    Calculate ATM strike price based on LTP and strike interval.

    Args:
        ltp: Last Traded Price of the underlying
        strike_int: Strike interval/difference

    Returns:
        ATM strike price rounded to nearest strike interval

    Example:
        LTP = 23587.50, strike_int = 50
        ATM = round(23587.50 / 50) * 50 = 23600
    """
    atm_strike = round(ltp / strike_int) * strike_int
    logger.info(f"Calculated ATM: LTP={ltp}, strike_int={strike_int}, ATM={atm_strike}")
    return atm_strike


def calculate_offset_strike(atm_strike: float, offset: str, strike_int: int, option_type: str) -> float:
    """
    Calculate the target strike based on ATM and offset.

    Args:
        atm_strike: ATM strike price
        offset: Offset like "ATM", "ITM1", "ITM2", "OTM1", "OTM2"
        strike_int: Strike interval
        option_type: "CE" or "PE"

    Returns:
        Target strike price

    Logic:
        For CE (Call):
            - ITM: ATM - (N * strike_int)  [Lower strike]
            - OTM: ATM + (N * strike_int)  [Higher strike]

        For PE (Put):
            - ITM: ATM + (N * strike_int)  [Higher strike]
            - OTM: ATM - (N * strike_int)  [Lower strike]

    Example:
        ATM = 23600, strike_int = 50, option_type = "CE", offset = "ITM2"
        Target = 23600 - (2 * 50) = 23500
    """
    offset = offset.upper()
    option_type = option_type.upper()

    if offset == "ATM":
        target_strike = atm_strike
    elif offset.startswith("ITM"):
        # Extract the number (ITM1 -> 1, ITM2 -> 2)
        num = int(offset[3:])
        if option_type == "CE":
            # For Call, ITM means lower strike
            target_strike = atm_strike - (num * strike_int)
        else:  # PE
            # For Put, ITM means higher strike
            target_strike = atm_strike + (num * strike_int)
    elif offset.startswith("OTM"):
        # Extract the number (OTM1 -> 1, OTM2 -> 2)
        num = int(offset[3:])
        if option_type == "CE":
            # For Call, OTM means higher strike
            target_strike = atm_strike + (num * strike_int)
        else:  # PE
            # For Put, OTM means lower strike
            target_strike = atm_strike - (num * strike_int)
    else:
        logger.error(f"Invalid offset: {offset}")
        raise ValueError(f"Invalid offset: {offset}")

    logger.info(f"Calculated target strike: ATM={atm_strike}, offset={offset}, type={option_type}, target={target_strike}")
    return target_strike


def construct_option_symbol(base_symbol: str, expiry_date: str, strike: float, option_type: str) -> str:
    """
    Construct option symbol in OpenAlgo format.

    Format: [Base Symbol][Expiry Date][Strike Price][Option Type]

    Args:
        base_symbol: Base symbol like "NIFTY", "BANKNIFTY", "RELIANCE"
        expiry_date: Expiry in DDMMMYY format like "28OCT25"
        strike: Strike price like 23500 or 292.5
        option_type: "CE" or "PE"

    Returns:
        Option symbol like "NIFTY28OCT2523500CE" or "VEDL25APR24292.5CE"

    Examples:
        construct_option_symbol("NIFTY", "28MAR24", 20800, "CE") -> "NIFTY28MAR2420800CE"
        construct_option_symbol("VEDL", "25APR24", 292.5, "CE") -> "VEDL25APR24292.5CE"
    """
    # Format strike: Remove .0 if it's a whole number, otherwise keep decimal
    if strike == int(strike):
        strike_str = str(int(strike))
    else:
        strike_str = str(strike)

    option_symbol = f"{base_symbol}{expiry_date}{strike_str}{option_type.upper()}"
    logger.info(f"Constructed option symbol: {option_symbol}")
    return option_symbol


def find_option_in_database(option_symbol: str, exchange: str) -> Optional[Dict[str, Any]]:
    """
    Find the option symbol in the database and return its details.

    Args:
        option_symbol: Constructed option symbol like "NIFTY28OCT2523500CE"
        exchange: Exchange like "NFO", "BFO", "MCX", "CDS"

    Returns:
        Dictionary with symbol details or None if not found
    """
    try:
        # Query the database
        result = db_session.query(SymToken).filter(
            SymToken.symbol == option_symbol,
            SymToken.exchange == exchange
        ).first()

        if result:
            logger.info(f"Found option in database: {option_symbol} on {exchange}")
            return {
                'symbol': result.symbol,
                'brsymbol': result.brsymbol,
                'name': result.name,
                'exchange': result.exchange,
                'brexchange': result.brexchange,
                'token': result.token,
                'expiry': result.expiry,
                'strike': result.strike,
                'lotsize': result.lotsize,
                'instrumenttype': result.instrumenttype,
                'tick_size': result.tick_size
            }
        else:
            logger.warning(f"Option symbol not found in database: {option_symbol} on {exchange}")
            return None

    except Exception as e:
        logger.error(f"Error querying database for option symbol: {e}")
        return None


def get_option_exchange(underlying_exchange: str) -> str:
    """
    Map underlying exchange to options exchange.

    Args:
        underlying_exchange: Exchange like "NSE_INDEX", "NSE", "BSE_INDEX", "BSE"

    Returns:
        Options exchange like "NFO", "BFO", "MCX", "CDS"

    Logic:
        NSE / NSE_INDEX -> NFO
        BSE / BSE_INDEX -> BFO
        MCX -> MCX (commodities have options on same exchange)
        CDS -> CDS (currency options on same exchange)
    """
    underlying_exchange = underlying_exchange.upper()

    if underlying_exchange in ['NSE', 'NSE_INDEX']:
        return 'NFO'
    elif underlying_exchange in ['BSE', 'BSE_INDEX']:
        return 'BFO'
    elif underlying_exchange == 'MCX':
        return 'MCX'
    elif underlying_exchange == 'CDS':
        return 'CDS'
    else:
        logger.warning(f"Unknown exchange mapping for: {underlying_exchange}, defaulting to NFO")
        return 'NFO'


def get_option_symbol(
    underlying: str,
    exchange: str,
    expiry_date: Optional[str],
    strike_int: int,
    offset: str,
    option_type: str,
    api_key: str
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Main function to get option symbol based on underlying and parameters.

    Args:
        underlying: Underlying symbol (e.g., "NIFTY", "NIFTY28OCT25FUT", "RELIANCE")
        exchange: Exchange (e.g., "NSE_INDEX", "NSE", "NFO")
        expiry_date: Expiry date in DDMMMYY format (optional if embedded in underlying)
        strike_int: Strike interval (e.g., 50 for NIFTY)
        offset: Offset from ATM (e.g., "ATM", "ITM1", "OTM2")
        option_type: Option type ("CE" or "PE")
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Step 1: Parse underlying to extract base symbol and expiry
        base_symbol, embedded_expiry = parse_underlying_symbol(underlying)

        # Determine final expiry date
        final_expiry = embedded_expiry or expiry_date
        if not final_expiry:
            logger.error("No expiry date provided or found in underlying symbol")
            return False, {
                'status': 'error',
                'message': 'Expiry date required. Provide via expiry_date parameter or embed in underlying (e.g., NIFTY28OCT25FUT).'
            }, 400

        # Step 2: Determine the quote exchange (where to fetch LTP from)
        # If exchange is already NFO/BFO, we need to get LTP from index/equity exchange
        quote_exchange = exchange
        if exchange.upper() in ['NFO', 'BFO']:
            # User passed options exchange, need to map back to index/equity
            if base_symbol in ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'INDIAVIX']:
                quote_exchange = 'NSE_INDEX'
            elif base_symbol in ['SENSEX', 'BANKEX', 'SENSEX50']:
                quote_exchange = 'BSE_INDEX'
            else:
                # Assume it's an equity symbol
                quote_exchange = 'NSE' if exchange.upper() == 'NFO' else 'BSE'

        # Construct the symbol to fetch quotes for
        # If underlying already has expiry embedded, use base symbol only
        # Otherwise, use underlying as-is
        if embedded_expiry:
            quote_symbol = base_symbol
        else:
            quote_symbol = underlying

        logger.info(f"Fetching LTP for: {quote_symbol} on {quote_exchange}")

        # Step 3: Get LTP of underlying
        success, quote_response, status_code = get_quotes(
            symbol=quote_symbol,
            exchange=quote_exchange,
            api_key=api_key
        )

        if not success:
            logger.error(f"Failed to fetch quotes: {quote_response.get('message', 'Unknown error')}")
            return False, {
                'status': 'error',
                'message': f"Failed to fetch LTP for {quote_symbol}. {quote_response.get('message', 'Unknown error')}"
            }, status_code

        # Extract LTP from quote response
        ltp = quote_response.get('data', {}).get('ltp')
        if ltp is None:
            logger.error(f"LTP not found in quote response for {quote_symbol}")
            return False, {
                'status': 'error',
                'message': f'Could not determine LTP for {quote_symbol}.'
            }, 500

        logger.info(f"Got LTP: {ltp} for {quote_symbol}")

        # Step 4: Calculate ATM strike
        atm_strike = get_atm_strike(ltp, strike_int)

        # Step 5: Calculate target strike based on offset
        target_strike = calculate_offset_strike(atm_strike, offset, strike_int, option_type)

        # Step 6: Construct option symbol
        option_symbol = construct_option_symbol(base_symbol, final_expiry, target_strike, option_type)

        # Step 7: Map to options exchange
        options_exchange = get_option_exchange(quote_exchange)

        # Step 8: Find option in database
        option_details = find_option_in_database(option_symbol, options_exchange)

        if not option_details:
            logger.warning(f"Option symbol {option_symbol} not found in database for {options_exchange}")
            return False, {
                'status': 'error',
                'message': f'Option symbol {option_symbol} not found in {options_exchange}. Symbol may not exist or master contract needs update.'
            }, 404

        # Step 9: Return success response with simplified format
        return True, {
            'status': 'success',
            'symbol': option_details['symbol'],
            'exchange': option_details['exchange'],
            'lotsize': option_details['lotsize'],
            'tick_size': option_details['tick_size'],
            'underlying_ltp': ltp
        }, 200

    except ValueError as e:
        logger.error(f"Validation error in get_option_symbol: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 400
    except Exception as e:
        logger.exception(f"Error in get_option_symbol: {e}")
        return False, {
            'status': 'error',
            'message': f'An error occurred while processing option symbol request: {str(e)}'
        }, 500
