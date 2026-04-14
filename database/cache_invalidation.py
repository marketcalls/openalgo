# database/cache_invalidation.py
"""
ZeroMQ-based cache invalidation for multi-process deployments.

This module provides cross-process cache invalidation using ZeroMQ pub/sub.
When auth tokens are updated or revoked in the Flask process, invalidation
messages are published to all subscribed processes (e.g., WebSocket proxy).

This solves the stale cache issue described in GitHub issue #765.
"""

import json
import os
import threading

import zmq

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
    """
    ZeroMQ publisher for broadcasting cache invalidation events.

    Uses the same ZMQ port as market data (from ZMQ_PORT env var).
    Messages are prefixed with CACHE_INVALIDATE to distinguish from market data.
    """

    def __init__(self):
        self.context = None
        self.socket = None
        self._initialized = False
        self._lock = threading.Lock()

    def _ensure_initialized(self):
        """Lazily initialize ZMQ connection on first use"""
        if self._initialized:
            return True

        with self._lock:
            if self._initialized:
                return True

            try:
                self.context = zmq.Context()
                self.socket = self.context.socket(zmq.PUB)

                zmq_host = os.getenv("ZMQ_HOST", "127.0.0.1")
                zmq_port = os.getenv("ZMQ_PORT", "5555")

                # Connect as publisher (broker adapters bind, we connect)
                self.socket.connect(f"tcp://{zmq_host}:{zmq_port}")

                # Set socket options
                self.socket.setsockopt(zmq.LINGER, 1000)  # 1 second linger on close
                self.socket.setsockopt(zmq.SNDHWM, 100)   # High water mark

                self._initialized = True
                logger.debug(f"Cache invalidation publisher connected to tcp://{zmq_host}:{zmq_port}")
                return True

            except Exception as e:
                logger.exception(f"Failed to initialize cache invalidation publisher: {e}")
                return False

    def publish_invalidation(self, user_id: str, cache_type: str = ALL_CACHE_TYPE):
        """
        Publish a cache invalidation message for a specific user.

        Args:
            user_id: The user whose cache should be invalidated
            cache_type: Type of cache to invalidate (AUTH, FEED, or ALL)
        """
        if not self._ensure_initialized():
            logger.warning(f"Cache invalidation skipped - publisher not initialized for user: {user_id}")
            return False

        try:
            # Create topic and message
            topic = f"{CACHE_INVALIDATION_PREFIX}_{cache_type}_{user_id}"
            message = {
                "action": "invalidate",
                "user_id": user_id,
                "cache_type": cache_type,
            }

            # Send as multipart message (topic + data)
            self.socket.send_multipart([
                topic.encode("utf-8"),
                json.dumps(message).encode("utf-8")
            ])

            logger.info(f"Published cache invalidation for user: {user_id}, type: {cache_type}")
            return True

        except Exception as e:
            logger.exception(f"Failed to publish cache invalidation for user {user_id}: {e}")
            return False

    def close(self):
        """Close ZMQ connections"""
        try:
            if self.socket:
                self.socket.close()
            if self.context:
                self.context.term()
            self._initialized = False
            logger.debug("Cache invalidation publisher closed")
        except Exception as e:
            logger.exception(f"Error closing cache invalidation publisher: {e}")


def get_cache_invalidation_publisher() -> CacheInvalidationPublisher:
    """
    Get the singleton cache invalidation publisher instance.

    Returns:
        CacheInvalidationPublisher: The publisher instance
    """
    global _publisher_instance

    if _publisher_instance is None:
        with _publisher_lock:
            if _publisher_instance is None:
                _publisher_instance = CacheInvalidationPublisher()

    return _publisher_instance


def publish_auth_cache_invalidation(user_id: str):
    """
    Convenience function to publish auth cache invalidation.

    Args:
        user_id: The user whose auth cache should be invalidated
    """
    publisher = get_cache_invalidation_publisher()
    return publisher.publish_invalidation(user_id, AUTH_CACHE_TYPE)


def publish_feed_cache_invalidation(user_id: str):
    """
    Convenience function to publish feed cache invalidation.

    Args:
        user_id: The user whose feed cache should be invalidated
    """
    publisher = get_cache_invalidation_publisher()
    return publisher.publish_invalidation(user_id, FEED_CACHE_TYPE)


def publish_all_cache_invalidation(user_id: str):
    """
    Convenience function to publish all cache invalidation.

    Args:
        user_id: The user whose all caches should be invalidated
    """
    publisher = get_cache_invalidation_publisher()
    return publisher.publish_invalidation(user_id, ALL_CACHE_TYPE)
