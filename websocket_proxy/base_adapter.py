import json
import threading
import zmq
import os
import random
import socket
from abc import ABC, abstractmethod
from utils.logging import get_logger
from datetime import datetime

# RedPanda/Kafka imports
try:
    from kafka import KafkaProducer, KafkaConsumer
    from kafka.errors import KafkaError
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False

# Initialize logger
logger = get_logger(__name__)

def is_port_available(port):
    """
    Check if a port is available for use
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except socket.error:
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
        ports_to_remove = []
        for port in list(BaseBrokerWebSocketAdapter._bound_ports):
            if is_port_available(port):
                logger.info(f"Port {port} in registry is actually free now, removing from bound ports")
                ports_to_remove.append(port)
        
        # Remove ports that are actually available now
        for port in ports_to_remove:
            BaseBrokerWebSocketAdapter._bound_ports.remove(port)
    
    # Now find a new free port
    for _ in range(max_attempts):
        # Try a sequential port first, then random if that fails
        current_port = start_port
        
        # Check if this port is available and not in our bound_ports set
        if (current_port not in BaseBrokerWebSocketAdapter._bound_ports and 
                is_port_available(current_port)):
            return current_port
            
        # Try a random port between start_port and 65535
        current_port = random.randint(start_port, 65535)
        if (current_port not in BaseBrokerWebSocketAdapter._bound_ports and 
                is_port_available(current_port)):
            return current_port
            
        # Increment start_port for next sequential try
        start_port = min(start_port + 1, 65000)  # Cap at 65000 to stay in safe range
        
    # If we get here, we couldn't find an available port
    logger.error("Failed to find an available port after maximum attempts")
    return None


def find_free_redpanda_port(start_port=9092, max_attempts=50):
    """
    Find an available port starting from start_port for RedPanda broker
    
    Args:
        start_port (int): Port number to start the search from (default 9092 for Kafka)
        max_attempts (int): Maximum number of attempts to find a free port
        
    Returns:
        int: Available port number, or None if no port is available
    """
    # Create logger here instead of using self.logger because this is a standalone function
    logger = get_logger("redpanda_port_finder")
    
    # First check if any ports in the bound_ports set are actually free now
    # This handles cases where the process that had the port died without cleanup
    with BaseBrokerWebSocketAdapter._port_lock:
        ports_to_remove = []
        for port in list(BaseBrokerWebSocketAdapter._bound_redpanda_ports):
            if is_port_available(port):
                logger.info(f"RedPanda port {port} in registry is actually free now, removing from bound ports")
                ports_to_remove.append(port)
        
        # Remove ports that are actually available now
        for port in ports_to_remove:
            BaseBrokerWebSocketAdapter._bound_redpanda_ports.remove(port)
    
    # Now find a new free port
    for _ in range(max_attempts):
        # Try a sequential port first, then random if that fails
        current_port = start_port
        
        # Check if this port is available and not in our bound_ports set
        if (current_port not in BaseBrokerWebSocketAdapter._bound_redpanda_ports and 
                is_port_available(current_port)):
            return current_port
            
        # Try a random port between start_port and 65535
        current_port = random.randint(start_port, 65535)
        if (current_port not in BaseBrokerWebSocketAdapter._bound_redpanda_ports and 
                is_port_available(current_port)):
            return current_port
            
        # Increment start_port for next sequential try
        start_port = min(start_port + 1, 65000)  # Cap at 65000 to stay in safe range
        
    # If we get here, we couldn't find an available port
    logger.error("Failed to find an available RedPanda port after maximum attempts")
    return None


class BaseBrokerWebSocketAdapter(ABC):
    """
    Base class for all broker-specific WebSocket adapters that implements
    common functionality and defines the interface for broker-specific implementations.
    """
    # Class variables to track bound ports across instances
    _bound_ports = set()
    _bound_redpanda_ports = set()
    _port_lock = threading.Lock()
    
    def __init__(self):
        # ZeroMQ publisher setup for internal message distribution
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)

        # ZMQ publishing control
        self.zmq_enabled = self._should_enable_zmq()
        
        # Find an available port for ZMQ only if enabled
        self.logger = get_logger("broker_adapter")
        if self.zmq_enabled:
            self.zmq_port = self._bind_to_available_port()
            self.logger.info(f"ZeroMQ socket bound to port {self.zmq_port}")
            # Updating used ZMQ_PORT in environment variable.
            # We must use os.environ (not os.getenv) for setting environment variables
            os.environ["ZMQ_PORT"] = str(self.zmq_port)
        else:
            self.zmq_port = None
            self.logger.info("ZeroMQ publishing disabled")
        
        # RedPanda/Kafka setup
        self.redpanda_enabled = self._should_enable_redpanda()
        self.kafka_producer = None
        self.kafka_consumer = None
        self.redpanda_config = None
        self.redpanda_topics = {}
        
        if self.redpanda_enabled:
            self._setup_redpanda()
        
        # Subscription tracking
        self.subscriptions = {}
        self.connected = False

    def _should_enable_zmq(self):
        """
        Check if ZeroMQ should be enabled based on environment variables
        """
        # Check environment variable
        enable_zmq = os.getenv('ENABLE_ZMQ_PUBLISH', 'true').lower() in ('true', '1', 'yes', 'on')
        
        if enable_zmq:
            self.logger.info("ZeroMQ publishing enabled via environment variable")
        #else:
        #    self.logger.info("ZeroMQ publishing disabled. Set ENABLE_ZMQ_PUBLISH=true to enable")
            
        return enable_zmq

    def _should_enable_redpanda(self):
        """
        Check if RedPanda should be enabled based on environment variables and availability
        """
        if not KAFKA_AVAILABLE:
            self.logger.warning("Kafka library not available. Install with: pip install kafka-python")
            return False
            
        # Check environment variable
        enable_redpanda = os.getenv('ENABLE_REDPANDA', 'false').lower() in ('true', '1', 'yes', 'on')
        
        if enable_redpanda:
            self.logger.info("RedPanda streaming enabled via environment variable")
        else:
            self.logger.info("RedPanda streaming disabled. Set ENABLE_REDPANDA=true to enable")
            
        return enable_redpanda
        
    def _setup_redpanda(self):
        """
        Setup RedPanda/Kafka configuration and connections
        """
        try:
            # Get RedPanda configuration from environment
            self.redpanda_config = {
                'bootstrap_servers': os.getenv('REDPANDA_BROKERS', 'localhost:9092'),
                'topic_prefix': os.getenv('REDPANDA_TOPIC_PREFIX', 'openalgo'),
                'compression_type': os.getenv('REDPANDA_COMPRESSION', 'snappy'),
                'batch_size': int(os.getenv('REDPANDA_BATCH_SIZE', '16384')),
                'buffer_memory': int(os.getenv('REDPANDA_BUFFER_MEMORY', '33554432')),
                'linger_ms': int(os.getenv('REDPANDA_LINGER_MS', '10')),
                'acks': os.getenv('REDPANDA_ACKS', 'all'),
                'retries': int(os.getenv('REDPANDA_RETRIES', '3')),
                'client_id': os.getenv('REDPANDA_CLIENT_ID', f'openalgo-{os.getpid()}'),
                'max_in_flight_requests_per_connection': int(os.getenv('REDPANDA_MAX_IN_FLIGHT_REQUESTS', '1'))
            }
            
            # Define topics for different data types
            self.redpanda_topics = {
                'tick_data': f"{self.redpanda_config['topic_prefix']}.tick.raw"
            }
            
            # Initialize Kafka producer
            self._init_kafka_producer()
            
            # Store RedPanda port in environment
            redpanda_port = self.redpanda_config['bootstrap_servers'].split(':')[-1]
            os.environ["REDPANDA_PORT"] = str(redpanda_port)            
            
            self.logger.info(f"RedPanda configuration initialized: {self.redpanda_config['bootstrap_servers']}")
            

        except Exception as e:
            self.logger.error(f"Failed to setup RedPanda configuration: {e}")
            self.redpanda_enabled = False
            
    def _init_kafka_producer(self):
        """
        Initialize Kafka producer for publishing market data
        """
        try:
            producer_config = {
                'bootstrap_servers': self.redpanda_config['bootstrap_servers'],
                'client_id': self.redpanda_config['client_id'],
                'value_serializer': lambda v: json.dumps(v).encode('utf-8'),
                'key_serializer': lambda k: str(k).encode('utf-8') if k else None,
                'acks': self.redpanda_config['acks'],
                'retries': self.redpanda_config['retries'],
                'batch_size': self.redpanda_config['batch_size'],
                'buffer_memory': self.redpanda_config['buffer_memory'],
                'linger_ms': self.redpanda_config['linger_ms'],
                'compression_type': self.redpanda_config['compression_type'],
                'max_in_flight_requests_per_connection': self.redpanda_config['max_in_flight_requests_per_connection'],
                'enable_idempotence': True
            }
            
            self.kafka_producer = KafkaProducer(**producer_config)
            self.logger.info("Kafka producer initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Kafka producer: {e}")
            self.redpanda_enabled = False
            
    # def _init_kafka_consumer(self, topics, group_id=None):
    #     """
    #     Initialize Kafka consumer for reading market data
        
    #     Args:
    #         topics: List of topics to subscribe to
    #         group_id: Consumer group ID
    #     """
    #     try:
    #         if not group_id:
    #             group_id = f"openalgo-consumer-{os.getpid()}"
                
    #         consumer_config = {
    #             'bootstrap_servers': self.redpanda_config['bootstrap_servers'],
    #             'client_id': self.redpanda_config['client_id'],
    #             'group_id': group_id,
    #             'value_deserializer': lambda m: json.loads(m.decode('utf-8')),
    #             'key_deserializer': lambda k: k.decode('utf-8') if k else None,
    #             'auto_offset_reset': 'latest',
    #             'enable_auto_commit': True,
    #             'auto_commit_interval_ms': 1000,
    #             'session_timeout_ms': 30000,
    #             'heartbeat_interval_ms': 3000
    #         }
            
    #         self.kafka_consumer = KafkaConsumer(*topics, **consumer_config)
    #         self.logger.info(f"Kafka consumer initialized for topics: {topics}")
    #         return self.kafka_consumer
            
    #    except Exception as e:
    #        self.logger.error(f"Failed to initialize Kafka consumer: {e}")
    #        return None
        
    def _bind_to_available_port(self):
        """
        Find an available port and bind the socket to it
        """
        with BaseBrokerWebSocketAdapter._port_lock:
            # Try several times to find and bind to an available port
            for attempt in range(5):  # Try up to 5 times
                try:
                    # Get default port from environment or fallback to 5555
                    default_port = int(os.getenv('ZMQ_PORT', '5555'))
                    if attempt == 0 and default_port not in BaseBrokerWebSocketAdapter._bound_ports:
                        # Try default port first, but wrap in try-except to handle race conditions
                        # where the port appears free but can't be bound
                        try:
                            if is_port_available(default_port):
                                port = default_port
                                self.socket.bind(f"tcp://*:{port}")
                                BaseBrokerWebSocketAdapter._bound_ports.add(port)
                                self.logger.info(f"Successfully bound to default ZMQ port {port} from environment")
                                return port
                        except (zmq.ZMQError, socket.error) as e:
                            self.logger.warning(f"Default port {default_port} from environment appears available but binding failed: {e}")
                            # Fall through to random port allocation
                    
                    # Use random port allocation
                    port = find_free_zmq_port(start_port=5556 + random.randint(0, 1000))
                    if not port:
                        self.logger.warning(f"Failed to find free port on attempt {attempt+1}, retrying...")
                        continue
                        
                    # Try to bind to the randomly selected port
                    try:
                        self.socket.bind(f"tcp://*:{port}")
                        BaseBrokerWebSocketAdapter._bound_ports.add(port)
                        self.logger.info(f"Successfully bound to ZMQ port {port} (attempt {attempt+1})")
                        return port
                    except zmq.ZMQError as e:
                        self.logger.warning(f"Failed to bind to port {port}: {e}")
                        continue
                        
                except Exception as e:
                    self.logger.warning(f"Unexpected error in port binding (attempt {attempt+1}): {e}")
                    continue
            
            # If we get here, all attempts failed
            self.logger.error("Failed to bind to any available port after multiple attempts")
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
        Properly clean up ZeroMQ resources and release bound ports
        """
        try:
            # Release the port from the bound ports set
            if hasattr(self, 'zmq_port'):
                with BaseBrokerWebSocketAdapter._port_lock:
                    if self.zmq_port in BaseBrokerWebSocketAdapter._bound_ports:
                        BaseBrokerWebSocketAdapter._bound_ports.remove(self.zmq_port)
                        self.logger.info(f"Released port {self.zmq_port} from bound ports registry")
            
            # Close the socket
            if hasattr(self, 'socket') and self.socket:
                self.socket.close(linger=0)  # Don't linger on close
                self.logger.info("ZeroMQ socket closed")
                
            # Terminate the context
            if hasattr(self, 'context') and self.context:
                self.context.term()
                self.logger.info("ZeroMQ context terminated")
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
    
    def publish_market_data(self, topic, data):
        """
        Publish market data to ZeroMQ subscribers
        
        Args:
            topic: Topic string for subscriber filtering (e.g., 'NSE_RELIANCE_LTP')
            data: Market data dictionary
        """
        try:
            self.socket.send_multipart([
                topic.encode('utf-8'),
                json.dumps(data).encode('utf-8')
            ])
        except Exception as e:
            self.logger.exception(f"Error publishing market data: {e}")
    
    def _create_success_response(self, message, **kwargs):
        """
        Create a standard success response
        """
        response = {
            'status': 'success',
            'message': message
        }
        response.update(kwargs)
        return response
    
    def _create_error_response(self, code, message):
        """
        Create a standard error response
        """
        return {
            'status': 'error',
            'code': code,
            'message': message
        }
