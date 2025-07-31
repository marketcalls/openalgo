import traceback
from typing import Tuple, Dict, Any, Optional

from database.auth_db import get_auth_token_broker
from database.symbol import SymToken, db_session
from sqlalchemy.orm.exc import NoResultFound
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

def get_symbol_info_with_auth(
    symbol: str,
    exchange: str,
    auth_token: str,
    broker: str
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get symbol information using provided auth token.
    
    Args:
        symbol: Symbol to look up
        exchange: Exchange to look up the symbol in
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    try:
        # Query the database for the symbol
        result = db_session.query(SymToken).filter(
            SymToken.symbol == symbol,
            SymToken.exchange == exchange
        ).first()
        
        if result is None:
            error_response = {
                'status': 'error',
                'message': f'Symbol {symbol} not found in exchange {exchange}'
            }
            return False, error_response, 404
        
        # Transform the SymToken object to a dictionary
        symbol_info = {
            'id': result.id,
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
        
        response_data = {
            'data': symbol_info,
            'status': 'success'
        }
        
        return True, response_data, 200
        
    except NoResultFound:
        error_response = {
            'status': 'error',
            'message': f'Symbol {symbol} not found in exchange {exchange}'
        }
        return False, error_response, 404
        
    except Exception as e:
        logger.error(f"Error retrieving symbol information: {e}")
        traceback.print_exc()
        error_response = {
            'status': 'error',
            'message': str(e)
        }
        return False, error_response, 500

def get_symbol_info(
    symbol: str,
    exchange: str,
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get symbol information for a given symbol and exchange.
    Supports both API-based authentication and direct internal calls.
    
    Args:
        symbol: Symbol to look up
        exchange: Exchange to look up the symbol in
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {
                'status': 'error',
                'message': 'Invalid openalgo apikey'
            }
            return False, error_response, 403
        
        return get_symbol_info_with_auth(symbol, exchange, AUTH_TOKEN, broker_name)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_symbol_info_with_auth(symbol, exchange, auth_token, broker)
    
    # Case 3: No authentication required for this endpoint
    # Symbol information can be accessed without authentication
    elif not api_key and not auth_token and not broker:
        # Use a dummy auth token and broker since they're not used in the actual implementation
        return get_symbol_info_with_auth(symbol, exchange, "", "")
    
    # Case 4: Invalid parameters
    else:
        error_response = {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }
        return False, error_response, 400
