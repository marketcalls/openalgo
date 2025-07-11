import socket
from utils.logging import get_logger

logger = get_logger("websocket_proxy")

def is_port_in_use(host, port):
    """
    Check if a port is already in use on a specific host
    
    Args:
        host (str): Hostname to check
        port (int): Port number to check
        
    Returns:
        bool: True if the port is in use, False otherwise
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
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
        if not is_port_in_use('localhost', port):
            return port
            
    logger.error(f"Could not find an available port after {max_attempts} attempts starting from {start_port}")
    return None
