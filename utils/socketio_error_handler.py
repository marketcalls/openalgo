"""
Socket.IO Error Handler
Handles common Socket.IO errors like disconnected sessions gracefully
"""

from utils.logging import get_logger
from flask_socketio import disconnect
import functools

logger = get_logger(__name__)

def handle_disconnected_session(f):
    """
    Decorator to handle disconnected session errors in Socket.IO event handlers
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except KeyError as e:
            if str(e) == "'Session is disconnected'":
                logger.debug(f"Socket.IO session already disconnected in {f.__name__}")
                disconnect()
                return None
            raise
        except Exception as e:
            if "Session is disconnected" in str(e):
                logger.debug(f"Socket.IO session disconnected in {f.__name__}: {e}")
                disconnect()
                return None
            raise
    return wrapper

def init_socketio_error_handling(socketio_instance):
    """
    Initialize Socket.IO error handling
    
    Args:
        socketio_instance: The Flask-SocketIO instance
    """
    
    @socketio_instance.on_error_default
    def default_error_handler(e):
        """
        Default error handler for all namespaces
        """
        error_msg = str(e)
        
        # Handle common disconnection errors silently
        if "Session is disconnected" in error_msg:
            logger.debug(f"Socket.IO session disconnected: {error_msg}")
            return False  # Don't emit error to client
        
        # Log other errors
        logger.error(f"Socket.IO error: {e}")
        return True  # Let the error propagate
    
    logger.info("Socket.IO error handling initialized")