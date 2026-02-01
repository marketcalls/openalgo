# utils/ngrok_manager.py
"""
Ngrok tunnel manager for OpenAlgo.
Handles tunnel creation, cleanup, and graceful shutdown.
Cross-platform compatible (Windows, Linux, macOS).
"""

import atexit
import logging
import os
import signal
import threading
from urllib.parse import urlparse

from utils.logging import get_logger

logger = get_logger(__name__)

# Suppress verbose pyngrok library logging (it logs at INFO level by default)
logging.getLogger("pyngrok").setLevel(logging.WARNING)
logging.getLogger("pyngrok.ngrok").setLevel(logging.WARNING)
logging.getLogger("pyngrok.process").setLevel(logging.WARNING)

# Global variables with thread safety
_ngrok_tunnel = None
_ngrok_lock = threading.Lock()
_ngrok_initialized = False
_original_sigint_handler = None
_original_sigterm_handler = None


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
    """Cleanup ngrok tunnel on shutdown. Always tries to kill ngrok processes. Thread-safe."""
    global _ngrok_tunnel

    # Thread-safe extraction of tunnel reference
    with _ngrok_lock:
        tunnel_to_cleanup = _ngrok_tunnel
        _ngrok_tunnel = None

    try:
        from pyngrok import ngrok

        # First, try to disconnect tracked tunnel
        if tunnel_to_cleanup:
            try:
                logger.info("Disconnecting ngrok tunnel...")
                ngrok.disconnect(tunnel_to_cleanup)
            except Exception as e:
                logger.debug(f"Error disconnecting tunnel: {e}")

        # Always kill ngrok process to ensure cleanup
        # This handles cases where tunnel wasn't tracked or was created externally
        try:
            ngrok.kill()
            logger.info("ngrok process killed successfully")
        except Exception as e:
            logger.debug(f"ngrok kill: {e}")

    except ImportError:
        logger.debug("pyngrok not available for cleanup")
    except Exception as e:
        logger.warning(f"Error during ngrok cleanup: {e}")


def _signal_handler(signum, frame):
    """Handle shutdown signals - cleanup ngrok then chain to original handler."""
    global _original_sigint_handler, _original_sigterm_handler
    import platform

    logger.info(f"Received signal {signum}, cleaning up ngrok...")
    cleanup_ngrok()

    # Chain to the original handler so Flask/SocketIO can shutdown properly
    if signum == signal.SIGINT:
        if _original_sigint_handler and callable(_original_sigint_handler):
            _original_sigint_handler(signum, frame)
        elif _original_sigint_handler == signal.SIG_DFL:
            raise KeyboardInterrupt
        else:
            raise KeyboardInterrupt
    elif platform.system() != "Windows" and signum == signal.SIGTERM:
        if _original_sigterm_handler and callable(_original_sigterm_handler):
            _original_sigterm_handler(signum, frame)
        elif _original_sigterm_handler == signal.SIG_DFL:
            raise SystemExit(0)
        else:
            raise SystemExit(0)
    else:
        # Unknown signal - just exit
        raise SystemExit(0)


def setup_ngrok_handlers():
    """Register cleanup and signal handlers for ngrok. Works on Windows, Linux, and macOS."""
    import platform

    global _ngrok_initialized, _original_sigint_handler, _original_sigterm_handler

    if _ngrok_initialized:
        return

    # Register cleanup handlers for graceful shutdown (atexit)
    atexit.register(cleanup_ngrok)

    # Save original signal handlers so we can chain to them
    _original_sigint_handler = signal.getsignal(signal.SIGINT)

    # Register signal handlers
    # SIGINT (Ctrl+C) works on all platforms
    signal.signal(signal.SIGINT, _signal_handler)

    # SIGTERM is not available on Windows
    if platform.system() != "Windows":
        _original_sigterm_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, _signal_handler)

    _ngrok_initialized = True
    logger.debug(f"ngrok cleanup handlers registered for {platform.system()}")


def start_ngrok_tunnel(port: int = 5000) -> str | None:
    """
    Start ngrok tunnel with domain from HOST_SERVER if configured.

    Args:
        port: The local port to tunnel (default: 5000)

    Returns:
        The public ngrok URL if successful, None otherwise
    """
    global _ngrok_tunnel

    # Always kill any existing ngrok process first, even if ngrok is disabled
    # This ensures old tunnels are cleaned up when user disables ngrok
    kill_existing_ngrok()

    if os.getenv("NGROK_ALLOW", "FALSE").upper() != "TRUE":
        logger.debug("ngrok is disabled (NGROK_ALLOW != TRUE)")
        return None

    try:
        import time

        from pyngrok import ngrok

        time.sleep(0.5)  # Brief wait for process to fully terminate

        # Extract domain from HOST_SERVER if provided
        host_server_env = os.getenv("HOST_SERVER", "")
        ngrok_url = None

        if (
            host_server_env
            and "localhost" not in host_server_env.lower()
            and "127.0.0.1" not in host_server_env
        ):
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
            logger.debug(f"ngrok URL: {ngrok_url}")
            return ngrok_url

    except Exception as e:
        print(f"Failed to start ngrok tunnel: {e}")
        logger.exception(f"Failed to start ngrok tunnel: {e}")

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
    return os.getenv("NGROK_ALLOW", "FALSE").upper() == "TRUE"
