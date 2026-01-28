"""
Enhanced Token DB with Full Memory Caching for 100,000+ symbols
Optimized for zero-config deployment with configurable session reset time (SESSION_EXPIRY_TIME)
"""

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz

from utils.logging import get_logger

logger = get_logger(__name__)

# FNO exchanges that have derivatives
FNO_EXCHANGES = {"NFO", "BFO", "MCX", "CDS"}

# Regex pattern to extract underlying from OpenAlgo symbol format
# Format: [BaseSymbol][DDMMMYY][StrikePrice][CE/PE] or [BaseSymbol][DDMMMYY]FUT
# Examples: NIFTY28MAR2420800CE, BANKNIFTY24APR24FUT, CRUDEOIL17APR246750CE
_UNDERLYING_PATTERN = re.compile(
    r"^(.+?)"  # Underlying (non-greedy capture)
    r"(\d{2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2})"  # Date: DDMMMYY
    r"(?:\d+(?:\.\d+)?)?(?:FUT|CE|PE)?$",  # Optional strike + FUT/CE/PE
    re.IGNORECASE,
)


def extract_underlying_from_symbol(symbol: str, exchange: str) -> str | None:
    """
    Extract underlying name from OpenAlgo symbol format.

    OpenAlgo symbol formats:
    - Futures: [BaseSymbol][DDMMMYY]FUT (e.g., BANKNIFTY24APR24FUT -> BANKNIFTY)
    - Options: [BaseSymbol][DDMMMYY][Strike][CE/PE] (e.g., NIFTY28MAR2420800CE -> NIFTY)

    Args:
        symbol: OpenAlgo formatted symbol
        exchange: Exchange code (NFO, BFO, MCX, CDS, etc.)

    Returns:
        Underlying name or None if not extractable
    """
    if not symbol or exchange not in FNO_EXCHANGES:
        return None

    match = _UNDERLYING_PATTERN.match(symbol.upper())
    if match:
        return match.group(1)

    return None


@dataclass
class CacheStats:
    """Statistics for cache performance monitoring"""

    hits: int = 0
    misses: int = 0
    db_queries: int = 0
    bulk_queries: int = 0
    cache_loads: int = 0
    last_loaded: datetime | None = None
    total_symbols: int = 0
    memory_usage_mb: float = 0.0

    def get_hit_rate(self) -> float:
        """Calculate cache hit rate"""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    def to_dict(self) -> dict:
        """Convert stats to dictionary for API response"""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{self.get_hit_rate():.2f}%",
            "db_queries": self.db_queries,
            "bulk_queries": self.bulk_queries,
            "cache_loads": self.cache_loads,
            "last_loaded": self.last_loaded.isoformat() if self.last_loaded else None,
            "total_symbols": self.total_symbols,
            "memory_usage_mb": f"{self.memory_usage_mb:.2f}",
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
    expiry: str | None = None
    strike: float | None = None
    lotsize: int | None = None
    instrumenttype: str | None = None
    tick_size: float | None = None
    underlying: str | None = None  # Extracted from OpenAlgo symbol format for F&O


class BrokerSymbolCache:
    """
    High-performance in-memory cache for broker symbols
    Designed to handle 100,000+ symbols with minimal memory footprint
    """

    def __init__(self):
        # Active broker context
        self.active_broker: str | None = None
        self.cache_loaded: bool = False

        # Primary storage - all symbols in memory
        self.symbols: dict[str, SymbolData] = {}

        # Multi-index maps for O(1) lookups
        self.by_symbol_exchange: dict[tuple[str, str], SymbolData] = {}
        self.by_token_exchange: dict[tuple[str, str], SymbolData] = {}
        self.by_brsymbol_exchange: dict[tuple[str, str], SymbolData] = {}
        self.by_token: dict[str, SymbolData] = {}

        # Pre-computed indexes for FNO filter performance (O(1) lookups)
        self.by_exchange: dict[str, list[SymbolData]] = defaultdict(list)
        self.expiries_by_exchange: dict[str, set[str]] = defaultdict(set)
        self.underlyings_by_exchange: dict[str, set[str]] = defaultdict(set)
        self.expiries_by_exchange_underlying: dict[tuple[str, str], set[str]] = defaultdict(set)

        # Cache statistics
        self.stats = CacheStats()

        # Session management
        self.session_start: datetime | None = None
        self.next_reset_time: datetime | None = None

        logger.debug("BrokerSymbolCache initialized")

    def load_all_symbols(self, broker: str) -> bool:
        """
        Load all symbols for the active broker into memory
        This is called once after master contract download
        """
        try:
            from database.symbol import SymToken

            start_time = time.time()
            logger.debug(f"Loading all symbols for broker: {broker}")

            # Clear existing cache
            self.clear_cache()

            # Query all symbols from database
            symbols = SymToken.query.all()

            if not symbols:
                logger.warning(f"No symbols found in database for broker: {broker}")
                return False

            # Build in-memory structures
            for sym in symbols:
                # Extract underlying from OpenAlgo symbol format for FNO exchanges
                underlying = None
                if sym.exchange in FNO_EXCHANGES:
                    underlying = extract_underlying_from_symbol(sym.symbol, sym.exchange)

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
                    tick_size=sym.tick_size,
                    underlying=underlying,
                )

                # Store in primary dict
                self.symbols[sym.token] = symbol_data

                # Build indexes
                self.by_symbol_exchange[(sym.symbol, sym.exchange)] = symbol_data
                self.by_token_exchange[(sym.token, sym.exchange)] = symbol_data
                self.by_brsymbol_exchange[(sym.brsymbol, sym.exchange)] = symbol_data
                self.by_token[sym.token] = symbol_data

                # Build FNO filter indexes for O(1) lookups
                self.by_exchange[sym.exchange].append(symbol_data)
                if sym.expiry:
                    self.expiries_by_exchange[sym.exchange].add(sym.expiry)
                    # Use extracted underlying for index (more reliable than broker's name field)
                    if underlying:
                        self.expiries_by_exchange_underlying[(sym.exchange, underlying)].add(sym.expiry)
                # Use extracted underlying for underlyings index
                if underlying:
                    self.underlyings_by_exchange[sym.exchange].add(underlying)

            # Update cache metadata
            self.active_broker = broker
            self.cache_loaded = True
            self.stats.total_symbols = len(symbols)
            self.stats.cache_loads += 1
            self.stats.last_loaded = datetime.now(pytz.timezone("Asia/Kolkata"))

            # Calculate memory usage (rough estimate)
            self.stats.memory_usage_mb = (
                len(self.symbols) * 500  # ~500 bytes per symbol
            ) / (1024 * 1024)

            load_time = time.time() - start_time
            logger.debug(
                f"Successfully loaded {self.stats.total_symbols} symbols "
                f"in {load_time:.2f} seconds. "
                f"Memory usage: {self.stats.memory_usage_mb:.2f} MB"
            )

            # Set session timing
            self._set_session_timing()

            return True

        except Exception as e:
            logger.exception(f"Error loading symbols into cache: {e}")
            return False

    def _set_session_timing(self):
        """Set session start and next reset time from SESSION_EXPIRY_TIME env variable"""
        import os

        now_ist = datetime.now(pytz.timezone("Asia/Kolkata"))
        self.session_start = now_ist

        # Get session expiry time from environment (default to 3:00 if not set)
        expiry_time = os.getenv("SESSION_EXPIRY_TIME", "03:00")
        try:
            hour, minute = map(int, expiry_time.split(":"))
        except ValueError:
            logger.warning(
                f"Invalid SESSION_EXPIRY_TIME format: {expiry_time}. Using default 03:00"
            )
            hour, minute = 3, 0

        # Calculate next expiry time
        next_reset = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_ist >= next_reset:
            next_reset += timedelta(days=1)

        self.next_reset_time = next_reset
        logger.debug(f"Cache valid until: {self.next_reset_time} (Session expiry: {expiry_time})")

    def is_cache_valid(self) -> bool:
        """Check if cache is still valid (before session expiry reset)"""
        if not self.cache_loaded or not self.next_reset_time:
            return False

        now_ist = datetime.now(pytz.timezone("Asia/Kolkata"))
        return now_ist < self.next_reset_time

    def get_token(self, symbol: str, exchange: str) -> str | None:
        """Get token for symbol and exchange - O(1) lookup"""
        self.stats.hits += 1
        key = (symbol, exchange)
        if key in self.by_symbol_exchange:
            return self.by_symbol_exchange[key].token

        self.stats.hits -= 1
        self.stats.misses += 1
        return None

    def get_symbol(self, token: str, exchange: str) -> str | None:
        """Get symbol for token and exchange - O(1) lookup"""
        self.stats.hits += 1
        key = (token, exchange)
        if key in self.by_token_exchange:
            return self.by_token_exchange[key].symbol

        self.stats.hits -= 1
        self.stats.misses += 1
        return None

    def get_br_symbol(self, symbol: str, exchange: str) -> str | None:
        """Get broker symbol for symbol and exchange - O(1) lookup"""
        self.stats.hits += 1
        key = (symbol, exchange)
        if key in self.by_symbol_exchange:
            return self.by_symbol_exchange[key].brsymbol

        self.stats.hits -= 1
        self.stats.misses += 1
        return None

    def get_oa_symbol(self, brsymbol: str, exchange: str) -> str | None:
        """Get OpenAlgo symbol for broker symbol and exchange - O(1) lookup"""
        self.stats.hits += 1
        key = (brsymbol, exchange)
        if key in self.by_brsymbol_exchange:
            return self.by_brsymbol_exchange[key].symbol

        self.stats.hits -= 1
        self.stats.misses += 1
        return None

    def get_brexchange(self, symbol: str, exchange: str) -> str | None:
        """Get broker exchange for symbol and exchange - O(1) lookup"""
        self.stats.hits += 1
        key = (symbol, exchange)
        if key in self.by_symbol_exchange:
            return self.by_symbol_exchange[key].brexchange

        self.stats.hits -= 1
        self.stats.misses += 1
        return None

    def get_symbol_info(self, symbol: str, exchange: str) -> SymbolData | None:
        """Get full symbol data for symbol and exchange - O(1) lookup"""
        self.stats.hits += 1
        key = (symbol, exchange)
        if key in self.by_symbol_exchange:
            return self.by_symbol_exchange[key]

        self.stats.hits -= 1
        self.stats.misses += 1
        return None

    def get_symbol_data(self, token: str) -> SymbolData | None:
        """Get complete symbol data by token - O(1) lookup"""
        self.stats.hits += 1
        if token in self.by_token:
            return self.by_token[token]

        self.stats.hits -= 1
        self.stats.misses += 1
        return None

    def get_tokens_bulk(self, symbol_exchange_pairs: list[tuple[str, str]]) -> list[str | None]:
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

    def get_symbols_bulk(self, token_exchange_pairs: list[tuple[str, str]]) -> list[str | None]:
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

    def search_symbols(
        self, query: str, exchange: str | None = None, limit: int = 50
    ) -> list[SymbolData]:
        """
        Search symbols by partial match with multi-term support.
        All terms must match (AND logic).
        Returns list of matching SymbolData objects
        Optimized to use exchange index when available
        """
        # Split query into terms
        terms = [term.strip().upper() for term in query.split() if term.strip()]
        if not terms:
            return []

        matches = []

        # Parse numeric terms for strike matching
        num_terms = []
        for term in terms:
            try:
                num_terms.append(float(term))
            except ValueError:
                pass

        # Use exchange index if available - significantly faster
        if exchange and exchange in self.by_exchange:
            symbols_to_search = self.by_exchange[exchange]
        else:
            symbols_to_search = self.symbols.values()

        for symbol_data in symbols_to_search:
            # All terms must match
            all_match = True
            for term in terms:
                term_match = (
                    term in symbol_data.symbol.upper()
                    or term in symbol_data.brsymbol.upper()
                    or (symbol_data.name and term in symbol_data.name.upper())
                    or (symbol_data.token and term in symbol_data.token)
                )
                # Also check numeric terms against strike
                if not term_match and num_terms and symbol_data.strike:
                    try:
                        if float(term) == symbol_data.strike:
                            term_match = True
                    except ValueError:
                        pass

                if not term_match:
                    all_match = False
                    break

            if all_match:
                matches.append(symbol_data)

                if len(matches) >= limit:
                    break

        return matches

    def fno_search_symbols(
        self,
        query: str | None = None,
        exchange: str | None = None,
        expiry: str | None = None,
        instrumenttype: str | None = None,
        strike_min: float | None = None,
        strike_max: float | None = None,
        underlying: str | None = None,
        limit: int = 500,
    ) -> list[SymbolData]:
        """
        FNO-specific search with advanced filters - in-memory cache search
        Optimized to use exchange index for O(n/exchanges) instead of O(n) iteration

        Args:
            query: Optional search query string
            exchange: Exchange filter (NFO, BFO, MCX, CDS)
            expiry: Expiry date filter (e.g., "26-DEC-24")
            instrumenttype: "FUT", "CE", or "PE" (based on symbol suffix)
            strike_min: Minimum strike price
            strike_max: Maximum strike price
            underlying: Underlying symbol name (e.g., "NIFTY")
            limit: Maximum results to return

        Returns:
            List of matching SymbolData objects
        """
        matches = []
        query_upper = query.upper() if query else None
        underlying_upper = underlying.strip().upper() if underlying else None
        expiry_stripped = expiry.strip() if expiry else None
        inst_type = instrumenttype.strip().upper() if instrumenttype else None

        # Parse numeric terms from query for strike matching
        query_terms = []
        query_nums = []
        if query_upper:
            for term in query_upper.split():
                term = term.strip()
                if term:
                    query_terms.append(term)
                    try:
                        query_nums.append(float(term))
                    except ValueError:
                        pass

        # Use exchange index if available - significantly faster for FNO searches
        if exchange and exchange in self.by_exchange:
            symbols_to_search = self.by_exchange[exchange]
        else:
            # Fallback to all symbols if no exchange filter
            symbols_to_search = self.symbols.values()

        for symbol_data in symbols_to_search:
            # Underlying filter (use extracted underlying from OpenAlgo symbol format)
            if underlying_upper and (
                not symbol_data.underlying or symbol_data.underlying != underlying_upper
            ):
                continue

            # Expiry filter
            if expiry_stripped and symbol_data.expiry != expiry_stripped:
                continue

            # Instrument type filter (based on symbol suffix)
            if inst_type:
                symbol_upper = symbol_data.symbol.upper()
                if inst_type == "FUT" and not symbol_upper.endswith("FUT"):
                    continue
                elif inst_type == "CE" and not symbol_upper.endswith("CE"):
                    continue
                elif inst_type == "PE" and not symbol_upper.endswith("PE"):
                    continue

            # Strike range filter
            if strike_min is not None and (
                symbol_data.strike is None or symbol_data.strike < strike_min
            ):
                continue
            if strike_max is not None and (
                symbol_data.strike is None or symbol_data.strike > strike_max
            ):
                continue

            # Query text search (if provided)
            if query_terms:
                # All terms must match
                all_match = True
                for term in query_terms:
                    term_match = (
                        term in symbol_data.symbol.upper()
                        or term in symbol_data.brsymbol.upper()
                        or (symbol_data.name and term in symbol_data.name.upper())
                        or (symbol_data.token and term in symbol_data.token)
                    )
                    if not term_match:
                        all_match = False
                        break

                # Also check numeric terms against strike
                if not all_match and query_nums and symbol_data.strike:
                    for num in query_nums:
                        if symbol_data.strike == num:
                            all_match = True
                            break

                if not all_match:
                    continue

            matches.append(symbol_data)

        # Smart sorting: prioritize exact underlying matches, then alphabetical
        # Extract the primary search term (first term) for relevance scoring
        primary_term = query_terms[0] if query_terms else None

        def sort_key(s):
            # Priority 1: Exact match on underlying (e.g., "NIFTY" matches underlying="NIFTY" exactly)
            underlying_exact = (
                0 if (primary_term and s.underlying and s.underlying == primary_term) else 1
            )

            # Priority 2: Underlying starts with search term (e.g., "NIFTY" before "BANKNIFTY")
            underlying_starts = (
                0 if (primary_term and s.underlying and s.underlying.startswith(primary_term)) else 1
            )

            # Priority 3: Symbol starts with search term
            symbol_starts = 0 if (primary_term and s.symbol.upper().startswith(primary_term)) else 1

            # Priority 4: Alphabetical by symbol
            return (underlying_exact, underlying_starts, symbol_starts, s.symbol)

        matches.sort(key=sort_key)
        return matches[:limit]

    def clear_cache(self):
        """Clear all cached data"""
        self.symbols.clear()
        self.by_symbol_exchange.clear()
        self.by_token_exchange.clear()
        self.by_brsymbol_exchange.clear()
        self.by_token.clear()
        # Clear FNO filter indexes
        self.by_exchange.clear()
        self.expiries_by_exchange.clear()
        self.underlyings_by_exchange.clear()
        self.expiries_by_exchange_underlying.clear()
        self.cache_loaded = False
        self.active_broker = None
        logger.debug("Cache cleared")

    def get_cache_info(self) -> dict:
        """Get cache information for monitoring"""
        return {
            "active_broker": self.active_broker,
            "cache_loaded": self.cache_loaded,
            "total_symbols": self.stats.total_symbols,
            "cache_valid": self.is_cache_valid(),
            "session_start": self.session_start.isoformat() if self.session_start else None,
            "next_reset": self.next_reset_time.isoformat() if self.next_reset_time else None,
            "stats": self.stats.to_dict(),
        }


# Global cache instance (singleton pattern)
_cache_instance: BrokerSymbolCache | None = None


def get_cache() -> BrokerSymbolCache:
    """Get or create the global cache instance"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = BrokerSymbolCache()
    return _cache_instance


# Public API - Drop-in replacement for existing token_db functions
def get_token(symbol: str, exchange: str) -> str | None:
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


def get_symbol(token: str, exchange: str) -> str | None:
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


def get_br_symbol(symbol: str, exchange: str) -> str | None:
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


def get_oa_symbol(brsymbol: str, exchange: str) -> str | None:
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


def get_brexchange(symbol: str, exchange: str) -> str | None:
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


def get_symbol_info(symbol: str, exchange: str) -> SymbolData | None:
    """
    Get full symbol information (SymbolData object) for a given symbol and exchange
    Returns SymbolData with all fields: token, lotsize, strike, expiry, etc.
    First checks cache, falls back to database if needed
    """
    cache = get_cache()

    if cache.cache_loaded and cache.is_cache_valid():
        result = cache.get_symbol_info(symbol, exchange)
        if result is not None:
            return result

    cache.stats.db_queries += 1
    return get_symbol_info_dbquery(symbol, exchange)


# Database fallback functions (imported from original token_db)
def get_token_dbquery(symbol: str, exchange: str) -> str | None:
    """Query database for token by symbol and exchange"""
    try:
        from database.symbol import SymToken

        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            return sym_token.token
        else:
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database: {e}")
        return None


def get_symbol_dbquery(token: str, exchange: str) -> str | None:
    """Query database for symbol by token and exchange"""
    try:
        from database.symbol import SymToken

        sym_token = SymToken.query.filter_by(token=token, exchange=exchange).first()
        if sym_token:
            return sym_token.symbol
        else:
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database: {e}")
        return None


def get_br_symbol_dbquery(symbol: str, exchange: str) -> str | None:
    """Query database for broker symbol"""
    try:
        from database.symbol import SymToken

        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            return sym_token.brsymbol
        else:
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database: {e}")
        return None


def get_oa_symbol_dbquery(brsymbol: str, exchange: str) -> str | None:
    """Query database for OpenAlgo symbol"""
    try:
        from database.symbol import SymToken

        sym_token = SymToken.query.filter_by(brsymbol=brsymbol, exchange=exchange).first()
        if sym_token:
            return sym_token.symbol
        else:
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database: {e}")
        return None


def get_brexchange_dbquery(symbol: str, exchange: str) -> str | None:
    """Query database for broker exchange"""
    try:
        from database.symbol import SymToken

        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            return sym_token.brexchange
        else:
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database: {e}")
        return None


def get_symbol_info_dbquery(symbol: str, exchange: str) -> SymbolData | None:
    """Query database for full symbol information, returns SymbolData object"""
    try:
        from database.symbol import SymToken

        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            # Convert SymToken database object to SymbolData
            return SymbolData(
                symbol=sym_token.symbol,
                brsymbol=sym_token.brsymbol,
                name=sym_token.name,
                exchange=sym_token.exchange,
                brexchange=sym_token.brexchange,
                token=sym_token.token,
                expiry=sym_token.expiry,
                strike=sym_token.strike,
                lotsize=sym_token.lotsize,
                instrumenttype=sym_token.instrumenttype,
                tick_size=sym_token.tick_size,
            )
        else:
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database: {e}")
        return None


def get_symbol_count() -> int:
    """Get the total count of symbols in the database"""
    try:
        from database.symbol import SymToken

        count = SymToken.query.count()
        return count
    except Exception as e:
        logger.exception(f"Error while counting symbols: {e}")
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
def get_tokens_bulk(symbol_exchange_pairs: list[tuple[str, str]]) -> list[str | None]:
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


def get_symbols_bulk(token_exchange_pairs: list[tuple[str, str]]) -> list[str | None]:
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
def search_symbols(query: str, exchange: str | None = None, limit: int = 50) -> list[dict]:
    """
    Search symbols with cache support
    Returns list of symbol dictionaries
    """
    cache = get_cache()

    if cache.cache_loaded and cache.is_cache_valid():
        results = cache.search_symbols(query, exchange, limit)
        return [
            {
                "symbol": s.symbol,
                "brsymbol": s.brsymbol,
                "name": s.name,
                "exchange": s.exchange,
                "token": s.token,
                "instrumenttype": s.instrumenttype,
            }
            for s in results
        ]

    # Fallback to database search
    try:
        from database.symbol import SymToken

        query_obj = SymToken.query.filter(SymToken.symbol.like(f"%{query}%"))
        if exchange:
            query_obj = query_obj.filter_by(exchange=exchange)

        results = query_obj.limit(limit).all()
        return [
            {
                "symbol": r.symbol,
                "brsymbol": r.brsymbol,
                "name": r.name,
                "exchange": r.exchange,
                "token": r.token,
                "instrumenttype": r.instrumenttype,
            }
            for r in results
        ]
    except Exception as e:
        logger.exception(f"Error searching symbols: {e}")
        return []


def fno_search_symbols(
    query: str | None = None,
    exchange: str | None = None,
    expiry: str | None = None,
    instrumenttype: str | None = None,
    strike_min: float | None = None,
    strike_max: float | None = None,
    underlying: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """
    FNO-specific search with advanced filters - uses cache for fast in-memory search
    Falls back to database if cache is not available

    Args:
        query: Optional search query string
        exchange: Exchange filter (NFO, BFO, MCX, CDS)
        expiry: Expiry date filter (e.g., "26-DEC-24")
        instrumenttype: "FUT", "CE", or "PE" (based on symbol suffix)
        strike_min: Minimum strike price
        strike_max: Maximum strike price
        underlying: Underlying symbol name (e.g., "NIFTY")
        limit: Maximum results to return

    Returns:
        List of symbol dictionaries with all fields
    """
    cache = get_cache()

    # Import freeze qty function
    from database.qty_freeze_db import get_freeze_qty_for_option

    if cache.cache_loaded and cache.is_cache_valid():
        results = cache.fno_search_symbols(
            query=query,
            exchange=exchange,
            expiry=expiry,
            instrumenttype=instrumenttype,
            strike_min=strike_min,
            strike_max=strike_max,
            underlying=underlying,
            limit=limit,
        )
        return [
            {
                "symbol": s.symbol,
                "brsymbol": s.brsymbol,
                "name": s.name,
                "exchange": s.exchange,
                "brexchange": s.brexchange,
                "token": s.token,
                "expiry": s.expiry,
                "strike": s.strike,
                "lotsize": s.lotsize,
                "instrumenttype": s.instrumenttype,
                "tick_size": s.tick_size,
                "underlying": s.underlying,
                "freeze_qty": get_freeze_qty_for_option(s.symbol, s.exchange),
            }
            for s in results
        ]

    # Fallback to database search (import the DB-based function)
    logger.debug("Cache not available, falling back to database FNO search")
    cache.stats.db_queries += 1

    try:
        from database.symbol import fno_search_symbols_db

        return fno_search_symbols_db(
            query=query,
            exchange=exchange,
            expiry=expiry,
            instrumenttype=instrumenttype,
            strike_min=strike_min,
            strike_max=strike_max,
            underlying=underlying,
            limit=limit,
        )
    except Exception as e:
        logger.exception(f"Error in FNO search fallback: {e}")
        return []


def get_distinct_expiries_cached(
    exchange: str | None = None, underlying: str | None = None
) -> list[str]:
    """
    Get distinct expiry dates from cache - fast O(1) lookup using pre-computed indexes
    Falls back to database if cache is not available
    """
    cache = get_cache()

    if cache.cache_loaded and cache.is_cache_valid():
        from datetime import datetime

        # Use pre-computed indexes for O(1) lookup instead of iterating all symbols
        underlying_upper = underlying.strip().upper() if underlying else None

        if exchange and underlying_upper:
            # Use the combined index for exchange + underlying
            expiries = cache.expiries_by_exchange_underlying.get((exchange, underlying_upper), set())
        elif exchange:
            # Use the exchange-only index
            expiries = cache.expiries_by_exchange.get(exchange, set())
        else:
            # No filter - combine all expiries (rare case)
            expiries = set()
            for exp_set in cache.expiries_by_exchange.values():
                expiries.update(exp_set)

        # Sort expiries chronologically
        def parse_expiry(exp_str):
            try:
                return datetime.strptime(exp_str, "%d-%b-%y")
            except ValueError:
                try:
                    return datetime.strptime(exp_str, "%d-%b-%Y")
                except ValueError:
                    return datetime.max

        return sorted(list(expiries), key=parse_expiry)

    # Fallback to database
    try:
        from database.symbol import get_distinct_expiries

        return get_distinct_expiries(exchange=exchange, underlying=underlying)
    except Exception as e:
        logger.exception(f"Error getting expiries: {e}")
        return []


def get_distinct_underlyings_cached(exchange: str | None = None) -> list[str]:
    """
    Get distinct underlying names from cache - fast O(1) lookup using pre-computed indexes
    Falls back to database if cache is not available
    """
    cache = get_cache()

    if cache.cache_loaded and cache.is_cache_valid():
        # Use pre-computed index for O(1) lookup instead of iterating all symbols
        if exchange:
            underlyings = cache.underlyings_by_exchange.get(exchange, set())
        else:
            # No filter - combine all underlyings (rare case)
            underlyings = set()
            for underlying_set in cache.underlyings_by_exchange.values():
                underlyings.update(underlying_set)

        return sorted(list(underlyings))

    # Fallback to database
    try:
        from database.symbol import get_distinct_underlyings

        return get_distinct_underlyings(exchange=exchange)
    except Exception as e:
        logger.exception(f"Error getting underlyings: {e}")
        return []
