"""
Connection Manager for WebSocket Proxy

Handles multiple WebSocket connections per broker to overcome symbol limits.
Each broker typically limits symbols per WebSocket session (e.g., Angel: 1000, Zerodha: 3000).
This module manages connection pooling transparently without modifying broker adapters.

Configuration:
    MAX_SYMBOLS_PER_WEBSOCKET: Maximum symbols per single WebSocket connection (default: 1000)
    MAX_WEBSOCKET_CONNECTIONS: Maximum WebSocket connections per user/broker (default: 3)
"""

import os
import json
import threading
import zmq
from typing import Dict, List, Optional, Any, Tuple, Callable
from collections import defaultdict
from utils.logging import get_logger

logger = get_logger(__name__)

# Default configuration - can be overridden via environment variables
DEFAULT_MAX_SYMBOLS_PER_WEBSOCKET = 1000
DEFAULT_MAX_WEBSOCKET_CONNECTIONS = 3


def get_max_symbols_per_websocket() -> int:
    """Get maximum symbols per WebSocket connection from config"""
    return int(os.getenv('MAX_SYMBOLS_PER_WEBSOCKET', DEFAULT_MAX_SYMBOLS_PER_WEBSOCKET))


def get_max_websocket_connections() -> int:
    """Get maximum WebSocket connections from config"""
    return int(os.getenv('MAX_WEBSOCKET_CONNECTIONS', DEFAULT_MAX_WEBSOCKET_CONNECTIONS))


class SharedZmqPublisher:
    """
    Shared ZeroMQ publisher that can be used by multiple adapter instances.
    Ensures all connections publish to the same ZeroMQ socket, so the WebSocketProxy
    receives data from all connections on a single port.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern to ensure only one shared publisher exists"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self.logger = get_logger("shared_zmq_publisher")
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.setsockopt(zmq.LINGER, 1000)
        self.socket.setsockopt(zmq.SNDHWM, 1000)
        self.zmq_port = None
        self._bound = False
        self._publish_lock = threading.Lock()

    def bind(self, port: Optional[int] = None) -> int:
        """
        Bind to a ZeroMQ port. If already bound, returns existing port.

        Args:
            port: Optional specific port to bind to

        Returns:
            The port number that was bound
        """
        if self._bound:
            return self.zmq_port

        with self._lock:
            if self._bound:
                return self.zmq_port

            # Try specified port or find available one
            if port:
                try:
                    self.socket.bind(f"tcp://*:{port}")
                    self.zmq_port = port
                    self._bound = True
                    os.environ["ZMQ_PORT"] = str(port)
                    self.logger.info(f"Shared ZMQ publisher bound to port {port}")
                    return port
                except zmq.ZMQError as e:
                    self.logger.warning(f"Failed to bind to port {port}: {e}")

            # Find available port
            default_port = int(os.getenv('ZMQ_PORT', '5555'))
            for attempt_port in range(default_port, default_port + 100):
                try:
                    self.socket.bind(f"tcp://*:{attempt_port}")
                    self.zmq_port = attempt_port
                    self._bound = True
                    os.environ["ZMQ_PORT"] = str(attempt_port)
                    self.logger.info(f"Shared ZMQ publisher bound to port {attempt_port}")
                    return attempt_port
                except zmq.ZMQError:
                    continue

            raise RuntimeError("Could not bind shared ZMQ publisher to any port")

    def publish(self, topic: str, data: dict):
        """
        Publish market data to ZeroMQ subscribers.
        Thread-safe publishing.

        Args:
            topic: Topic string for subscriber filtering
            data: Market data dictionary
        """
        if not self._bound:
            self.logger.error("Cannot publish: ZMQ socket not bound")
            return

        with self._publish_lock:
            try:
                self.socket.send_multipart([
                    topic.encode('utf-8'),
                    json.dumps(data).encode('utf-8')
                ])
            except Exception as e:
                self.logger.error(f"Error publishing to ZMQ: {e}")

    def cleanup(self):
        """Clean up ZeroMQ resources"""
        try:
            if self.socket:
                self.socket.close(linger=0)
            if self.context:
                self.context.term()
            self._bound = False
            self._initialized = False
            SharedZmqPublisher._instance = None
        except Exception as e:
            self.logger.error(f"Error cleaning up shared ZMQ publisher: {e}")


class ConnectionPool:
    """
    Manages multiple WebSocket connections for a single broker/user.

    Automatically creates new connections when symbol limits are reached,
    up to the configured maximum. Distributes subscriptions across connections
    and aggregates data from all connections through a shared ZeroMQ publisher.

    Usage:
        pool = ConnectionPool(
            adapter_class=AngelWebSocketAdapter,
            broker_name='angel',
            user_id='user123'
        )
        pool.initialize()
        pool.connect()
        pool.subscribe('RELIANCE', 'NSE', mode=2)
    """

    def __init__(
        self,
        adapter_class: type,
        broker_name: str,
        user_id: str,
        max_symbols_per_connection: Optional[int] = None,
        max_connections: Optional[int] = None
    ):
        """
        Initialize the connection pool.

        Args:
            adapter_class: The broker adapter class to instantiate
            broker_name: Name of the broker (e.g., 'angel', 'zerodha')
            user_id: User ID for authentication
            max_symbols_per_connection: Max symbols per WebSocket (default from config)
            max_connections: Max WebSocket connections (default from config)
        """
        self.adapter_class = adapter_class
        self.broker_name = broker_name
        self.user_id = user_id
        self.max_symbols = max_symbols_per_connection or get_max_symbols_per_websocket()
        self.max_connections = max_connections or get_max_websocket_connections()

        self.logger = get_logger(f"connection_pool_{broker_name}")
        self.lock = threading.RLock()

        # Connection tracking
        self.adapters: List[Any] = []  # List of adapter instances
        self.adapter_symbol_counts: List[int] = []  # Symbols per adapter

        # Subscription tracking: (symbol, exchange, mode) -> adapter_index
        self.subscription_map: Dict[Tuple[str, str, int], int] = {}

        # Shared ZeroMQ publisher
        self.shared_publisher = SharedZmqPublisher()

        # State
        self.initialized = False
        self.connected = False

        self.logger.info(
            f"ConnectionPool created for {broker_name}: "
            f"max {self.max_symbols} symbols/connection, "
            f"max {self.max_connections} connections"
        )

    def _create_adapter(self) -> Any:
        """
        Create a new adapter instance configured to use the shared ZeroMQ publisher.

        Returns:
            New adapter instance
        """
        # Ensure shared publisher is bound
        self.shared_publisher.bind()

        # Create adapter instance
        adapter = self.adapter_class()

        # Override the adapter's publish method to use shared publisher
        original_publish = adapter.publish_market_data

        def shared_publish(topic: str, data: dict):
            self.shared_publisher.publish(topic, data)

        adapter.publish_market_data = shared_publish

        # Mark that this adapter uses shared ZMQ (to skip individual cleanup)
        adapter._uses_shared_zmq = True

        return adapter

    def _get_adapter_with_capacity(self) -> Tuple[int, Any]:
        """
        Get an adapter with available capacity, or create a new one.

        Returns:
            Tuple of (adapter_index, adapter_instance)

        Raises:
            RuntimeError: If max connections reached and all are full
        """
        with self.lock:
            # Find adapter with capacity
            for idx, count in enumerate(self.adapter_symbol_counts):
                if count < self.max_symbols:
                    return idx, self.adapters[idx]

            # Need new adapter
            if len(self.adapters) >= self.max_connections:
                total_symbols = sum(self.adapter_symbol_counts)
                raise RuntimeError(
                    f"Maximum capacity reached: {self.max_connections} connections × "
                    f"{self.max_symbols} symbols = {self.max_connections * self.max_symbols} symbols. "
                    f"Currently subscribed to {total_symbols} symbols."
                )

            # Create new adapter
            self.logger.info(
                f"Creating connection {len(self.adapters) + 1}/{self.max_connections} "
                f"for {self.broker_name}"
            )

            adapter = self._create_adapter()

            # Initialize and connect the new adapter
            adapter.initialize(self.broker_name, self.user_id)
            adapter.connect()

            self.adapters.append(adapter)
            self.adapter_symbol_counts.append(0)

            return len(self.adapters) - 1, adapter

    def initialize(self, broker_name: str = None, user_id: str = None, auth_data: dict = None) -> dict:
        """
        Initialize the connection pool with the first adapter.

        Args:
            broker_name: Optional broker name override
            user_id: Optional user ID override
            auth_data: Optional authentication data

        Returns:
            Initialization result dict
        """
        if self.initialized:
            return {'success': True, 'message': 'Already initialized'}

        with self.lock:
            try:
                # Use provided values or defaults
                self.broker_name = broker_name or self.broker_name
                self.user_id = user_id or self.user_id

                # Ensure shared publisher is ready
                self.shared_publisher.bind()

                # Create first adapter
                adapter = self._create_adapter()
                result = adapter.initialize(self.broker_name, self.user_id, auth_data)

                if result and not result.get('success', True):
                    return result

                self.adapters.append(adapter)
                self.adapter_symbol_counts.append(0)
                self.initialized = True

                self.logger.info(f"ConnectionPool initialized for {self.broker_name}")
                return {'success': True, 'message': 'Connection pool initialized'}

            except Exception as e:
                self.logger.error(f"Failed to initialize connection pool: {e}")
                return {'success': False, 'error': str(e)}

    def connect(self) -> dict:
        """
        Connect the first adapter in the pool.
        Additional connections are created on-demand when capacity is needed.

        Returns:
            Connection result dict
        """
        if not self.initialized:
            return {'success': False, 'error': 'Not initialized'}

        if self.connected:
            return {'success': True, 'message': 'Already connected'}

        with self.lock:
            try:
                if self.adapters:
                    result = self.adapters[0].connect()
                    if result and not result.get('success', True):
                        return result
                    self.connected = True
                    return {'success': True, 'message': 'Connected'}
                else:
                    return {'success': False, 'error': 'No adapters available'}

            except Exception as e:
                self.logger.error(f"Failed to connect: {e}")
                return {'success': False, 'error': str(e)}

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> dict:
        """
        Subscribe to market data, automatically using connection with capacity.

        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Subscription mode (1=LTP, 2=Quote, 3=Depth)
            depth_level: Market depth level

        Returns:
            Subscription result dict
        """
        sub_key = (symbol, exchange, mode)

        with self.lock:
            # Check if already subscribed
            if sub_key in self.subscription_map:
                return {
                    'status': 'success',
                    'message': f'Already subscribed to {symbol}.{exchange}',
                    'connection': self.subscription_map[sub_key] + 1
                }

            try:
                # Get adapter with capacity
                adapter_idx, adapter = self._get_adapter_with_capacity()

                # Subscribe
                result = adapter.subscribe(symbol, exchange, mode, depth_level)

                if result.get('status') == 'success':
                    self.subscription_map[sub_key] = adapter_idx
                    self.adapter_symbol_counts[adapter_idx] += 1

                    # Add connection info to result
                    result['connection'] = adapter_idx + 1
                    result['total_connections'] = len(self.adapters)
                    result['symbols_on_connection'] = self.adapter_symbol_counts[adapter_idx]

                    self.logger.debug(
                        f"Subscribed {symbol}.{exchange} on connection {adapter_idx + 1}, "
                        f"symbols: {self.adapter_symbol_counts[adapter_idx]}/{self.max_symbols}"
                    )

                return result

            except RuntimeError as e:
                # Max capacity reached
                return {
                    'status': 'error',
                    'code': 'MAX_CAPACITY_REACHED',
                    'message': str(e)
                }
            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                return {
                    'status': 'error',
                    'code': 'SUBSCRIPTION_ERROR',
                    'message': str(e)
                }

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict:
        """
        Unsubscribe from market data.

        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Subscription mode

        Returns:
            Unsubscription result dict
        """
        sub_key = (symbol, exchange, mode)

        with self.lock:
            if sub_key not in self.subscription_map:
                return {
                    'status': 'error',
                    'code': 'NOT_SUBSCRIBED',
                    'message': f'Not subscribed to {symbol}.{exchange}'
                }

            try:
                adapter_idx = self.subscription_map[sub_key]
                adapter = self.adapters[adapter_idx]

                result = adapter.unsubscribe(symbol, exchange, mode)

                if result.get('status') == 'success':
                    del self.subscription_map[sub_key]
                    self.adapter_symbol_counts[adapter_idx] -= 1

                    self.logger.debug(
                        f"Unsubscribed {symbol}.{exchange} from connection {adapter_idx + 1}, "
                        f"remaining: {self.adapter_symbol_counts[adapter_idx]}"
                    )

                return result

            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                return {
                    'status': 'error',
                    'code': 'UNSUBSCRIPTION_ERROR',
                    'message': str(e)
                }

    def unsubscribe_all(self):
        """Unsubscribe from all symbols across all connections"""
        with self.lock:
            for adapter in self.adapters:
                if hasattr(adapter, 'unsubscribe_all'):
                    adapter.unsubscribe_all()

            self.subscription_map.clear()
            self.adapter_symbol_counts = [0] * len(self.adapters)

            self.logger.info("Unsubscribed from all symbols")

    def disconnect(self):
        """Disconnect all adapters and clean up"""
        with self.lock:
            for idx, adapter in enumerate(self.adapters):
                try:
                    # Skip ZMQ cleanup for adapters using shared publisher
                    if hasattr(adapter, '_uses_shared_zmq') and adapter._uses_shared_zmq:
                        # Temporarily disable ZMQ cleanup
                        original_cleanup = adapter.cleanup_zmq
                        adapter.cleanup_zmq = lambda: None

                    adapter.disconnect()

                    self.logger.debug(f"Disconnected connection {idx + 1}")
                except Exception as e:
                    self.logger.error(f"Error disconnecting adapter {idx + 1}: {e}")

            self.adapters.clear()
            self.adapter_symbol_counts.clear()
            self.subscription_map.clear()
            self.connected = False
            self.initialized = False

            self.logger.info("ConnectionPool disconnected")

    def get_stats(self) -> dict:
        """
        Get pool statistics.

        Returns:
            Dict with pool statistics
        """
        with self.lock:
            total_symbols = sum(self.adapter_symbol_counts)
            max_capacity = self.max_connections * self.max_symbols

            return {
                'broker': self.broker_name,
                'user_id': self.user_id,
                'active_connections': len(self.adapters),
                'max_connections': self.max_connections,
                'max_symbols_per_connection': self.max_symbols,
                'total_subscriptions': total_symbols,
                'max_capacity': max_capacity,
                'capacity_used_percent': (total_symbols / max_capacity * 100) if max_capacity > 0 else 0,
                'connections': [
                    {
                        'index': idx + 1,
                        'symbols': count,
                        'capacity_percent': (count / self.max_symbols * 100)
                    }
                    for idx, count in enumerate(self.adapter_symbol_counts)
                ]
            }

    # Compatibility methods to match BaseBrokerWebSocketAdapter interface

    @property
    def subscriptions(self) -> dict:
        """Get subscriptions dict for compatibility"""
        return {
            f"{k[0]}_{k[1]}_{k[2]}": {'symbol': k[0], 'exchange': k[1], 'mode': k[2]}
            for k in self.subscription_map.keys()
        }

    def publish_market_data(self, topic: str, data: dict):
        """Publish market data through shared publisher"""
        self.shared_publisher.publish(topic, data)


def create_pooled_adapter(
    adapter_class: type,
    broker_name: str,
    max_symbols_per_connection: Optional[int] = None,
    max_connections: Optional[int] = None
) -> Callable:
    """
    Factory function to create a pooled adapter factory.

    This returns a function that can be used in place of direct adapter instantiation,
    providing transparent connection pooling.

    Args:
        adapter_class: The broker adapter class
        broker_name: Name of the broker
        max_symbols_per_connection: Optional override for max symbols
        max_connections: Optional override for max connections

    Returns:
        A factory function that creates ConnectionPool instances
    """
    def factory():
        # The pool will be initialized with user_id later
        # Return a wrapper that creates the pool on first use
        class PooledAdapterWrapper:
            def __init__(self):
                self._pool = None
                self._adapter_class = adapter_class
                self._broker_name = broker_name
                self._max_symbols = max_symbols_per_connection
                self._max_connections = max_connections

            def _ensure_pool(self, user_id: str) -> ConnectionPool:
                if self._pool is None:
                    self._pool = ConnectionPool(
                        adapter_class=self._adapter_class,
                        broker_name=self._broker_name,
                        user_id=user_id,
                        max_symbols_per_connection=self._max_symbols,
                        max_connections=self._max_connections
                    )
                return self._pool

            def initialize(self, broker_name: str, user_id: str, auth_data: dict = None):
                pool = self._ensure_pool(user_id)
                return pool.initialize(broker_name, user_id, auth_data)

            def connect(self):
                if self._pool:
                    return self._pool.connect()
                return {'success': False, 'error': 'Not initialized'}

            def disconnect(self):
                if self._pool:
                    self._pool.disconnect()

            def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5):
                if self._pool:
                    return self._pool.subscribe(symbol, exchange, mode, depth_level)
                return {'status': 'error', 'message': 'Not initialized'}

            def unsubscribe(self, symbol: str, exchange: str, mode: int = 2):
                if self._pool:
                    return self._pool.unsubscribe(symbol, exchange, mode)
                return {'status': 'error', 'message': 'Not initialized'}

            def unsubscribe_all(self):
                if self._pool:
                    self._pool.unsubscribe_all()

            def get_stats(self):
                if self._pool:
                    return self._pool.get_stats()
                return {}

            @property
            def subscriptions(self):
                if self._pool:
                    return self._pool.subscriptions
                return {}

            def publish_market_data(self, topic: str, data: dict):
                if self._pool:
                    self._pool.publish_market_data(topic, data)

        return PooledAdapterWrapper()

    return factory
