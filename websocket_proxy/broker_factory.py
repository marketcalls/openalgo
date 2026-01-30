import importlib
from typing import Dict, Optional, Type

from utils.logging import get_logger

from .base_adapter import (
    ENABLE_CONNECTION_POOLING,
    MAX_SYMBOLS_PER_WEBSOCKET,
    MAX_WEBSOCKET_CONNECTIONS,
    BaseBrokerWebSocketAdapter,
)
from .connection_manager import ConnectionPool

logger = get_logger(__name__)

# Registry of all supported broker adapters
BROKER_ADAPTERS: dict[str, type[BaseBrokerWebSocketAdapter]] = {}

# Registry of pooled adapters (one pool per user_id + broker combination)
_POOLED_ADAPTERS: dict[str, ConnectionPool] = {}


def register_adapter(broker_name: str, adapter_class: type[BaseBrokerWebSocketAdapter]) -> None:
    """
    Register a broker adapter class for a specific broker

    Args:
        broker_name: Name of the broker
        adapter_class: Class that implements the BaseBrokerWebSocketAdapter interface
    """
    BROKER_ADAPTERS[broker_name.lower()] = adapter_class


def _get_adapter_class(broker_name: str) -> type[BaseBrokerWebSocketAdapter]:
    """
    Get the adapter class for a broker (without instantiating).

    Args:
        broker_name: Name of the broker

    Returns:
        The adapter class

    Raises:
        ValueError: If broker is not supported
    """
    broker_name = broker_name.lower()

    # Check if adapter is registered
    if broker_name in BROKER_ADAPTERS:
        return BROKER_ADAPTERS[broker_name]

    # Try dynamic import if not registered
    try:
        # Try to import from broker-specific directory first
        module_name = f"broker.{broker_name}.streaming.{broker_name}_adapter"
        class_name = f"{broker_name.capitalize()}WebSocketAdapter"

        try:
            module = importlib.import_module(module_name)
            adapter_class = getattr(module, class_name)
            register_adapter(broker_name, adapter_class)
            return adapter_class
        except (ImportError, AttributeError) as e:
            logger.warning(f"Could not import from broker-specific path: {e}")

            # Try websocket_proxy directory as fallback
            module_name = f"websocket_proxy.{broker_name}_adapter"
            module = importlib.import_module(module_name)
            adapter_class = getattr(module, class_name)
            register_adapter(broker_name, adapter_class)
            return adapter_class

    except (ImportError, AttributeError) as e:
        logger.exception(f"Failed to load adapter for broker {broker_name}: {e}")
        raise ValueError(f"Unsupported broker: {broker_name}. No adapter available.")


def create_broker_adapter(
    broker_name: str, use_pooling: bool | None = None
) -> BaseBrokerWebSocketAdapter | None:
    """
    Create an instance of the appropriate broker adapter.

    When connection pooling is enabled, returns a ConnectionPool that automatically
    manages multiple WebSocket connections to handle symbol limits.

    Args:
        broker_name: Name of the broker (e.g., 'angel', 'zerodha')
        use_pooling: Override for connection pooling. If None, uses global setting.

    Returns:
        BaseBrokerWebSocketAdapter or ConnectionPool: An adapter instance

    Raises:
        ValueError: If the broker is not supported
    """
    broker_name = broker_name.lower()

    # Determine if pooling should be used
    pooling_enabled = use_pooling if use_pooling is not None else ENABLE_CONNECTION_POOLING

    # Get the adapter class
    adapter_class = _get_adapter_class(broker_name)

    if pooling_enabled:
        logger.info(
            f"Creating pooled adapter for broker: {broker_name} "
            f"(max {MAX_SYMBOLS_PER_WEBSOCKET} symbols × {MAX_WEBSOCKET_CONNECTIONS} connections)"
        )
        # Return a ConnectionPool wrapper
        # Note: The pool is initialized later with user_id via initialize() method
        return _PooledAdapterWrapper(adapter_class, broker_name)
    else:
        logger.info(f"Creating single adapter for broker: {broker_name} (pooling disabled)")
        return adapter_class()


class _PooledAdapterWrapper:
    """
    Wrapper that creates a ConnectionPool when initialized with user_id.
    Provides the same interface as BaseBrokerWebSocketAdapter.
    """

    def __init__(self, adapter_class: type, broker_name: str):
        self._adapter_class = adapter_class
        self._broker_name = broker_name
        self._pool: ConnectionPool | None = None
        self._user_id: str | None = None
        self.logger = get_logger(f"pooled_adapter_{broker_name}")

    def _ensure_pool(self, user_id: str) -> ConnectionPool:
        """Create or get existing pool for this user"""
        if self._pool is None:
            pool_key = f"{self._broker_name}_{user_id}"

            # Check if pool already exists for this user
            if pool_key in _POOLED_ADAPTERS:
                self._pool = _POOLED_ADAPTERS[pool_key]
                self.logger.info(f"Reusing existing pool for {pool_key}")
            else:
                self._pool = ConnectionPool(
                    adapter_class=self._adapter_class,
                    broker_name=self._broker_name,
                    user_id=user_id,
                    max_symbols_per_connection=MAX_SYMBOLS_PER_WEBSOCKET,
                    max_connections=MAX_WEBSOCKET_CONNECTIONS,
                )
                _POOLED_ADAPTERS[pool_key] = self._pool
                self.logger.info(
                    f"Created new connection pool for {pool_key}: "
                    f"max {MAX_SYMBOLS_PER_WEBSOCKET} symbols × {MAX_WEBSOCKET_CONNECTIONS} connections"
                )

            self._user_id = user_id

        return self._pool

    def initialize(self, broker_name: str, user_id: str, auth_data: dict = None, force: bool = False):
        """Initialize the pool with user credentials

        Args:
            broker_name: The broker name
            user_id: The user ID
            auth_data: Optional authentication data
            force: If True, force re-initialization with fresh credentials (issue #765)
        """
        pool = self._ensure_pool(user_id)
        return pool.initialize(broker_name, user_id, auth_data, force=force)

    def connect(self):
        """Connect the pool"""
        if self._pool:
            return self._pool.connect()
        return {"success": False, "error": "Not initialized"}

    def disconnect(self):
        """Disconnect and cleanup the pool"""
        if self._pool:
            self._pool.disconnect()
            # Remove from global registry
            pool_key = f"{self._broker_name}_{self._user_id}"
            _POOLED_ADAPTERS.pop(pool_key, None)

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5):
        """Subscribe to market data"""
        if self._pool:
            return self._pool.subscribe(symbol, exchange, mode, depth_level)
        return {"status": "error", "message": "Not initialized"}

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2):
        """Unsubscribe from market data"""
        if self._pool:
            return self._pool.unsubscribe(symbol, exchange, mode)
        return {"status": "error", "message": "Not initialized"}

    def unsubscribe_all(self):
        """Unsubscribe from all symbols"""
        if self._pool:
            self._pool.unsubscribe_all()

    def get_stats(self) -> dict:
        """Get pool statistics"""
        if self._pool:
            return self._pool.get_stats()
        return {}

    @property
    def subscriptions(self) -> dict:
        """Get current subscriptions"""
        if self._pool:
            return self._pool.subscriptions
        return {}

    @property
    def connected(self) -> bool:
        """Check if pool is connected"""
        if self._pool:
            return self._pool.connected
        return False

    def publish_market_data(self, topic: str, data: dict):
        """Publish market data through the pool"""
        if self._pool:
            self._pool.publish_market_data(topic, data)

    # =========================================================================
    # Authentication Helper Methods (Issue #765 - Stale Token Handling)
    # =========================================================================
    # These methods delegate to the underlying adapter or implement the logic
    # directly for handling stale auth tokens in multi-process deployments.

    def is_auth_error(self, error_message: str) -> bool:
        """
        Check if an error message indicates an authentication failure.

        Args:
            error_message: The error message string

        Returns:
            True if the error indicates authentication failure (401/403)
        """
        if not error_message:
            return False

        error_lower = str(error_message).lower()
        auth_error_indicators = [
            "401",
            "403",
            "unauthorized",
            "forbidden",
            "authentication failed",
            "auth failed",
            "invalid token",
            "token expired",
            "access denied",
            "invalid credentials",
            "session expired",
        ]
        return any(indicator in error_lower for indicator in auth_error_indicators)

    def clear_auth_cache_for_user(self, user_id: str):
        """
        Clear all cached authentication data for a user.

        Call this when you detect stale credentials (e.g., 403 error from broker).

        Args:
            user_id: The user's ID
        """
        try:
            from database.auth_db import (
                auth_cache,
                feed_token_cache,
            )

            cache_key_auth = f"auth-{user_id}"
            cache_key_feed = f"feed-{user_id}"

            caches_cleared = []
            if cache_key_auth in auth_cache:
                del auth_cache[cache_key_auth]
                caches_cleared.append("auth_cache")
            if cache_key_feed in feed_token_cache:
                del feed_token_cache[cache_key_feed]
                caches_cleared.append("feed_token_cache")
            # Note: broker_cache is keyed by API key, not user_id, so we skip it here
            # It only caches broker names which don't affect auth token validation

            if caches_cleared:
                self.logger.info(f"Cleared auth caches for user {user_id}: {', '.join(caches_cleared)}")
            else:
                self.logger.debug(f"No cached auth data found for user {user_id}")

        except Exception as e:
            self.logger.exception(f"Error clearing auth cache for user {user_id}: {e}")


def get_pool_stats(broker_name: str = None) -> dict:
    """
    Get statistics for all connection pools or a specific broker.

    Args:
        broker_name: Optional broker name to filter stats

    Returns:
        Dictionary with pool statistics
    """
    stats = {}
    for pool_key, pool in _POOLED_ADAPTERS.items():
        if broker_name is None or pool_key.startswith(broker_name):
            stats[pool_key] = pool.get_stats()
    return stats


def cleanup_all_pools():
    """Disconnect and cleanup all connection pools"""
    for pool_key, pool in list(_POOLED_ADAPTERS.items()):
        try:
            pool.disconnect()
        except Exception as e:
            logger.exception(f"Error cleaning up pool {pool_key}: {e}")
    _POOLED_ADAPTERS.clear()


def get_resource_health() -> dict:
    """
    Get comprehensive health statistics for all WebSocket proxy resources.

    This is useful for monitoring file descriptors, memory usage, and
    connection health across all broker adapters and pools.

    Returns:
        dict: Health statistics including:
            - adapter_resources: ZMQ socket and context stats
            - registered_adapters: Count of registered broker adapters
            - active_pools: Stats for each active connection pool
    """
    try:
        adapter_stats = BaseBrokerWebSocketAdapter.get_resource_stats()
    except Exception as e:
        logger.warning(f"Error getting adapter stats: {e}")
        adapter_stats = {"error": str(e)}

    pool_stats = {}
    for pool_key, pool in _POOLED_ADAPTERS.items():
        try:
            pool_stats[pool_key] = pool.get_stats()
        except Exception as e:
            pool_stats[pool_key] = {"error": str(e)}

    return {
        "adapter_resources": adapter_stats,
        "registered_adapters": {
            "count": len(BROKER_ADAPTERS),
            "brokers": list(BROKER_ADAPTERS.keys()),
        },
        "active_pools": {
            "count": len(_POOLED_ADAPTERS),
            "pools": pool_stats,
        },
    }
