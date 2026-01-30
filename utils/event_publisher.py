"""
Event Publisher Abstraction Layer

This module provides an abstraction layer for publishing order events and system notifications.
Supports both Socket.IO (default) and Kafka modes, controlled by ORDER_EVENT_MODE environment variable.

Usage:
    from utils.event_publisher import get_event_publisher
    
    event_publisher = get_event_publisher()
    event_publisher.publish_order_event(
        user_id="user123",
        symbol="SBIN-EQ",
        action="BUY",
        orderid="ORD123",
        mode="live"
    )

Environment Variables:
    ORDER_EVENT_MODE: 'SOCKETIO' (default) or 'KAFKA'
    KAFKA_BOOTSTRAP_SERVERS: Comma-separated Kafka broker addresses (required for KAFKA mode)
    KAFKA_ORDER_EVENTS_TOPIC: Topic name for publishing events (required for KAFKA mode)
    KAFKA_PRODUCER_COMPRESSION: Compression type (default: 'snappy')
    KAFKA_PRODUCER_BATCH_SIZE: Batch size in bytes (default: 16384)
    KAFKA_PRODUCER_LINGER_MS: Linger time in milliseconds (default: 10)
    KAFKA_PRODUCER_ACKS: Acknowledgment mode (default: 'all')
    KAFKA_PRODUCER_RETRIES: Number of retries (default: 3)
    KAFKA_PRODUCER_REQUEST_TIMEOUT_MS: Request timeout in milliseconds (default: 30000)
"""

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional

from utils.logging import get_logger

logger = get_logger(__name__)


class EventPublisher(ABC):
    """Abstract base class for event publishing"""

    @abstractmethod
    def publish_order_event(
        self,
        user_id: str,
        symbol: str,
        action: str,
        orderid: str,
        mode: str,
        **kwargs
    ) -> bool:
        """
        Publish order placement event
        
        Args:
            user_id: User ID who placed the order
            symbol: Trading symbol (e.g., 'SBIN-EQ')
            action: Order action ('BUY' or 'SELL')
            orderid: Unique order ID
            mode: Trading mode ('live' or 'sandbox')
            **kwargs: Additional order details (broker, quantity, price, etc.)
            
        Returns:
            bool: True if published successfully, False otherwise
        """
        pass

    @abstractmethod
    def publish_analyzer_update(
        self,
        user_id: str,
        request: Dict[str, Any],
        response: Dict[str, Any]
    ) -> bool:
        """
        Publish analyzer mode update
        
        Args:
            user_id: User ID
            request: Original request data (without apikey)
            response: Response data from sandbox/analyzer
            
        Returns:
            bool: True if published successfully, False otherwise
        """
        pass

    @abstractmethod
    def publish_order_notification(
        self,
        user_id: str,
        symbol: str,
        status: str,
        message: str,
        **kwargs
    ) -> bool:
        """
        Publish order notification
        
        Args:
            user_id: User ID
            symbol: Trading symbol
            status: Notification status ('info', 'success', 'warning', 'error')
            message: Notification message
            **kwargs: Additional notification details
            
        Returns:
            bool: True if published successfully, False otherwise
        """
        pass

    @abstractmethod
    def publish_master_contract_download(
        self,
        broker: str,
        status: str,
        message: str,
        **kwargs
    ) -> bool:
        """
        Publish master contract download event
        
        Args:
            broker: Broker name
            status: Download status ('success', 'error', 'in_progress')
            message: Status message
            **kwargs: Additional details (symbols_count, download_time_seconds, etc.)
            
        Returns:
            bool: True if published successfully, False otherwise
        """
        pass

    @abstractmethod
    def publish_password_change(
        self,
        user_id: str,
        status: str,
        message: str,
        **kwargs
    ) -> bool:
        """
        Publish password change event
        
        Args:
            user_id: User ID who changed password
            status: Change status ('success', 'error')
            message: Status message
            **kwargs: Additional details (ip_address, user_agent, etc.)
            
        Returns:
            bool: True if published successfully, False otherwise
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """
        Close publisher and cleanup resources
        """
        pass


class SocketIOEventPublisher(EventPublisher):
    """Socket.IO implementation - maintains current behavior"""

    def __init__(self, socketio_instance):
        """
        Initialize Socket.IO event publisher
        
        Args:
            socketio_instance: Flask-SocketIO instance from extensions.py
        """
        self.socketio = socketio_instance
        logger.info("SocketIOEventPublisher initialized")

    def publish_order_event(
        self,
        user_id: str,
        symbol: str,
        action: str,
        orderid: str,
        mode: str,
        **kwargs
    ) -> bool:
        """Publish order event via Socket.IO"""
        try:
            data = {
                "symbol": symbol,
                "action": action,
                "orderid": orderid,
                "mode": mode,
                **kwargs
            }
            
            # Emit asynchronously (non-blocking)
            self.socketio.start_background_task(
                self.socketio.emit,
                "order_event",
                data
            )
            
            logger.debug(f"Published order_event via Socket.IO: {orderid}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish order_event via Socket.IO: {e}")
            return False

    def publish_analyzer_update(
        self,
        user_id: str,
        request: Dict[str, Any],
        response: Dict[str, Any]
    ) -> bool:
        """Publish analyzer update via Socket.IO"""
        try:
            data = {
                "request": request,
                "response": response
            }
            
            self.socketio.start_background_task(
                self.socketio.emit,
                "analyzer_update",
                data
            )
            
            logger.debug(f"Published analyzer_update via Socket.IO for user: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish analyzer_update via Socket.IO: {e}")
            return False

    def publish_order_notification(
        self,
        user_id: str,
        symbol: str,
        status: str,
        message: str,
        **kwargs
    ) -> bool:
        """Publish order notification via Socket.IO"""
        try:
            data = {
                "symbol": symbol,
                "status": status,
                "message": message,
                **kwargs
            }
            
            self.socketio.start_background_task(
                self.socketio.emit,
                "order_notification",
                data
            )
            
            logger.debug(f"Published order_notification via Socket.IO: {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish order_notification via Socket.IO: {e}")
            return False

    def publish_master_contract_download(
        self,
        broker: str,
        status: str,
        message: str,
        **kwargs
    ) -> bool:
        """Publish master contract download event via Socket.IO"""
        try:
            data = {
                "broker": broker,
                "status": status,
                "message": message,
                **kwargs
            }
            
            self.socketio.emit("master_contract_download", data)
            
            logger.info(f"Published master_contract_download via Socket.IO: {broker}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish master_contract_download via Socket.IO: {e}")
            return False

    def publish_password_change(
        self,
        user_id: str,
        status: str,
        message: str,
        **kwargs
    ) -> bool:
        """Publish password change event via Socket.IO"""
        try:
            data = {
                "user": user_id,
                "status": status,
                "message": message,
                **kwargs
            }
            
            self.socketio.emit("password_change", data)
            
            logger.info(f"Published password_change via Socket.IO: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish password_change via Socket.IO: {e}")
            return False

    def close(self) -> None:
        """Close Socket.IO publisher (no cleanup needed)"""
        logger.debug("SocketIOEventPublisher closed")


class KafkaEventPublisher(EventPublisher):
    """Kafka implementation - publishes to Kafka topic"""

    def __init__(self, bootstrap_servers: str, topic: str):
        """
        Initialize Kafka event publisher
        
        Args:
            bootstrap_servers: Comma-separated Kafka broker addresses
            topic: Kafka topic name for publishing events
            
        Raises:
            ImportError: If kafka-python is not installed
            Exception: If connection to Kafka fails
        """
        try:
            from kafka import KafkaProducer
        except ImportError:
            logger.error("kafka-python not installed. Run: pip install kafka-python==2.0.2")
            raise ImportError(
                "kafka-python is required for KAFKA mode. "
                "Install with: pip install kafka-python==2.0.2"
            )
        
        self.topic = topic
        self.bootstrap_servers = bootstrap_servers
        
        # Kafka producer configuration
        producer_config = {
            'bootstrap_servers': bootstrap_servers.split(','),
            'value_serializer': lambda v: json.dumps(v).encode('utf-8'),
            'key_serializer': lambda k: k.encode('utf-8') if k else None,
            'compression_type': os.getenv('KAFKA_PRODUCER_COMPRESSION', 'snappy'),
            'batch_size': int(os.getenv('KAFKA_PRODUCER_BATCH_SIZE', '16384')),
            'linger_ms': int(os.getenv('KAFKA_PRODUCER_LINGER_MS', '10')),
            'acks': os.getenv('KAFKA_PRODUCER_ACKS', 'all'),
            'retries': int(os.getenv('KAFKA_PRODUCER_RETRIES', '3')),
            'request_timeout_ms': int(os.getenv('KAFKA_PRODUCER_REQUEST_TIMEOUT_MS', '30000')),
            'max_in_flight_requests_per_connection': 5,
            'enable_idempotence': True
        }
        
        try:
            self.producer = KafkaProducer(**producer_config)
            logger.info(
                f"KafkaEventPublisher initialized\n"
                f"  Topic: {topic}\n"
                f"  Bootstrap servers: {bootstrap_servers}\n"
                f"  Compression: {producer_config['compression_type']}\n"
                f"  Batch size: {producer_config['batch_size']} bytes\n"
                f"  Linger: {producer_config['linger_ms']} ms"
            )
        except Exception as e:
            logger.error(f"Failed to initialize Kafka producer: {e}")
            raise

    def _create_message(
        self,
        event_type: str,
        user_id: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create standardized Kafka message
        
        Args:
            event_type: Type of event (order_event, analyzer_update, etc.)
            user_id: User ID associated with the event
            data: Event-specific data
            
        Returns:
            Dict containing the complete message
        """
        return {
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "user_id": user_id,
            "source": "openalgo",
            "version": "1.0",
            "data": data
        }

    def _publish_to_kafka(
        self,
        event_type: str,
        user_id: str,
        data: Dict[str, Any],
        wait_for_ack: bool = False
    ) -> bool:
        """
        Helper method to publish message to Kafka
        
        Args:
            event_type: Type of event
            user_id: User ID (used as partition key)
            data: Event data
            wait_for_ack: If True, wait for broker acknowledgment (blocking)
            
        Returns:
            bool: True if published successfully, False otherwise
        """
        try:
            message = self._create_message(event_type, user_id, data)
            
            future = self.producer.send(
                self.topic,
                key=user_id,
                value=message
            )
            
            if wait_for_ack:
                # Wait for confirmation (blocking) - use for critical events
                record_metadata = future.get(timeout=10)
                logger.debug(
                    f"Published {event_type} to Kafka: "
                    f"partition={record_metadata.partition}, "
                    f"offset={record_metadata.offset}"
                )
            else:
                # Non-blocking - don't wait for confirmation
                logger.debug(f"Queued {event_type} to Kafka for user: {user_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish {event_type} to Kafka: {e}")
            return False

    def publish_order_event(
        self,
        user_id: str,
        symbol: str,
        action: str,
        orderid: str,
        mode: str,
        **kwargs
    ) -> bool:
        """Publish order event to Kafka"""
        data = {
            "symbol": symbol,
            "action": action,
            "orderid": orderid,
            "mode": mode,
            **kwargs
        }
        
        # Wait for acknowledgment for critical order events
        return self._publish_to_kafka("order_event", user_id, data, wait_for_ack=True)

    def publish_analyzer_update(
        self,
        user_id: str,
        request: Dict[str, Any],
        response: Dict[str, Any]
    ) -> bool:
        """Publish analyzer update to Kafka"""
        data = {
            "request": request,
            "response": response
        }
        
        return self._publish_to_kafka("analyzer_update", user_id, data)

    def publish_order_notification(
        self,
        user_id: str,
        symbol: str,
        status: str,
        message: str,
        **kwargs
    ) -> bool:
        """Publish order notification to Kafka"""
        data = {
            "symbol": symbol,
            "status": status,
            "message": message,
            **kwargs
        }
        
        return self._publish_to_kafka("order_notification", user_id, data)

    def publish_master_contract_download(
        self,
        broker: str,
        status: str,
        message: str,
        **kwargs
    ) -> bool:
        """Publish master contract download event to Kafka"""
        data = {
            "broker": broker,
            "status": status,
            "message": message,
            **kwargs
        }
        
        # Use 'admin' as user_id for system events
        return self._publish_to_kafka("master_contract_download", "admin", data)

    def publish_password_change(
        self,
        user_id: str,
        status: str,
        message: str,
        **kwargs
    ) -> bool:
        """Publish password change event to Kafka"""
        data = {
            "user": user_id,
            "status": status,
            "message": message,
            **kwargs
        }
        
        # Wait for acknowledgment for security events
        return self._publish_to_kafka("password_change", user_id, data, wait_for_ack=True)

    def close(self) -> None:
        """Close Kafka producer and flush pending messages"""
        try:
            logger.info("Closing Kafka producer...")
            self.producer.flush(timeout=5)
            self.producer.close(timeout=5)
            logger.info("Kafka producer closed successfully")
        except Exception as e:
            logger.error(f"Error closing Kafka producer: {e}")


class EventPublisherFactory:
    """Factory to create appropriate event publisher based on configuration"""

    _instance: Optional[EventPublisher] = None

    @classmethod
    def create_publisher(cls) -> EventPublisher:
        """
        Create and return event publisher based on ORDER_EVENT_MODE
        
        This method implements the singleton pattern to ensure only one
        publisher instance is created per application lifecycle.
        
        Returns:
            EventPublisher: SocketIO or Kafka publisher instance
            
        Raises:
            ValueError: If ORDER_EVENT_MODE is invalid or required config missing
            ImportError: If kafka-python not installed when KAFKA mode selected
        """
        # Return existing instance if available (singleton pattern)
        if cls._instance is not None:
            return cls._instance
        
        mode = os.getenv('ORDER_EVENT_MODE', 'SOCKETIO').upper()
        
        if mode == 'KAFKA':
            # Validate Kafka configuration
            bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS')
            topic = os.getenv('KAFKA_ORDER_EVENTS_TOPIC')
            
            if not bootstrap_servers:
                raise ValueError(
                    "KAFKA mode requires KAFKA_BOOTSTRAP_SERVERS environment variable"
                )
            
            if not topic:
                raise ValueError(
                    "KAFKA mode requires KAFKA_ORDER_EVENTS_TOPIC environment variable"
                )
            
            cls._instance = KafkaEventPublisher(bootstrap_servers, topic)
            logger.info("✓ Using Kafka for order events")
            
        elif mode == 'SOCKETIO':
            # Default to Socket.IO
            from extensions import socketio
            cls._instance = SocketIOEventPublisher(socketio)
            logger.info("✓ Using Socket.IO for order events (default)")
            
        else:
            raise ValueError(
                f"Invalid ORDER_EVENT_MODE: '{mode}'. Must be 'SOCKETIO' or 'KAFKA'"
            )
        
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """
        Reset the singleton instance (useful for testing)
        
        Warning: This should only be used in tests. In production,
        the publisher instance should be created once and reused.
        """
        if cls._instance is not None:
            try:
                cls._instance.close()
            except Exception as e:
                logger.warning(f"Error closing publisher during reset: {e}")
        cls._instance = None
        logger.debug("EventPublisherFactory reset")


# Convenience function for getting the event publisher
def get_event_publisher() -> EventPublisher:
    """
    Get the event publisher instance
    
    This is the recommended way to get the event publisher in application code.
    
    Returns:
        EventPublisher: Singleton event publisher instance
        
    Example:
        from utils.event_publisher import get_event_publisher
        
        publisher = get_event_publisher()
        publisher.publish_order_event(
            user_id="user123",
            symbol="SBIN-EQ",
            action="BUY",
            orderid="ORD123",
            mode="live"
        )
    """
    return EventPublisherFactory.create_publisher()


# Cleanup on module unload
import atexit

def _cleanup_publisher():
    """Cleanup function called on application exit"""
    if EventPublisherFactory._instance is not None:
        try:
            EventPublisherFactory._instance.close()
            logger.info("Event publisher cleanup completed")
        except Exception as e:
            logger.error(f"Error during event publisher cleanup: {e}")

atexit.register(_cleanup_publisher)
