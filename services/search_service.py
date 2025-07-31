from database.symbol import enhanced_search_symbols
from database.auth_db import verify_api_key
from utils.logging import get_logger
from typing import Tuple, Dict, Any, List

logger = get_logger(__name__)

def search_symbols(query: str, exchange: str = None, api_key: str = None) -> Tuple[bool, Dict[str, Any], int]:
    """
    Search for symbols in the database
    
    Args:
        query: Search query/symbol name
        exchange: Optional exchange filter (NSE, BSE, etc.)
        api_key: API key for authentication
    
    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Validate API key if provided
        if api_key:
            user_id = verify_api_key(api_key)
            if not user_id:
                logger.warning(f"Invalid API key provided for search")
                return False, {
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }, 403
        
        # Validate input
        if not query or not query.strip():
            logger.warning("Empty search query provided")
            return False, {
                'status': 'error',
                'message': 'Query parameter is required and cannot be empty'
            }, 400
        
        query = query.strip()
        logger.info(f"Searching symbols for query: {query}, exchange: {exchange}")
        
        # Perform the search
        results = enhanced_search_symbols(query, exchange)
        
        if not results:
            logger.info(f"No results found for query: {query}")
            return True, {
                'status': 'success',
                'message': 'No matching symbols found',
                'data': []
            }, 200
        
        # Convert results to dict format
        results_data = []
        for result in results:
            result_dict = {
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
            results_data.append(result_dict)
        
        logger.info(f"Found {len(results_data)} results for query: {query}")
        
        return True, {
            'status': 'success',
            'message': f'Found {len(results_data)} matching symbols',
            'data': results_data
        }, 200
        
    except Exception as e:
        logger.exception(f"Error in search_symbols: {e}")
        return False, {
            'status': 'error',
            'message': 'An error occurred while searching symbols'
        }, 500