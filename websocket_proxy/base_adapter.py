import json
import threading
import zmq
import logging
import random
import socket
from abc import ABC, abstractmethod

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
    logger = logging.getLogger("zmq_port_finder")
    
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

class BaseBrokerWebSocketAdapter(ABC):
    """
    Base class for all broker-specific WebSocket adapters that implements
    common functionality and defines the interface for broker-specific implementations.
    """
    # Class variable to track bound ports across instances
    _bound_ports = set()
    _port_lock = threading.Lock()
    
    def __init__(self):
        # ZeroMQ publisher setup for internal message distribution
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        
        # Find an available port for ZMQ
        self.logger = logging.getLogger("broker_adapter")
        self.zmq_port = self._bind_to_available_port()
        self.logger.info(f"ZeroMQ socket bound to port {self.zmq_port}")
        
        # Subscription tracking
        self.subscriptions = {}
        self.connected = False
        
    def _bind_to_available_port(self):
        """
        Find an available port and bind the socket to it
        """
        with BaseBrokerWebSocketAdapter._port_lock:
            # Try several times to find and bind to an available port
            for attempt in range(5):  # Try up to 5 times
                try:
                    if attempt == 0 and 5555 not in BaseBrokerWebSocketAdapter._bound_ports:
                        # Try default port first, but wrap in try-except to handle race conditions
                        # where the port appears free but can't be bound
                        try:
                            if is_port_available(5555):
                                port = 5555
                                self.socket.bind(f"tcp://*:{port}")
                                BaseBrokerWebSocketAdapter._bound_ports.add(port)
                                self.logger.info(f"Successfully bound to default ZMQ port {port}")
                                return port
                        except (zmq.ZMQError, socket.error) as e:
                            self.logger.warning(f"Default port 5555 appears available but binding failed: {e}")
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
            self.logger.error(f"Error cleaning up ZeroMQ resources: {e}")
            
    def __del__(self):
        """
        Destructor to ensure ZeroMQ resources are properly cleaned up
        """
        try:
            self.cleanup_zmq()
        except Exception as e:
            # Can't use self.logger here as it might be gone during destruction
            print(f"Error in __del__ cleaning up ZMQ resources: {e}")
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
            self.logger.error(f"Error publishing market data: {e}")
    
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
