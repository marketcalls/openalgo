import socket
import time
from utils.logging import get_logger

logger = get_logger("websocket_proxy")

def is_port_in_use(host, port, wait_time=0):
    """
    Check if a port is already in use on a specific host
    
    Args:
        host (str): Hostname to check
        port (int): Port number to check
        wait_time (float): Time to wait for port to be released (for cleanup scenarios)
        
    Returns:
        bool: True if the port is in use, False otherwise
    """
    # If wait_time is specified, check multiple times
    if wait_time > 0:
        attempts = int(wait_time * 10)  # Check every 0.1 seconds
        for attempt in range(attempts):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind((host, port))
                    # Port is not in use
                    return False
                except OSError:
                    if attempt == attempts - 1:  # Last attempt
                        logger.info(f"Port {port} is still in use on {host} after {wait_time}s wait")
                        return True
                    time.sleep(0.1)  # Wait 0.1 second before next attempt
    else:
        # Single check
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                # Port is not in use
                return False
            except OSError:
                # Port is in use
                logger.info(f"Port {port} is already in use on {host}")
                return True
            
def find_available_port(start_port=8899, max_attempts=10):
    """
    Find an available port starting from the given port
    
    Args:
        start_port (int): Port to start searching from
        max_attempts (int): Maximum number of ports to try
        
    Returns:
        int: Available port number, or None if no port is available
    """
    for port in range(start_port, start_port + max_attempts):
        if not is_port_in_use('127.0.0.1', port):
            return port
            
    logger.error(f"Could not find an available port after {max_attempts} attempts starting from {start_port}")
    return None
