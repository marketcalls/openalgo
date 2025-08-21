from database.symbol import SymToken, db_session
from database.auth_db import verify_api_key
from utils.logging import get_logger
from typing import Tuple, Dict, Any, List
from sqlalchemy import distinct, func

logger = get_logger(__name__)

def get_expiry_dates(symbol: str, exchange: str, instrumenttype: str, api_key: str = None) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get expiry dates for F&O symbols (futures or options) for a given underlying symbol.
    
    Args:
        symbol: Underlying symbol (e.g., NIFTY, BANKNIFTY)
        exchange: Exchange (NFO, BFO, MCX, CDS)
        instrumenttype: Type of instrument (futures or options)
        api_key: API key for authentication
    
    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Validate API key if provided
        if api_key:
            user_id = verify_api_key(api_key)
            if not user_id:
                logger.warning(f"Invalid API key provided for expiry dates")
                return False, {
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }, 403
        
        # Validate input
        if not symbol or not symbol.strip():
            logger.warning("Empty symbol provided")
            return False, {
                'status': 'error',
                'message': 'Symbol parameter is required and cannot be empty'
            }, 400
            
        if not exchange or not exchange.strip():
            logger.warning("Empty exchange provided")
            return False, {
                'status': 'error',
                'message': 'Exchange parameter is required and cannot be empty'
            }, 400
            
        if not instrumenttype or not instrumenttype.strip():
            logger.warning("Empty instrumenttype provided")
            return False, {
                'status': 'error',
                'message': 'Instrumenttype parameter is required and cannot be empty'
            }, 400
            
        # Validate instrumenttype
        if instrumenttype.lower() not in ['futures', 'options']:
            logger.warning(f"Invalid instrumenttype provided: {instrumenttype}")
            return False, {
                'status': 'error',
                'message': 'Instrumenttype must be either "futures" or "options"'
            }, 400
        
        # Validate exchange
        supported_exchanges = ['NFO', 'BFO', 'MCX', 'CDS']
        if exchange.upper() not in supported_exchanges:
            logger.warning(f"Unsupported exchange provided: {exchange}")
            return False, {
                'status': 'error',
                'message': f'Exchange must be one of: {", ".join(supported_exchanges)}'
            }, 400
        
        symbol = symbol.strip().upper()
        exchange = exchange.strip().upper()
        instrumenttype = instrumenttype.strip().lower()
        
        logger.info(f"Getting expiry dates for symbol: {symbol}, exchange: {exchange}, instrumenttype: {instrumenttype}")
        
        # Build query based on instrument type
        # For exact matching, we need to ensure the symbol starts with the underlying symbol
        # followed by a date pattern (for F&O instruments)
        # Use startswith and filter in Python for exact matching
        query = db_session.query(SymToken.symbol, SymToken.expiry, SymToken.instrumenttype).filter(
            SymToken.symbol.like(f'{symbol}%'),
            SymToken.exchange == exchange,
            SymToken.expiry.isnot(None),
            SymToken.expiry != ''
        )
        
        # Filter by instrument type based on exchange
        if instrumenttype == 'futures':
            # All exchanges support FUT along with their specific types
            if exchange in ['NFO', 'BFO']:
                query = query.filter(SymToken.instrumenttype.in_(['FUTSTK', 'FUTIDX', 'FUT']))
            elif exchange == 'MCX':
                query = query.filter(SymToken.instrumenttype.in_(['FUTCOM', 'FUTENR', 'FUT']))
            elif exchange == 'CDS':
                query = query.filter(SymToken.instrumenttype.in_(['FUTCUR', 'FUTIRC', 'FUT']))
        else:  # options
            # All exchanges support CE/PE along with their specific types
            if exchange in ['NFO', 'BFO']:
                query = query.filter(SymToken.instrumenttype.in_(['OPTSTK', 'OPTIDX', 'CE', 'PE']))
            elif exchange == 'MCX':
                query = query.filter(SymToken.instrumenttype.in_(['OPTFUT', 'CE', 'PE']))
            elif exchange == 'CDS':
                query = query.filter(SymToken.instrumenttype.in_(['OPTCUR', 'OPTIRC', 'CE', 'PE']))
        
        # Execute query and get results
        results = query.all()
        
        if not results:
            logger.info(f"No expiry dates found for symbol: {symbol}, exchange: {exchange}, instrumenttype: {instrumenttype}")
            return True, {
                'status': 'success',
                'message': f'No expiry dates found for {symbol} {instrumenttype} in {exchange}',
                'data': []
            }, 200
        
        # Debug: Log some sample symbols to understand the format
        logger.info(f"Sample symbols found: {[r[0] for r in results[:5]]}")
        
        # Filter for exact symbol match and extract expiry dates
        # Pattern: SYMBOL + DDMMMYY (like BANKNIFTY31JUL25) + optional suffix (like FUT/CE/PE)
        import re
        # For futures, we need to handle the FUT suffix
        if instrumenttype == 'futures':
            pattern = f'^{symbol}[0-9]{{2}}[A-Z]{{3}}[0-9]{{2}}(FUT)?'
        else:
            # For options: SYMBOL + DDMMMYY + strike + CE/PE
            pattern = f'^{symbol}[0-9]{{2}}[A-Z]{{3}}[0-9]{{2}}'
        
        filtered_expiry_dates = set()
        for result in results:
            symbol_name, expiry_date, _ = result
            logger.debug(f"Checking symbol: {symbol_name} against pattern: {pattern}")
            if re.match(pattern, symbol_name):
                filtered_expiry_dates.add(expiry_date)
                logger.debug(f"Pattern matched: {symbol_name} -> {expiry_date}")
        
        # If no exact matches found, let's be more lenient and check different patterns
        if not filtered_expiry_dates:
            logger.info(f"No exact matches found. Trying alternative patterns.")
            # Try different patterns that might exist in the database
            if instrumenttype == 'futures':
                alternative_patterns = [
                    f'^{symbol}[0-9]{{2}}[A-Z]{{3}}[0-9]{{2}}FUT',  # RELIANCE31JUL25FUT
                    f'^{symbol}[0-9]{{2}}[A-Z]{{3}}[0-9]{{2}}',  # RELIANCE31JUL25
                    f'^{symbol}[0-9]{{2}}[A-Z]{{3}}FUT',  # RELIANCE31JULFUT
                    f'^{symbol}[0-9]{{4}}[A-Z]{{3}}FUT',  # RELIANCE2025JULFUT
                    f'^{symbol}[A-Z]{{3}}[0-9]{{2}}FUT',  # RELIANCEJUL25FUT
                    f'^{symbol}[A-Z]{{3}}[0-9]{{4}}FUT',  # RELIANCEJUL2025FUT
                ]
            else:
                alternative_patterns = [
                    f'^{symbol}[0-9]{{2}}[A-Z]{{3}}[0-9]{{2}}',  # BANKNIFTY31JUL25
                    f'^{symbol}[0-9]{{2}}[A-Z]{{3}}',  # BANKNIFTY31JUL
                    f'^{symbol}[0-9]{{4}}[A-Z]{{3}}',  # BANKNIFTY2025JUL
                    f'^{symbol}[A-Z]{{3}}[0-9]{{2}}',  # BANKNIFTYJUL25
                    f'^{symbol}[A-Z]{{3}}[0-9]{{4}}',  # BANKNIFTYJUL2025
                ]
            
            for alt_pattern in alternative_patterns:
                temp_matches = set()
                for result in results:
                    symbol_name, expiry_date, _ = result
                    if re.match(alt_pattern, symbol_name):
                        temp_matches.add(expiry_date)
                        logger.debug(f"Alternative pattern {alt_pattern} matched: {symbol_name}")
                
                if temp_matches:
                    filtered_expiry_dates = temp_matches
                    logger.info(f"Found matches with alternative pattern: {alt_pattern}")
                    break
        
        # Convert to sorted list (sort by date, not alphabetically)
        from datetime import datetime
        
        def sort_expiry_dates(date_list):
            """Sort expiry dates chronologically"""
            def parse_date(date_str):
                try:
                    # Parse date format like "31-JUL-25" 
                    return datetime.strptime(date_str, "%d-%b-%y")
                except ValueError:
                    try:
                        # Try alternative format like "31-JUL-2025"
                        return datetime.strptime(date_str, "%d-%b-%Y")
                    except ValueError:
                        # If parsing fails, return a very distant future date to put unparseable dates at the end
                        logger.warning(f"Could not parse expiry date: {date_str}, placing at end of list")
                        return datetime.max
            
            # Sort by parsed date
            return sorted(date_list, key=parse_date)
        
        expiry_dates = sort_expiry_dates(list(filtered_expiry_dates))
        
        logger.info(f"Found {len(expiry_dates)} expiry dates for symbol: {symbol}")
        
        return True, {
            'status': 'success',
            'message': f'Found {len(expiry_dates)} expiry dates for {symbol} {instrumenttype} in {exchange}',
            'data': expiry_dates
        }, 200
        
    except Exception as e:
        logger.exception(f"Error in get_expiry_dates: {e}")
        return False, {
            'status': 'error',
            'message': 'An error occurred while fetching expiry dates'
        }, 500