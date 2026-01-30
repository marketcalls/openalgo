import json
import os
import random
import socket
import threading
from abc import ABC, abstractmethod

import zmq

from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# =============================================================================
# Connection Pool Configuration
# =============================================================================
# These settings control how the websocket_proxy handles broker symbol limits.
# Most brokers limit symbols per WebSocket connection (e.g., Angel: 1000, Zerodha: 3000).
# The connection pool automatically creates additional connections when limits are reached.

# Maximum symbols per single WebSocket connection
# Set lower than broker limits to be safe (Angel=1000, Zerodha=3000)
MAX_SYMBOLS_PER_WEBSOCKET = int(os.getenv("MAX_SYMBOLS_PER_WEBSOCKET", "1000"))

# Maximum WebSocket connections per user/broker
# Total capacity = MAX_SYMBOLS_PER_WEBSOCKET × MAX_WEBSOCKET_CONNECTIONS
MAX_WEBSOCKET_CONNECTIONS = int(os.getenv("MAX_WEBSOCKET_CONNECTIONS", "3"))

# Enable/disable connection pooling globally
# When disabled, falls back to single connection per broker
ENABLE_CONNECTION_POOLING = os.getenv("ENABLE_CONNECTION_POOLING", "true").lower() == "true"


def is_port_available(port):
    """
    Check if a port is available for use
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.settimeout(1.0)
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def find_free_zmq_port(start_port=5556, max_attempts=50):
    """
    Find an available port starting from start_port that's not already bound

    Args:
        start_port (int): Port number to start the search from
        max_attempts (int): Maximum number of attempts to find a free port

    Returns:
        int: Available port number, or None if no port is available
    """
    # Create logger here instead of using self.logger because this is a standalone function
    logger = get_logger("zmq_port_finder")

    # First check if any ports in the bound_ports set are actually free now
    # This handles cases where the process that had the port died without cleanup
    with BaseBrokerWebSocketAdapter._port_lock:
        ports_to_remove = [
            port for port in BaseBrokerWebSocketAdapter._bound_ports if is_port_available(port)
        ]

        # Remove ports that are actually available now
        for port in ports_to_remove:
            BaseBrokerWebSocketAdapter._bound_ports.remove(port)
            logger.info(f"Port {port} removed from bound ports registry")

    # Now find a new free port
    for _ in range(max_attempts):
        # Try a sequential port first, then random if that fails
        if start_port not in BaseBrokerWebSocketAdapter._bound_ports and is_port_available(
            start_port
        ):
            return start_port

        # Try a random port between start_port and 65535
        random_port = random.randint(start_port, 65535)
        if random_port not in BaseBrokerWebSocketAdapter._bound_ports and is_port_available(
            random_port
        ):
            return random_port

        start_port = min(start_port + 1, 65000)

    # If we get here, we couldn't find an available port
    logger.error("Failed to find an available port after maximum attempts")
    return None


class BaseBrokerWebSocketAdapter(ABC):
    """
    Base class for all broker-specific WebSocket adapters that implements
    common functionality and defines the interface for broker-specific implementations.
    """

    # Class variable to track bound ports across instances
    _bound_ports = set()
    _port_lock = threading.Lock()
    _shared_context = None
    _context_lock = threading.Lock()
    _instance_count = 0  # Track active adapter instances for cleanup decisions

    def __init__(self, use_shared_zmq: bool = False, shared_publisher=None):
        """
        Initialize the base broker adapter.

        Args:
            use_shared_zmq: If True, use a shared ZeroMQ publisher instead of creating one.
                           This is used by ConnectionPool for multi-connection support.
            shared_publisher: The shared publisher instance to use when use_shared_zmq=True
        """
        self.logger = get_logger("broker_adapter")
        self.logger.info("BaseBrokerWebSocketAdapter initializing")

        # Track instance count for shared context cleanup decisions
        with self._context_lock:
            BaseBrokerWebSocketAdapter._instance_count += 1
            self.logger.debug(f"Adapter instance count: {BaseBrokerWebSocketAdapter._instance_count}")

        # Check if being created within a ConnectionPool context
        # This handles the case where broker adapters don't forward kwargs to super().__init__()
        try:
            from .connection_manager import (
                get_shared_publisher_for_pooled_creation,
                is_pooled_creation,
            )

            if is_pooled_creation():
                use_shared_zmq = True
                shared_publisher = get_shared_publisher_for_pooled_creation()
                self.logger.info("Detected pooled creation context - using shared ZMQ")
        except ImportError:
            pass  # connection_manager not available, use provided params

        # Track if using shared ZMQ (for connection pooling)
        self._uses_shared_zmq = use_shared_zmq
        self._shared_publisher = shared_publisher

        try:
            if use_shared_zmq and shared_publisher:
                # Use shared publisher's socket instead of creating own
                self.socket = shared_publisher.socket
                self.zmq_port = shared_publisher.zmq_port
                self.context = shared_publisher.context
                self.logger.info(f"Using shared ZMQ publisher on port {self.zmq_port}")
            else:
                # Initialize own ZeroMQ context and socket
                self._initialize_shared_context()

                # Create socket and bind to port
                self.socket = self._create_socket()
                self.zmq_port = self._bind_to_available_port()
                os.environ["ZMQ_PORT"] = str(self.zmq_port)
                self.logger.info(f"BaseBrokerWebSocketAdapter initialized on port {self.zmq_port}")

            # Initialize instance variables
            self.subscriptions = {}
            self.connected = False

        except Exception as e:
            self.logger.exception(f"Error in BaseBrokerWebSocketAdapter init: {e}")
            raise

    def _initialize_shared_context(self):
        """
        Initialize shared ZeroMQ context if not already created
        """
        with self._context_lock:
            if not BaseBrokerWebSocketAdapter._shared_context:
                self.logger.info("Creating shared ZMQ context")
                BaseBrokerWebSocketAdapter._shared_context = zmq.Context()

        self.context = BaseBrokerWebSocketAdapter._shared_context

    def _create_socket(self):
        """
        Create and configure ZeroMQ socket
        """
        with self._context_lock:
            socket = self.context.socket(zmq.PUB)
            socket.setsockopt(zmq.LINGER, 1000)  # 1 second linger
            socket.setsockopt(zmq.SNDHWM, 1000)  # High water mark
            return socket

    def _bind_to_available_port(self):
        """
        Find an available port and bind the socket to it.
        If binding fails, closes the socket to prevent FD leak.
        """
        with self._port_lock:
            # Try default port from environment first
            default_port = int(os.getenv("ZMQ_PORT", "5555"))

            if default_port not in self._bound_ports and is_port_available(default_port):
                try:
                    self.socket.bind(f"tcp://*:{default_port}")
                    self._bound_ports.add(default_port)
                    self.logger.info(f"Bound to default port {default_port}")
                    return default_port
                except zmq.ZMQError as e:
                    self.logger.warning(f"Failed to bind to default port {default_port}: {e}")

            # Find random available port
            for attempt in range(5):
                port = find_free_zmq_port(start_port=5556 + random.randint(0, 1000))

                if not port:
                    self.logger.warning(f"Failed to find free port on attempt {attempt + 1}")
                    continue

                try:
                    self.socket.bind(f"tcp://*:{port}")
                    self._bound_ports.add(port)
                    self.logger.info(f"Successfully bound to port {port}")
                    return port
                except zmq.ZMQError as e:
                    self.logger.warning(f"Failed to bind to port {port}: {e}")
                    continue

            # All binding attempts failed - clean up socket to prevent FD leak
            try:
                if hasattr(self, "socket") and self.socket:
                    self.socket.close(linger=0)
                    self.socket = None
                    self.logger.warning("Closed socket after failed binding attempts")
            except Exception as cleanup_err:
                self.logger.warning(f"Error closing socket after bind failure: {cleanup_err}")

            raise RuntimeError("Could not bind to any available ZMQ port after multiple attempts")

    @abstractmethod
    def initialize(self, broker_name, user_id, auth_data=None):
        """
        Initialize connection with broker WebSocket API

        Args:
            broker_name: The name of the broker (e.g., 'angel', 'zerodha')
            user_id: The user's ID or client code
            auth_data: Dict containing authentication data, if not provided will fetch from DB
        """
        pass

    @abstractmethod
    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        """
        Subscribe to market data with the specified mode and depth level

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE')
            mode: Subscription mode - 1:LTP, 2:Quote, 4:Depth
            depth_level: Market depth level (5, 20, or 30 depending on broker support)

        Returns:
            dict: Response with status and capability information
        """
        pass

    @abstractmethod
    def unsubscribe(self, symbol, exchange, mode=2):
        """
        Unsubscribe from market data

        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Subscription mode

        Returns:
            dict: Response with status
        """
        pass

    @abstractmethod
    def connect(self):
        """
        Establish connection to the broker's WebSocket
        """
        pass

    @abstractmethod
    def disconnect(self):
        """
        Disconnect from the broker's WebSocket
        """
        pass

    def cleanup_zmq(self):
        """
        Properly clean up ZeroMQ resources and release bound ports.
        Skips cleanup if using shared ZeroMQ publisher (connection pooling mode).
        Also manages shared context lifecycle based on instance count.

        This method is idempotent - calling it multiple times is safe.
        """
        # Prevent double cleanup (e.g., explicit cleanup followed by __del__)
        if hasattr(self, "_zmq_cleaned_up") and self._zmq_cleaned_up:
            return
        self._zmq_cleaned_up = True

        # Skip cleanup if using shared ZMQ (managed by ConnectionPool)
        if hasattr(self, "_uses_shared_zmq") and self._uses_shared_zmq:
            self.logger.debug("Skipping ZMQ cleanup - using shared publisher")
            # Still decrement instance count (only once due to _zmq_cleaned_up flag)
            with self._context_lock:
                BaseBrokerWebSocketAdapter._instance_count = max(0, BaseBrokerWebSocketAdapter._instance_count - 1)
            return

        try:
            # Release the port from the bound ports set
            if hasattr(self, "zmq_port") and self.zmq_port:
                with self._port_lock:
                    self._bound_ports.discard(self.zmq_port)
                    self.logger.info(f"Released port {self.zmq_port}")

            # Close the socket
            if hasattr(self, "socket") and self.socket:
                self.socket.close(linger=0)  # Don't linger on close
                self.socket = None
                self.logger.info("ZeroMQ socket closed")

            # Decrement instance count and cleanup shared context if last instance
            with self._context_lock:
                BaseBrokerWebSocketAdapter._instance_count = max(0, BaseBrokerWebSocketAdapter._instance_count - 1)
                self.logger.debug(f"Adapter instance count after cleanup: {BaseBrokerWebSocketAdapter._instance_count}")

                # If this was the last instance, clean up shared context
                if BaseBrokerWebSocketAdapter._instance_count == 0 and BaseBrokerWebSocketAdapter._shared_context:
                    self.logger.info("Last adapter instance - cleaning up shared ZMQ context")
                    try:
                        BaseBrokerWebSocketAdapter._shared_context.term()
                    except Exception as ctx_err:
                        self.logger.warning(f"Error terminating shared context: {ctx_err}")
                    finally:
                        BaseBrokerWebSocketAdapter._shared_context = None

        except Exception as e:
            self.logger.exception(f"Error cleaning up ZeroMQ resources: {e}")

    def __del__(self):
        """
        Destructor to ensure ZeroMQ resources are properly cleaned up
        """
        try:
            self.cleanup_zmq()
        except Exception as e:
            # Can't use self.logger here as it might be gone during destruction
            logger.exception(f"Error in __del__ cleaning up ZMQ resources: {e}")
            pass

    @classmethod
    def cleanup_shared_context(cls):
        """
        Force cleanup of shared ZeroMQ context.

        Call this during app shutdown or restart to ensure all ZMQ resources
        are released, even if individual adapters weren't properly cleaned up.
        This is useful for scenarios where the app restarts without a full
        process exit.
        """
        with cls._context_lock:
            if cls._shared_context:
                try:
                    logger.info("Force cleaning up shared ZMQ context")
                    cls._shared_context.term()
                except Exception as e:
                    logger.warning(f"Error during forced context cleanup: {e}")
                finally:
                    cls._shared_context = None
                    cls._instance_count = 0

            # Also clear bound ports registry
            with cls._port_lock:
                if cls._bound_ports:
                    logger.info(f"Clearing {len(cls._bound_ports)} bound ports from registry")
                    cls._bound_ports.clear()

    @classmethod
    def get_resource_stats(cls) -> dict:
        """
        Get statistics about ZMQ resources for health monitoring.

        Returns:
            dict: Resource statistics including instance count and bound ports
        """
        with cls._context_lock:
            with cls._port_lock:
                return {
                    "active_adapter_instances": cls._instance_count,
                    "bound_ports_count": len(cls._bound_ports),
                    "bound_ports": list(cls._bound_ports),
                    "shared_context_active": cls._shared_context is not None,
                }

    def publish_market_data(self, topic, data):
        """
        Publish market data to ZeroMQ subscribers

        Args:
            topic: Topic string for subscriber filtering (e.g., 'NSE_RELIANCE_LTP')
            data: Market data dictionary
        """
        try:
            if self._uses_shared_zmq and self._shared_publisher:
                # Use shared publisher (connection pooling mode)
                self._shared_publisher.publish(topic, data)
            elif self.socket:
                # Use own socket
                self.socket.send_multipart(
                    [topic.encode("utf-8"), json.dumps(data).encode("utf-8")]
                )
            else:
                self.logger.warning("No ZMQ socket available for publishing")
        except Exception as e:
            self.logger.exception(f"Error publishing market data: {e}")

    def _create_success_response(self, message, **kwargs):
        """
        Create a standard success response
        """
        response = {"status": "success", "message": message}
        response.update(kwargs)
        return response

    def _create_error_response(self, code, message):
        """
        Create a standard error response
        """
        return {"status": "error", "code": code, "message": message}

    # =========================================================================
    # Authentication Helper Methods (Issue #765 - Stale Token Handling)
    # =========================================================================
    # These methods provide a standardized way for broker adapters to handle
    # authentication, including automatic retry with fresh tokens on 403 errors.

    def get_auth_token_for_user(self, user_id: str, bypass_cache: bool = False):
        """
        Get authentication token for a user with optional cache bypass.

        This is the recommended method for broker adapters to retrieve auth tokens.
        Use bypass_cache=True after receiving a 403 error to get fresh credentials.

        Args:
            user_id: The user's ID
            bypass_cache: If True, skip cache and query database directly

        Returns:
            The decrypted auth token, or None if not found/revoked
        """
        try:
            from database.auth_db import get_auth_token
            return get_auth_token(user_id, bypass_cache=bypass_cache)
        except Exception as e:
            self.logger.exception(f"Error getting auth token for user {user_id}: {e}")
            return None

    def get_fresh_auth_token(self, user_id: str):
        """
        Get fresh authentication token directly from database, bypassing cache.

        Use this method after receiving a 403/401 error to get the latest token.
        This clears the local cache entry and fetches fresh data from database.

        See GitHub issue #765 for details on the stale token problem this solves.

        Args:
            user_id: The user's ID

        Returns:
            The decrypted auth token, or None if not found/revoked
        """
        self.logger.info(f"Fetching fresh auth token for user {user_id} (bypassing cache)")
        return self.get_auth_token_for_user(user_id, bypass_cache=True)

    def clear_auth_cache_for_user(self, user_id: str):
        """
        Clear all cached authentication data for a user.

        Call this when you detect stale credentials (e.g., 403 error from broker).
        The next call to get_auth_token will fetch fresh data from database.

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

    def is_auth_error(self, error_message: str) -> bool:
        """
        Check if an error message indicates an authentication failure.

        Use this to detect when to retry with fresh credentials.

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

    def handle_auth_error_and_retry(self, user_id: str, retry_func, *args, **kwargs):
        """
        Handle authentication errors with automatic retry using fresh credentials.

        This method implements the database fallback pattern from issue #765:
        1. If an operation fails with 403/401, clear the cached token
        2. Fetch fresh token from database
        3. Retry the operation once with the new token

        Args:
            user_id: The user's ID for token refresh
            retry_func: The function to retry (should accept auth_token as first arg)
            *args: Additional positional arguments for retry_func
            **kwargs: Additional keyword arguments for retry_func

        Returns:
            The result of retry_func, or None if retry also fails
        """
        try:
            self.logger.info(f"Handling auth error for user {user_id} - fetching fresh token")

            # Clear stale cache
            self.clear_auth_cache_for_user(user_id)

            # Get fresh token from database
            fresh_token = self.get_fresh_auth_token(user_id)
            if not fresh_token:
                self.logger.error(f"No valid token found in database for user {user_id}")
                return None

            self.logger.info(f"Retrying operation with fresh token for user {user_id}")

            # Retry with fresh token
            return retry_func(fresh_token, *args, **kwargs)

        except Exception as e:
            self.logger.exception(f"Retry with fresh token failed for user {user_id}: {e}")
            return None
