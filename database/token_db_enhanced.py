"""
Enhanced Token DB with Full Memory Caching for 100,000+ symbols
Optimized for zero-config deployment with configurable session reset time (SESSION_EXPIRY_TIME)
"""

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import time
from dataclasses import dataclass, field
from collections import defaultdict
import pytz
from utils.logging import get_logger

logger = get_logger(__name__)

@dataclass
class CacheStats:
    """Statistics for cache performance monitoring"""
    hits: int = 0
    misses: int = 0
    db_queries: int = 0
    bulk_queries: int = 0
    cache_loads: int = 0
    last_loaded: Optional[datetime] = None
    total_symbols: int = 0
    memory_usage_mb: float = 0.0
    
    def get_hit_rate(self) -> float:
        """Calculate cache hit rate"""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0
    
    def to_dict(self) -> dict:
        """Convert stats to dictionary for API response"""
        return {
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': f"{self.get_hit_rate():.2f}%",
            'db_queries': self.db_queries,
            'bulk_queries': self.bulk_queries,
            'cache_loads': self.cache_loads,
            'last_loaded': self.last_loaded.isoformat() if self.last_loaded else None,
            'total_symbols': self.total_symbols,
            'memory_usage_mb': f"{self.memory_usage_mb:.2f}"
        }

@dataclass
class SymbolData:
    """Lightweight symbol data structure for in-memory storage"""
    symbol: str
    brsymbol: str
    name: str
    exchange: str
    brexchange: str
    token: str
    expiry: Optional[str] = None
    strike: Optional[float] = None
    lotsize: Optional[int] = None
    instrumenttype: Optional[str] = None
    tick_size: Optional[float] = None

class BrokerSymbolCache:
    """
    High-performance in-memory cache for broker symbols
    Designed to handle 100,000+ symbols with minimal memory footprint
    """
    
    def __init__(self):
        # Active broker context
        self.active_broker: Optional[str] = None
        self.cache_loaded: bool = False
        
        # Primary storage - all symbols in memory
        self.symbols: Dict[str, SymbolData] = {}
        
        # Multi-index maps for O(1) lookups
        self.by_symbol_exchange: Dict[Tuple[str, str], SymbolData] = {}
        self.by_token_exchange: Dict[Tuple[str, str], SymbolData] = {}
        self.by_brsymbol_exchange: Dict[Tuple[str, str], SymbolData] = {}
        self.by_token: Dict[str, SymbolData] = {}
        
        # Cache statistics
        self.stats = CacheStats()
        
        # Session management
        self.session_start: Optional[datetime] = None
        self.next_reset_time: Optional[datetime] = None
        
        logger.info("BrokerSymbolCache initialized")
    
    def load_all_symbols(self, broker: str) -> bool:
        """
        Load all symbols for the active broker into memory
        This is called once after master contract download
        """
        try:
            from database.symbol import SymToken
            
            start_time = time.time()
            logger.info(f"Loading all symbols for broker: {broker}")
            
            # Clear existing cache
            self.clear_cache()
            
            # Query all symbols from database
            symbols = SymToken.query.all()
            
            if not symbols:
                logger.warning(f"No symbols found in database for broker: {broker}")
                return False
            
            # Build in-memory structures
            for sym in symbols:
                # Create lightweight data object
                symbol_data = SymbolData(
                    symbol=sym.symbol,
                    brsymbol=sym.brsymbol,
                    name=sym.name,
                    exchange=sym.exchange,
                    brexchange=sym.brexchange,
                    token=sym.token,
                    expiry=sym.expiry,
                    strike=sym.strike,
                    lotsize=sym.lotsize,
                    instrumenttype=sym.instrumenttype,
                    tick_size=sym.tick_size
                )
                
                # Store in primary dict
                self.symbols[sym.token] = symbol_data
                
                # Build indexes
                self.by_symbol_exchange[(sym.symbol, sym.exchange)] = symbol_data
                self.by_token_exchange[(sym.token, sym.exchange)] = symbol_data
                self.by_brsymbol_exchange[(sym.brsymbol, sym.exchange)] = symbol_data
                self.by_token[sym.token] = symbol_data
            
            # Update cache metadata
            self.active_broker = broker
            self.cache_loaded = True
            self.stats.total_symbols = len(symbols)
            self.stats.cache_loads += 1
            self.stats.last_loaded = datetime.now(pytz.timezone('Asia/Kolkata'))
            
            # Calculate memory usage (rough estimate)
            self.stats.memory_usage_mb = (
                len(self.symbols) * 500  # ~500 bytes per symbol
            ) / (1024 * 1024)
            
            load_time = time.time() - start_time
            logger.info(
                f"Successfully loaded {self.stats.total_symbols} symbols "
                f"in {load_time:.2f} seconds. "
                f"Memory usage: {self.stats.memory_usage_mb:.2f} MB"
            )
            
            # Set session timing
            self._set_session_timing()
            
            return True
            
        except Exception as e:
            logger.error(f"Error loading symbols into cache: {e}")
            return False
    
    def _set_session_timing(self):
        """Set session start and next reset time from SESSION_EXPIRY_TIME env variable"""
        import os
        now_ist = datetime.now(pytz.timezone('Asia/Kolkata'))
        self.session_start = now_ist
        
        # Get session expiry time from environment (default to 3:00 if not set)
        expiry_time = os.getenv('SESSION_EXPIRY_TIME', '03:00')
        try:
            hour, minute = map(int, expiry_time.split(':'))
        except ValueError:
            logger.warning(f"Invalid SESSION_EXPIRY_TIME format: {expiry_time}. Using default 03:00")
            hour, minute = 3, 0
        
        # Calculate next expiry time
        next_reset = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_ist >= next_reset:
            next_reset += timedelta(days=1)
        
        self.next_reset_time = next_reset
        logger.info(f"Cache valid until: {self.next_reset_time} (Session expiry: {expiry_time})")
    
    def is_cache_valid(self) -> bool:
        """Check if cache is still valid (before session expiry reset)"""
        if not self.cache_loaded or not self.next_reset_time:
            return False
        
        now_ist = datetime.now(pytz.timezone('Asia/Kolkata'))
        return now_ist < self.next_reset_time
    
    def get_token(self, symbol: str, exchange: str) -> Optional[str]:
        """Get token for symbol and exchange - O(1) lookup"""
        self.stats.hits += 1
        key = (symbol, exchange)
        if key in self.by_symbol_exchange:
            return self.by_symbol_exchange[key].token
        
        self.stats.hits -= 1
        self.stats.misses += 1
        return None
    
    def get_symbol(self, token: str, exchange: str) -> Optional[str]:
        """Get symbol for token and exchange - O(1) lookup"""
        self.stats.hits += 1
        key = (token, exchange)
        if key in self.by_token_exchange:
            return self.by_token_exchange[key].symbol
        
        self.stats.hits -= 1
        self.stats.misses += 1
        return None
    
    def get_br_symbol(self, symbol: str, exchange: str) -> Optional[str]:
        """Get broker symbol for symbol and exchange - O(1) lookup"""
        self.stats.hits += 1
        key = (symbol, exchange)
        if key in self.by_symbol_exchange:
            return self.by_symbol_exchange[key].brsymbol
        
        self.stats.hits -= 1
        self.stats.misses += 1
        return None
    
    def get_oa_symbol(self, brsymbol: str, exchange: str) -> Optional[str]:
        """Get OpenAlgo symbol for broker symbol and exchange - O(1) lookup"""
        self.stats.hits += 1
        key = (brsymbol, exchange)
        if key in self.by_brsymbol_exchange:
            return self.by_brsymbol_exchange[key].symbol
        
        self.stats.hits -= 1
        self.stats.misses += 1
        return None
    
    def get_brexchange(self, symbol: str, exchange: str) -> Optional[str]:
        """Get broker exchange for symbol and exchange - O(1) lookup"""
        self.stats.hits += 1
        key = (symbol, exchange)
        if key in self.by_symbol_exchange:
            return self.by_symbol_exchange[key].brexchange
        
        self.stats.hits -= 1
        self.stats.misses += 1
        return None
    
    def get_symbol_data(self, token: str) -> Optional[SymbolData]:
        """Get complete symbol data by token - O(1) lookup"""
        self.stats.hits += 1
        if token in self.by_token:
            return self.by_token[token]
        
        self.stats.hits -= 1
        self.stats.misses += 1
        return None
    
    def get_tokens_bulk(self, symbol_exchange_pairs: List[Tuple[str, str]]) -> List[Optional[str]]:
        """
        Bulk retrieve tokens for multiple symbol-exchange pairs
        Optimized for performance with single pass
        """
        self.stats.bulk_queries += 1
        results = []
        
        for symbol, exchange in symbol_exchange_pairs:
            key = (symbol, exchange)
            if key in self.by_symbol_exchange:
                results.append(self.by_symbol_exchange[key].token)
                self.stats.hits += 1
            else:
                results.append(None)
                self.stats.misses += 1
        
        return results
    
    def get_symbols_bulk(self, token_exchange_pairs: List[Tuple[str, str]]) -> List[Optional[str]]:
        """
        Bulk retrieve symbols for multiple token-exchange pairs
        """
        self.stats.bulk_queries += 1
        results = []
        
        for token, exchange in token_exchange_pairs:
            key = (token, exchange)
            if key in self.by_token_exchange:
                results.append(self.by_token_exchange[key].symbol)
                self.stats.hits += 1
            else:
                results.append(None)
                self.stats.misses += 1
        
        return results
    
    def search_symbols(self, query: str, exchange: Optional[str] = None, limit: int = 50) -> List[SymbolData]:
        """
        Search symbols by partial match
        Returns list of matching SymbolData objects
        """
        query = query.upper()
        matches = []
        
        for symbol_data in self.symbols.values():
            # Skip if exchange filter doesn't match
            if exchange and symbol_data.exchange != exchange:
                continue
            
            # Check for match in symbol, brsymbol, or name
            if (query in symbol_data.symbol.upper() or 
                query in symbol_data.brsymbol.upper() or 
                (symbol_data.name and query in symbol_data.name.upper())):
                matches.append(symbol_data)
                
                if len(matches) >= limit:
                    break
        
        return matches
    
    def clear_cache(self):
        """Clear all cached data"""
        self.symbols.clear()
        self.by_symbol_exchange.clear()
        self.by_token_exchange.clear()
        self.by_brsymbol_exchange.clear()
        self.by_token.clear()
        self.cache_loaded = False
        self.active_broker = None
        logger.info("Cache cleared")
    
    def get_cache_info(self) -> dict:
        """Get cache information for monitoring"""
        return {
            'active_broker': self.active_broker,
            'cache_loaded': self.cache_loaded,
            'total_symbols': self.stats.total_symbols,
            'cache_valid': self.is_cache_valid(),
            'session_start': self.session_start.isoformat() if self.session_start else None,
            'next_reset': self.next_reset_time.isoformat() if self.next_reset_time else None,
            'stats': self.stats.to_dict()
        }

# Global cache instance (singleton pattern)
_cache_instance: Optional[BrokerSymbolCache] = None

def get_cache() -> BrokerSymbolCache:
    """Get or create the global cache instance"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = BrokerSymbolCache()
    return _cache_instance

# Public API - Drop-in replacement for existing token_db functions
def get_token(symbol: str, exchange: str) -> Optional[str]:
    """
    Get token for a given symbol and exchange
    First checks cache, falls back to database if needed
    """
    cache = get_cache()
    
    # Check if cache is loaded and valid
    if cache.cache_loaded and cache.is_cache_valid():
        result = cache.get_token(symbol, exchange)
        if result is not None:
            return result
    
    # Fallback to database query
    cache.stats.db_queries += 1
    return get_token_dbquery(symbol, exchange)

def get_symbol(token: str, exchange: str) -> Optional[str]:
    """
    Get symbol for a given token and exchange
    """
    cache = get_cache()
    
    if cache.cache_loaded and cache.is_cache_valid():
        result = cache.get_symbol(token, exchange)
        if result is not None:
            return result
    
    cache.stats.db_queries += 1
    return get_symbol_dbquery(token, exchange)

def get_br_symbol(symbol: str, exchange: str) -> Optional[str]:
    """
    Get broker symbol for a given symbol and exchange
    """
    cache = get_cache()
    
    if cache.cache_loaded and cache.is_cache_valid():
        result = cache.get_br_symbol(symbol, exchange)
        if result is not None:
            return result
    
    cache.stats.db_queries += 1
    return get_br_symbol_dbquery(symbol, exchange)

def get_oa_symbol(brsymbol: str, exchange: str) -> Optional[str]:
    """
    Get OpenAlgo symbol for a given broker symbol and exchange
    """
    cache = get_cache()
    
    if cache.cache_loaded and cache.is_cache_valid():
        result = cache.get_oa_symbol(brsymbol, exchange)
        if result is not None:
            return result
    
    cache.stats.db_queries += 1
    return get_oa_symbol_dbquery(brsymbol, exchange)

def get_brexchange(symbol: str, exchange: str) -> Optional[str]:
    """
    Get broker exchange for a given symbol and exchange
    """
    cache = get_cache()
    
    if cache.cache_loaded and cache.is_cache_valid():
        result = cache.get_brexchange(symbol, exchange)
        if result is not None:
            return result
    
    cache.stats.db_queries += 1
    return get_brexchange_dbquery(symbol, exchange)

# Database fallback functions (imported from original token_db)
def get_token_dbquery(symbol: str, exchange: str) -> Optional[str]:
    """Query database for token by symbol and exchange"""
    try:
        from database.symbol import SymToken
        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            return sym_token.token
        else:
            return None
    except Exception as e:
        logger.error(f"Error while querying the database: {e}")
        return None

def get_symbol_dbquery(token: str, exchange: str) -> Optional[str]:
    """Query database for symbol by token and exchange"""
    try:
        from database.symbol import SymToken
        sym_token = SymToken.query.filter_by(token=token, exchange=exchange).first()
        if sym_token:
            return sym_token.symbol
        else:
            return None
    except Exception as e:
        logger.error(f"Error while querying the database: {e}")
        return None

def get_br_symbol_dbquery(symbol: str, exchange: str) -> Optional[str]:
    """Query database for broker symbol"""
    try:
        from database.symbol import SymToken
        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            return sym_token.brsymbol
        else:
            return None
    except Exception as e:
        logger.error(f"Error while querying the database: {e}")
        return None

def get_oa_symbol_dbquery(brsymbol: str, exchange: str) -> Optional[str]:
    """Query database for OpenAlgo symbol"""
    try:
        from database.symbol import SymToken
        sym_token = SymToken.query.filter_by(brsymbol=brsymbol, exchange=exchange).first()
        if sym_token:
            return sym_token.symbol
        else:
            return None
    except Exception as e:
        logger.error(f"Error while querying the database: {e}")
        return None

def get_brexchange_dbquery(symbol: str, exchange: str) -> Optional[str]:
    """Query database for broker exchange"""
    try:
        from database.symbol import SymToken
        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            return sym_token.brexchange
        else:
            return None
    except Exception as e:
        logger.error(f"Error while querying the database: {e}")
        return None

def get_symbol_count() -> int:
    """Get the total count of symbols in the database"""
    try:
        from database.symbol import SymToken
        count = SymToken.query.count()
        return count
    except Exception as e:
        logger.error(f"Error while counting symbols: {e}")
        return 0

# Cache management functions
def load_cache_for_broker(broker: str) -> bool:
    """
    Load cache for a specific broker
    Called after master contract download completes
    """
    cache = get_cache()
    return cache.load_all_symbols(broker)

def clear_cache():
    """Clear the cache - useful for manual refresh"""
    cache = get_cache()
    cache.clear_cache()

def get_cache_stats() -> dict:
    """Get cache statistics for monitoring"""
    cache = get_cache()
    return cache.get_cache_info()

# Bulk operations for performance
def get_tokens_bulk(symbol_exchange_pairs: List[Tuple[str, str]]) -> List[Optional[str]]:
    """Bulk retrieve tokens - optimized for performance"""
    cache = get_cache()
    
    if cache.cache_loaded and cache.is_cache_valid():
        return cache.get_tokens_bulk(symbol_exchange_pairs)
    
    # Fallback to individual queries
    results = []
    for symbol, exchange in symbol_exchange_pairs:
        cache.stats.db_queries += 1
        results.append(get_token_dbquery(symbol, exchange))
    return results

def get_symbols_bulk(token_exchange_pairs: List[Tuple[str, str]]) -> List[Optional[str]]:
    """Bulk retrieve symbols - optimized for performance"""
    cache = get_cache()
    
    if cache.cache_loaded and cache.is_cache_valid():
        return cache.get_symbols_bulk(token_exchange_pairs)
    
    # Fallback to individual queries
    results = []
    for token, exchange in token_exchange_pairs:
        cache.stats.db_queries += 1
        results.append(get_symbol_dbquery(token, exchange))
    return results

# Search functionality
def search_symbols(query: str, exchange: Optional[str] = None, limit: int = 50) -> List[dict]:
    """
    Search symbols with cache support
    Returns list of symbol dictionaries
    """
    cache = get_cache()
    
    if cache.cache_loaded and cache.is_cache_valid():
        results = cache.search_symbols(query, exchange, limit)
        return [
            {
                'symbol': s.symbol,
                'brsymbol': s.brsymbol,
                'name': s.name,
                'exchange': s.exchange,
                'token': s.token,
                'instrumenttype': s.instrumenttype
            }
            for s in results
        ]
    
    # Fallback to database search
    try:
        from database.symbol import SymToken
        query_obj = SymToken.query.filter(SymToken.symbol.like(f'%{query}%'))
        if exchange:
            query_obj = query_obj.filter_by(exchange=exchange)
        
        results = query_obj.limit(limit).all()
        return [
            {
                'symbol': r.symbol,
                'brsymbol': r.brsymbol,
                'name': r.name,
                'exchange': r.exchange,
                'token': r.token,
                'instrumenttype': r.instrumenttype
            }
            for r in results
        ]
    except Exception as e:
        logger.error(f"Error searching symbols: {e}")
        return []