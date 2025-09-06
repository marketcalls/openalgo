# Original token_db.py - Backup copy
from database.symbol import SymToken  # Import here to avoid circular imports
from cachetools import TTLCache
from utils.logging import get_logger

logger = get_logger(__name__)

# Define a cache for the tokens, symbols with a max size and a 3600-second TTL
token_cache = TTLCache(maxsize=1024, ttl=3600)

def get_token(symbol, exchange):
    """
    Retrieves a token for a given symbol and exchange, utilizing a cache to improve performance.
    """
    cache_key = f"{symbol}-{exchange}"
    # Attempt to retrieve from cache
    if cache_key in token_cache:
        return token_cache[cache_key]
    else:
        # Query database if not in cache
        token = get_token_dbquery(symbol, exchange)
        # Cache the result for future requests
        if token is not None:
            token_cache[cache_key] = token
        return token

def get_token_dbquery(symbol, exchange):
    """
    Queries the database for a token by symbol and exchange.
    """
    
    try:
        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            return sym_token.token
        else:
            return None
    except Exception as e:
        logger.error(f"Error while querying the database: {e}")
        return None
    


def get_symbol(token, exchange):
    """
    Retrieves a symbol for a given token and exchange, utilizing a cache to improve performance.
    """
    cache_key = f"{token}-{exchange}"
    # Attempt to retrieve from cache
    if cache_key in token_cache:
        return token_cache[cache_key]
    else:
        # Query database if not in cache
        symbol = get_symbol_dbquery(token, exchange)
        # Cache the result for future requests
        if symbol is not None:
            token_cache[cache_key] = symbol
        return symbol

def get_symbol_dbquery(token, exchange):
    """
    Queries the database for a symbol by token and exchange.
    """
    try:
        sym_token = SymToken.query.filter_by(token=token, exchange=exchange).first()
        if sym_token:
            return sym_token.symbol
        else:
            return None
    except Exception as e:
        logger.error(f"Error while querying the database: {e}")
        return None


def get_oa_symbol(symbol, exchange):
    """
    Retrieves a symbol for a given token and exchange, utilizing a cache to improve performance.
    """
    cache_key = f"oa{symbol}-{exchange}"
    # Attempt to retrieve from cache
    if cache_key in token_cache:
        return token_cache[cache_key]
    else:
        # Query database if not in cache
        oasymbol = get_oa_symbol_dbquery(symbol, exchange)
        # Cache the result for future requests
        if oasymbol is not None:
            token_cache[cache_key] = oasymbol
        return oasymbol

def get_oa_symbol_dbquery(symbol, exchange):
    """
    Queries the database for a symbol by token and exchange.
    """
    try:
        sym_token = SymToken.query.filter_by(brsymbol=symbol, exchange=exchange).first()
        if sym_token:
            return sym_token.symbol
        else:
            return None
    except Exception as e:
        logger.error(f"Error while querying the database: {e}")
        return None

def get_symbol_count():
    """
    Get the total count of symbols in the database.
    """
    try:
        count = SymToken.query.count()
        return count
    except Exception as e:
        logger.error(f"Error while counting symbols: {e}")
        return 0


def get_br_symbol(symbol, exchange):
    """
    Retrieves a symbol for a given token and exchange, utilizing a cache to improve performance.
    """
    cache_key = f"br{symbol}-{exchange}"
    # Attempt to retrieve from cache
    if cache_key in token_cache:
        return token_cache[cache_key]
    else:
        # Query database if not in cache
        brsymbol = get_br_symbol_dbquery(symbol, exchange)
        # Cache the result for future requests
        if brsymbol is not None:
            token_cache[cache_key] = brsymbol
        return brsymbol

def get_br_symbol_dbquery(symbol, exchange):
    """
    Queries the database for a symbol by token and exchange.
    """
    try:
        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            return sym_token.brsymbol
        else:
            return None
    except Exception as e:
        logger.error(f"Error while querying the database: {e}")
        return None

def get_brexchange(symbol, exchange):
    """
    Retrieves the broker exchange for a given symbol and exchange, utilizing a cache to improve performance.
    """
    cache_key = f"brex-{symbol}-{exchange}"
    # Attempt to retrieve from cache
    if cache_key in token_cache:
        return token_cache[cache_key]
    else:
        # Query database if not in cache
        brexchange = get_brexchange_dbquery(symbol, exchange)
        # Cache the result for future requests
        if brexchange is not None:
            token_cache[cache_key] = brexchange
        return brexchange

def get_brexchange_dbquery(symbol, exchange):
    """
    Queries the database for a broker exchange by symbol and exchange.
    """
    try:
        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            return sym_token.brexchange
        else:
            return None
    except Exception as e:
        logger.error(f"Error while querying the database: {e}")
        return None