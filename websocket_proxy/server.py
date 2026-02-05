import asyncio as aio
import json
import os
import signal
import socket
import threading
import time
from collections import defaultdict
from typing import Any, Dict, Optional, Set, Tuple

import websockets
import zmq
import zmq.asyncio
from dotenv import load_dotenv
from sqlalchemy import text

from database.auth_db import get_broker_name, verify_api_key
from services.market_data_service import get_market_data_service
from utils.logging import get_logger, highlight_url

from .base_adapter import BaseBrokerWebSocketAdapter
from .broker_factory import create_broker_adapter
from .port_check import find_available_port, is_port_in_use

# Initialize logger
logger = get_logger("websocket_proxy")


class WebSocketProxy:
    """
    WebSocket Proxy Server that handles client connections and authentication,
    manages subscriptions, and routes market data from broker adapters to clients.
    Supports dynamic broker selection based on user configuration.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        """
        Initialize the WebSocket Proxy

        Args:
            host: Hostname to bind the WebSocket server to
            port: Port number to bind the WebSocket server to
        """
        self.host = host
        self.port = port

        # Check if the required port is already in use - wait briefly for cleanup to complete
        if is_port_in_use(host, port, wait_time=2.0):  # Wait up to 2 seconds for port release
            error_msg = (
                f"WebSocket port {port} is already in use on {host}.\n"
                f"This port is required for SDK compatibility (see strategies/ltp_example.py).\n"
                f"Please:\n"
                f"1. Stop any other OpenAlgo instances running on port {port}\n"
                f"2. Kill any processes using port {port}: lsof -ti:{port} | xargs kill -9\n"
                f"3. Or wait for the port to be released\n"
                f"Cannot start WebSocket server with port switching as it would break SDK clients."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        self.clients = {}  # Maps client_id to websocket connection
        self.subscriptions = {}  # Maps client_id to set of subscriptions
        self.broker_adapters = {}  # Maps user_id to broker adapter
        self.user_mapping = {}  # Maps client_id to user_id
        self.user_broker_mapping = {}  # Maps user_id to broker_name
        self.running = False

        # PERFORMANCE OPTIMIZATION: Subscription index for O(1) lookup
        # Maps (symbol, exchange, mode) -> set of client_ids
        # This eliminates the need for nested loops in zmq_listener
        self.subscription_index: dict[tuple[str, str, int], set[int]] = defaultdict(set)

        # PERFORMANCE OPTIMIZATION 2: Message throttling to avoid excessive updates
        # Maps (symbol, exchange, mode) -> last message timestamp
        # Prevents sending duplicate LTP updates faster than 50ms
        self.last_message_time: dict[tuple[str, str, int], float] = {}
        self.message_throttle_interval = 0.05  # 50ms minimum between messages

        # PERFORMANCE OPTIMIZATION 3: Pre-compute mode mappings
        self.MODE_MAP = {"LTP": 1, "QUOTE": 2, "DEPTH": 3}

        # RESOURCE MONITORING: Track metrics for health checks
        self._stats_lock = aio.Lock() if hasattr(aio, 'Lock') else None
        self._messages_processed = 0
        self._last_cleanup_time = time.time()
        self._cleanup_interval = 300  # Clean stale entries every 5 minutes
        self._throttle_entry_max_age = 60  # Remove throttle entries older than 60 seconds

        # ZeroMQ context for subscribing to broker adapters
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.SUB)
        # Connecting to ZMQ
        ZMQ_HOST = os.getenv("ZMQ_HOST", "127.0.0.1")
        ZMQ_PORT = os.getenv("ZMQ_PORT")
        self.socket.connect(f"tcp://{ZMQ_HOST}:{ZMQ_PORT}")  # Connect to broker adapter publisher

        # Set up ZeroMQ subscriber to receive all messages
        self.socket.setsockopt(zmq.SUBSCRIBE, b"")  # Subscribe to all topics

    async def start(self):
        """Start the WebSocket server and ZeroMQ listener"""
        self.running = True

        try:
            # Start ZeroMQ listener
            logger.debug("Initializing ZeroMQ listener task")

            # Get the current event loop
            loop = aio.get_running_loop()

            # Create the ZMQ listener task
            zmq_task = loop.create_task(self.zmq_listener())

            # Start WebSocket server
            stop = aio.Future()  # Used to stop the server

            # Create a task to monitor the running flag
            async def monitor_shutdown():
                while self.running:
                    await aio.sleep(0.5)
                stop.set_result(None)

            monitor_task = aio.create_task(monitor_shutdown())

            # Handle graceful shutdown
            # Windows doesn't support add_signal_handler, so we'll use a simpler approach
            # Also, when running in a thread on Unix systems, signal handlers can't be set
            try:
                loop = aio.get_running_loop()

                # Check if we're in the main thread
                if threading.current_thread() is threading.main_thread():
                    try:
                        for sig in (signal.SIGINT, signal.SIGTERM):
                            loop.add_signal_handler(sig, stop.set_result, None)
                        logger.debug("Signal handlers registered successfully")
                    except (NotImplementedError, RuntimeError) as e:
                        # On Windows or when in a non-main thread
                        logger.debug(
                            f"Signal handlers not registered: {e}. Using fallback mechanism."
                        )
                else:
                    logger.debug("Running in a non-main thread. Signal handlers will not be used.")
            except RuntimeError:
                logger.debug("No running event loop found for signal handlers")

            highlighted_address = highlight_url(f"{self.host}:{self.port}")
            logger.debug(f"Starting WebSocket server on {highlighted_address}")

            # Try to start the WebSocket server with proper socket options for immediate port reuse
            try:
                # Start WebSocket server with socket reuse options
                self.server = await websockets.serve(
                    self.handle_client,
                    self.host,
                    self.port,
                    # Enable socket reuse for immediate port availability after close
                    reuse_port=True if hasattr(socket, "SO_REUSEPORT") else False,
                )

                highlighted_success_address = highlight_url(f"{self.host}:{self.port}")
                logger.debug(
                    f"WebSocket server successfully started on {highlighted_success_address}"
                )

                await stop  # Wait until stopped

                # Cancel the monitor task
                monitor_task.cancel()
                try:
                    await monitor_task
                except aio.CancelledError:
                    pass

            except Exception as e:
                logger.exception(f"Failed to start WebSocket server: {e}")
                raise

        except Exception as e:
            logger.exception(f"Error in start method: {e}")
            raise

    async def stop(self):
        """Stop the WebSocket server and clean up all resources"""
        logger.info("Stopping WebSocket server...")
        self.running = False

        try:
            # Close the WebSocket server first (this releases the port)
            if hasattr(self, "server") and self.server:
                try:
                    logger.info("Closing WebSocket server...")
                    # On Windows, we need to handle the case where we're in a different event loop
                    try:
                        self.server.close()
                        await self.server.wait_closed()
                        logger.info("WebSocket server closed and port released")
                    except RuntimeError as e:
                        if "attached to a different loop" in str(e):
                            logger.warning(
                                f"WebSocket server cleanup skipped due to event loop mismatch: {e}"
                            )
                            # Force close the server without waiting
                            try:
                                self.server.close()
                            except:
                                pass
                        else:
                            raise
                except Exception as e:
                    logger.exception(f"Error closing WebSocket server: {e}")

            # Close all client connections
            close_tasks = []
            for client_id, websocket in self.clients.items():
                try:
                    if hasattr(websocket, "open") and websocket.open:
                        close_tasks.append(websocket.close())
                except Exception as e:
                    logger.exception(f"Error preparing to close client {client_id}: {e}")

            # Wait for all connections to close with timeout
            if close_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*close_tasks, return_exceptions=True),
                        timeout=2.0,  # 2 second timeout
                    )
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for client connections to close")

            # Disconnect all broker adapters
            for user_id, adapter in self.broker_adapters.items():
                try:
                    adapter.disconnect()
                except Exception as e:
                    logger.exception(f"Error disconnecting adapter for user {user_id}: {e}")

            # Close ZeroMQ socket with linger=0 for immediate close
            if hasattr(self, "socket") and self.socket:
                try:
                    self.socket.setsockopt(zmq.LINGER, 0)  # Don't wait for pending messages
                    self.socket.close()
                except Exception as e:
                    logger.exception(f"Error closing ZMQ socket: {e}")

            # Close ZeroMQ context with timeout
            if hasattr(self, "context") and self.context:
                try:
                    self.context.term()
                except Exception as e:
                    logger.exception(f"Error terminating ZMQ context: {e}")

            logger.info("WebSocket server stopped and resources cleaned up")

        except Exception as e:
            logger.exception(f"Error during WebSocket server stop: {e}")

    def _cleanup_zmq_sync(self):
        """
        Synchronous cleanup of ZeroMQ resources.
        Called from __del__ to ensure resources are freed even if stop() is never called.
        """
        try:
            if hasattr(self, "socket") and self.socket:
                try:
                    self.socket.setsockopt(zmq.LINGER, 0)
                    self.socket.close()
                except Exception:
                    pass  # Ignore errors during cleanup
                finally:
                    self.socket = None

            if hasattr(self, "context") and self.context:
                try:
                    self.context.term()
                except Exception:
                    pass  # Ignore errors during cleanup
                finally:
                    self.context = None
        except Exception:
            pass  # Suppress all errors in cleanup

    def __del__(self):
        """
        Destructor to ensure ZeroMQ resources are cleaned up.
        This is a safety net for cases where stop() is never called
        (e.g., exception during start() or unexpected termination).
        """
        try:
            self.running = False
            self._cleanup_zmq_sync()
        except Exception:
            pass  # Cannot raise in __del__

    def get_health_stats(self) -> dict:
        """
        Get health statistics for monitoring file descriptors and resources.

        Returns:
            dict: Health statistics including connection counts, subscription metrics,
                  and resource usage information.
        """
        try:
            # Get base adapter stats if available
            from .base_adapter import BaseBrokerWebSocketAdapter
            adapter_stats = BaseBrokerWebSocketAdapter.get_resource_stats()
        except Exception:
            adapter_stats = {}

        # Calculate subscription index stats
        total_subscriptions = len(self.subscription_index)
        total_client_subscriptions = sum(len(clients) for clients in self.subscription_index.values())
        throttle_entries = len(self.last_message_time)

        return {
            "server": {
                "running": self.running,
                "host": self.host,
                "port": self.port,
            },
            "clients": {
                "connected_count": len(self.clients),
                "user_mappings": len(self.user_mapping),
            },
            "subscriptions": {
                "unique_symbols": total_subscriptions,
                "total_client_subscriptions": total_client_subscriptions,
                "per_client_counts": {
                    str(client_id): len(subs)
                    for client_id, subs in self.subscriptions.items()
                },
            },
            "broker_adapters": {
                "active_count": len(self.broker_adapters),
                "brokers": list(self.user_broker_mapping.values()),
            },
            "performance": {
                "throttle_entries": throttle_entries,
                "messages_processed": self._messages_processed,
                "last_cleanup_time": self._last_cleanup_time,
            },
            "zmq_resources": adapter_stats,
        }

    def _cleanup_stale_throttle_entries(self):
        """
        Remove stale entries from last_message_time dict.

        This prevents unbounded memory growth from symbols that were
        subscribed to but are no longer active.
        """
        current_time = time.time()

        # Only run cleanup periodically
        if current_time - self._last_cleanup_time < self._cleanup_interval:
            return

        self._last_cleanup_time = current_time
        initial_count = len(self.last_message_time)

        # Find and remove stale entries
        stale_keys = [
            key for key, timestamp in self.last_message_time.items()
            if current_time - timestamp > self._throttle_entry_max_age
        ]

        for key in stale_keys:
            del self.last_message_time[key]

        if stale_keys:
            logger.info(
                f"Cleaned up {len(stale_keys)} stale throttle entries "
                f"(was {initial_count}, now {len(self.last_message_time)})"
            )

        # Log subscription index stats periodically
        total_subs = len(self.subscription_index)
        total_clients = len(self.clients)
        if total_subs > 0 or total_clients > 0:
            logger.debug(
                f"Resource stats: {total_clients} clients, "
                f"{total_subs} unique subscriptions, "
                f"{len(self.last_message_time)} throttle entries"
            )

    async def handle_client(self, websocket):
        """
        Handle a client connection

        Args:
            websocket: The WebSocket connection
        """
        client_id = id(websocket)
        self.clients[client_id] = websocket
        self.subscriptions[client_id] = set()

        # Get path info from websocket if available
        path = getattr(websocket, "path", "/unknown")
        logger.info(f"Client connected: {client_id} from path: {path}")

        try:
            # Process messages from the client
            async for message in websocket:
                try:
                    # OPTIMIZATION: Remove debug logging from hot path
                    # logger.debug(f"Received message from client {client_id}: {message}")
                    await self.process_client_message(client_id, message)
                except Exception as e:
                    logger.exception(f"Error processing message from client {client_id}: {e}")
                    # Send error to client but don't disconnect
                    try:
                        await self.send_error(client_id, "PROCESSING_ERROR", str(e))
                    except:
                        pass
        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"Client disconnected: {client_id}, code: {e.code}, reason: {e.reason}")
        except Exception as e:
            logger.exception(f"Unexpected error handling client {client_id}: {e}")
        finally:
            # Clean up when the client disconnects
            await self.cleanup_client(client_id)

    async def cleanup_client(self, client_id):
        """
        Clean up client resources when they disconnect

        Args:
            client_id: Client ID to clean up
        """
        # Remove client from tracking
        if client_id in self.clients:
            del self.clients[client_id]

        # Clean up subscriptions
        if client_id in self.subscriptions:
            subscriptions = self.subscriptions[client_id]
            # Unsubscribe from all subscriptions
            for sub_json in subscriptions:
                try:
                    # Parse the JSON string to get the subscription info
                    sub_info = json.loads(sub_json)
                    symbol = sub_info.get("symbol")
                    exchange = sub_info.get("exchange")
                    mode = sub_info.get("mode")

                    # OPTIMIZATION: Remove from subscription index
                    sub_key = (symbol, exchange, mode)
                    should_unsubscribe_from_adapter = False
                    if sub_key in self.subscription_index:
                        self.subscription_index[sub_key].discard(client_id)
                        # Clean up empty entries and mark for adapter unsubscription
                        if not self.subscription_index[sub_key]:
                            del self.subscription_index[sub_key]
                            # Only unsubscribe from adapter when last client unsubscribes
                            should_unsubscribe_from_adapter = True

                    # Get the user's broker adapter
                    # Only unsubscribe from adapter if this was the last client for this symbol
                    user_id = self.user_mapping.get(client_id)
                    if (
                        should_unsubscribe_from_adapter
                        and user_id
                        and user_id in self.broker_adapters
                    ):
                        adapter = self.broker_adapters[user_id]
                        adapter.unsubscribe(symbol, exchange, mode)
                        logger.debug(
                            f"Last client unsubscribed from {symbol}:{exchange}, unsubscribing from adapter"
                        )
                except json.JSONDecodeError as e:
                    logger.exception(f"Error parsing subscription: {sub_json}, Error: {e}")
                except Exception as e:
                    logger.exception(f"Error processing subscription: {e}")
                    continue

            del self.subscriptions[client_id]

        # Remove from user mapping
        if client_id in self.user_mapping:
            user_id = self.user_mapping[client_id]

            # Check if this was the last client for this user
            is_last_client = True
            for other_client_id, other_user_id in self.user_mapping.items():
                if other_client_id != client_id and other_user_id == user_id:
                    is_last_client = False
                    break

            # If this was the last client for this user, handle the adapter state
            if is_last_client and user_id in self.broker_adapters:
                adapter = self.broker_adapters[user_id]
                broker_name = self.user_broker_mapping.get(user_id)

                # For Flattrade and Shoonya, keep the connection alive and just unsubscribe from data
                if broker_name in ["flattrade", "shoonya"] and hasattr(adapter, "unsubscribe_all"):
                    logger.info(
                        f"{broker_name.title()} adapter for user {user_id}: last client disconnected. Unsubscribing all symbols instead of disconnecting."
                    )
                    adapter.unsubscribe_all()
                else:
                    # For all other brokers, disconnect the adapter completely
                    logger.info(
                        f"Last client for user {user_id} disconnected. Disconnecting {broker_name or 'unknown broker'} adapter."
                    )
                    adapter.disconnect()
                    del self.broker_adapters[user_id]
                    if user_id in self.user_broker_mapping:
                        del self.user_broker_mapping[user_id]

            del self.user_mapping[client_id]

    async def process_client_message(self, client_id, message):
        """
        Process messages from a client

        Args:
            client_id: ID of the client
            message: The message from the client
        """
        try:
            data = json.loads(message)
            # OPTIMIZATION: Remove debug logging from hot path
            # logger.debug(f"Parsed message from client {client_id}: {data}")

            # Accept both 'action' and 'type' fields for better compatibility with different clients
            action = data.get("action") or data.get("type")
            # OPTIMIZATION: Only log important actions, not every subscribe/unsubscribe
            if action not in ["subscribe", "unsubscribe"]:
                logger.info(f"Client {client_id} requested action: {action}")

            if action in ["authenticate", "auth"]:
                await self.authenticate_client(client_id, data)
            elif action == "subscribe":
                await self.subscribe_client(client_id, data)
            elif action in ["unsubscribe", "unsubscribe_all"]:
                await self.unsubscribe_client(client_id, data)
            elif action == "get_broker_info":
                await self.get_broker_info(client_id)
            elif action == "get_supported_brokers":
                await self.get_supported_brokers(client_id)
            elif action == "ping":
                await self.handle_ping(client_id, data)
            else:
                logger.warning(f"Client {client_id} requested invalid action: {action}")
                await self.send_error(client_id, "INVALID_ACTION", f"Invalid action: {action}")
        except json.JSONDecodeError:
            logger.exception(f"Invalid JSON from client {client_id}: {message}")
            await self.send_error(client_id, "INVALID_JSON", "Invalid JSON message")
        except Exception as e:
            logger.exception(f"Error processing client message: {e}")
            await self.send_error(client_id, "SERVER_ERROR", str(e))

    async def get_user_broker_configuration(self, user_id):
        """
        Get the broker configuration for a specific user from database

        Args:
            user_id: User ID to get broker configuration for

        Returns:
            dict: Broker configuration containing broker_name and credentials
        """
        try:
            from sqlalchemy import text

            from database.auth_db import get_broker_name

            # Get user's connected broker from database
            # This queries the auth_token table to find the user's active broker
            query = text("""
                SELECT broker FROM auth_token 
                WHERE user_id = :user_id 
                ORDER BY id DESC 
                LIMIT 1
            """)

            result = db.session.execute(query, {"user_id": user_id}).fetchone()

            if result and result.broker:
                broker_name = result.broker
                logger.info(f"Found broker '{broker_name}' for user {user_id} from database")
            else:
                # Fallback to environment variable
                valid_brokers = os.getenv("VALID_BROKERS", "angel").split(",")
                broker_name = valid_brokers[0].strip() if valid_brokers else "angel"
                logger.warning(
                    f"No broker found in database for user {user_id}, using fallback: {broker_name}"
                )

            # Get broker credentials from environment variables
            # In a production system, these would be stored encrypted in the database per user
            broker_config = {
                "broker_name": broker_name,
                "api_key": os.getenv("BROKER_API_KEY"),
                "api_secret": os.getenv("BROKER_API_SECRET"),
                "api_key_market": os.getenv("BROKER_API_KEY_MARKET"),
                "api_secret_market": os.getenv("BROKER_API_SECRET_MARKET"),
                "broker_user_id": os.getenv("BROKER_USER_ID"),
                "password": os.getenv("BROKER_PASSWORD"),
                "totp_secret": os.getenv("BROKER_TOTP_SECRET"),
            }

            # Validate broker is supported
            valid_brokers_list = os.getenv("VALID_BROKERS", "").split(",")
            valid_brokers_list = [b.strip() for b in valid_brokers_list if b.strip()]

            if broker_name not in valid_brokers_list:
                logger.error(
                    f"Broker '{broker_name}' is not in VALID_BROKERS list: {valid_brokers_list}"
                )
                return None

            if not broker_config.get("broker_name"):
                logger.error(f"No broker configuration found for user {user_id}")
                return None

            logger.info(
                f"Retrieved broker configuration for user {user_id}: {broker_config['broker_name']}"
            )
            return broker_config

        except Exception as e:
            logger.exception(f"Error getting broker configuration for user {user_id}: {e}")
            return None

    async def authenticate_client(self, client_id, data):
        """
        Authenticate a client using their API key and determine their broker

        Args:
            client_id: ID of the client
            data: Authentication data containing API key
        """
        # Accept both 'api_key' and 'apikey' formats for compatibility
        api_key = data.get("api_key") or data.get("apikey")

        if not api_key:
            await self.send_error(client_id, "AUTHENTICATION_ERROR", "API key is required")
            return

        # Verify the API key and get the user ID
        user_id = verify_api_key(api_key)

        if not user_id:
            await self.send_error(client_id, "AUTHENTICATION_ERROR", "Invalid API key")
            return

        # Store the user mapping
        self.user_mapping[client_id] = user_id

        # Get broker name
        broker_name = get_broker_name(api_key)

        if not broker_name:
            await self.send_error(
                client_id, "BROKER_ERROR", "No broker configuration found for user"
            )
            return

        # Store the broker mapping for this user
        self.user_broker_mapping[user_id] = broker_name

        # Create or reuse broker adapter
        if user_id not in self.broker_adapters:
            try:
                # Create broker adapter with dynamic broker selection
                adapter = create_broker_adapter(broker_name)
                if not adapter:
                    await self.send_error(
                        client_id,
                        "BROKER_ERROR",
                        f"Failed to create adapter for broker: {broker_name}",
                    )
                    return

                # Initialize adapter with broker configuration
                # The adapter's initialize method should handle broker-specific setup
                initialization_result = adapter.initialize(broker_name, user_id)
                if initialization_result and initialization_result.get("status") == "error":
                    error_msg = initialization_result.get(
                        "message", initialization_result.get("error", "Failed to initialize broker adapter")
                    )

                    # Check if this is an auth error (403/401) - retry with fresh token
                    # This handles the stale cache issue described in GitHub issue #765
                    if adapter.is_auth_error(error_msg):
                        logger.warning(f"Auth error during initialization for user {user_id}, retrying with fresh token")
                        adapter.clear_auth_cache_for_user(user_id)

                        # Retry initialization with fresh credentials
                        initialization_result = adapter.initialize(broker_name, user_id)
                        if initialization_result and initialization_result.get("status") == "error":
                            error_msg = initialization_result.get("message", "Failed to initialize after retry")
                            await self.send_error(client_id, "BROKER_INIT_ERROR", error_msg)
                            return
                    else:
                        await self.send_error(client_id, "BROKER_INIT_ERROR", error_msg)
                        return

                # Connect to the broker
                connect_result = adapter.connect()
                # Handle both response formats:
                # - Adapter format: {"status": "error", "code": "...", "message": "..."}
                # - ConnectionPool format: {"success": False, "error": "..."}
                is_error = (
                    (connect_result and connect_result.get("status") == "error") or
                    (connect_result and connect_result.get("success") == False)
                )
                if is_error:
                    error_msg = connect_result.get("message", connect_result.get("error", "Failed to connect to broker"))
                    error_code = connect_result.get("code", "")

                    # Always retry connection failures with fresh token (issue #765)
                    # Connection failures after re-login are almost always due to stale cached tokens
                    # The upstox_client logs "401 Unauthorized" but returns generic "CONNECTION_FAILED"
                    should_retry = (
                        adapter.is_auth_error(error_msg) or
                        error_code in ("CONNECTION_FAILED", "CONNECTION_ERROR") or
                        "failed to connect" in error_msg.lower()
                    )

                    if should_retry:
                        logger.warning(f"Connection failed for user {user_id}, retrying with fresh token (error: {error_msg}, code: {error_code})")

                        # Clear stale cache in WebSocket process (issue #765)
                        self._clear_auth_cache_for_user(user_id)
                        adapter.clear_auth_cache_for_user(user_id)

                        # Re-initialize with fresh credentials from database
                        # Use force=True for pooled adapters to override existing initialization
                        logger.info(f"Re-initializing adapter for user {user_id} with fresh token")
                        try:
                            # Try with force parameter (supported by _PooledAdapterWrapper)
                            init_retry_result = adapter.initialize(broker_name, user_id, force=True)
                        except TypeError:
                            # Fallback for raw adapters that don't support force parameter
                            init_retry_result = adapter.initialize(broker_name, user_id)
                        # Handle both response formats
                        init_is_error = (
                            (init_retry_result and init_retry_result.get("status") == "error") or
                            (init_retry_result and init_retry_result.get("success") == False)
                        )
                        if init_is_error:
                            error_msg = init_retry_result.get("message", init_retry_result.get("error", "Failed to re-initialize"))
                            logger.error(f"Re-initialization failed for user {user_id}: {error_msg}")
                            await self.send_error(client_id, "BROKER_INIT_ERROR", error_msg)
                            return

                        # Retry connection
                        logger.info(f"Retrying connection for user {user_id}")
                        connect_result = adapter.connect()
                        # Handle both response formats
                        connect_is_error = (
                            (connect_result and connect_result.get("status") == "error") or
                            (connect_result and connect_result.get("success") == False)
                        )
                        if connect_is_error:
                            error_msg = connect_result.get("message", connect_result.get("error", "Failed to connect after retry"))
                            logger.error(f"Retry connection also failed for user {user_id}: {error_msg}")
                            await self.send_error(client_id, "BROKER_CONNECTION_ERROR", error_msg)
                            return

                        logger.info(f"Retry successful for user {user_id}")
                    else:
                        await self.send_error(client_id, "BROKER_CONNECTION_ERROR", error_msg)
                        return

                # Store the adapter
                self.broker_adapters[user_id] = adapter

                logger.info(
                    f"Successfully created and connected {broker_name} adapter for user {user_id}"
                )

            except Exception as e:
                error_str = str(e)
                logger.exception(f"Failed to create broker adapter for {broker_name}: {e}")

                # Check if exception is an auth error - retry with fresh token
                # This handles the stale cache issue described in GitHub issue #765
                if self._is_auth_error_exception(error_str):
                    logger.warning(f"Auth exception for user {user_id}, retrying with fresh token")
                    try:
                        self._clear_auth_cache_for_user(user_id)

                        # Retry adapter creation
                        adapter = create_broker_adapter(broker_name)
                        if adapter:
                            # Clear cache on the new adapter as well
                            if hasattr(adapter, 'clear_auth_cache_for_user'):
                                adapter.clear_auth_cache_for_user(user_id)

                            initialization_result = adapter.initialize(broker_name, user_id)
                            # Handle both response formats
                            init_is_error = (
                                (initialization_result and initialization_result.get("status") == "error") or
                                (initialization_result and initialization_result.get("success") == False)
                            )
                            if not init_is_error:
                                connect_result = adapter.connect()
                                # Handle both response formats
                                connect_is_error = (
                                    (connect_result and connect_result.get("status") == "error") or
                                    (connect_result and connect_result.get("success") == False)
                                )
                                if not connect_is_error:
                                    self.broker_adapters[user_id] = adapter
                                    logger.info(f"Successfully connected {broker_name} adapter for user {user_id} after retry")
                                    # Fall through to success response
                                else:
                                    error_msg = connect_result.get("message", connect_result.get("error", "Failed to connect after retry"))
                                    await self.send_error(client_id, "BROKER_CONNECTION_ERROR", error_msg)
                                    return
                            else:
                                error_msg = initialization_result.get("message", initialization_result.get("error", "Failed to initialize after retry"))
                                await self.send_error(client_id, "BROKER_INIT_ERROR", error_msg)
                                return
                        else:
                            await self.send_error(client_id, "BROKER_ERROR", f"Failed to create adapter for {broker_name}")
                            return
                    except Exception as retry_error:
                        logger.exception(f"Retry also failed for {broker_name}: {retry_error}")
                        await self.send_error(client_id, "BROKER_ERROR", str(retry_error))
                        return
                else:
                    import traceback
                    logger.exception(traceback.format_exc())
                    await self.send_error(client_id, "BROKER_ERROR", error_str)
                    return

        # Send success response with broker information
        await self.send_message(
            client_id,
            {
                "type": "auth",
                "status": "success",
                "message": "Authentication successful",
                "broker": broker_name,
                "user_id": user_id,
                "supported_features": {"ltp": True, "quote": True, "depth": True},
            },
        )

    async def get_supported_brokers(self, client_id):
        """
        Get list of supported brokers from environment configuration

        Args:
            client_id: ID of the client
        """
        try:
            valid_brokers = os.getenv("VALID_BROKERS", "").split(",")
            supported_brokers = [broker.strip() for broker in valid_brokers if broker.strip()]

            await self.send_message(
                client_id,
                {
                    "type": "supported_brokers",
                    "status": "success",
                    "brokers": supported_brokers,
                    "count": len(supported_brokers),
                },
            )
        except Exception as e:
            logger.exception(f"Error getting supported brokers: {e}")
            await self.send_error(client_id, "BROKER_LIST_ERROR", str(e))

    async def get_broker_info(self, client_id):
        """
        Get broker information for an authenticated client

        Args:
            client_id: ID of the client
        """
        # Check if the client is authenticated
        if client_id not in self.user_mapping:
            await self.send_error(client_id, "NOT_AUTHENTICATED", "You must authenticate first")
            return

        user_id = self.user_mapping[client_id]
        broker_name = self.user_broker_mapping.get(user_id)

        if not broker_name:
            await self.send_error(client_id, "BROKER_ERROR", "Broker information not available")
            return

        # Get adapter status
        adapter_status = "disconnected"
        if user_id in self.broker_adapters:
            adapter = self.broker_adapters[user_id]
            # Assuming the adapter has a status method or property
            adapter_status = getattr(adapter, "status", "connected")

        await self.send_message(
            client_id,
            {
                "type": "broker_info",
                "status": "success",
                "broker": broker_name,
                "adapter_status": adapter_status,
                "user_id": user_id,
            },
        )

    async def handle_ping(self, client_id, data):
        """
        Handle ping request from client

        Args:
            client_id: ID of the client
            data: Ping data containing optional timestamp
        """
        logger.debug(f"Handling ping from client {client_id}: {data}")
        client_timestamp = data.get("timestamp")
        ping_id = data.get("_pingId")
        server_timestamp = int(time.time() * 1000)  # Current time in milliseconds

        response = {"type": "pong", "status": "success", "server_timestamp": server_timestamp}

        # Include client timestamp in response if provided (for latency calculation)
        if client_timestamp is not None:
            response["client_timestamp"] = client_timestamp

        # Echo back _pingId for frontend latency calculation
        if ping_id is not None:
            response["_pingId"] = ping_id

        logger.debug(f"Sending pong to client {client_id}: {response}")
        await self.send_message(client_id, response)

    async def subscribe_client(self, client_id, data):
        """
        Subscribe a client to market data using their configured broker

        Args:
            client_id: ID of the client
            data: Subscription data
        """
        # Check if the client is authenticated
        if client_id not in self.user_mapping:
            await self.send_error(client_id, "NOT_AUTHENTICATED", "You must authenticate first")
            return

        # Get subscription parameters
        symbols = data.get("symbols") or []  # Handle array of symbols
        mode_str = data.get("mode", "Quote")  # Get mode as string (LTP, Quote, Depth)
        depth_level = data.get("depth", 5)  # Default to 5 levels

        # Map string mode to numeric mode
        mode_mapping = {"LTP": 1, "Quote": 2, "Depth": 3}

        # Convert string mode to numeric if needed
        mode = mode_mapping.get(mode_str, mode_str) if isinstance(mode_str, str) else mode_str

        # Handle case where a single symbol is passed directly instead of as an array
        if not symbols and (data.get("symbol") and data.get("exchange")):
            symbols = [{"symbol": data.get("symbol"), "exchange": data.get("exchange")}]

        if not symbols:
            await self.send_error(
                client_id, "INVALID_PARAMETERS", "At least one symbol must be specified"
            )
            return

        # Get the user's broker adapter
        user_id = self.user_mapping[client_id]
        if user_id not in self.broker_adapters:
            await self.send_error(client_id, "BROKER_ERROR", "Broker adapter not found")
            return

        adapter = self.broker_adapters[user_id]
        broker_name = self.user_broker_mapping.get(user_id, "unknown")

        # Process each symbol in the subscription request
        subscription_responses = []
        subscription_success = True

        for symbol_info in symbols:
            symbol = symbol_info.get("symbol")
            exchange = symbol_info.get("exchange")

            if not symbol or not exchange:
                continue  # Skip invalid symbols

            # Subscribe to market data
            response = adapter.subscribe(symbol, exchange, mode, depth_level)

            if response.get("status") == "success":
                # Store the subscription
                subscription_info = {
                    "symbol": symbol,
                    "exchange": exchange,
                    "mode": mode,
                    "depth_level": depth_level,
                    "broker": broker_name,
                }

                if client_id in self.subscriptions:
                    self.subscriptions[client_id].add(json.dumps(subscription_info))
                else:
                    self.subscriptions[client_id] = {json.dumps(subscription_info)}

                # OPTIMIZATION: Update subscription index for O(1) lookup
                sub_key = (symbol, exchange, mode)
                self.subscription_index[sub_key].add(client_id)

                # Add to successful subscriptions
                subscription_responses.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "status": "success",
                        "mode": mode_str,
                        "depth": response.get("actual_depth", depth_level),
                        "broker": broker_name,
                    }
                )
            else:
                subscription_success = False
                # Add to failed subscriptions
                subscription_responses.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "status": "error",
                        "message": response.get("message", "Subscription failed"),
                        "broker": broker_name,
                    }
                )

        # Send combined response
        await self.send_message(
            client_id,
            {
                "type": "subscribe",
                "status": "success" if subscription_success else "partial",
                "subscriptions": subscription_responses,
                "message": "Subscription processing complete",
                "broker": broker_name,
            },
        )

    async def unsubscribe_client(self, client_id, data):
        """
        Unsubscribe a client from market data

        Args:
            client_id: ID of the client
            data: Unsubscription data
        """
        # Check if the client is authenticated
        if client_id not in self.user_mapping:
            await self.send_error(client_id, "NOT_AUTHENTICATED", "You must authenticate first")
            return

        # Check if this is an unsubscribe_all request
        is_unsubscribe_all = (
            data.get("type") == "unsubscribe_all" or data.get("action") == "unsubscribe_all"
        )

        # Get unsubscription parameters for specific symbols
        symbols = data.get("symbols") or []

        # Handle single symbol format
        if not symbols and not is_unsubscribe_all and (data.get("symbol") and data.get("exchange")):
            symbols = [
                {
                    "symbol": data.get("symbol"),
                    "exchange": data.get("exchange"),
                    "mode": data.get("mode", 2),  # Default to Quote mode
                }
            ]

        # If no symbols provided and not unsubscribe_all, return error
        if not symbols and not is_unsubscribe_all:
            await self.send_error(
                client_id, "INVALID_PARAMETERS", "Either symbols or unsubscribe_all is required"
            )
            return

        # Get the user's broker adapter
        user_id = self.user_mapping[client_id]
        if user_id not in self.broker_adapters:
            await self.send_error(client_id, "BROKER_ERROR", "Broker adapter not found")
            return

        adapter = self.broker_adapters[user_id]
        broker_name = self.user_broker_mapping.get(user_id, "unknown")

        # Process unsubscribe request
        successful_unsubscriptions = []
        failed_unsubscriptions = []

        # Handle unsubscribe_all case
        if is_unsubscribe_all:
            # Get all current subscriptions
            if client_id in self.subscriptions:
                # Convert all stored subscription strings back to dictionaries
                all_subscriptions = []
                for sub_json in self.subscriptions[client_id]:
                    try:
                        sub_dict = json.loads(sub_json)
                        all_subscriptions.append(sub_dict)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse subscription: {sub_json}")

                # Unsubscribe from each subscription
                for sub in all_subscriptions:
                    symbol = sub.get("symbol")
                    exchange = sub.get("exchange")
                    mode = sub.get("mode")

                    if symbol and exchange:
                        # Remove from subscription index and check if we should unsubscribe from adapter
                        sub_key = (symbol, exchange, mode)
                        should_unsubscribe_from_adapter = False
                        if sub_key in self.subscription_index:
                            self.subscription_index[sub_key].discard(client_id)
                            # Only unsubscribe from adapter when last client unsubscribes
                            if not self.subscription_index[sub_key]:
                                del self.subscription_index[sub_key]
                                should_unsubscribe_from_adapter = True

                        # Only call adapter.unsubscribe if this was the last client for this symbol
                        if should_unsubscribe_from_adapter:
                            response = adapter.unsubscribe(symbol, exchange, mode)
                            logger.debug(
                                f"Last client unsubscribed from {symbol}:{exchange}, unsubscribing from adapter"
                            )

                            if response.get("status") != "success":
                                failed_unsubscriptions.append(
                                    {
                                        "symbol": symbol,
                                        "exchange": exchange,
                                        "status": "error",
                                        "message": response.get("message", "Unsubscription failed"),
                                        "broker": broker_name,
                                    }
                                )
                                continue

                        successful_unsubscriptions.append(
                            {
                                "symbol": symbol,
                                "exchange": exchange,
                                "status": "success",
                                "broker": broker_name,
                            }
                        )

                # Clear all subscriptions for this client
                self.subscriptions[client_id].clear()
        else:
            # Process specific symbols
            for symbol_info in symbols:
                symbol = symbol_info.get("symbol")
                exchange = symbol_info.get("exchange")
                mode = symbol_info.get("mode", 2)  # Default to Quote mode

                if not symbol or not exchange:
                    continue  # Skip invalid symbols

                # Remove from subscription index and check if we should unsubscribe from adapter
                sub_key = (symbol, exchange, mode)
                should_unsubscribe_from_adapter = False
                if sub_key in self.subscription_index:
                    self.subscription_index[sub_key].discard(client_id)
                    # Only unsubscribe from adapter when last client unsubscribes
                    if not self.subscription_index[sub_key]:
                        del self.subscription_index[sub_key]
                        should_unsubscribe_from_adapter = True

                # Remove from client's subscription list
                if client_id in self.subscriptions:
                    # Remove any matching subscription (with or without broker info)
                    subscriptions_to_remove = []
                    for sub_json in self.subscriptions[client_id]:
                        try:
                            sub_data = json.loads(sub_json)
                            if (
                                sub_data.get("symbol") == symbol
                                and sub_data.get("exchange") == exchange
                                and sub_data.get("mode") == mode
                            ):
                                subscriptions_to_remove.append(sub_json)
                        except json.JSONDecodeError:
                            continue

                    for sub_json in subscriptions_to_remove:
                        self.subscriptions[client_id].discard(sub_json)

                # Only call adapter.unsubscribe if this was the last client for this symbol
                if should_unsubscribe_from_adapter:
                    response = adapter.unsubscribe(symbol, exchange, mode)
                    logger.debug(
                        f"Last client unsubscribed from {symbol}:{exchange}, unsubscribing from adapter"
                    )

                    if response.get("status") != "success":
                        failed_unsubscriptions.append(
                            {
                                "symbol": symbol,
                                "exchange": exchange,
                                "status": "error",
                                "message": response.get("message", "Unsubscription failed"),
                                "broker": broker_name,
                            }
                        )
                        continue

                successful_unsubscriptions.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "status": "success",
                        "broker": broker_name,
                    }
                )

        # Send combined response
        status = "success"
        if len(failed_unsubscriptions) > 0 and len(successful_unsubscriptions) > 0:
            status = "partial"
        elif len(failed_unsubscriptions) > 0 and len(successful_unsubscriptions) == 0:
            status = "error"

        await self.send_message(
            client_id,
            {
                "type": "unsubscribe",
                "status": status,
                "message": "Unsubscription processing complete",
                "successful": successful_unsubscriptions,
                "failed": failed_unsubscriptions,
                "broker": broker_name,
            },
        )

    async def send_message(self, client_id, message):
        """
        Send a message to a client

        Args:
            client_id: ID of the client
            message: The message to send
        """
        if client_id in self.clients:
            websocket = self.clients[client_id]
            try:
                await websocket.send(json.dumps(message))
            except websockets.exceptions.ConnectionClosed:
                logger.info(f"Connection closed while sending message to client {client_id}")

    async def send_error(self, client_id, code, message):
        """
        Send an error message to a client

        Args:
            client_id: ID of the client
            code: Error code
            message: Error message
        """
        await self.send_message(client_id, {"status": "error", "code": code, "message": message})

    def _handle_cache_invalidation(self, topic_str: str, data_str: str):
        """
        Handle cache invalidation messages from Flask process.

        When a user re-authenticates or logs out, Flask publishes a cache invalidation
        message via ZeroMQ. This method clears the local auth caches so that the next
        request fetches fresh data from the database.

        This solves the stale token issue described in GitHub issue #765.

        Args:
            topic_str: The ZMQ topic (format: CACHE_INVALIDATE_{TYPE}_{USER_ID})
            data_str: JSON string with invalidation details
        """
        try:
            # Import caches locally to avoid circular imports
            from database.auth_db import (
                auth_cache,
                broker_cache,
                feed_token_cache,
                invalid_api_key_cache,
                verified_api_key_cache,
            )

            # Parse the invalidation message
            message = json.loads(data_str)
            user_id = message.get("user_id")
            cache_type = message.get("cache_type", "ALL")

            if not user_id:
                logger.warning("Cache invalidation message missing user_id")
                return

            logger.info(f"Received cache invalidation for user: {user_id}, type: {cache_type}")

            # CRITICAL: Clear ALL cache entries to prevent stale token issues
            # This is necessary because get_auth_token_broker() uses a different cache key format
            # (sha256(api_key)_include_feed_token) than the user-id based keys.
            # Without clearing all entries, old cached tokens would persist and cause
            # 401 Unauthorized errors after re-login.
            # See GitHub issue #851 for details on this cache key mismatch bug.
            caches_cleared = []

            if cache_type in ("AUTH", "ALL"):
                auth_cache.clear()
                caches_cleared.append("auth_cache")

            if cache_type in ("FEED", "ALL"):
                feed_token_cache.clear()
                caches_cleared.append("feed_token_cache")

            if cache_type == "ALL":
                broker_cache.clear()
                caches_cleared.append("broker_cache")

                verified_api_key_cache.clear()
                invalid_api_key_cache.clear()
                caches_cleared.append("verified_api_key_cache")
                caches_cleared.append("invalid_api_key_cache")

            if caches_cleared:
                logger.info(f"Cleared caches for user {user_id}: {', '.join(caches_cleared)}")
            else:
                logger.debug(f"No cached data found for user {user_id}")

            # Also disconnect and clean up any existing broker adapters for this user
            # This forces re-initialization with fresh credentials on next connection
            if user_id in self.broker_adapters:
                try:
                    adapter = self.broker_adapters[user_id]
                    adapter.disconnect()
                    del self.broker_adapters[user_id]
                    logger.info(f"Disconnected stale broker adapter for user {user_id}")
                except Exception as adapter_error:
                    logger.warning(f"Error disconnecting adapter for user {user_id}: {adapter_error}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse cache invalidation message: {e}")
        except Exception as e:
            logger.exception(f"Error processing cache invalidation: {e}")

    def _is_auth_error_exception(self, error_message: str) -> bool:
        """
        Check if an error message indicates an authentication failure.

        Used to detect when to retry with fresh credentials (issue #765).

        Args:
            error_message: The error message string

        Returns:
            True if the error indicates authentication failure (401/403)
        """
        if not error_message:
            return False

        error_lower = str(error_message).lower()
        auth_error_indicators = [
            "401",
            "403",
            "unauthorized",
            "forbidden",
            "authentication failed",
            "auth failed",
            "invalid token",
            "token expired",
            "access denied",
            "invalid credentials",
            "session expired",
        ]
        return any(indicator in error_lower for indicator in auth_error_indicators)

    def _clear_auth_cache_for_user(self, user_id: str):
        """
        Clear all cached authentication data for a user.

        Called when detecting stale credentials (e.g., 403 error from broker).
        See GitHub issue #765 for details.

        Args:
            user_id: The user's ID
        """
        try:
            from database.auth_db import (
                auth_cache,
                broker_cache,
                feed_token_cache,
            )

            cache_key_auth = f"auth-{user_id}"
            cache_key_feed = f"feed-{user_id}"

            caches_cleared = []
            if cache_key_auth in auth_cache:
                del auth_cache[cache_key_auth]
                caches_cleared.append("auth_cache")
            if cache_key_feed in feed_token_cache:
                del feed_token_cache[cache_key_feed]
                caches_cleared.append("feed_token_cache")
            if cache_key_auth in broker_cache:
                del broker_cache[cache_key_auth]
                caches_cleared.append("broker_cache")

            if caches_cleared:
                logger.info(f"Cleared auth caches for user {user_id}: {', '.join(caches_cleared)}")
            else:
                logger.debug(f"No cached auth data found for user {user_id}")

        except Exception as e:
            logger.exception(f"Error clearing auth cache for user {user_id}: {e}")

    async def zmq_listener(self):
        """
        OPTIMIZED: Listen for messages from broker adapters via ZeroMQ and forward to clients

        Key Performance Improvements:
        1. Increased timeout from 0.1s to 0.3s (reduces busy-waiting by 66%)
        2. Use subscription_index for O(1) lookup instead of O(n²) iteration
        3. Batch message sending with asyncio.gather

        Also handles cache invalidation messages from Flask process for cross-process
        cache synchronization (see GitHub issue #765).
        """
        logger.debug("Starting OPTIMIZED ZeroMQ listener with subscription indexing and cache invalidation support")

        while self.running:
            try:
                # Check if we should stop
                if not self.running:
                    break

                # RESOURCE CLEANUP: Periodically clean stale throttle entries
                self._cleanup_stale_throttle_entries()

                # OPTIMIZATION 1: Increased timeout to reduce busy-waiting
                try:
                    [topic, data] = await aio.wait_for(
                        self.socket.recv_multipart(),
                        timeout=0.3,  # Increased from 0.1s (66% less CPU usage)
                    )
                except TimeoutError:
                    # No message received within timeout, continue the loop
                    continue

                # Parse the message
                topic_str = topic.decode("utf-8")
                data_str = data.decode("utf-8")

                # Handle cache invalidation messages (from Flask process)
                # These messages clear stale auth tokens after re-login
                # See GitHub issue #765 for details
                if topic_str.startswith("CACHE_INVALIDATE"):
                    try:
                        self._handle_cache_invalidation(topic_str, data_str)
                    except Exception as e:
                        logger.exception(f"Error handling cache invalidation: {e}")
                    continue  # Skip market data processing for cache messages

                market_data = json.loads(data_str)

                # Extract topic components
                # Support both formats:
                # New format: BROKER_EXCHANGE_SYMBOL_MODE (with broker name)
                # Old format: EXCHANGE_SYMBOL_MODE (without broker name)
                # Special case: NSE_INDEX_SYMBOL_MODE (exchange contains underscore)
                parts = topic_str.split("_")

                # Special case handling for NSE_INDEX and BSE_INDEX
                if len(parts) >= 4 and parts[0] == "NSE" and parts[1] == "INDEX":
                    broker_name = "unknown"
                    exchange = "NSE_INDEX"
                    symbol = parts[2]
                    mode_str = parts[3]
                elif len(parts) >= 4 and parts[0] == "BSE" and parts[1] == "INDEX":
                    broker_name = "unknown"
                    exchange = "BSE_INDEX"
                    symbol = parts[2]
                    mode_str = parts[3]
                elif len(parts) >= 5 and parts[1] == "INDEX":  # BROKER_NSE_INDEX_SYMBOL_MODE format
                    broker_name = parts[0]
                    exchange = f"{parts[1]}_{parts[2]}"
                    symbol = parts[3]
                    mode_str = parts[4]
                elif len(parts) >= 4:
                    # Standard format with broker name
                    broker_name = parts[0]
                    exchange = parts[1]
                    symbol = parts[2]
                    mode_str = parts[3]
                elif len(parts) >= 3:
                    # Old format without broker name
                    broker_name = "unknown"
                    exchange = parts[0]
                    symbol = parts[1]
                    mode_str = parts[2]
                else:
                    logger.warning(f"Invalid topic format: {topic_str}")
                    continue

                # OPTIMIZATION: Use pre-computed mode map
                mode = self.MODE_MAP.get(mode_str)

                if not mode:
                    logger.warning(f"Invalid mode in topic: {mode_str}")
                    continue

                # OPTIMIZATION: Message throttling for high-frequency updates
                # Skip if we sent the same message too recently (reduces CPU on fast updates)
                sub_key = (symbol, exchange, mode)
                current_time = time.time()

                # Only throttle LTP mode (mode 1), not Quote/Depth
                if mode == 1:  # LTP mode
                    last_time = self.last_message_time.get(sub_key, 0)
                    if current_time - last_time < self.message_throttle_interval:
                        continue  # Skip this update, too soon
                    self.last_message_time[sub_key] = current_time

                # Feed market data to MarketDataService for backend consumers
                # (sandbox execution engine, position MTM, RMS, etc.)
                # This runs regardless of whether WebSocket clients are subscribed
                try:
                    mds_data = {
                        "symbol": symbol,
                        "exchange": exchange,
                        "mode": mode,
                        "data": market_data,
                    }
                    market_data_service = get_market_data_service()
                    market_data_service.process_market_data(mds_data)
                except Exception as mds_error:
                    # Don't block WebSocket delivery if MarketDataService has issues
                    logger.debug(f"MarketDataService processing error: {mds_error}")

                # OPTIMIZATION 2: O(1) lookup using subscription index
                # Instead of iterating through ALL clients and ALL subscriptions (O(n²)),
                # directly lookup clients subscribed to this specific (symbol, exchange, mode)
                client_ids = self.subscription_index.get(sub_key, set()).copy()

                if not client_ids:
                    continue  # No WebSocket clients subscribed, skip delivery

                # OPTIMIZATION 3: Batch message sends for parallel delivery
                send_tasks = []

                # OPTIMIZATION 4: Pre-create base message (reused for all clients)
                # This avoids creating the same dict 1000 times
                base_message = {
                    "type": "market_data",
                    "symbol": symbol,
                    "exchange": exchange,
                    "mode": mode,
                    "data": market_data,
                }

                # OPTIMIZATION 5: Pre-serialize JSON once (not per-client)
                # Most clients get the same message, so serialize once
                base_message_str = None

                for client_id in client_ids:
                    # Verify client still exists
                    if client_id not in self.clients:
                        continue

                    # Verify user mapping exists
                    user_id = self.user_mapping.get(client_id)
                    if not user_id:
                        continue

                    # Check broker match (important for multi-broker setups)
                    client_broker = self.user_broker_mapping.get(user_id)
                    if broker_name != "unknown" and client_broker and client_broker != broker_name:
                        continue

                    # Add broker to message
                    message = base_message.copy()
                    message["broker"] = broker_name if broker_name != "unknown" else client_broker

                    # Add to batch
                    send_tasks.append(self.send_message(client_id, message))

                # Send all messages in parallel (non-blocking)
                if send_tasks:
                    await aio.gather(*send_tasks, return_exceptions=True)

                # METRICS: Track message count for health monitoring
                self._messages_processed += 1

            except Exception as e:
                logger.exception(f"Error in ZeroMQ listener: {e}")
                # Continue running despite errors
                await aio.sleep(1)


# Entry point for running the server standalone
async def main():
    """Main entry point for running the WebSocket proxy server"""
    proxy = None

    try:
        # Load environment variables
        load_dotenv()

        # Get WebSocket configuration from environment variables
        ws_host = os.getenv("WEBSOCKET_HOST", "127.0.0.1")
        ws_port = int(os.getenv("WEBSOCKET_PORT", "8765"))

        # Create and start the WebSocket proxy
        proxy = WebSocketProxy(host=ws_host, port=ws_port)

        await proxy.start()

    except KeyboardInterrupt:
        logger.info("Server stopped by user (KeyboardInterrupt)")
    except RuntimeError as e:
        if "set_wakeup_fd only works in main thread" in str(e):
            logger.error(f"Error in start method: {e}")
            logger.info("Starting ZeroMQ listener without signal handlers")
            # Continue with ZeroMQ listener even if signal handlers fail
            if proxy:
                await proxy.zmq_listener()
        else:
            logger.error(f"Runtime error: {e}")
            raise
    except Exception as e:
        import traceback

        error_details = traceback.format_exc()
        logger.exception(f"Server error: {e}\n{error_details}")
        raise
    finally:
        # Always clean up resources
        if proxy:
            try:
                await proxy.stop()
            except Exception as cleanup_error:
                logger.exception(f"Error during cleanup: {cleanup_error}")


if __name__ == "__main__":
    aio.run(main())
