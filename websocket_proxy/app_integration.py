import asyncio
import threading
import sys
import platform
import os
import signal
import atexit

from .server import main as websocket_main
from utils.logging import get_logger, highlight_url

# Set the correct event loop policy for Windows to avoid ZeroMQ warnings
if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Global flag to track if the WebSocket server has been started
# Used to prevent multiple instances in Flask debug mode
_websocket_server_started = False
_websocket_proxy_instance = None
_websocket_thread = None

logger = get_logger(__name__)

# Check if we're in the Flask child process that should start the WebSocket server
def should_start_websocket():
    """
    Determine if the current process should start the WebSocket server
    
    In Flask debug mode with reloader enabled, we only want to start the
    WebSocket server in the child process, not the parent process that
    monitors for file changes.
    
    Returns:
        bool: True if we should start the WebSocket server, False otherwise
    """
    # In debug mode, only start in the Flask child process
    if os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true'):
        # WERKZEUG_RUN_MAIN is set to 'true' by Flask in the child process
        # that actually runs the application
        return os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    
    # In non-debug mode, always start
    return True

def cleanup_websocket_server():
    """Clean up WebSocket server resources - cross-platform compatible"""
    global _websocket_proxy_instance, _websocket_thread
    
    try:
        logger.info("Cleaning up WebSocket server...")
        
        if _websocket_proxy_instance:
            # For Windows compatibility, set a shutdown flag instead of trying to 
            # manipulate the event loop from a different thread
            _websocket_proxy_instance.running = False
            
            # Try to close the server gracefully
            try:
                if hasattr(_websocket_proxy_instance, 'server') and _websocket_proxy_instance.server:
                    try:
                        _websocket_proxy_instance.server.close()
                    except Exception as e:
                        logger.warning(f"Error closing server handle: {e}")
                
                # Close ZMQ resources immediately
                if hasattr(_websocket_proxy_instance, 'socket') and _websocket_proxy_instance.socket:
                    try:
                        import zmq
                        _websocket_proxy_instance.socket.setsockopt(zmq.LINGER, 0)
                        _websocket_proxy_instance.socket.close()
                    except Exception as e:
                        logger.warning(f"Error closing ZMQ socket: {e}")
                
                if hasattr(_websocket_proxy_instance, 'context') and _websocket_proxy_instance.context:
                    try:
                        _websocket_proxy_instance.context.term()
                    except Exception as e:
                        logger.warning(f"Error terminating ZMQ context: {e}")
                        
            except Exception as e:
                logger.error(f"Error during WebSocket cleanup: {e}")
            finally:
                _websocket_proxy_instance = None
        
        if _websocket_thread and _websocket_thread.is_alive():
            logger.info("Waiting for WebSocket thread to finish...")
            _websocket_thread.join(timeout=3.0)  # Reduced timeout for faster shutdown
            if _websocket_thread.is_alive():
                logger.warning("WebSocket thread did not finish gracefully")
            _websocket_thread = None
            
        logger.info("WebSocket server cleanup completed")
        
    except Exception as e:
        logger.error(f"Error during WebSocket cleanup: {e}")
        # Last resort: force cleanup
        _websocket_proxy_instance = None
        _websocket_thread = None

def signal_handler(signum, frame):
    """Handle SIGINT (Ctrl+C) and SIGTERM signals"""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    cleanup_websocket_server()
    # Use os._exit() for immediate termination across all platforms
    os._exit(0)

def start_websocket_server():
    """
    Start the WebSocket proxy server in a separate thread.
    This function should be called when the Flask app starts.
    """
    global _websocket_proxy_instance, _websocket_thread
    
    logger.info("Starting WebSocket proxy server in a separate thread")
    
    def run_websocket_server():
        """Run the WebSocket server in an event loop"""
        global _websocket_proxy_instance
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Import here to avoid circular imports
            from .server import WebSocketProxy
            import os
            from dotenv import load_dotenv
            
            load_dotenv()
            ws_host = os.getenv('WEBSOCKET_HOST', '127.0.0.1')
            ws_port = int(os.getenv('WEBSOCKET_PORT', '8765'))
            
            # Create and store the proxy instance
            _websocket_proxy_instance = WebSocketProxy(host=ws_host, port=ws_port)
            
            # Start the proxy
            loop.run_until_complete(_websocket_proxy_instance.start())
            
        except Exception as e:
            logger.exception(f"Error in WebSocket server thread: {e}")
            _websocket_proxy_instance = None
    
    # Start the WebSocket server in a daemon thread
    _websocket_thread = threading.Thread(
        target=run_websocket_server,
        daemon=False  # Changed to False so we can properly clean up
    )
    _websocket_thread.start()
    
    # Register cleanup handlers
    atexit.register(cleanup_websocket_server)
    
    # Register signal handlers for graceful shutdown
    try:
        # SIGINT (Ctrl+C) - Available on all platforms
        signal.signal(signal.SIGINT, signal_handler)
        signals_registered = ["SIGINT"]
        
        # SIGTERM - Available on Unix-like systems (Mac, Linux)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, signal_handler)
            signals_registered.append("SIGTERM")
        
        logger.info(f"Signal handlers registered: {', '.join(signals_registered)}")
    except Exception as e:
        logger.warning(f"Could not register signal handlers: {e}")
    
    logger.info("WebSocket proxy server thread started")
    return _websocket_thread
    
def start_websocket_proxy(app):
    """
    Integrate the WebSocket proxy server with a Flask application.
    This should be called during app initialization.
    
    Args:
        app: Flask application instance
    """
    global _websocket_server_started
    
    # Check if this process should start the WebSocket server
    if should_start_websocket():
        # Our flag will prevent multiple starts if called multiple times
        if not _websocket_server_started:
            _websocket_server_started = True
            logger.info("Starting WebSocket server in Flask application process")
            start_websocket_server()
            logger.info("WebSocket server integration with Flask complete")
        else:
            logger.info("WebSocket server already running, skipping initialization")
    else:
        logger.info("Skipping WebSocket server in parent/monitor process")
