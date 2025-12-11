# database/cache_restoration.py
"""
Cache Restoration Module

Restores in-memory caches from database on application startup.
This allows the app to resume operations without requiring re-login
after a restart.

Restores:
1. Symbol cache - All trading symbols/tokens from database
2. Auth cache - Valid (non-revoked) authentication tokens
3. Broker cache - Broker name mappings

Usage:
    from database.cache_restoration import restore_all_caches

    # Call during app startup
    with app.app_context():
        restore_all_caches()
"""

import time
from utils.logging import get_logger

logger = get_logger(__name__)


def restore_symbol_cache() -> dict:
    """
    Restore symbol cache from database on startup.

    Loads all symbols from the symtoken table into the in-memory
    BrokerSymbolCache for fast O(1) lookups.

    Returns:
        dict: Statistics about the restoration
            - success: bool
            - symbols_loaded: int
            - broker: str or None
            - time_ms: float
            - error: str or None
    """
    result = {
        'success': False,
        'symbols_loaded': 0,
        'broker': None,
        'time_ms': 0,
        'error': None
    }

    start_time = time.time()

    try:
        from database.token_db_enhanced import get_cache
        from database.auth_db import Auth

        # Find the active broker from auth table (non-revoked)
        auth_record = Auth.query.filter_by(is_revoked=False).first()

        if not auth_record:
            result['error'] = 'No active broker session found in database'
            logger.debug("Symbol cache restoration skipped: No active broker session")
            return result

        broker = auth_record.broker
        result['broker'] = broker

        # Get the symbol cache instance
        cache = get_cache()

        # Check if already loaded
        if cache.cache_loaded and cache.stats.total_symbols > 0:
            result['success'] = True
            result['symbols_loaded'] = cache.stats.total_symbols
            result['time_ms'] = (time.time() - start_time) * 1000
            logger.debug(f"Symbol cache already loaded: {cache.stats.total_symbols} symbols")
            return result

        # Load symbols from database
        success = cache.load_all_symbols(broker)

        if success:
            result['success'] = True
            result['symbols_loaded'] = cache.stats.total_symbols
            logger.debug(
                f"Symbol cache restored: {cache.stats.total_symbols} symbols "
                f"for broker '{broker}' in {(time.time() - start_time)*1000:.0f}ms"
            )
        else:
            result['error'] = 'Failed to load symbols from database'
            logger.warning("Symbol cache restoration failed: No symbols in database")

    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Error restoring symbol cache: {e}")

    result['time_ms'] = (time.time() - start_time) * 1000
    return result


def restore_auth_cache() -> dict:
    """
    Restore auth cache from database on startup.

    Loads all non-revoked authentication tokens into the in-memory
    auth_cache for fast access.

    Returns:
        dict: Statistics about the restoration
            - success: bool
            - tokens_loaded: int
            - users: list of usernames
            - time_ms: float
            - error: str or None
    """
    result = {
        'success': False,
        'tokens_loaded': 0,
        'users': [],
        'time_ms': 0,
        'error': None
    }

    start_time = time.time()

    try:
        from database.auth_db import (
            Auth,
            auth_cache,
            feed_token_cache,
            broker_cache
        )

        # Get all non-revoked auth records
        auth_records = Auth.query.filter_by(is_revoked=False).all()

        if not auth_records:
            result['error'] = 'No active auth tokens found in database'
            logger.debug("Auth cache restoration skipped: No active sessions")
            return result

        tokens_loaded = 0
        users = []

        for auth_record in auth_records:
            try:
                name = auth_record.name

                # Populate auth cache
                cache_key_auth = f"auth-{name}"
                auth_cache[cache_key_auth] = auth_record

                # Populate feed token cache if available
                if auth_record.feed_token:
                    cache_key_feed = f"feed-{name}"
                    feed_token_cache[cache_key_feed] = auth_record

                # Note: Broker cache is not restored here because it uses hashed API key as key,
                # which we can't reconstruct without the actual API key.
                # It will be populated on first API call.

                tokens_loaded += 1
                users.append(name)

            except Exception as e:
                logger.warning(f"Failed to restore auth for user {auth_record.name}: {e}")
                continue

        result['success'] = tokens_loaded > 0
        result['tokens_loaded'] = tokens_loaded
        result['users'] = users

        if tokens_loaded > 0:
            logger.debug(f"Auth cache restored: {tokens_loaded} tokens for users: {users}")

    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Error restoring auth cache: {e}")

    result['time_ms'] = (time.time() - start_time) * 1000
    return result


def restore_all_caches() -> dict:
    """
    Restore all caches from database on application startup.

    This is the main entry point for cache restoration.
    Should be called during app startup after database initialization.

    Returns:
        dict: Complete restoration statistics
            - success: bool (True if at least one cache restored)
            - symbol_cache: dict with symbol cache stats
            - auth_cache: dict with auth cache stats
            - total_time_ms: float
    """
    logger.debug("Starting cache restoration from database...")

    total_start = time.time()

    result = {
        'success': False,
        'symbol_cache': None,
        'auth_cache': None,
        'total_time_ms': 0
    }

    # Restore auth cache first (needed to determine broker for symbols)
    result['auth_cache'] = restore_auth_cache()

    # Restore symbol cache
    result['symbol_cache'] = restore_symbol_cache()

    # Calculate totals
    result['total_time_ms'] = (time.time() - total_start) * 1000

    # Success if at least one cache was restored
    result['success'] = (
        result['auth_cache'].get('success', False) or
        result['symbol_cache'].get('success', False)
    )

    # Log summary
    auth_count = result['auth_cache'].get('tokens_loaded', 0)
    symbol_count = result['symbol_cache'].get('symbols_loaded', 0)

    if result['success']:
        logger.debug(
            f"Cache restoration complete: "
            f"{auth_count} auth tokens, {symbol_count} symbols "
            f"in {result['total_time_ms']:.0f}ms"
        )
    else:
        logger.debug(
            f"Cache restoration skipped: No active sessions found. "
            f"Caches will be populated on user login."
        )

    return result


def get_cache_restoration_status() -> dict:
    """
    Get current status of caches (for diagnostics).

    Returns:
        dict: Current cache status
    """
    status = {
        'auth_cache': {'loaded': False, 'count': 0},
        'feed_token_cache': {'loaded': False, 'count': 0},
        'broker_cache': {'loaded': False, 'count': 0},
        'symbol_cache': {'loaded': False, 'count': 0, 'broker': None}
    }

    try:
        from database.auth_db import auth_cache, feed_token_cache, broker_cache

        status['auth_cache'] = {
            'loaded': len(auth_cache) > 0,
            'count': len(auth_cache)
        }
        status['feed_token_cache'] = {
            'loaded': len(feed_token_cache) > 0,
            'count': len(feed_token_cache)
        }
        status['broker_cache'] = {
            'loaded': len(broker_cache) > 0,
            'count': len(broker_cache)
        }
    except Exception as e:
        logger.debug(f"Error getting auth cache status: {e}")

    try:
        from database.token_db_enhanced import get_cache
        cache = get_cache()

        status['symbol_cache'] = {
            'loaded': cache.cache_loaded,
            'count': cache.stats.total_symbols,
            'broker': cache.active_broker,
            'memory_mb': cache.stats.memory_usage_mb
        }
    except Exception as e:
        logger.debug(f"Error getting symbol cache status: {e}")

    return status
