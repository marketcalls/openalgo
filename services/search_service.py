from typing import Any, Dict, List, Tuple

from database.auth_db import verify_api_key
from database.qty_freeze_db import get_freeze_qty_for_option
from database.token_db_enhanced import get_cache
from utils.logging import get_logger

logger = get_logger(__name__)


def search_symbols(
    query: str, exchange: str = None, api_key: str = None
) -> tuple[bool, dict[str, Any], int]:
    """
    Search for symbols using in-memory cache for fast performance.
    Falls back to database if cache is not available.

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
                logger.warning("Invalid API key provided for search")
                return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403

        # Validate input
        if not query or not query.strip():
            logger.warning("Empty search query provided")
            return (
                False,
                {"status": "error", "message": "Query parameter is required and cannot be empty"},
                400,
            )

        query = query.strip()
        logger.info(f"Searching symbols for query: {query}, exchange: {exchange}")

        # Try cache-based search first
        cache = get_cache()
        if cache.cache_loaded and cache.is_cache_valid():
            results = cache.search_symbols(query, exchange, limit=500)

            if not results:
                logger.info(f"No results found for query: {query}")
                return (
                    True,
                    {"status": "success", "message": "No matching symbols found", "data": []},
                    200,
                )

            # Convert SymbolData to dict format
            results_data = [
                {
                    "symbol": r.symbol,
                    "brsymbol": r.brsymbol,
                    "name": r.name,
                    "exchange": r.exchange,
                    "brexchange": r.brexchange,
                    "token": r.token,
                    "expiry": r.expiry,
                    "strike": r.strike,
                    "lotsize": r.lotsize,
                    "instrumenttype": r.instrumenttype,
                    "tick_size": r.tick_size,
                    "freeze_qty": get_freeze_qty_for_option(r.symbol, r.exchange),
                }
                for r in results
            ]

            logger.info(f"Found {len(results_data)} results for query: {query} (from cache)")

            return (
                True,
                {
                    "status": "success",
                    "message": f"Found {len(results_data)} matching symbols",
                    "data": results_data,
                },
                200,
            )

        # Fallback to database search
        logger.debug("Cache not available, falling back to database search")
        from database.symbol import enhanced_search_symbols

        results = enhanced_search_symbols(query, exchange)

        if not results:
            logger.info(f"No results found for query: {query}")
            return (
                True,
                {"status": "success", "message": "No matching symbols found", "data": []},
                200,
            )

        # Convert results to dict format
        results_data = [
            {
                "symbol": result.symbol,
                "brsymbol": result.brsymbol,
                "name": result.name,
                "exchange": result.exchange,
                "brexchange": result.brexchange,
                "token": result.token,
                "expiry": result.expiry,
                "strike": result.strike,
                "lotsize": result.lotsize,
                "instrumenttype": result.instrumenttype,
                "tick_size": result.tick_size,
                "freeze_qty": get_freeze_qty_for_option(result.symbol, result.exchange),
            }
            for result in results
        ]

        logger.info(f"Found {len(results_data)} results for query: {query} (from database)")

        return (
            True,
            {
                "status": "success",
                "message": f"Found {len(results_data)} matching symbols",
                "data": results_data,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error in search_symbols: {e}")
        return (
            False,
            {"status": "error", "message": "An error occurred while searching symbols"},
            500,
        )
