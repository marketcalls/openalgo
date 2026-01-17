# utils/ngrok_manager.py
"""
Ngrok tunnel manager for OpenAlgo.
Handles tunnel creation, cleanup, and graceful shutdown.
"""

import os
import atexit
import signal
from urllib.parse import urlparse
from utils.logging import get_logger

logger = get_logger(__name__)

# Global variable to track ngrok tunnel
_ngrok_tunnel = None
_ngrok_initialized = False


def kill_existing_ngrok():
    """Kill any existing ngrok processes."""
    try:
        from pyngrok import ngrok
        ngrok.kill()
        logger.debug("Killed existing ngrok process")
        return True
    except Exception as e:
        logger.debug(f"No existing ngrok process to kill: {e}")
        return False


def cleanup_ngrok():
    """Cleanup ngrok tunnel on shutdown."""
    global _ngrok_tunnel
    if _ngrok_tunnel:
        try:
            from pyngrok import ngrok
            logger.info("Shutting down ngrok tunnel...")
            ngrok.disconnect(_ngrok_tunnel)
            ngrok.kill()
            _ngrok_tunnel = None
            logger.info("ngrok tunnel closed successfully")
        except Exception as e:
            logger.warning(f"Error during ngrok cleanup: {e}")


def _signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    cleanup_ngrok()
    raise SystemExit(0)


def setup_ngrok_handlers():
    """Register cleanup and signal handlers for ngrok."""
    global _ngrok_initialized
    if _ngrok_initialized:
        return

    # Register cleanup handlers for graceful shutdown
    atexit.register(cleanup_ngrok)

    # Register signal handlers
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    _ngrok_initialized = True
    logger.debug("ngrok cleanup handlers registered")


def start_ngrok_tunnel(port: int = 5000) -> str | None:
    """
    Start ngrok tunnel with domain from HOST_SERVER if configured.

    Args:
        port: The local port to tunnel (default: 5000)

    Returns:
        The public ngrok URL if successful, None otherwise
    """
    global _ngrok_tunnel

    if os.getenv('NGROK_ALLOW', 'FALSE').upper() != 'TRUE':
        logger.debug("ngrok is disabled (NGROK_ALLOW != TRUE)")
        return None

    try:
        from pyngrok import ngrok
        import time

        # Kill any existing ngrok process first
        kill_existing_ngrok()
        time.sleep(0.5)  # Brief wait for process to fully terminate

        # Extract domain from HOST_SERVER if provided
        host_server_env = os.getenv('HOST_SERVER', '')
        ngrok_url = None

        if host_server_env and 'localhost' not in host_server_env.lower() and '127.0.0.1' not in host_server_env:
            parsed = urlparse(host_server_env)
            domain = parsed.netloc or parsed.path

            if domain:
                # Start ngrok with the custom domain
                logger.debug(f"Starting ngrok with custom domain: {domain}")
                tunnel = ngrok.connect(port, domain=domain)
                ngrok_url = tunnel.public_url
                _ngrok_tunnel = tunnel
        else:
            # Start ngrok without custom domain (will get random URL)
            logger.debug("Starting ngrok without custom domain")
            tunnel = ngrok.connect(port)
            ngrok_url = tunnel.public_url
            _ngrok_tunnel = tunnel

        if ngrok_url:
            print(f"Ngrok tunnel established: {ngrok_url}")
            logger.info(f"ngrok URL: {ngrok_url}")
            return ngrok_url

    except Exception as e:
        print(f"Failed to start ngrok tunnel: {e}")
        logger.error(f"Failed to start ngrok tunnel: {e}")

    return None


def get_ngrok_url() -> str | None:
    """Get the current ngrok public URL if tunnel is active."""
    global _ngrok_tunnel
    if _ngrok_tunnel:
        try:
            return _ngrok_tunnel.public_url
        except:
            pass
    return None


def is_ngrok_enabled() -> bool:
    """Check if ngrok is enabled in configuration."""
    return os.getenv('NGROK_ALLOW', 'FALSE').upper() == 'TRUE'
