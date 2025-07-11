import asyncio
import threading
import sys
import platform
import os

from .server import main as websocket_main
from utils.logging import get_logger, highlight_url

# Set the correct event loop policy for Windows to avoid ZeroMQ warnings
if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Global flag to track if the WebSocket server has been started
# Used to prevent multiple instances in Flask debug mode
_websocket_server_started = False

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

def start_websocket_server():
    """
    Start the WebSocket proxy server in a separate thread.
    This function should be called when the Flask app starts.
    """
    logger.info("Starting WebSocket proxy server in a separate thread")
    
    def run_websocket_server():
        """Run the WebSocket server in an event loop"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(websocket_main())
        except Exception as e:
            logger.exception(f"Error in WebSocket server thread: {e}")
    
    # Start the WebSocket server in a daemon thread
    websocket_thread = threading.Thread(
        target=run_websocket_server,
        daemon=True  # This ensures the thread will exit when the main program exits
    )
    websocket_thread.start()
    
    logger.info("WebSocket proxy server thread started")
    return websocket_thread
    
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
