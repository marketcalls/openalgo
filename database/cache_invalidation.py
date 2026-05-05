# database/cache_invalidation.py
"""
ZeroMQ-based cache invalidation for cross-component delivery.

When auth tokens are updated or revoked from a Flask request handler,
an invalidation message is published on the same ZMQ bus that broker
adapters use for market data. The websocket proxy's existing SUB
listener picks it up via the `CACHE_INVALIDATE_*` topic prefix and
clears its local auth caches.

Fix history — issue #1374:
Earlier this module created its own `zmq.PUB` socket and `connect()`ed
to the ZMQ port. That collided with `SharedZmqPublisher` (also a PUB,
but `bind`-ing the same endpoint) — two PUBs on one wire is an invalid
ZMQ topology and messages were silently dropped. The fix routes
publishes through the existing `SharedZmqPublisher` singleton, so there
is exactly one PUB on the wire and the proxy's SUB receives both market
data and cache invalidations through the same pipe. No new port, no new
env var.
"""

import threading

from utils.logging import get_logger

logger = get_logger(__name__)

# Cache invalidation message types
CACHE_INVALIDATION_PREFIX = "CACHE_INVALIDATE"
AUTH_CACHE_TYPE = "AUTH"
FEED_CACHE_TYPE = "FEED"
ALL_CACHE_TYPE = "ALL"

# Singleton publisher instance
_publisher_instance = None
_publisher_lock = threading.Lock()


class CacheInvalidationPublisher:
    """Thin wrapper that emits cache-invalidation events through the
    shared market-data publisher (`SharedZmqPublisher`). Owns no ZMQ
    socket of its own — that ownership lives in `connection_manager`.
    """

    def publish_invalidation(self, user_id: str, cache_type: str = ALL_CACHE_TYPE) -> bool:
        """Publish a cache invalidation message for a specific user.

        Args:
            user_id: The user whose cache should be invalidated
            cache_type: Type of cache to invalidate (AUTH, FEED, or ALL)
        """
        if not user_id:
            logger.warning("Cache invalidation skipped — no user_id supplied")
            return False

        try:
            # Lazy import — avoids a circular dependency between database and
            # websocket_proxy packages, and keeps cache_invalidation usable
            # even when the websocket subsystem is disabled.
            from websocket_proxy.connection_manager import SharedZmqPublisher

            publisher = SharedZmqPublisher()
            if not publisher._bound:
                publisher.bind()  # idempotent — only binds first time

            topic = f"{CACHE_INVALIDATION_PREFIX}_{cache_type}_{user_id}"
            message = {
                "action": "invalidate",
                "user_id": user_id,
                "cache_type": cache_type,
            }
            publisher.publish(topic, message)

            logger.info(f"Published cache invalidation for user: {user_id}, type: {cache_type}")
            return True

        except Exception as e:
            logger.exception(f"Failed to publish cache invalidation for user {user_id}: {e}")
            return False

    def close(self) -> None:
        """No-op kept for backward compatibility — this class no longer
        owns the ZMQ socket. The shared publisher is cleaned up by
        `ConnectionPool.disconnect` / `SharedZmqPublisher.cleanup`.
        """
        return None


def get_cache_invalidation_publisher() -> CacheInvalidationPublisher:
    """Return the singleton cache invalidation publisher."""
    global _publisher_instance

    if _publisher_instance is None:
        with _publisher_lock:
            if _publisher_instance is None:
                _publisher_instance = CacheInvalidationPublisher()

    return _publisher_instance


def publish_auth_cache_invalidation(user_id: str) -> bool:
    """Convenience function to publish an AUTH-cache invalidation."""
    return get_cache_invalidation_publisher().publish_invalidation(user_id, AUTH_CACHE_TYPE)


def publish_feed_cache_invalidation(user_id: str) -> bool:
    """Convenience function to publish a FEED-cache invalidation."""
    return get_cache_invalidation_publisher().publish_invalidation(user_id, FEED_CACHE_TYPE)


def publish_all_cache_invalidation(user_id: str) -> bool:
    """Convenience function to publish an ALL-cache invalidation."""
    return get_cache_invalidation_publisher().publish_invalidation(user_id, ALL_CACHE_TYPE)
