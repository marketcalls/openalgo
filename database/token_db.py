"""
Token Database Module - Enhanced with Full Memory Cache
This module provides the same API as before but now uses intelligent in-memory caching
for 100,000+ symbols with O(1) lookup performance.

All existing code will continue to work without any changes.
"""

# Import all functions from the enhanced module
# This makes the enhanced cache transparent to existing code
from database.token_db_enhanced import (
    get_token,
    get_symbol,
    get_oa_symbol,
    get_br_symbol,
    get_brexchange,
    get_symbol_count,
    # Additional functions for backward compatibility
    get_token_dbquery,
    get_symbol_dbquery,
    get_oa_symbol_dbquery,
    get_br_symbol_dbquery,
    get_brexchange_dbquery,
    # New bulk operations (optional - won't break existing code)
    get_tokens_bulk,
    get_symbols_bulk,
    search_symbols,
    # Cache management (optional - won't break existing code)
    load_cache_for_broker,
    clear_cache,
    get_cache_stats
)

# For complete backward compatibility, also expose the old cache variable
# (though it's not used anymore, some code might reference it)
from cachetools import TTLCache
token_cache = TTLCache(maxsize=1024, ttl=3600)  # Dummy cache for compatibility

# Re-export everything so imports work identically
__all__ = [
    'get_token',
    'get_symbol',
    'get_oa_symbol',
    'get_br_symbol',
    'get_brexchange',
    'get_symbol_count',
    'get_token_dbquery',
    'get_symbol_dbquery',
    'get_oa_symbol_dbquery',
    'get_br_symbol_dbquery',
    'get_brexchange_dbquery',
    'token_cache',  # For backward compatibility
    # New functions (won't affect existing code)
    'get_tokens_bulk',
    'get_symbols_bulk',
    'search_symbols',
    'load_cache_for_broker',
    'clear_cache',
    'get_cache_stats'
]