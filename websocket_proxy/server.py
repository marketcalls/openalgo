import asyncio as aio
import websockets
import json
import logging
import signal
import zmq
import zmq.asyncio
import threading
import time
import os
from typing import Dict, Set, Any, Optional
from dotenv import load_dotenv

from .port_check import is_port_in_use, find_available_port
from database.auth_db import get_broker_name
from sqlalchemy import text
from database.auth_db import verify_api_key
from .broker_factory import create_broker_adapter
from .base_adapter import BaseBrokerWebSocketAdapter

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("websocket_proxy")

class WebSocketProxy:
    """
    WebSocket Proxy Server that handles client connections and authentication,
    manages subscriptions, and routes market data from broker adapters to clients.
    Supports dynamic broker selection based on user configuration.
    """
    
    def __init__(self, host: str = "localhost", port: int = 8765):
        """
        Initialize the WebSocket Proxy
        
        Args:
            host: Hostname to bind the WebSocket server to
            port: Port number to bind the WebSocket server to
        """
        self.host = host
        
        # Check if the port is already in use and find an available one if needed
        if is_port_in_use(host, port):
            # Debug mode starts two instances, so original port may be taken
            available_port = find_available_port(port + 1)
            if available_port:
                logger.info(f"Port {port} is in use, using port {available_port} instead")
                self.port = available_port
            else:
                # If no port is available, we'll try the original port anyway
                # This will likely fail, but we'll handle the error gracefully
                logger.warning(f"Could not find an available port, using {port} anyway")
                self.port = port
        else:
            self.port = port
        
        self.clients = {}  # Maps client_id to websocket connection
        self.subscriptions = {}  # Maps client_id to set of subscriptions
        self.broker_adapters = {}  # Maps user_id to broker adapter
        self.user_mapping = {}  # Maps client_id to user_id
        self.user_broker_mapping = {}  # Maps user_id to broker_name
        self.running = False
        
        # ZeroMQ context for subscribing to broker adapters
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.SUB)
        # Connecting to ZMQ
        ZMQ_HOST = os.getenv('ZMQ_HOST', 'localhost')
        ZMQ_PORT = os.getenv('ZMQ_PORT')
        self.socket.connect(f"tcp://{ZMQ_HOST}:{ZMQ_PORT}")  # Connect to broker adapter publisher
        
        # Set up ZeroMQ subscriber to receive all messages
        self.socket.setsockopt(zmq.SUBSCRIBE, b"")  # Subscribe to all topics
    
    async def start(self):
        """Start the WebSocket server and ZeroMQ listener"""
        self.running = True
        
        try:
            # Start ZeroMQ listener
            logger.info("Initializing ZeroMQ listener task")
            
            # Get the current event loop
            loop = aio.get_running_loop()
            
            # Create the ZMQ listener task
            zmq_task = loop.create_task(self.zmq_listener())
            
            # Start WebSocket server
            stop = aio.Future()  # Used to stop the server
            
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
                        logger.info("Signal handlers registered successfully")
                    except (NotImplementedError, RuntimeError) as e:
                        # On Windows or when in a non-main thread
                        logger.info(f"Signal handlers not registered: {e}. Using fallback mechanism.")
                else:
                    logger.info("Running in a non-main thread. Signal handlers will not be used.")
            except RuntimeError:
                logger.info("No running event loop found for signal handlers")
            
            logger.info(f"Starting WebSocket server on {self.host}:{self.port}")
            
            # Try to start the WebSocket server with more detailed error logging
            try:
                async with websockets.serve(self.handle_client, self.host, self.port):
                    logger.info(f"WebSocket server successfully started on {self.host}:{self.port}")
                    await stop  # Wait until stopped
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                logger.error(f"Failed to start WebSocket server: {e}\n{error_details}")
                raise
                
        except Exception as e:
            logger.error(f"Error in start method: {e}")
            raise
    
    async def stop(self):
        """Stop the WebSocket server"""
        self.running = False
        
        # Close all client connections
        for client_id, websocket in self.clients.items():
            await websocket.close()
        
        # Disconnect all broker adapters
        for user_id, adapter in self.broker_adapters.items():
            adapter.disconnect()
    
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
        path = getattr(websocket, 'path', '/unknown')
        logger.info(f"Client connected: {client_id} from path: {path}")
        
        try:
            # Process messages from the client
            async for message in websocket:
                try:
                    logger.debug(f"Received message from client {client_id}: {message}")
                    await self.process_client_message(client_id, message)
                except Exception as e:
                    import traceback
                    logger.error(f"Error processing message from client {client_id}: {e}\n{traceback.format_exc()}")
                    # Send error to client but don't disconnect
                    try:
                        await self.send_error(client_id, "PROCESSING_ERROR", str(e))
                    except:
                        pass
        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"Client disconnected: {client_id}, code: {e.code}, reason: {e.reason}")
        except Exception as e:
            import traceback
            logger.error(f"Unexpected error handling client {client_id}: {e}\n{traceback.format_exc()}")
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
                    symbol = sub_info.get('symbol')
                    exchange = sub_info.get('exchange')
                    mode = sub_info.get('mode')
                    
                    # Get the user's broker adapter
                    user_id = self.user_mapping.get(client_id)
                    if user_id and user_id in self.broker_adapters:
                        adapter = self.broker_adapters[user_id]
                        adapter.unsubscribe(symbol, exchange, mode)
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing subscription: {sub_json}, Error: {e}")
                except Exception as e:
                    logger.error(f"Error processing subscription: {e}")
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
            
            # If this was the last client for this user, disconnect the broker adapter
            if is_last_client and user_id in self.broker_adapters:
                self.broker_adapters[user_id].disconnect()
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
            logger.debug(f"Parsed message from client {client_id}: {data}")
            
            # Accept both 'action' and 'type' fields for better compatibility with different clients
            action = data.get("action") or data.get("type")
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
            else:
                logger.warning(f"Client {client_id} requested invalid action: {action}")
                await self.send_error(client_id, "INVALID_ACTION", f"Invalid action: {action}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from client {client_id}: {message}")
            await self.send_error(client_id, "INVALID_JSON", "Invalid JSON message")
        except Exception as e:
            import traceback
            logger.error(f"Error processing client message: {e}\n{traceback.format_exc()}")
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
            from database.auth_db import get_broker_name
            from sqlalchemy import text
            
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
                valid_brokers = os.getenv('VALID_BROKERS', 'angel').split(',')
                broker_name = valid_brokers[0].strip() if valid_brokers else 'angel'
                logger.warning(f"No broker found in database for user {user_id}, using fallback: {broker_name}")
            
            # Get broker credentials from environment variables
            # In a production system, these would be stored encrypted in the database per user
            broker_config = {
                'broker_name': broker_name,
                'api_key': os.getenv('BROKER_API_KEY'),
                'api_secret': os.getenv('BROKER_API_SECRET'),
                'api_key_market': os.getenv('BROKER_API_KEY_MARKET'),
                'api_secret_market': os.getenv('BROKER_API_SECRET_MARKET'),
                'broker_user_id': os.getenv('BROKER_USER_ID'),
                'password': os.getenv('BROKER_PASSWORD'),
                'totp_secret': os.getenv('BROKER_TOTP_SECRET')
            }
            
            # Validate broker is supported
            valid_brokers_list = os.getenv('VALID_BROKERS', '').split(',')
            valid_brokers_list = [b.strip() for b in valid_brokers_list if b.strip()]
            
            if broker_name not in valid_brokers_list:
                logger.error(f"Broker '{broker_name}' is not in VALID_BROKERS list: {valid_brokers_list}")
                return None
            
            if not broker_config.get('broker_name'):
                logger.error(f"No broker configuration found for user {user_id}")
                return None
            
            logger.info(f"Retrieved broker configuration for user {user_id}: {broker_config['broker_name']}")
            return broker_config
            
        except Exception as e:
            logger.error(f"Error getting broker configuration for user {user_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    async def authenticate_client(self, client_id, data):
        """
        Authenticate a client using their API key and determine their broker
        
        Args:
            client_id: ID of the client
            data: Authentication data containing API key
        """
        api_key = data.get("api_key")
        
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
            await self.send_error(client_id, "BROKER_ERROR", "No broker configuration found for user")
            return
        
        # Store the broker mapping for this user
        self.user_broker_mapping[user_id] = broker_name
        
        # Create or reuse broker adapter
        if user_id not in self.broker_adapters:
            try:
                # Create broker adapter with dynamic broker selection
                adapter = create_broker_adapter(broker_name)
                if not adapter:
                    await self.send_error(client_id, "BROKER_ERROR", f"Failed to create adapter for broker: {broker_name}")
                    return
                
                # Initialize adapter with broker configuration
                # The adapter's initialize method should handle broker-specific setup
                initialization_result = adapter.initialize(broker_name, user_id)
                if initialization_result and not initialization_result.get('success', True):
                    error_msg = initialization_result.get('error', 'Failed to initialize broker adapter')
                    await self.send_error(client_id, "BROKER_INIT_ERROR", error_msg)
                    return
                
                # Connect to the broker
                connect_result = adapter.connect()
                if connect_result and not connect_result.get('success', True):
                    error_msg = connect_result.get('error', 'Failed to connect to broker')
                    await self.send_error(client_id, "BROKER_CONNECTION_ERROR", error_msg)
                    return
                
                # Store the adapter
                self.broker_adapters[user_id] = adapter
                
                logger.info(f"Successfully created and connected {broker_name} adapter for user {user_id}")
                
            except Exception as e:
                logger.error(f"Failed to create broker adapter for {broker_name}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await self.send_error(client_id, "BROKER_ERROR", str(e))
                return
        
        # Send success response with broker information
        await self.send_message(client_id, {
            "type": "auth",
            "status": "success",
            "message": "Authentication successful",
            "broker": broker_name,
            "user_id": user_id,
            "supported_features": {
                "ltp": True,
                "quote": True,
                "depth": True
            }
        })
    
    async def get_supported_brokers(self, client_id):
        """
        Get list of supported brokers from environment configuration
        
        Args:
            client_id: ID of the client
        """
        try:
            valid_brokers = os.getenv('VALID_BROKERS', '').split(',')
            supported_brokers = [broker.strip() for broker in valid_brokers if broker.strip()]
            
            await self.send_message(client_id, {
                "type": "supported_brokers",
                "status": "success",
                "brokers": supported_brokers,
                "count": len(supported_brokers)
            })
        except Exception as e:
            logger.error(f"Error getting supported brokers: {e}")
            await self.send_error(client_id, "BROKER_LIST_ERROR", str(e))
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
            adapter_status = getattr(adapter, 'status', 'connected')
        
        await self.send_message(client_id, {
            "type": "broker_info",
            "status": "success",
            "broker": broker_name,
            "adapter_status": adapter_status,
            "user_id": user_id
        })
    
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
        mode_mapping = {
            "LTP": 1,
            "Quote": 2, 
            "Depth": 3
        }
        
        # Convert string mode to numeric if needed
        mode = mode_mapping.get(mode_str, mode_str) if isinstance(mode_str, str) else mode_str
        
        # Handle case where a single symbol is passed directly instead of as an array
        if not symbols and (data.get("symbol") and data.get("exchange")):
            symbols = [{
                "symbol": data.get("symbol"),
                "exchange": data.get("exchange")
            }]
        
        if not symbols:
            await self.send_error(client_id, "INVALID_PARAMETERS", "At least one symbol must be specified")
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
                    "broker": broker_name
                }
                
                if client_id in self.subscriptions:
                    self.subscriptions[client_id].add(json.dumps(subscription_info))
                else:
                    self.subscriptions[client_id] = {json.dumps(subscription_info)}
                
                # Add to successful subscriptions
                subscription_responses.append({
                    "symbol": symbol,
                    "exchange": exchange,
                    "status": "success",
                    "mode": mode_str,
                    "depth": response.get("actual_depth", depth_level),
                    "broker": broker_name
                })
            else:
                subscription_success = False
                # Add to failed subscriptions
                subscription_responses.append({
                    "symbol": symbol,
                    "exchange": exchange,
                    "status": "error",
                    "message": response.get("message", "Subscription failed"),
                    "broker": broker_name
                })
        
        # Send combined response
        await self.send_message(client_id, {
            "type": "subscribe",
            "status": "success" if subscription_success else "partial",
            "subscriptions": subscription_responses,
            "message": "Subscription processing complete",
            "broker": broker_name
        })
    
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
        is_unsubscribe_all = data.get("type") == "unsubscribe_all" or data.get("action") == "unsubscribe_all"
        
        # Get unsubscription parameters for specific symbols
        symbols = data.get("symbols") or []
        
        # Handle single symbol format
        if not symbols and not is_unsubscribe_all and (data.get("symbol") and data.get("exchange")):
            symbols = [{
                "symbol": data.get("symbol"),
                "exchange": data.get("exchange"),
                "mode": data.get("mode", 2)  # Default to Quote mode
            }]
        
        # If no symbols provided and not unsubscribe_all, return error
        if not symbols and not is_unsubscribe_all:
            await self.send_error(client_id, "INVALID_PARAMETERS", "Either symbols or unsubscribe_all is required")
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
                        response = adapter.unsubscribe(symbol, exchange, mode)
                        
                        if response.get("status") == "success":
                            successful_unsubscriptions.append({
                                "symbol": symbol,
                                "exchange": exchange,
                                "status": "success",
                                "broker": broker_name
                            })
                        else:
                            failed_unsubscriptions.append({
                                "symbol": symbol,
                                "exchange": exchange,
                                "status": "error",
                                "message": response.get("message", "Unsubscription failed"),
                                "broker": broker_name
                            })
                
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
                
                # Unsubscribe from market data
                response = adapter.unsubscribe(symbol, exchange, mode)
                
                if response.get("status") == "success":
                    # Try to remove subscription
                    if client_id in self.subscriptions:
                        subscription_info = {
                            "symbol": symbol,
                            "exchange": exchange,
                            "mode": mode,
                            "broker": broker_name
                        }
                        subscription_key = json.dumps(subscription_info)
                        # Remove any matching subscription (with or without broker info)
                        subscriptions_to_remove = []
                        for sub_key in self.subscriptions[client_id]:
                            try:
                                sub_data = json.loads(sub_key)
                                if (sub_data.get("symbol") == symbol and 
                                    sub_data.get("exchange") == exchange and 
                                    sub_data.get("mode") == mode):
                                    subscriptions_to_remove.append(sub_key)
                            except json.JSONDecodeError:
                                continue
                        
                        for sub_key in subscriptions_to_remove:
                            self.subscriptions[client_id].discard(sub_key)
                    
                    successful_unsubscriptions.append({
                        "symbol": symbol,
                        "exchange": exchange,
                        "status": "success",
                        "broker": broker_name
                    })
                else:
                    failed_unsubscriptions.append({
                        "symbol": symbol,
                        "exchange": exchange,
                        "status": "error",
                        "message": response.get("message", "Unsubscription failed"),
                        "broker": broker_name
                    })
        
        # Send combined response
        status = "success"
        if len(failed_unsubscriptions) > 0 and len(successful_unsubscriptions) > 0:
            status = "partial"
        elif len(failed_unsubscriptions) > 0 and len(successful_unsubscriptions) == 0:
            status = "error"
            
        await self.send_message(client_id, {
            "type": "unsubscribe",
            "status": status,
            "message": "Unsubscription processing complete",
            "successful": successful_unsubscriptions,
            "failed": failed_unsubscriptions,
            "broker": broker_name
        })
    
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
        await self.send_message(client_id, {
            "status": "error",
            "code": code,
            "message": message
        })
    
    async def zmq_listener(self):
        """Listen for messages from broker adapters via ZeroMQ and forward to clients"""
        logger.info("Starting ZeroMQ listener")
        
        while self.running:
            try:
                # Receive message from ZeroMQ with a timeout
                try:
                    [topic, data] = await aio.wait_for(
                        self.socket.recv_multipart(),
                        timeout=0.1
                    )
                except aio.TimeoutError:
                    # No message received within timeout, continue the loop
                    continue
                
                # Parse the message
                topic_str = topic.decode('utf-8')
                data_str = data.decode('utf-8')
                market_data = json.loads(data_str)
                
                # Extract topic components
                # Support both formats:
                # New format: BROKER_EXCHANGE_SYMBOL_MODE (with broker name)
                # Old format: EXCHANGE_SYMBOL_MODE (without broker name)
                # Special case: NSE_INDEX_SYMBOL_MODE (exchange contains underscore)
                parts = topic_str.split('_')
                
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
                
                # Map mode string to mode number
                mode_map = {"LTP": 1, "QUOTE": 2, "DEPTH": 3}
                mode = mode_map.get(mode_str)
                
                if not mode:
                    logger.warning(f"Invalid mode in topic: {mode_str}")
                    continue
                
                # Find clients subscribed to this data
                # Create a snapshot of the subscriptions before iteration to avoid
                # 'dictionary changed size during iteration' errors
                subscriptions_snapshot = list(self.subscriptions.items())
                
                for client_id, subscriptions in subscriptions_snapshot:
                    user_id = self.user_mapping.get(client_id)
                    if not user_id:
                        continue
                    
                    # Check if this client's broker matches the message broker (if broker is specified)
                    client_broker = self.user_broker_mapping.get(user_id)
                    if broker_name != "unknown" and client_broker and client_broker != broker_name:
                        continue  # Skip if broker doesn't match
                    
                    # Create a snapshot of the subscription set before iteration
                    subscriptions_list = list(subscriptions)
                    for sub_json in subscriptions_list:
                        try:
                            sub = json.loads(sub_json)
                            
                            # Check subscription match
                            if (sub.get("symbol") == symbol and 
                                sub.get("exchange") == exchange and 
                                (sub.get("mode") == mode or 
                                 (mode_str == "LTP" and sub.get("mode") == 1) or
                                 (mode_str == "QUOTE" and sub.get("mode") == 2) or
                                 (mode_str == "DEPTH" and sub.get("mode") == 3))):
                                
                                # Forward data to the client
                                await self.send_message(client_id, {
                                    "type": "market_data",
                                    "symbol": symbol,
                                    "exchange": exchange,
                                    "mode": mode,
                                    "broker": broker_name if broker_name != "unknown" else client_broker,
                                    "data": market_data
                                })
                        except json.JSONDecodeError as e:
                            logger.error(f"Error parsing subscription: {sub_json}, Error: {e}")
                            continue
            
            except Exception as e:
                logger.error(f"Error in ZeroMQ listener: {e}")
                # Continue running despite errors
                await aio.sleep(1)

# Entry point for running the server standalone
async def main():
    """Main entry point for running the WebSocket proxy server"""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load environment variables
    load_dotenv()
    
    # Get WebSocket configuration from environment variables
    ws_host = os.getenv('WEBSOCKET_HOST', 'localhost')
    ws_port = int(os.getenv('WEBSOCKET_PORT', '8765'))
    
    # Create and start the WebSocket proxy
    proxy = WebSocketProxy(host=ws_host, port=ws_port)
    
    try:
        await proxy.start()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except RuntimeError as e:
        if "set_wakeup_fd only works in main thread" in str(e):
            logger.error(f"Error in start method: {e}")
            logger.info("Starting ZeroMQ listener without signal handlers")
            # Continue with ZeroMQ listener even if signal handlers fail
            await proxy.zmq_listener()
        else:
            logger.error(f"Server error: {e}")
            raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Server error: {e}\n{error_details}")
    finally:
        await proxy.stop()

if __name__ == "__main__":
    aio.run(main())