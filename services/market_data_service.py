"""
Enhanced Market Data Service for Trade Management

This service provides reliable real-time market data for:
- OpenAlgo Flow (stoploss, target, price monitoring)
- Watchlist Management
- Dashboard displays
- Future RMS Engine

Features:
- Connection health monitoring
- Data validation and stale data detection
- Priority subscriber system (critical vs display)
- Auto-reconnection awareness
- Health status API
"""

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


class SubscriberPriority(IntEnum):
    """Priority levels for subscribers - lower number = higher priority"""

    CRITICAL = 1  # Trade management (stoploss, target) - processed first
    HIGH = 2  # Price alerts, monitoring
    NORMAL = 3  # Watchlist, general display
    LOW = 4  # Dashboard, analytics


class ConnectionStatus(IntEnum):
    """Connection status states"""

    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    AUTHENTICATED = 3
    STALE = 4  # Connected but no data received recently


@dataclass
class HealthStatus:
    """Health status of the market data service"""

    status: str = "unknown"
    connected: bool = False
    authenticated: bool = False
    last_data_timestamp: float = 0
    last_data_age_seconds: float = 0
    data_flow_healthy: bool = False
    cache_size: int = 0
    total_subscribers: int = 0
    critical_subscribers: int = 0
    total_updates_processed: int = 0
    validation_errors: int = 0
    stale_data_events: int = 0
    reconnect_count: int = 0
    uptime_seconds: float = 0
    message: str = ""


@dataclass
class ValidationResult:
    """Result of data validation"""

    valid: bool
    error: str = ""
    warnings: list[str] = field(default_factory=list)


class MarketDataValidator:
    """Validates incoming market data for reliability"""

    # Maximum allowed price change percentage (circuit breaker check)
    MAX_PRICE_CHANGE_PERCENT = 20.0

    # Maximum age of data in seconds before considered stale
    MAX_DATA_AGE_SECONDS = 60

    def __init__(self):
        self.last_known_prices: dict[str, float] = {}
        self.lock = threading.Lock()

    def validate(self, data: dict[str, Any]) -> ValidationResult:
        """
        Validate incoming market data

        Args:
            data: Market data dictionary

        Returns:
            ValidationResult with validation status
        """
        warnings = []

        # Check required fields
        symbol = data.get("symbol")
        exchange = data.get("exchange")

        if not symbol or not exchange:
            return ValidationResult(valid=False, error="Missing symbol or exchange")

        market_data = data.get("data", {})
        ltp = market_data.get("ltp")

        # Check LTP is valid
        if ltp is None:
            return ValidationResult(valid=False, error="Missing LTP value")

        if not isinstance(ltp, (int, float)):
            return ValidationResult(valid=False, error=f"Invalid LTP type: {type(ltp)}")

        if ltp <= 0:
            return ValidationResult(valid=False, error=f"Invalid LTP value: {ltp}")

        # Check for stale timestamp
        timestamp = market_data.get("timestamp")
        if timestamp:
            # Convert string timestamp to number if needed (some brokers send string)
            if isinstance(timestamp, str):
                try:
                    timestamp = float(timestamp)
                except (ValueError, TypeError):
                    timestamp = None

            if timestamp:
                # Handle both epoch seconds and milliseconds
                if timestamp > 1e12:  # Milliseconds
                    timestamp = timestamp / 1000

                data_age = time.time() - timestamp
                if data_age > self.MAX_DATA_AGE_SECONDS:
                    warnings.append(f"Data is {data_age:.1f} seconds old")

        # Circuit breaker check - large price changes
        symbol_key = f"{exchange}:{symbol}"
        with self.lock:
            if symbol_key in self.last_known_prices:
                last_price = self.last_known_prices[symbol_key]
                if last_price > 0:
                    change_percent = abs((ltp - last_price) / last_price) * 100
                    if change_percent > self.MAX_PRICE_CHANGE_PERCENT:
                        warnings.append(f"Large price change: {change_percent:.2f}%")

            # Update last known price
            self.last_known_prices[symbol_key] = ltp

        return ValidationResult(valid=True, warnings=warnings)

    def clear_price_history(self, symbol_key: str | None = None):
        """Clear price history for validation"""
        with self.lock:
            if symbol_key:
                self.last_known_prices.pop(symbol_key, None)
            else:
                self.last_known_prices.clear()


class ConnectionHealthMonitor:
    """Monitors WebSocket connection health"""

    # Maximum time without data before connection considered stale
    MAX_DATA_GAP_SECONDS = 30

    # Health check interval
    HEALTH_CHECK_INTERVAL = 5

    def __init__(self):
        self.last_data_timestamp: float = 0
        self.connection_status = ConnectionStatus.DISCONNECTED
        self.reconnect_count = 0
        self.start_time = time.time()
        self.lock = threading.Lock()

        # Health event callbacks
        self.on_connection_lost: Callable | None = None
        self.on_connection_restored: Callable | None = None
        self.on_data_stale: Callable | None = None

        # Start health check thread
        self._running = True
        self._health_thread = threading.Thread(target=self._health_check_loop, daemon=True)
        self._health_thread.start()

    def record_data_received(self):
        """Record that data was received"""
        with self.lock:
            self.last_data_timestamp = time.time()
            if self.connection_status == ConnectionStatus.STALE:
                self.connection_status = ConnectionStatus.AUTHENTICATED
                if self.on_connection_restored:
                    try:
                        self.on_connection_restored()
                    except Exception as e:
                        logger.exception(f"Error in connection restored callback: {e}")

    def set_connected(self, connected: bool, authenticated: bool = False):
        """Update connection status"""
        with self.lock:
            if connected:
                if authenticated:
                    self.connection_status = ConnectionStatus.AUTHENTICATED
                else:
                    self.connection_status = ConnectionStatus.CONNECTED
            else:
                prev_status = self.connection_status
                self.connection_status = ConnectionStatus.DISCONNECTED
                if prev_status in (ConnectionStatus.CONNECTED, ConnectionStatus.AUTHENTICATED):
                    self.reconnect_count += 1
                    if self.on_connection_lost:
                        try:
                            self.on_connection_lost()
                        except Exception as e:
                            logger.exception(f"Error in connection lost callback: {e}")

    def get_health(self) -> dict[str, Any]:
        """Get current health status"""
        with self.lock:
            now = time.time()
            data_age = now - self.last_data_timestamp if self.last_data_timestamp > 0 else -1

            is_healthy = self.connection_status == ConnectionStatus.AUTHENTICATED and (
                data_age < self.MAX_DATA_GAP_SECONDS or data_age < 0
            )

            return {
                "healthy": is_healthy,
                "connection_status": self.connection_status.name,
                "last_data_age_seconds": round(data_age, 2) if data_age >= 0 else None,
                "data_flow_active": data_age < self.MAX_DATA_GAP_SECONDS
                if data_age >= 0
                else False,
                "reconnect_count": self.reconnect_count,
                "uptime_seconds": round(now - self.start_time, 2),
            }

    def is_data_fresh(self, max_age_seconds: float = None) -> bool:
        """Check if data is fresh enough for trade management"""
        max_age = max_age_seconds or self.MAX_DATA_GAP_SECONDS
        with self.lock:
            if self.last_data_timestamp == 0:
                return False
            return (time.time() - self.last_data_timestamp) < max_age

    def _health_check_loop(self):
        """Background thread to check health"""
        while self._running:
            try:
                time.sleep(self.HEALTH_CHECK_INTERVAL)

                with self.lock:
                    if self.connection_status == ConnectionStatus.AUTHENTICATED:
                        data_age = time.time() - self.last_data_timestamp
                        if self.last_data_timestamp > 0 and data_age > self.MAX_DATA_GAP_SECONDS:
                            self.connection_status = ConnectionStatus.STALE
                            logger.warning(f"Connection marked stale - no data for {data_age:.1f}s")
                            if self.on_data_stale:
                                try:
                                    self.on_data_stale()
                                except Exception as e:
                                    logger.exception(f"Error in data stale callback: {e}")
            except Exception as e:
                logger.exception(f"Error in health check loop: {e}")

    def stop(self):
        """Stop the health monitor"""
        self._running = False


class MarketDataService:
    """
    Enhanced singleton service for managing market data across the application.

    Features:
    - Connection health monitoring
    - Data validation
    - Priority-based subscriber system
    - Stale data protection for trade management
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
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
        self.data_lock = threading.Lock()

        # Market data cache structure
        self.market_data_cache: dict[str, dict[str, Any]] = {}

        # Enhanced subscriber system with priorities
        # {priority: {subscriber_id: {callback, filter, name}}}
        self.priority_subscribers: dict[int, dict[int, dict]] = defaultdict(dict)
        self.subscriber_id_counter = 0

        # Legacy subscribers (for backward compatibility)
        self.subscribers = defaultdict(dict)

        # User-specific data tracking
        self.user_access_tracking = defaultdict(dict)

        # Initialize components
        self.validator = MarketDataValidator()
        self.health_monitor = ConnectionHealthMonitor()

        # Setup health monitor callbacks
        self.health_monitor.on_connection_lost = self._on_connection_lost
        self.health_monitor.on_connection_restored = self._on_connection_restored
        self.health_monitor.on_data_stale = self._on_data_stale

        # Metrics
        self.metrics = {
            "total_updates": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "validation_errors": 0,
            "stale_data_events": 0,
            "last_cleanup": time.time(),
            "start_time": time.time(),
        }

        # Stale data protection flags
        self._trade_management_paused = False
        self._pause_reason = ""

        # Start cleanup thread
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()

        logger.debug("Enhanced MarketDataService initialized")

    def process_market_data(self, data: dict[str, Any]) -> bool:
        """
        Process incoming market data from WebSocket

        Args:
            data: Market data dictionary from WebSocket

        Returns:
            bool: True if data was processed successfully
        """
        try:
            # Validate data
            validation_result = self.validator.validate(data)

            if not validation_result.valid:
                self.metrics["validation_errors"] += 1
                logger.warning(f"Data validation failed: {validation_result.error}")
                return False

            if validation_result.warnings:
                for warning in validation_result.warnings:
                    logger.debug(f"Data warning: {warning}")

            # Record data received for health monitoring
            self.health_monitor.record_data_received()

            # Extract data
            symbol = data.get("symbol")
            exchange = data.get("exchange")
            mode = data.get("mode")
            market_data = data.get("data", {})

            if not symbol or not exchange:
                return False

            symbol_key = f"{exchange}:{symbol}"
            timestamp = int(time.time())

            with self.data_lock:
                # Initialize cache entry if needed
                if symbol_key not in self.market_data_cache:
                    self.market_data_cache[symbol_key] = {
                        "symbol": symbol,
                        "exchange": exchange,
                        "last_update": timestamp,
                    }

                cache_entry = self.market_data_cache[symbol_key]

                # Update based on mode
                if mode == 1:  # LTP
                    cache_entry["ltp"] = {
                        "value": market_data.get("ltp", 0),
                        "timestamp": market_data.get("timestamp", timestamp),
                        "volume": market_data.get("volume", 0),
                    }
                elif mode == 2:  # Quote
                    cache_entry["quote"] = {
                        "open": market_data.get("open", 0),
                        "high": market_data.get("high", 0),
                        "low": market_data.get("low", 0),
                        "close": market_data.get("close", 0),
                        "ltp": market_data.get("ltp", 0),
                        "volume": market_data.get("volume", 0),
                        "change": market_data.get("change", 0),
                        "change_percent": market_data.get("change_percent", 0),
                        "timestamp": market_data.get("timestamp", timestamp),
                    }
                    # Also update LTP from quote
                    cache_entry["ltp"] = {
                        "value": market_data.get("ltp", 0),
                        "timestamp": market_data.get("timestamp", timestamp),
                        "volume": market_data.get("volume", 0),
                    }
                elif mode == 3:  # Depth
                    cache_entry["depth"] = {
                        "buy": market_data.get("depth", {}).get("buy", []),
                        "sell": market_data.get("depth", {}).get("sell", []),
                        "ltp": market_data.get("ltp", 0),
                        "timestamp": market_data.get("timestamp", timestamp),
                    }

                cache_entry["last_update"] = timestamp
                self.metrics["total_updates"] += 1

            # Broadcast to subscribers by priority (critical first)
            self._broadcast_update_priority(symbol_key, mode, data)

            # Also broadcast using legacy system for backward compatibility
            self._broadcast_update(symbol_key, mode, data)

            return True

        except Exception as e:
            logger.exception(f"Error processing market data: {e}")
            return False

    def subscribe_with_priority(
        self,
        priority: SubscriberPriority,
        event_type: str,
        callback: Callable,
        filter_symbols: set[str] | None = None,
        name: str = "",
    ) -> int:
        """
        Subscribe to market data updates with priority

        Args:
            priority: Subscriber priority (CRITICAL, HIGH, NORMAL, LOW)
            event_type: Type of update ('ltp', 'quote', 'depth', 'all')
            callback: Function to call with updates
            filter_symbols: Optional set of symbol keys to filter updates
            name: Optional name for the subscriber (for debugging)

        Returns:
            Subscriber ID for unsubscribing
        """
        with self.data_lock:
            self.subscriber_id_counter += 1
            subscriber_id = self.subscriber_id_counter

            self.priority_subscribers[priority][subscriber_id] = {
                "callback": callback,
                "filter": filter_symbols,
                "event_type": event_type,
                "name": name or f"subscriber_{subscriber_id}",
                "created_at": time.time(),
            }

        logger.debug(
            f"Added priority subscriber {subscriber_id} ({name}) - priority={priority.name}, type={event_type}"
        )
        return subscriber_id

    def subscribe_critical(
        self, callback: Callable, filter_symbols: set[str] | None = None, name: str = ""
    ) -> int:
        """
        Subscribe with CRITICAL priority for trade management
        (stoploss, target monitoring)

        Args:
            callback: Function to call with LTP updates
            filter_symbols: Symbols to monitor
            name: Subscriber name

        Returns:
            Subscriber ID
        """
        return self.subscribe_with_priority(
            SubscriberPriority.CRITICAL, "ltp", callback, filter_symbols, name or "trade_management"
        )

    def unsubscribe_priority(self, subscriber_id: int) -> bool:
        """
        Unsubscribe a priority subscriber

        Args:
            subscriber_id: ID returned from subscribe_with_priority

        Returns:
            True if unsubscribed successfully
        """
        with self.data_lock:
            for priority in self.priority_subscribers:
                if subscriber_id in self.priority_subscribers[priority]:
                    name = self.priority_subscribers[priority][subscriber_id].get("name", "")
                    del self.priority_subscribers[priority][subscriber_id]
                    logger.info(f"Removed priority subscriber {subscriber_id} ({name})")
                    return True

        return False

    # Legacy subscribe method for backward compatibility
    def subscribe_to_updates(
        self, event_type: str, callback: Callable, filter_symbols: set[str] | None = None
    ) -> int:
        """
        Subscribe to market data updates (legacy method)

        Args:
            event_type: Type of update ('ltp', 'quote', 'depth', 'all')
            callback: Function to call with updates
            filter_symbols: Optional set of symbol keys to filter updates

        Returns:
            Subscriber ID for unsubscribing
        """
        with self.data_lock:
            self.subscriber_id_counter += 1
            subscriber_id = self.subscriber_id_counter

            self.subscribers[event_type][subscriber_id] = {
                "callback": callback,
                "filter": filter_symbols,
            }

        logger.info(f"Added subscriber {subscriber_id} for {event_type} updates")
        return subscriber_id

    def unsubscribe_from_updates(self, subscriber_id: int) -> bool:
        """
        Unsubscribe from market data updates (legacy method)

        Args:
            subscriber_id: ID returned from subscribe_to_updates

        Returns:
            True if unsubscribed successfully
        """
        # Try priority subscribers first
        if self.unsubscribe_priority(subscriber_id):
            return True

        # Then try legacy subscribers
        with self.data_lock:
            for event_type in self.subscribers:
                if subscriber_id in self.subscribers[event_type]:
                    del self.subscribers[event_type][subscriber_id]
                    logger.info(f"Removed subscriber {subscriber_id}")
                    return True

        return False

    def get_ltp(self, symbol: str, exchange: str) -> dict[str, Any] | None:
        """
        Get latest LTP for a symbol

        Args:
            symbol: Trading symbol
            exchange: Exchange name

        Returns:
            LTP data dictionary or None
        """
        symbol_key = f"{exchange}:{symbol}"

        with self.data_lock:
            if symbol_key in self.market_data_cache:
                self.metrics["cache_hits"] += 1
                return self.market_data_cache[symbol_key].get("ltp")

        self.metrics["cache_misses"] += 1
        return None

    def get_ltp_value(self, symbol: str, exchange: str) -> float | None:
        """
        Get just the LTP value for a symbol (convenience method)

        Args:
            symbol: Trading symbol
            exchange: Exchange name

        Returns:
            LTP value or None
        """
        ltp_data = self.get_ltp(symbol, exchange)
        if ltp_data:
            return ltp_data.get("value")
        return None

    def get_quote(self, symbol: str, exchange: str) -> dict[str, Any] | None:
        """
        Get latest quote for a symbol

        Args:
            symbol: Trading symbol
            exchange: Exchange name

        Returns:
            Quote data dictionary or None
        """
        symbol_key = f"{exchange}:{symbol}"

        with self.data_lock:
            if symbol_key in self.market_data_cache:
                self.metrics["cache_hits"] += 1
                return self.market_data_cache[symbol_key].get("quote")

        self.metrics["cache_misses"] += 1
        return None

    def get_market_depth(self, symbol: str, exchange: str) -> dict[str, Any] | None:
        """
        Get market depth for a symbol

        Args:
            symbol: Trading symbol
            exchange: Exchange name

        Returns:
            Market depth data dictionary or None
        """
        symbol_key = f"{exchange}:{symbol}"

        with self.data_lock:
            if symbol_key in self.market_data_cache:
                self.metrics["cache_hits"] += 1
                return self.market_data_cache[symbol_key].get("depth")

        self.metrics["cache_misses"] += 1
        return None

    def get_all_data(self, symbol: str, exchange: str) -> dict[str, Any]:
        """
        Get all available data for a symbol

        Args:
            symbol: Trading symbol
            exchange: Exchange name

        Returns:
            All market data for the symbol
        """
        symbol_key = f"{exchange}:{symbol}"

        with self.data_lock:
            if symbol_key in self.market_data_cache:
                return dict(self.market_data_cache[symbol_key])

        return {}

    def get_multiple_ltps(self, symbols: list[dict[str, str]]) -> dict[str, Any]:
        """
        Get LTPs for multiple symbols

        Args:
            symbols: List of symbol dictionaries with 'symbol' and 'exchange' keys

        Returns:
            Dictionary mapping symbol_key to LTP data
        """
        result = {}

        with self.data_lock:
            for symbol_info in symbols:
                symbol = symbol_info.get("symbol")
                exchange = symbol_info.get("exchange")
                if symbol and exchange:
                    symbol_key = f"{exchange}:{symbol}"
                    if symbol_key in self.market_data_cache:
                        ltp_data = self.market_data_cache[symbol_key].get("ltp")
                        if ltp_data:
                            result[symbol_key] = ltp_data

        return result

    def is_data_fresh(
        self, symbol: str = None, exchange: str = None, max_age_seconds: float = 30
    ) -> bool:
        """
        Check if data is fresh enough for trade management

        Args:
            symbol: Optional symbol to check
            exchange: Optional exchange
            max_age_seconds: Maximum acceptable age

        Returns:
            True if data is fresh
        """
        # First check overall health
        if not self.health_monitor.is_data_fresh(max_age_seconds):
            return False

        # If specific symbol requested, check its freshness
        if symbol and exchange:
            symbol_key = f"{exchange}:{symbol}"
            with self.data_lock:
                if symbol_key in self.market_data_cache:
                    last_update = self.market_data_cache[symbol_key].get("last_update", 0)
                    return (time.time() - last_update) < max_age_seconds
                return False

        return True

    def is_trade_management_safe(self) -> tuple[bool, str]:
        """
        Check if it's safe to perform trade management operations
        (stoploss, target triggers)

        Returns:
            Tuple of (is_safe, reason_if_not_safe)
        """
        if self._trade_management_paused:
            return False, self._pause_reason

        health = self.health_monitor.get_health()

        if not health["healthy"]:
            return False, f"Connection unhealthy: {health['connection_status']}"

        if not health["data_flow_active"]:
            return False, f"Data flow inactive for {health['last_data_age_seconds']}s"

        return True, ""

    def get_health_status(self) -> HealthStatus:
        """
        Get comprehensive health status of the service

        Returns:
            HealthStatus object with all health metrics
        """
        health = self.health_monitor.get_health()

        with self.data_lock:
            total_subscribers = sum(len(subs) for subs in self.priority_subscribers.values()) + sum(
                len(subs) for subs in self.subscribers.values()
            )

            critical_subscribers = len(
                self.priority_subscribers.get(SubscriberPriority.CRITICAL, {})
            )

        return HealthStatus(
            status="healthy" if health["healthy"] else "unhealthy",
            connected=health["connection_status"] in ("CONNECTED", "AUTHENTICATED"),
            authenticated=health["connection_status"] == "AUTHENTICATED",
            last_data_timestamp=self.health_monitor.last_data_timestamp,
            last_data_age_seconds=health["last_data_age_seconds"] or 0,
            data_flow_healthy=health["data_flow_active"],
            cache_size=len(self.market_data_cache),
            total_subscribers=total_subscribers,
            critical_subscribers=critical_subscribers,
            total_updates_processed=self.metrics["total_updates"],
            validation_errors=self.metrics["validation_errors"],
            stale_data_events=self.metrics["stale_data_events"],
            reconnect_count=health["reconnect_count"],
            uptime_seconds=health["uptime_seconds"],
            message=self._pause_reason if self._trade_management_paused else "",
        )

    def get_cache_metrics(self) -> dict[str, Any]:
        """Get performance metrics"""
        with self.data_lock:
            total_requests = self.metrics["cache_hits"] + self.metrics["cache_misses"]
            hit_rate = (
                (self.metrics["cache_hits"] / total_requests * 100) if total_requests > 0 else 0
            )

            return {
                "total_symbols": len(self.market_data_cache),
                "total_updates": self.metrics["total_updates"],
                "cache_hits": self.metrics["cache_hits"],
                "cache_misses": self.metrics["cache_misses"],
                "hit_rate": round(hit_rate, 2),
                "validation_errors": self.metrics["validation_errors"],
                "stale_data_events": self.metrics["stale_data_events"],
                "total_subscribers": sum(len(subs) for subs in self.priority_subscribers.values())
                + sum(len(subs) for subs in self.subscribers.values()),
                "critical_subscribers": len(
                    self.priority_subscribers.get(SubscriberPriority.CRITICAL, {})
                ),
            }

    def register_user_callback(self, username: str) -> bool:
        """
        Register market data callback for a specific user

        Args:
            username: Username

        Returns:
            Success status
        """
        from .websocket_service import register_market_data_callback

        def user_callback(data):
            try:
                self.process_market_data(data)
            except Exception as e:
                logger.exception(f"Error processing market data in callback: {e}")

        return register_market_data_callback(username, user_callback)

    def update_connection_status(self, connected: bool, authenticated: bool = False):
        """
        Update connection status (called by websocket_service)

        Args:
            connected: Whether connected
            authenticated: Whether authenticated
        """
        self.health_monitor.set_connected(connected, authenticated)

    def clear_cache(self, symbol: str | None = None, exchange: str | None = None) -> None:
        """
        Clear market data cache

        Args:
            symbol: Specific symbol to clear (optional)
            exchange: Exchange for the symbol (optional)
        """
        with self.data_lock:
            if symbol and exchange:
                symbol_key = f"{exchange}:{symbol}"
                if symbol_key in self.market_data_cache:
                    del self.market_data_cache[symbol_key]
                    self.validator.clear_price_history(symbol_key)
                    logger.info(f"Cleared cache for {symbol_key}")
            else:
                self.market_data_cache.clear()
                self.validator.clear_price_history()
                logger.info("Cleared entire market data cache")

    def _broadcast_update_priority(self, symbol_key: str, mode: int, data: dict[str, Any]) -> None:
        """
        Broadcast updates to priority subscribers (critical first)

        Args:
            symbol_key: Symbol key (exchange:symbol)
            mode: Update mode (1=LTP, 2=Quote, 3=Depth)
            data: Full data to broadcast
        """
        mode_to_event = {1: "ltp", 2: "quote", 3: "depth"}
        event_type = mode_to_event.get(mode, "all")

        # Process subscribers by priority (CRITICAL first)
        for priority in sorted(self.priority_subscribers.keys()):
            with self.data_lock:
                subscribers = list(self.priority_subscribers[priority].values())

            for subscriber in subscribers:
                try:
                    # Check event type filter
                    sub_event_type = subscriber.get("event_type", "all")
                    if sub_event_type != "all" and sub_event_type != event_type:
                        continue

                    # Check symbol filter
                    if subscriber["filter"] and symbol_key not in subscriber["filter"]:
                        continue

                    # Call the callback
                    subscriber["callback"](data)

                except Exception as e:
                    logger.exception(
                        f"Error in priority subscriber callback ({subscriber.get('name', 'unknown')}): {e}"
                    )

    def _broadcast_update(self, symbol_key: str, mode: int, data: dict[str, Any]) -> None:
        """
        Broadcast updates to legacy subscribers (backward compatibility)

        Args:
            symbol_key: Symbol key (exchange:symbol)
            mode: Update mode (1=LTP, 2=Quote, 3=Depth)
            data: Full data to broadcast
        """
        mode_to_event = {1: "ltp", 2: "quote", 3: "depth"}
        event_type = mode_to_event.get(mode, "all")

        # Broadcast to specific event subscribers
        with self.data_lock:
            subscribers = list(self.subscribers[event_type].values())
            all_subscribers = list(self.subscribers["all"].values())

        for subscriber in subscribers + all_subscribers:
            try:
                # Check filter
                if subscriber["filter"] and symbol_key not in subscriber["filter"]:
                    continue

                # Call the callback
                subscriber["callback"](data)
            except Exception as e:
                logger.exception(f"Error in subscriber callback: {e}")

    def _on_connection_lost(self):
        """Handle connection lost event"""
        logger.warning("Market data connection lost")
        self._trade_management_paused = True
        self._pause_reason = "Connection lost - trade management paused for safety"
        self.metrics["stale_data_events"] += 1

    def _on_connection_restored(self):
        """Handle connection restored event"""
        logger.info("Market data connection restored")
        self._trade_management_paused = False
        self._pause_reason = ""

    def _on_data_stale(self):
        """Handle data stale event"""
        logger.warning("Market data is stale")
        self._trade_management_paused = True
        self._pause_reason = "Data is stale - trade management paused for safety"
        self.metrics["stale_data_events"] += 1

    def _cleanup_loop(self) -> None:
        """Background thread to clean up stale data"""
        while True:
            try:
                time.sleep(300)  # Run every 5 minutes

                current_time = time.time()
                stale_threshold = 3600  # 1 hour

                with self.data_lock:
                    # Clean up stale market data
                    stale_symbols = []
                    for symbol_key, data in self.market_data_cache.items():
                        if current_time - data.get("last_update", 0) > stale_threshold:
                            stale_symbols.append(symbol_key)

                    for symbol_key in stale_symbols:
                        del self.market_data_cache[symbol_key]
                        self.validator.clear_price_history(symbol_key)

                    # Clean up old user access tracking
                    for user_id in list(self.user_access_tracking.keys()):
                        user_data = self.user_access_tracking[user_id]
                        stale_accesses = [
                            symbol_key
                            for symbol_key, last_access in user_data.items()
                            if current_time - last_access > stale_threshold
                        ]
                        for symbol_key in stale_accesses:
                            del user_data[symbol_key]

                        if not user_data:
                            del self.user_access_tracking[user_id]

                    self.metrics["last_cleanup"] = current_time

                if stale_symbols:
                    logger.info(f"Cleaned up {len(stale_symbols)} stale market data entries")

            except Exception as e:
                logger.exception(f"Error in cleanup loop: {e}")


# Global instance
_market_data_service = MarketDataService()


# Convenience functions
def get_market_data_service() -> MarketDataService:
    """Get the global MarketDataService instance"""
    return _market_data_service


def get_ltp(symbol: str, exchange: str) -> dict[str, Any] | None:
    """Get LTP for a symbol"""
    return _market_data_service.get_ltp(symbol, exchange)


def get_ltp_value(symbol: str, exchange: str) -> float | None:
    """Get just the LTP value for a symbol"""
    return _market_data_service.get_ltp_value(symbol, exchange)


def get_quote(symbol: str, exchange: str) -> dict[str, Any] | None:
    """Get quote for a symbol"""
    return _market_data_service.get_quote(symbol, exchange)


def get_market_depth(symbol: str, exchange: str) -> dict[str, Any] | None:
    """Get market depth for a symbol"""
    return _market_data_service.get_market_depth(symbol, exchange)


def subscribe_to_market_updates(
    event_type: str, callback: Callable, filter_symbols: set[str] | None = None
) -> int:
    """Subscribe to market data updates (legacy)"""
    return _market_data_service.subscribe_to_updates(event_type, callback, filter_symbols)


def subscribe_critical(
    callback: Callable, filter_symbols: set[str] | None = None, name: str = ""
) -> int:
    """Subscribe with CRITICAL priority for trade management"""
    return _market_data_service.subscribe_critical(callback, filter_symbols, name)


def unsubscribe_from_market_updates(subscriber_id: int) -> bool:
    """Unsubscribe from market data updates"""
    return _market_data_service.unsubscribe_from_updates(subscriber_id)


def is_data_fresh(symbol: str = None, exchange: str = None, max_age_seconds: float = 30) -> bool:
    """Check if data is fresh enough for trade management"""
    return _market_data_service.is_data_fresh(symbol, exchange, max_age_seconds)


def is_trade_management_safe() -> tuple[bool, str]:
    """Check if it's safe to perform trade management operations"""
    return _market_data_service.is_trade_management_safe()


def get_health_status() -> HealthStatus:
    """Get comprehensive health status"""
    return _market_data_service.get_health_status()
